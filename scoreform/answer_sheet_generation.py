"""Managed, lifecycle-aware answer-sheet artifact generation."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from pds_core.route_ids import generate_route_id
from pds_core.routes import route_registration_path
from pds_core.routing_models import ModuleWorkRef

from scoreform.answer_sheet_persistence import (
    answer_sheet_issuance_path,
    answer_sheet_page_path,
    load_answer_sheet_issuance,
    transition_answer_sheet_issuance,
    write_answer_sheet_record_set,
)
from scoreform.answer_sheet_records import (
    AnswerSheetIssuance,
    AnswerSheetRecordSet,
    build_answer_sheet_record_set,
    generate_artifact_id,
    generate_generation_id,
)
from scoreform.answer_sheet_routes import (
    AnswerSheetPageRoute,
    RegisteredAnswerSheetPageRoute,
    build_answer_sheet_page_route,
    persist_answer_sheet_route_set,
    preflight_answer_sheet_route_destinations,
    preflight_answer_sheet_route_set,
)
from scoreform.templates import render_registered_answer_sheet_pdf


class AnswerSheetGenerationError(Exception):
    """Base class for managed artifact generation failures."""


class AnswerSheetGenerationPreflightError(AnswerSheetGenerationError):
    """Raised before any answer-sheet records are durably created."""


class AnswerSheetPredecessorError(AnswerSheetGenerationPreflightError):
    """Raised when current issuance lineage is ambiguous or concurrent."""


@dataclass(frozen=True, slots=True)
class AnswerSheetArtifactPlan:
    """Complete identity and route plan for one independently installed PDF."""

    generation_id: str
    artifact_id: str
    output_path: Path
    output_kind: str
    assignment: Mapping[str, object]
    students: tuple[Mapping[str, object], ...]
    record_sets: tuple[AnswerSheetRecordSet, ...]
    route_sets: tuple[tuple[AnswerSheetPageRoute, ...], ...]
    predecessors: tuple[AnswerSheetIssuance | None, ...]
    temporary_path: Path
    replaced_existing: bool

    @property
    def physical_page_count(self) -> int:
        return sum(len(record_set.pages) for record_set in self.record_sets)


@dataclass(frozen=True, slots=True)
class AnswerSheetArtifactResult:
    generation_id: str
    artifact_id: str
    output_path: str
    output_kind: str
    success: bool
    student_count: int
    issuance_count: int
    physical_page_count: int
    issuance_ids: tuple[str, ...]
    page_ids: tuple[str, ...]
    route_ids: tuple[str, ...]
    planned_route_count: int
    created_route_count: int
    verified_route_count: int
    installed: bool
    replaced_previous_output: bool
    predecessor_count: int
    superseded_predecessor_count: int
    failure_stage: str | None
    error: str | None
    warnings: tuple[str, ...] = ()
    created_registration_paths: tuple[str, ...] = ()
    verified_registration_paths: tuple[str, ...] = ()
    failed_predecessor_ids: tuple[str, ...] = ()

    @property
    def partial_success(self) -> bool:
        return self.installed and not self.success

    @property
    def completed(self) -> bool:
        """Return whether the canonical artifact was installed."""
        return self.installed

    @property
    def route_count(self) -> int:
        """Backward-compatible alias for verified registrations, not plans."""
        return self.verified_route_count


@dataclass(frozen=True, slots=True)
class AnswerSheetGenerationResult:
    generation_id: str
    artifacts: tuple[AnswerSheetArtifactResult, ...]

    @property
    def success(self) -> bool:
        return bool(self.artifacts) and all(item.success for item in self.artifacts)

    @property
    def completed_artifact_count(self) -> int:
        """Count installed artifacts, including installed partial successes."""
        return self.installed_artifact_count

    @property
    def installed_artifact_count(self) -> int:
        return sum(item.installed for item in self.artifacts)

    @property
    def clean_success_count(self) -> int:
        return sum(item.success for item in self.artifacts)

    @property
    def partial_artifact_count(self) -> int:
        return sum(item.partial_success for item in self.artifacts)

    @property
    def failed_before_install_count(self) -> int:
        return sum(not item.installed for item in self.artifacts)

    @property
    def failed_artifact_count(self) -> int:
        """Count all non-clean results, including installed partial successes."""
        return sum(not item.success for item in self.artifacts)

    @property
    def partial_success(self) -> bool:
        return self.installed_artifact_count > 0 and not self.success

    @property
    def physical_page_count(self) -> int:
        """Count pages in installed artifacts, including installed partials."""
        return sum(item.physical_page_count for item in self.artifacts if item.installed)

    @property
    def planned_route_count(self) -> int:
        return sum(item.planned_route_count for item in self.artifacts)

    @property
    def created_route_count(self) -> int:
        return sum(item.created_route_count for item in self.artifacts)

    @property
    def verified_route_count(self) -> int:
        return sum(item.verified_route_count for item in self.artifacts)

    @property
    def installed_route_count(self) -> int:
        """Count verified routes belonging to installed artifacts."""
        return sum(item.verified_route_count for item in self.artifacts if item.installed)

    @property
    def route_count(self) -> int:
        """Backward-compatible alias for installed verified route count."""
        return self.installed_route_count


def _remove_temporary_artifact(path: Path) -> tuple[str, ...]:
    """Best-effort cleanup that never masks the primary generation failure."""
    try:
        path.unlink(missing_ok=True)
    except Exception as error:
        return (f"Temporary artifact cleanup failed for {path}: {error}",)
    return ()


def preflight_generation_dependencies() -> None:
    """Import PDF, QR, and Pillow support before creating durable identities."""
    missing: list[str] = []
    try:
        import reportlab  # noqa: F401
    except Exception:
        missing.append("reportlab")
    try:
        import qrcode  # noqa: F401
    except Exception:
        missing.append('qrcode[pil]')
    try:
        from PIL import Image  # noqa: F401
    except Exception:
        missing.append("Pillow")
    if missing:
        raise AnswerSheetGenerationPreflightError(
            "Missing answer-sheet generation dependencies: "
            + ", ".join(missing)
            + '. Install the project dependencies with python -m pip install -e ".[dev]".'
        )


def discover_answer_sheet_issuances(
    workspace_root: str | Path, work_ref: ModuleWorkRef
) -> tuple[AnswerSheetIssuance, ...]:
    """Strictly load direct issuance JSON children for one exact work only."""
    # Build the directory through the canonical path helper without searching.
    sentinel = "iss_00000000000000000000000000000000"
    directory = answer_sheet_issuance_path(
        workspace_root, work_ref, sentinel
    ).parent
    if directory.is_symlink():
        raise AnswerSheetPredecessorError(
            f"Symlinked issuance directory is not allowed: {directory}"
        )
    if not directory.exists():
        return ()
    if not directory.is_dir():
        raise AnswerSheetPredecessorError(
            f"Issuance collection is not a directory: {directory}"
        )
    records: list[AnswerSheetIssuance] = []
    for child in sorted(directory.iterdir(), key=lambda path: path.name):
        if child.is_symlink():
            raise AnswerSheetPredecessorError(
                f"Symlinked issuance entry is not allowed: {child}"
            )
        if child.suffix != ".json":
            continue
        if not child.is_file():
            raise AnswerSheetPredecessorError(
                f"Issuance JSON entry is not a regular file: {child}"
            )
        issuance_id = child.stem
        try:
            issuance = load_answer_sheet_issuance(
                workspace_root, work_ref, issuance_id
            )
        except Exception as error:
            raise AnswerSheetPredecessorError(
                f"Could not strictly load issuance {child}: {error}"
            ) from error
        if child.name != f"{issuance.issuance_id}.json":
            raise AnswerSheetPredecessorError(
                f"Issuance filename does not match stored identity: {child}"
            )
        records.append(issuance)
    return tuple(records)


def select_current_predecessor(
    issuances: Sequence[AnswerSheetIssuance],
    *,
    work_ref: ModuleWorkRef,
    student_id: str,
    output_kind: str,
) -> AnswerSheetIssuance | None:
    """Select exactly zero or one current issued predecessor without guessing."""
    matching = tuple(
        issuance
        for issuance in issuances
        if (
            issuance.class_id == work_ref.class_id
            and issuance.assignment_id == work_ref.work_id
            and issuance.student_id == student_id
            and issuance.generation_context.output_kind == output_kind
        )
    )
    prepared = tuple(
        issuance for issuance in matching if issuance.lifecycle.status == "prepared"
    )
    if prepared:
        raise AnswerSheetPredecessorError(
            "A matching prepared issuance already exists; resolve the concurrent or "
            f"interrupted operation first: {prepared[0].issuance_id}"
        )
    candidates = tuple(
        issuance for issuance in matching if issuance.lifecycle.status == "issued"
    )
    if len(candidates) > 1:
        raise AnswerSheetPredecessorError(
            "Multiple current issued predecessor candidates are ambiguous for "
            f"student {student_id} and {output_kind}."
        )
    return candidates[0] if candidates else None


def _preflight_output_destination(output_path: Path) -> tuple[Path, bool]:
    if output_path.is_symlink():
        raise AnswerSheetGenerationPreflightError(
            f"Symlinked output path is not allowed: {output_path}"
        )
    replaced = output_path.exists()
    if replaced and not output_path.is_file():
        raise AnswerSheetGenerationPreflightError(
            f"Output destination is not a regular file: {output_path}"
        )
    parent = output_path.parent
    if parent.is_symlink() or not parent.is_dir():
        raise AnswerSheetGenerationPreflightError(
            f"Output parent is missing, symlinked, or not a directory: {parent}"
        )
    if not os.access(parent, os.W_OK):
        raise AnswerSheetGenerationPreflightError(
            f"Output parent is not writable: {parent}"
        )
    descriptor: int | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{output_path.stem}.", suffix=".tmp.pdf", dir=parent
        )
        os.close(descriptor)
        descriptor = None
    except OSError as error:
        if descriptor is not None:
            os.close(descriptor)
        raise AnswerSheetGenerationPreflightError(
            f"Could not exclusively create a temporary PDF in {parent}: {error}"
        ) from error
    return Path(temporary_name), replaced


def _record_destinations_are_free(
    workspace_root: str | Path,
    work_ref: ModuleWorkRef,
    record_set: AnswerSheetRecordSet,
    used_issuance_ids: set[str],
    used_page_ids: set[str],
) -> bool:
    issuance = record_set.issuance
    if issuance.issuance_id in used_issuance_ids:
        return False
    if any(page.page_id in used_page_ids for page in record_set.pages):
        return False
    destinations = (
        answer_sheet_issuance_path(workspace_root, work_ref, issuance.issuance_id),
        *(
            answer_sheet_page_path(workspace_root, work_ref, page.page_id)
            for page in record_set.pages
        ),
    )
    return all(not path.exists() and not path.is_symlink() for path in destinations)


def _plan_fresh_record_set(
    workspace_root: str | Path,
    work_ref: ModuleWorkRef,
    assignment: Mapping[str, object],
    student: Mapping[str, object],
    *,
    generation_id: str,
    artifact_id: str,
    output_kind: str,
    predecessor: AnswerSheetIssuance | None,
    used_issuance_ids: set[str],
    used_page_ids: set[str],
    retries: int,
) -> AnswerSheetRecordSet:
    for _attempt in range(retries):
        record_set = build_answer_sheet_record_set(
            work_ref.class_id,
            assignment,
            student,
            generation_id=generation_id,
            artifact_id=artifact_id,
            output_kind=output_kind,
            reason="regeneration" if predecessor is not None else "initial",
            predecessor_issuance_id=(
                predecessor.issuance_id if predecessor is not None else None
            ),
        )
        if _record_destinations_are_free(
            workspace_root,
            work_ref,
            record_set,
            used_issuance_ids,
            used_page_ids,
        ):
            used_issuance_ids.add(record_set.issuance.issuance_id)
            used_page_ids.update(page.page_id for page in record_set.pages)
            return record_set
    raise AnswerSheetGenerationPreflightError(
        f"Could not allocate collision-free answer-sheet record IDs after {retries} attempts."
    )


def _plan_fresh_routes(
    workspace_root: str | Path,
    work_ref: ModuleWorkRef,
    record_set: AnswerSheetRecordSet,
    *,
    used_route_ids: set[str],
    route_id_generator: Callable[[], str],
    retries: int,
) -> tuple[AnswerSheetPageRoute, ...]:
    routes: list[AnswerSheetPageRoute] = []
    for page in record_set.pages:
        for _attempt in range(retries):
            route_id = route_id_generator()
            route = build_answer_sheet_page_route(
                work_ref, page, route_id=route_id
            )
            destination = route_registration_path(workspace_root, route.locator)
            if route_id in used_route_ids:
                continue
            # Burn every generated identity immediately, including collisions.
            # A later filesystem change can therefore never make a rejected ID
            # eligible again within the complete command plan.
            used_route_ids.add(route_id)
            if not destination.exists() and not destination.is_symlink():
                routes.append(route)
                break
        else:
            raise AnswerSheetGenerationPreflightError(
                "Could not allocate a collision-free Core route ID for page "
                f"{page.page_id} after {retries} attempts."
            )
    return tuple(routes)


def plan_answer_sheet_artifact(
    workspace_root: str | Path,
    work_ref: ModuleWorkRef,
    assignment: Mapping[str, object],
    students: Sequence[Mapping[str, object]],
    output_path: str | Path,
    *,
    output_kind: str,
    generation_id: str,
    used_issuance_ids: set[str] | None = None,
    used_page_ids: set[str] | None = None,
    used_route_ids: set[str] | None = None,
    route_id_generator: Callable[[], str] = generate_route_id,
    collision_retries: int = 32,
) -> AnswerSheetArtifactPlan:
    """Complete preflight and identity planning without durable record mutation."""
    preflight_generation_dependencies()
    if output_kind not in {"individual_pdf", "class_packet_pdf"}:
        raise AnswerSheetGenerationPreflightError("Unsupported output kind.")
    selected_students = tuple(students)
    expected_count = 1 if output_kind == "individual_pdf" else len(selected_students)
    if not selected_students or len(selected_students) != expected_count:
        raise AnswerSheetGenerationPreflightError(
            "An individual artifact requires one student; a packet requires a non-empty roster."
        )
    destination = Path(output_path)
    temporary_path, replaced = _preflight_output_destination(destination)
    try:
        historical = discover_answer_sheet_issuances(workspace_root, work_ref)
        predecessors = tuple(
            select_current_predecessor(
                historical,
                work_ref=work_ref,
                student_id=str(student.get("student_id", "")),
                output_kind=output_kind,
            )
            for student in selected_students
        )
        artifact_id = generate_artifact_id()
        issuance_ids = used_issuance_ids if used_issuance_ids is not None else set()
        page_ids = used_page_ids if used_page_ids is not None else set()
        route_ids = used_route_ids if used_route_ids is not None else set()
        record_sets = tuple(
            _plan_fresh_record_set(
                workspace_root,
                work_ref,
                assignment,
                student,
                generation_id=generation_id,
                artifact_id=artifact_id,
                output_kind=output_kind,
                predecessor=predecessor,
                used_issuance_ids=issuance_ids,
                used_page_ids=page_ids,
                retries=collision_retries,
            )
            for student, predecessor in zip(
                selected_students, predecessors, strict=True
            )
        )
        route_sets = tuple(
            _plan_fresh_routes(
                workspace_root,
                work_ref,
                record_set,
                used_route_ids=route_ids,
                route_id_generator=route_id_generator,
                retries=collision_retries,
            )
            for record_set in record_sets
        )
        preflight_answer_sheet_route_destinations(
            workspace_root,
            tuple(route for route_set in route_sets for route in route_set),
        )
        return AnswerSheetArtifactPlan(
            generation_id,
            artifact_id,
            destination,
            output_kind,
            assignment,
            selected_students,
            record_sets,
            route_sets,
            predecessors,
            temporary_path,
            replaced,
        )
    except Exception as error:
        for warning in _remove_temporary_artifact(temporary_path):
            error.add_note(warning)
        raise


def _transition_many(
    workspace_root: str | Path,
    work_ref: ModuleWorkRef,
    record_sets: Sequence[AnswerSheetRecordSet],
    *,
    status: str,
    reason: str | None,
) -> list[str]:
    errors: list[str] = []
    timestamp = datetime.now(timezone.utc)
    for record_set in record_sets:
        issuance_id = record_set.issuance.issuance_id
        try:
            current = load_answer_sheet_issuance(
                workspace_root, work_ref, issuance_id
            )
            if current.lifecycle.status in {"cancelled", "invalidated", "superseded"}:
                continue
            transition_answer_sheet_issuance(
                workspace_root,
                work_ref,
                issuance_id,
                expected_revision=current.lifecycle.revision,
                new_status=status,
                timestamp=timestamp,
                reason=reason,
            )
        except Exception as error:
            errors.append(f"{issuance_id}: {error}")
    return errors


def _failure_warnings(
    compensation_errors: Sequence[str], cleanup_warnings: Sequence[str]
) -> tuple[str, ...]:
    return tuple(
        [
            *(f"Compensation failure: {item}" for item in compensation_errors),
            *cleanup_warnings,
        ]
    )


def _result(
    plan: AnswerSheetArtifactPlan,
    *,
    success: bool,
    stage: str | None,
    error: str | None,
    registered: Sequence[RegisteredAnswerSheetPageRoute] = (),
    created_paths: Sequence[str | Path] = (),
    superseded: int = 0,
    installed: bool = False,
    warnings: Sequence[str] = (),
    failed_predecessor_ids: Sequence[str] = (),
) -> AnswerSheetArtifactResult:
    route_ids = tuple(
        route.locator.route_id for route_set in plan.route_sets for route in route_set
    )
    verified_paths = tuple(
        os.fspath(item.registration_path) for item in registered
    )
    durable_paths = tuple(
        dict.fromkeys([*verified_paths, *(os.fspath(path) for path in created_paths)])
    )
    return AnswerSheetArtifactResult(
        generation_id=plan.generation_id,
        artifact_id=plan.artifact_id,
        output_path=os.fspath(plan.output_path),
        output_kind=plan.output_kind,
        success=success,
        student_count=len(plan.students),
        issuance_count=len(plan.record_sets),
        physical_page_count=plan.physical_page_count,
        issuance_ids=tuple(item.issuance.issuance_id for item in plan.record_sets),
        page_ids=tuple(
            page.page_id for item in plan.record_sets for page in item.pages
        ),
        route_ids=route_ids,
        planned_route_count=len(route_ids),
        created_route_count=len(durable_paths),
        verified_route_count=len(verified_paths),
        installed=installed,
        replaced_previous_output=plan.replaced_existing and (success or installed),
        predecessor_count=sum(item is not None for item in plan.predecessors),
        superseded_predecessor_count=superseded,
        failure_stage=stage,
        error=error,
        warnings=tuple(warnings),
        created_registration_paths=durable_paths,
        verified_registration_paths=verified_paths,
        failed_predecessor_ids=tuple(failed_predecessor_ids),
    )


def execute_answer_sheet_artifact(
    workspace_root: str | Path,
    work_ref: ModuleWorkRef,
    plan: AnswerSheetArtifactPlan,
) -> AnswerSheetArtifactResult:
    """Execute one artifact transaction in the contractually required order."""
    persisted_records: list[AnswerSheetRecordSet] = []
    registered: list[RegisteredAnswerSheetPageRoute] = []
    try:
        for record_set in plan.record_sets:
            write_answer_sheet_record_set(workspace_root, work_ref, record_set)
            persisted_records.append(record_set)
    except Exception as error:
        compensation = _transition_many(
            workspace_root,
            work_ref,
            persisted_records,
            status="cancelled",
            reason="Answer-sheet record persistence failed before route creation.",
        )
        cleanup = _remove_temporary_artifact(plan.temporary_path)
        warnings = _failure_warnings(compensation, cleanup)
        return _result(
            plan, success=False, stage="record_persistence", error=str(error), warnings=warnings
        )

    try:
        # Artifact-wide preflight ensures packet rendering cannot begin after only a
        # subset of its route destinations were checked.
        for record_set, route_set in zip(
            plan.record_sets, plan.route_sets, strict=True
        ):
            preflight_answer_sheet_route_set(
                workspace_root, work_ref, record_set, route_set
            )
        for record_set, route_set in zip(
            plan.record_sets, plan.route_sets, strict=True
        ):
            persisted = persist_answer_sheet_route_set(
                workspace_root, work_ref, record_set, route_set
            )
            registered.extend(persisted.routes)
    except Exception as error:
        created_paths = tuple(getattr(error, "created_paths", ()))
        registered.extend(getattr(error, "verified_routes", ()))
        any_route = bool(registered or created_paths)
        compensation = _transition_many(
            workspace_root,
            work_ref,
            persisted_records,
            status="invalidated" if any_route else "cancelled",
            reason=(
                "Core route registration failed during answer-sheet generation."
                if any_route
                else "Route preflight failed before any Core registration was created."
            ),
        )
        cleanup = _remove_temporary_artifact(plan.temporary_path)
        warnings = _failure_warnings(compensation, cleanup)
        return _result(
            plan,
            success=False,
            stage="route_persistence",
            error=str(error),
            registered=registered,
            created_paths=created_paths,
            warnings=warnings,
        )

    grouped: list[tuple[RegisteredAnswerSheetPageRoute, ...]] = []
    cursor = 0
    for route_set in plan.route_sets:
        grouped.append(tuple(registered[cursor : cursor + len(route_set)]))
        cursor += len(route_set)
    try:
        render_registered_answer_sheet_pdf(
            plan.temporary_path,
            plan.assignment,
            tuple(zip(plan.students, grouped, strict=True)),
        )
        if (
            plan.temporary_path.is_symlink()
            or not plan.temporary_path.is_file()
            or plan.temporary_path.stat().st_size == 0
        ):
            raise AnswerSheetGenerationError(
                "Temporary PDF is missing, not regular, or empty."
            )
        # Windows requires a writable descriptor for fsync/commit.
        descriptor = os.open(plan.temporary_path, os.O_RDWR)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except Exception as error:
        compensation = _transition_many(
            workspace_root,
            work_ref,
            persisted_records,
            status="invalidated",
            reason="Temporary answer-sheet PDF rendering failed.",
        )
        cleanup = _remove_temporary_artifact(plan.temporary_path)
        return _result(
            plan,
            success=False,
            stage="pdf_rendering",
            error=str(error),
            registered=registered,
            warnings=_failure_warnings(compensation, cleanup),
        )

    finalized: list[AnswerSheetRecordSet] = []
    timestamp = datetime.now(timezone.utc)
    try:
        for record_set in plan.record_sets:
            transition_answer_sheet_issuance(
                workspace_root,
                work_ref,
                record_set.issuance.issuance_id,
                expected_revision=1,
                new_status="issued",
                timestamp=timestamp,
            )
            finalized.append(record_set)
    except Exception as error:
        compensation = _transition_many(
            workspace_root,
            work_ref,
            persisted_records,
            status="invalidated",
            reason="Answer-sheet issuance finalization failed.",
        )
        cleanup = _remove_temporary_artifact(plan.temporary_path)
        return _result(
            plan,
            success=False,
            stage="issuance_finalization",
            error=str(error),
            registered=registered,
            warnings=_failure_warnings(compensation, cleanup),
        )

    try:
        os.replace(plan.temporary_path, plan.output_path)
    except OSError as error:
        compensation = _transition_many(
            workspace_root,
            work_ref,
            persisted_records,
            status="invalidated",
            reason="Canonical answer-sheet PDF installation failed.",
        )
        cleanup = _remove_temporary_artifact(plan.temporary_path)
        return _result(
            plan,
            success=False,
            stage="pdf_installation",
            error=str(error),
            registered=registered,
            warnings=_failure_warnings(compensation, cleanup),
        )

    superseded = 0
    supersession_errors: list[str] = []
    supersession_timestamp = datetime.now(timezone.utc)
    for predecessor, replacement in zip(
        plan.predecessors, plan.record_sets, strict=True
    ):
        if predecessor is None:
            continue
        try:
            transition_answer_sheet_issuance(
                workspace_root,
                work_ref,
                predecessor.issuance_id,
                expected_revision=predecessor.lifecycle.revision,
                new_status="superseded",
                timestamp=supersession_timestamp,
                reason="Replaced by successful ScoreForm regeneration.",
                replacement_issuance_id=replacement.issuance.issuance_id,
            )
            superseded += 1
        except Exception as error:
            supersession_errors.append(f"{predecessor.issuance_id}: {error}")
    if supersession_errors:
        failed_predecessor_ids = tuple(
            predecessor.issuance_id
            for predecessor in plan.predecessors
            if predecessor is not None
            and any(
                item.startswith(f"{predecessor.issuance_id}:")
                for item in supersession_errors
            )
        )
        return _result(
            plan,
            success=False,
            stage="predecessor_supersession",
            error="; ".join(supersession_errors),
            registered=registered,
            superseded=superseded,
            installed=True,
            failed_predecessor_ids=failed_predecessor_ids,
            warnings=(
                "The new PDF is installed and its new issuances remain issued, but "
                "one or more predecessors could not be superseded.",
            ),
        )
    return _result(
        plan,
        success=True,
        stage=None,
        error=None,
        registered=registered,
        superseded=superseded,
        installed=True,
    )


def generate_managed_answer_sheets(
    workspace_root: str | Path,
    work_ref: ModuleWorkRef,
    assignment: Mapping[str, object],
    roster: Mapping[str, object],
    *,
    individual_dir: str | Path,
    class_packet_path: str | Path,
    student_filename: Callable[[Mapping[str, object]], str],
    generation_id: str | None = None,
    route_id_generator: Callable[[], str] = generate_route_id,
) -> AnswerSheetGenerationResult:
    """Generate individual artifacts then one packet under one generation ID."""
    selected_generation_id = generation_id or generate_generation_id()
    students_value = roster.get("students")
    if not isinstance(students_value, list) or not students_value:
        raise AnswerSheetGenerationPreflightError(
            "Managed roster must contain at least one student."
        )
    students = tuple(students_value)
    used_issuance_ids: set[str] = set()
    used_page_ids: set[str] = set()
    used_route_ids: set[str] = set()
    results: list[AnswerSheetArtifactResult] = []

    artifact_requests = [
        ("individual_pdf", (student,), Path(individual_dir) / student_filename(student))
        for student in students
    ]
    artifact_requests.append(
        ("class_packet_pdf", students, Path(class_packet_path))
    )
    for output_kind, artifact_students, output_path in artifact_requests:
        try:
            plan = plan_answer_sheet_artifact(
                workspace_root,
                work_ref,
                assignment,
                artifact_students,
                output_path,
                output_kind=output_kind,
                generation_id=selected_generation_id,
                used_issuance_ids=used_issuance_ids,
                used_page_ids=used_page_ids,
                used_route_ids=used_route_ids,
                route_id_generator=route_id_generator,
            )
        except AnswerSheetGenerationPreflightError as error:
            # No durable identity from this artifact was written.  Earlier artifacts
            # are intentionally preserved and reported as completed.
            results.append(
                AnswerSheetArtifactResult(
                    generation_id=selected_generation_id,
                    artifact_id="",
                    output_path=os.fspath(output_path),
                    output_kind=output_kind,
                    success=False,
                    student_count=len(artifact_students),
                    issuance_count=0,
                    physical_page_count=0,
                    issuance_ids=(),
                    page_ids=(),
                    route_ids=(),
                    planned_route_count=0,
                    created_route_count=0,
                    verified_route_count=0,
                    installed=False,
                    replaced_previous_output=False,
                    predecessor_count=0,
                    superseded_predecessor_count=0,
                    failure_stage="preflight",
                    error=str(error),
                    warnings=tuple(getattr(error, "__notes__", ())),
                )
            )
            break
        except Exception as error:
            results.append(
                AnswerSheetArtifactResult(
                    generation_id=selected_generation_id,
                    artifact_id="",
                    output_path=os.fspath(output_path),
                    output_kind=output_kind,
                    success=False,
                    student_count=len(artifact_students),
                    issuance_count=0,
                    physical_page_count=0,
                    issuance_ids=(),
                    page_ids=(),
                    route_ids=(),
                    planned_route_count=0,
                    created_route_count=0,
                    verified_route_count=0,
                    installed=False,
                    replaced_previous_output=False,
                    predecessor_count=0,
                    superseded_predecessor_count=0,
                    failure_stage="orchestration",
                    error=str(error),
                    warnings=tuple(getattr(error, "__notes__", ())),
                )
            )
            break
        artifact_result = execute_answer_sheet_artifact(
            workspace_root, work_ref, plan
        )
        results.append(artifact_result)
        if not artifact_result.success:
            break
    return AnswerSheetGenerationResult(selected_generation_id, tuple(results))
