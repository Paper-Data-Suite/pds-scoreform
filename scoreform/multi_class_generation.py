"""Read-only planning primitives for multi-class managed answer-sheet generation."""

from __future__ import annotations

import contextlib
import hashlib
import io
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence

from scoreform.answer_sheet_generation import (
    AnswerSheetGenerationPreflightError,
    AnswerSheetGenerationResult,
    AnswerSheetPredecessorError,
    discover_answer_sheet_issuances,
    preflight_generation_dependencies,
    select_current_predecessor,
)
from scoreform.answer_sheet_records import generate_generation_id
from scoreform.assignment import AssignmentJsonBytesError, assignment_from_json_bytes
from scoreform.diagnostic_events import try_emit_diagnostic_event
from scoreform.layouts import get_layout
from scoreform.paging import page_count_for_question_count
from scoreform.roster import LegacyRoster, load_roster
from scoreform.templates import student_pdf_filename
from scoreform.work_paths import ScoreFormWorkPaths, scoreform_work_paths


class MultiClassGenerationError(Exception):
    """Base error for multi-class generation planning."""


class MultiClassGenerationValidationError(MultiClassGenerationError, ValueError):
    """Raised when the requested target set itself is invalid."""


@dataclass(frozen=True, slots=True)
class GenerationTargetRef:
    """One exact class-qualified managed assignment target."""

    class_id: str
    assignment_id: str


@dataclass(frozen=True, slots=True)
class GenerationTargetDiagnostic:
    """One bounded reason a target is not currently ready for generation."""

    code: str
    message: str


@dataclass(frozen=True, slots=True)
class GenerationFileSnapshot:
    """Digest of exact reviewed file bytes without retaining sensitive contents."""

    path: Path
    sha256: str
    byte_count: int


@dataclass(frozen=True, slots=True)
class GenerationLineageSnapshot:
    """Digest of exact issuance JSON names and bytes for one managed work item."""

    sha256: str
    json_entry_count: int


@dataclass(frozen=True, slots=True)
class GenerationTargetPlan:
    """Read-only generation preview for one exact managed target."""

    target: GenerationTargetRef
    work_paths: ScoreFormWorkPaths | None
    assignment_snapshot: GenerationFileSnapshot | None
    roster_snapshot: GenerationFileSnapshot | None
    lineage_snapshot: GenerationLineageSnapshot | None
    title: str | None
    layout_id: str | None
    question_count: int | None
    student_count: int | None
    pages_per_student: int | None
    individual_pdf_count: int | None
    individual_physical_page_count: int | None
    class_packet_pdf_count: int | None
    class_packet_physical_page_count: int | None
    total_pdf_artifact_count: int | None
    total_physical_page_count: int | None
    expected_route_count: int | None
    generation_state: str | None
    current_predecessor_count: int | None
    diagnostics: tuple[GenerationTargetDiagnostic, ...]

    @property
    def ready(self) -> bool:
        """Return whether all read-only readiness checks succeeded."""
        return not self.diagnostics


@dataclass(frozen=True, slots=True)
class MultiClassGenerationPlan:
    """Ordered, non-persistent generation plan for several exact targets."""

    workspace_root: Path
    targets: tuple[GenerationTargetPlan, ...]

    @property
    def ready(self) -> bool:
        return bool(self.targets) and all(target.ready for target in self.targets)

    @property
    def ready_targets(self) -> tuple[GenerationTargetPlan, ...]:
        return tuple(target for target in self.targets if target.ready)

    @property
    def blocked_targets(self) -> tuple[GenerationTargetPlan, ...]:
        return tuple(target for target in self.targets if not target.ready)


@dataclass(frozen=True, slots=True)
class GenerationPlanFreshnessDiagnostic:
    """One reason a previously reviewed plan must be rebuilt."""

    target: GenerationTargetRef
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class MultiClassGenerationFreshness:
    """Current reinspection result for a previously reviewed plan."""

    current_plan: MultiClassGenerationPlan
    diagnostics: tuple[GenerationPlanFreshnessDiagnostic, ...]

    @property
    def fresh(self) -> bool:
        return not self.diagnostics


class MultiClassGenerationPlanNotReadyError(MultiClassGenerationError):
    """Raised when execution is requested for a plan containing blockers."""

    def __init__(self, plan: MultiClassGenerationPlan):
        self.plan = plan
        super().__init__(
            "Multi-class generation plan contains blocked targets; build a ready plan before generation."
        )


class MultiClassGenerationStalePlanError(MultiClassGenerationError):
    """Raised before execution when the reviewed batch is no longer current."""

    def __init__(self, freshness: MultiClassGenerationFreshness):
        self.freshness = freshness
        super().__init__(
            "Multi-class generation plan changed after preview; build a new plan before generation."
        )


class MultiClassGenerationGlobalExecutionError(MultiClassGenerationError):
    """Signal that continuing to later targets would be unsafe or meaningless."""


class TargetGenerationExecutor(Protocol):
    """Exact per-target generation adapter used by the batch orchestrator."""

    def __call__(
        self,
        workspace_root: Path,
        target: GenerationTargetPlan,
        generation_id: str,
    ) -> AnswerSheetGenerationResult: ...


@dataclass(frozen=True, slots=True)
class GenerationTargetOutcome:
    """Truthful durable outcome for one selected generation target."""

    target: GenerationTargetRef
    status: str
    generation_result: AnswerSheetGenerationResult | None
    class_packet_path: str | None
    individual_templates_dir: str | None
    failure_stage: str | None
    error: str | None
    warnings: tuple[str, ...] = ()

    @property
    def clean_success(self) -> bool:
        return self.status == "clean_success"

    @property
    def partial_success(self) -> bool:
        return self.status == "partial"

    @property
    def failed(self) -> bool:
        return self.status == "failed"

    @property
    def not_attempted(self) -> bool:
        return self.status == "not_attempted"

    @property
    def installed_artifact_count(self) -> int:
        if self.generation_result is None:
            return 0
        return self.generation_result.installed_artifact_count

    @property
    def verified_route_count(self) -> int:
        if self.generation_result is None:
            return 0
        return self.generation_result.installed_route_count


@dataclass(frozen=True, slots=True)
class MultiClassGenerationResult:
    """Ordered batch outcome; successful earlier targets are never erased."""

    generation_id: str
    outcomes: tuple[GenerationTargetOutcome, ...]

    @property
    def success(self) -> bool:
        return bool(self.outcomes) and all(item.clean_success for item in self.outcomes)

    @property
    def clean_success_count(self) -> int:
        return sum(item.clean_success for item in self.outcomes)

    @property
    def partial_success_count(self) -> int:
        return sum(item.partial_success for item in self.outcomes)

    @property
    def failed_count(self) -> int:
        return sum(item.failed for item in self.outcomes)

    @property
    def not_attempted_count(self) -> int:
        return sum(item.not_attempted for item in self.outcomes)

    @property
    def installed_artifact_count(self) -> int:
        return sum(item.installed_artifact_count for item in self.outcomes)

    @property
    def verified_route_count(self) -> int:
        return sum(item.verified_route_count for item in self.outcomes)


class _TargetInspectionError(ValueError):
    """Internal bounded validation failure while inspecting one target."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _lexists(path: Path) -> bool:
    return os.path.lexists(os.fspath(path))


def _workspace_descendant_chain(
    workspace_root: str | Path,
    descendant: Path,
) -> tuple[Path, ...]:
    root = Path(os.path.abspath(os.fspath(workspace_root)))
    target = Path(os.path.abspath(os.fspath(descendant)))
    try:
        relative = target.relative_to(root)
    except ValueError as error:
        raise _TargetInspectionError(
            f"Managed path escapes the workspace: {descendant}"
        ) from error

    current = root
    chain: list[Path] = []
    for component in relative.parts:
        current = current / component
        chain.append(current)
    return tuple(chain)


def _require_safe_existing_directory_chain(
    workspace_root: str | Path,
    directory: Path,
    *,
    label: str,
) -> None:
    for entry in _workspace_descendant_chain(workspace_root, directory):
        if not _lexists(entry):
            raise _TargetInspectionError(f"{label} path component is missing: {entry}")
        if entry.is_symlink():
            raise _TargetInspectionError(
                f"{label} path chain contains a symbolic link: {entry}"
            )
        if not entry.is_dir():
            raise _TargetInspectionError(
                f"{label} path chain contains a non-directory entry: {entry}"
            )


def _check_creatable_directory_chain(
    workspace_root: str | Path,
    directory: Path,
    *,
    label: str,
) -> None:
    """Check existing components only; never create a directory during planning."""
    existing_parent: Path | None = None
    for entry in _workspace_descendant_chain(workspace_root, directory):
        if not _lexists(entry):
            continue
        if entry.is_symlink():
            raise _TargetInspectionError(
                f"{label} path chain contains a symbolic link: {entry}"
            )
        if not entry.is_dir():
            raise _TargetInspectionError(
                f"{label} path chain contains a non-directory entry: {entry}"
            )
        existing_parent = entry

    if existing_parent is not None and not os.access(existing_parent, os.W_OK):
        raise _TargetInspectionError(
            f"{label} nearest existing parent is not writable: {existing_parent}"
        )


def _snapshot_regular_file(path: Path, *, label: str) -> GenerationFileSnapshot:
    if path.is_symlink():
        raise _TargetInspectionError(f"{label} must not be a symbolic link: {path}")
    if not _lexists(path):
        raise _TargetInspectionError(f"{label} does not exist: {path}")
    if not path.is_file():
        raise _TargetInspectionError(f"{label} is not a regular file: {path}")
    try:
        data = path.read_bytes()
    except OSError as error:
        raise _TargetInspectionError(f"Could not read {label}: {error}") from error
    return GenerationFileSnapshot(path, _sha256(data), len(data))


def _snapshot_issuance_lineage(
    paths: ScoreFormWorkPaths,
) -> GenerationLineageSnapshot:
    directory = paths.answer_sheet_issuances_dir
    if directory.is_symlink():
        raise _TargetInspectionError(
            f"Answer-sheet issuance directory must not be a symbolic link: {directory}"
        )
    if not directory.exists():
        return GenerationLineageSnapshot(_sha256(b"missing"), 0)
    if not directory.is_dir():
        raise _TargetInspectionError(
            f"Answer-sheet issuance path is not a directory: {directory}"
        )

    hasher = hashlib.sha256()
    count = 0
    for child in sorted(directory.iterdir(), key=lambda path: path.name):
        if child.is_symlink():
            raise _TargetInspectionError(
                f"Answer-sheet issuance collection contains a symbolic link: {child}"
            )
        if child.suffix != ".json":
            continue
        if not child.is_file():
            raise _TargetInspectionError(
                f"Answer-sheet issuance JSON is not a regular file: {child}"
            )
        try:
            data = child.read_bytes()
        except OSError as error:
            raise _TargetInspectionError(
                f"Could not read answer-sheet issuance JSON {child}: {error}"
            ) from error
        name = child.name.encode("utf-8")
        hasher.update(len(name).to_bytes(8, "big"))
        hasher.update(name)
        hasher.update(len(data).to_bytes(8, "big"))
        hasher.update(data)
        count += 1
    return GenerationLineageSnapshot(hasher.hexdigest(), count)


def _load_assignment_snapshot(
    workspace_root: str | Path,
    paths: ScoreFormWorkPaths,
) -> tuple[GenerationFileSnapshot, dict[str, object]]:
    _require_safe_existing_directory_chain(
        workspace_root,
        paths.work_root,
        label="Managed ScoreForm work root",
    )
    snapshot = _snapshot_regular_file(
        paths.assignment_path,
        label="Managed assignment.json",
    )
    try:
        assignment = assignment_from_json_bytes(paths.assignment_path.read_bytes())
    except (OSError, AssignmentJsonBytesError) as error:
        raise _TargetInspectionError(
            f"Managed assignment.json is invalid: {error}"
        ) from error
    if assignment.get("assignment_id") != paths.work_ref.work_id:
        raise _TargetInspectionError(
            "Managed assignment_id does not match its canonical work identity."
        )
    current = _snapshot_regular_file(
        paths.assignment_path,
        label="Managed assignment.json",
    )
    if current != snapshot:
        raise _TargetInspectionError(
            "Managed assignment.json changed while the generation plan was being built."
        )
    return snapshot, assignment


def _load_roster_snapshot(
    workspace_root: str | Path,
    paths: ScoreFormWorkPaths,
) -> tuple[GenerationFileSnapshot, LegacyRoster]:
    _require_safe_existing_directory_chain(
        workspace_root,
        paths.roster_path.parent,
        label="Managed class roster",
    )
    snapshot = _snapshot_regular_file(paths.roster_path, label="Managed roster.csv")
    diagnostics = io.StringIO()
    with contextlib.redirect_stdout(diagnostics):
        roster = load_roster(paths.roster_path)
    if roster is None:
        detail = diagnostics.getvalue().strip()
        raise _TargetInspectionError(detail or "Managed roster.csv is invalid.")
    current = _snapshot_regular_file(paths.roster_path, label="Managed roster.csv")
    if current != snapshot:
        raise _TargetInspectionError(
            "Managed roster.csv changed while the generation plan was being built."
        )
    if roster.get("class_id") != paths.work_ref.class_id:
        raise _TargetInspectionError(
            "Managed roster class_id does not match the selected target class."
        )
    students = roster.get("students")
    if not isinstance(students, list) or not students:
        raise _TargetInspectionError("Managed roster must contain at least one student.")
    return snapshot, roster


def _check_output_destinations(
    workspace_root: str | Path,
    paths: ScoreFormWorkPaths,
    roster: LegacyRoster,
) -> None:
    _check_creatable_directory_chain(
        workspace_root,
        paths.templates_dir,
        label="Managed templates directory",
    )
    _check_creatable_directory_chain(
        workspace_root,
        paths.individual_templates_dir,
        label="Managed individual-template directory",
    )

    if _lexists(paths.class_packet_path):
        if paths.class_packet_path.is_symlink():
            raise _TargetInspectionError(
                f"Class-packet output must not be a symbolic link: {paths.class_packet_path}"
            )
        if not paths.class_packet_path.is_file():
            raise _TargetInspectionError(
                f"Class-packet output is not a regular file: {paths.class_packet_path}"
            )

    students = roster["students"]
    filenames = tuple(student_pdf_filename(student) for student in students)
    if len(set(filenames)) != len(filenames):
        raise _TargetInspectionError(
            "Managed roster maps multiple students to the same individual PDF filename."
        )
    for filename in filenames:
        output = paths.individual_templates_dir / filename
        if not _lexists(output):
            continue
        if output.is_symlink():
            raise _TargetInspectionError(
                f"Individual PDF output must not be a symbolic link: {output}"
            )
        if not output.is_file():
            raise _TargetInspectionError(
                f"Individual PDF output is not a regular file: {output}"
            )


def _inspect_generation_lineage(
    workspace_root: str | Path,
    paths: ScoreFormWorkPaths,
    roster: LegacyRoster,
) -> tuple[GenerationLineageSnapshot, str, int]:
    before = _snapshot_issuance_lineage(paths)
    try:
        issuances = discover_answer_sheet_issuances(workspace_root, paths.work_ref)
        predecessors = []
        for student in roster["students"]:
            student_id = str(student.get("student_id", ""))
            predecessors.append(
                select_current_predecessor(
                    issuances,
                    work_ref=paths.work_ref,
                    student_id=student_id,
                    output_kind="individual_pdf",
                )
            )
            predecessors.append(
                select_current_predecessor(
                    issuances,
                    work_ref=paths.work_ref,
                    student_id=student_id,
                    output_kind="class_packet_pdf",
                )
            )
    except (AnswerSheetPredecessorError, ValueError, OSError) as error:
        raise _TargetInspectionError(
            f"Current answer-sheet issuance state is not safely generatable: {error}"
        ) from error
    after = _snapshot_issuance_lineage(paths)
    if after != before:
        raise _TargetInspectionError(
            "Answer-sheet issuance state changed while the generation plan was being built."
        )

    current_count = sum(predecessor is not None for predecessor in predecessors)
    if current_count == 0:
        generation_state = "initial"
    elif current_count == len(predecessors):
        generation_state = "regeneration"
    else:
        generation_state = "mixed"
    return before, generation_state, current_count


def _diagnostic(code: str, message: str) -> GenerationTargetDiagnostic:
    return GenerationTargetDiagnostic(code=code, message=message)


def inspect_generation_target(
    workspace_root: str | Path,
    target: GenerationTargetRef,
) -> GenerationTargetPlan:
    """Inspect one target without allocating identity or mutating the workspace."""
    if not isinstance(target, GenerationTargetRef):
        raise MultiClassGenerationValidationError(
            "target must be a GenerationTargetRef."
        )

    diagnostics: list[GenerationTargetDiagnostic] = []
    paths: ScoreFormWorkPaths | None = None
    assignment_snapshot: GenerationFileSnapshot | None = None
    roster_snapshot: GenerationFileSnapshot | None = None
    lineage_snapshot: GenerationLineageSnapshot | None = None
    assignment: dict[str, object] | None = None
    roster: LegacyRoster | None = None
    title: str | None = None
    layout_id: str | None = None
    question_count: int | None = None
    student_count: int | None = None
    pages_per_student: int | None = None
    generation_state: str | None = None
    current_predecessor_count: int | None = None

    try:
        paths = scoreform_work_paths(
            workspace_root,
            target.class_id,
            target.assignment_id,
        )
    except (TypeError, ValueError) as error:
        diagnostics.append(_diagnostic("invalid_target_identity", str(error)))

    if paths is not None:
        try:
            assignment_snapshot, assignment = _load_assignment_snapshot(
                workspace_root,
                paths,
            )
        except _TargetInspectionError as error:
            diagnostics.append(_diagnostic("assignment_not_ready", str(error)))

        try:
            roster_snapshot, roster = _load_roster_snapshot(workspace_root, paths)
        except _TargetInspectionError as error:
            diagnostics.append(_diagnostic("roster_not_ready", str(error)))

    if assignment is not None:
        raw_title = assignment.get("title")
        raw_layout_id = assignment.get("layout_id")
        raw_question_count = assignment.get("question_count")
        if isinstance(raw_title, str):
            title = raw_title
        if isinstance(raw_layout_id, str):
            layout_id = raw_layout_id
        if isinstance(raw_question_count, int) and not isinstance(
            raw_question_count, bool
        ):
            question_count = raw_question_count
        try:
            layout = get_layout(layout_id)
            if question_count is None:
                raise ValueError("Validated assignment question_count is unavailable.")
            pages_per_student = page_count_for_question_count(question_count, layout)
        except ValueError as error:
            diagnostics.append(_diagnostic("layout_not_ready", str(error)))

    if roster is not None:
        student_count = len(roster["students"])

    try:
        preflight_generation_dependencies()
    except AnswerSheetGenerationPreflightError as error:
        diagnostics.append(_diagnostic("dependencies_not_ready", str(error)))

    if paths is not None and roster is not None:
        try:
            _check_output_destinations(workspace_root, paths, roster)
        except _TargetInspectionError as error:
            diagnostics.append(_diagnostic("output_not_ready", str(error)))

        try:
            (
                lineage_snapshot,
                generation_state,
                current_predecessor_count,
            ) = _inspect_generation_lineage(workspace_root, paths, roster)
        except _TargetInspectionError as error:
            diagnostics.append(_diagnostic("issuance_state_not_ready", str(error)))

    individual_pdf_count: int | None = None
    individual_physical_page_count: int | None = None
    class_packet_pdf_count: int | None = None
    class_packet_physical_page_count: int | None = None
    total_pdf_artifact_count: int | None = None
    total_physical_page_count: int | None = None
    expected_route_count: int | None = None
    if student_count is not None and pages_per_student is not None:
        individual_pdf_count = student_count
        individual_physical_page_count = student_count * pages_per_student
        class_packet_pdf_count = 1
        class_packet_physical_page_count = student_count * pages_per_student
        total_pdf_artifact_count = student_count + 1
        total_physical_page_count = (
            individual_physical_page_count + class_packet_physical_page_count
        )
        expected_route_count = total_physical_page_count

    return GenerationTargetPlan(
        target=target,
        work_paths=paths,
        assignment_snapshot=assignment_snapshot,
        roster_snapshot=roster_snapshot,
        lineage_snapshot=lineage_snapshot,
        title=title,
        layout_id=layout_id,
        question_count=question_count,
        student_count=student_count,
        pages_per_student=pages_per_student,
        individual_pdf_count=individual_pdf_count,
        individual_physical_page_count=individual_physical_page_count,
        class_packet_pdf_count=class_packet_pdf_count,
        class_packet_physical_page_count=class_packet_physical_page_count,
        total_pdf_artifact_count=total_pdf_artifact_count,
        total_physical_page_count=total_physical_page_count,
        expected_route_count=expected_route_count,
        generation_state=generation_state,
        current_predecessor_count=current_predecessor_count,
        diagnostics=tuple(diagnostics),
    )


def plan_multi_class_generation(
    workspace_root: str | Path,
    targets: Sequence[GenerationTargetRef],
) -> MultiClassGenerationPlan:
    """Build one ordered read-only plan and collect target-local blockers."""
    requested = tuple(targets)
    if not requested:
        raise MultiClassGenerationValidationError(
            "Multi-class generation requires at least one target."
        )
    if any(not isinstance(target, GenerationTargetRef) for target in requested):
        raise MultiClassGenerationValidationError(
            "Every generation target must be a GenerationTargetRef."
        )

    seen: set[tuple[str, str]] = set()
    for target in requested:
        identity = (target.class_id, target.assignment_id)
        if identity in seen:
            raise MultiClassGenerationValidationError(
                "Duplicate generation target: "
                f"{target.class_id}/{target.assignment_id}"
            )
        seen.add(identity)

    root = Path(workspace_root)
    return MultiClassGenerationPlan(
        workspace_root=root,
        targets=tuple(inspect_generation_target(root, target) for target in requested),
    )


def _freshness_diagnostic(
    target: GenerationTargetRef,
    code: str,
    message: str,
) -> GenerationPlanFreshnessDiagnostic:
    return GenerationPlanFreshnessDiagnostic(target, code, message)


def _target_freshness_diagnostics(
    reviewed: GenerationTargetPlan,
    refreshed: GenerationTargetPlan,
) -> tuple[GenerationPlanFreshnessDiagnostic, ...]:
    target = reviewed.target
    diagnostics: list[GenerationPlanFreshnessDiagnostic] = []
    if not reviewed.ready:
        diagnostics.append(
            _freshness_diagnostic(
                target,
                "reviewed_target_blocked",
                "The reviewed plan already contained a blocked target; build a ready plan before generation.",
            )
        )
    if not refreshed.ready:
        diagnostics.append(
            _freshness_diagnostic(
                target,
                "target_now_blocked",
                "Target is no longer ready: "
                + "; ".join(item.message for item in refreshed.diagnostics),
            )
        )
    if reviewed.assignment_snapshot != refreshed.assignment_snapshot:
        diagnostics.append(
            _freshness_diagnostic(
                target,
                "assignment_changed",
                "Managed assignment.json changed after preview; build a new plan.",
            )
        )
    if reviewed.roster_snapshot != refreshed.roster_snapshot:
        diagnostics.append(
            _freshness_diagnostic(
                target,
                "roster_changed",
                "Managed roster.csv changed after preview; build a new plan.",
            )
        )
    if reviewed.lineage_snapshot != refreshed.lineage_snapshot:
        diagnostics.append(
            _freshness_diagnostic(
                target,
                "issuance_state_changed",
                "Answer-sheet issuance state changed after preview; build a new plan.",
            )
        )
    return tuple(diagnostics)


def revalidate_multi_class_generation_plan(
    plan: MultiClassGenerationPlan,
) -> MultiClassGenerationFreshness:
    """Reinspect every target and report all reasons the reviewed plan is stale."""
    if not isinstance(plan, MultiClassGenerationPlan):
        raise MultiClassGenerationValidationError(
            "plan must be a MultiClassGenerationPlan."
        )
    refs = tuple(target.target for target in plan.targets)
    current = plan_multi_class_generation(plan.workspace_root, refs)
    diagnostics = tuple(
        diagnostic
        for reviewed, refreshed in zip(plan.targets, current.targets, strict=True)
        for diagnostic in _target_freshness_diagnostics(reviewed, refreshed)
    )
    return MultiClassGenerationFreshness(current, diagnostics)


@dataclass(slots=True)
class _BatchPhysicalIdentityRegistry:
    """Shared burned-identity sets for one executing batch only."""

    artifact_ids: set[str]
    issuance_ids: set[str]
    page_ids: set[str]
    route_ids: set[str]

    @classmethod
    def empty(cls) -> "_BatchPhysicalIdentityRegistry":
        return cls(set(), set(), set(), set())


def _default_target_executor(
    identity_registry: _BatchPhysicalIdentityRegistry,
) -> TargetGenerationExecutor:
    def execute(
        workspace_root: Path,
        target: GenerationTargetPlan,
        generation_id: str,
    ) -> AnswerSheetGenerationResult:
        from scoreform.generate_workflows import regenerate_answer_sheets_for_assignment

        result = regenerate_answer_sheets_for_assignment(
            target.target.class_id,
            target.target.assignment_id,
            workspace_root,
            generation_id=generation_id,
            used_artifact_ids=identity_registry.artifact_ids,
            used_issuance_ids=identity_registry.issuance_ids,
            used_page_ids=identity_registry.page_ids,
            used_route_ids=identity_registry.route_ids,
        )
        if result.generation_result is None:
            raise MultiClassGenerationGlobalExecutionError(
                "Managed generation returned no structured generation result."
            )
        return result.generation_result

    return execute


def _outcome_paths(target: GenerationTargetPlan) -> tuple[str | None, str | None]:
    if target.work_paths is None:
        return None, None
    return (
        os.fspath(target.work_paths.class_packet_path),
        os.fspath(target.work_paths.individual_templates_dir),
    )


def _generation_failure_details(
    generation_result: AnswerSheetGenerationResult,
) -> tuple[str | None, str | None, tuple[str, ...]]:
    failed = next(
        (item for item in reversed(generation_result.artifacts) if not item.success),
        None,
    )
    if failed is None:
        return None, None, ()
    warnings = tuple(
        warning
        for artifact in generation_result.artifacts
        for warning in artifact.warnings
    )
    return failed.failure_stage, failed.error, warnings


def _outcome_from_generation_result(
    target: GenerationTargetPlan,
    generation_result: AnswerSheetGenerationResult,
) -> GenerationTargetOutcome:
    packet_path, individual_dir = _outcome_paths(target)
    stage, error, warnings = _generation_failure_details(generation_result)
    if generation_result.success:
        status = "clean_success"
    elif generation_result.installed_artifact_count:
        status = "partial"
    else:
        status = "failed"
    return GenerationTargetOutcome(
        target=target.target,
        status=status,
        generation_result=generation_result,
        class_packet_path=packet_path,
        individual_templates_dir=individual_dir,
        failure_stage=stage,
        error=error,
        warnings=warnings,
    )


def _exception_outcome(
    target: GenerationTargetPlan,
    *,
    stage: str,
    error: Exception | str,
) -> GenerationTargetOutcome:
    packet_path, individual_dir = _outcome_paths(target)
    return GenerationTargetOutcome(
        target=target.target,
        status="failed",
        generation_result=None,
        class_packet_path=packet_path,
        individual_templates_dir=individual_dir,
        failure_stage=stage,
        error=str(error),
        warnings=tuple(getattr(error, "__notes__", ())) if isinstance(error, Exception) else (),
    )


def _not_attempted_outcome(
    target: GenerationTargetPlan,
    *,
    reason: str,
) -> GenerationTargetOutcome:
    packet_path, individual_dir = _outcome_paths(target)
    return GenerationTargetOutcome(
        target=target.target,
        status="not_attempted",
        generation_result=None,
        class_packet_path=packet_path,
        individual_templates_dir=individual_dir,
        failure_stage="batch_aborted",
        error=reason,
    )


def _is_global_execution_error(error: Exception) -> bool:
    if isinstance(error, MultiClassGenerationGlobalExecutionError):
        return True
    if isinstance(error, AnswerSheetGenerationPreflightError):
        return "Missing answer-sheet generation dependencies" in str(error)
    return not isinstance(
        error,
        (AnswerSheetGenerationPreflightError, FileNotFoundError, OSError, RuntimeError, ValueError),
    )


def execute_multi_class_generation(
    plan: MultiClassGenerationPlan,
    *,
    target_executor: TargetGenerationExecutor | None = None,
) -> MultiClassGenerationResult:
    """Execute a reviewed plan in order without pretending the batch is atomic."""
    if not isinstance(plan, MultiClassGenerationPlan):
        raise MultiClassGenerationValidationError(
            "plan must be a MultiClassGenerationPlan."
        )
    if not plan.ready:
        first_blocked = plan.blocked_targets[0]
        try_emit_diagnostic_event(
            plan.workspace_root,
            component="generation",
            workflow="generate_multi_class_answer_sheets",
            stage="validate_input",
            outcome="blocked",
            code="generation_preflight_failed",
            class_id=first_blocked.target.class_id,
            assignment_id=first_blocked.target.assignment_id,
        )
        raise MultiClassGenerationPlanNotReadyError(plan)

    freshness = revalidate_multi_class_generation_plan(plan)
    if not freshness.fresh:
        stale_target = freshness.diagnostics[0].target
        try_emit_diagnostic_event(
            plan.workspace_root,
            component="generation",
            workflow="generate_multi_class_answer_sheets",
            stage="validate_input",
            outcome="blocked",
            code="generation_conflict",
            class_id=stale_target.class_id,
            assignment_id=stale_target.assignment_id,
        )
        raise MultiClassGenerationStalePlanError(freshness)

    identity_registry = _BatchPhysicalIdentityRegistry.empty()
    executor = target_executor or _default_target_executor(identity_registry)
    generation_id = generate_generation_id()
    outcomes: list[GenerationTargetOutcome] = []
    reviewed_targets = plan.targets

    for index, reviewed in enumerate(reviewed_targets):
        refreshed = inspect_generation_target(plan.workspace_root, reviewed.target)
        target_staleness = _target_freshness_diagnostics(reviewed, refreshed)
        if target_staleness:
            outcomes.append(
                _exception_outcome(
                    reviewed,
                    stage="stale_plan",
                    error="; ".join(item.message for item in target_staleness),
                )
            )
            continue

        try:
            generation_result = executor(
                plan.workspace_root,
                refreshed,
                generation_id,
            )
        except Exception as error:
            structured_result = getattr(error, "generation_result", None)
            if isinstance(structured_result, AnswerSheetGenerationResult):
                outcomes.append(
                    _outcome_from_generation_result(
                        refreshed,
                        structured_result,
                    )
                )
                continue

            outcomes.append(
                _exception_outcome(
                    refreshed,
                    stage=(
                        "global_execution"
                        if _is_global_execution_error(error)
                        else "target_execution"
                    ),
                    error=error,
                )
            )
            if _is_global_execution_error(error):
                reason = (
                    "Batch stopped after a shared or unexpected execution failure: "
                    + str(error)
                )
                outcomes.extend(
                    _not_attempted_outcome(target, reason=reason)
                    for target in reviewed_targets[index + 1 :]
                )
                break
            continue

        if not isinstance(generation_result, AnswerSheetGenerationResult):
            error = MultiClassGenerationGlobalExecutionError(
                "Target executor returned an unsupported result type."
            )
            outcomes.append(
                _exception_outcome(
                    refreshed,
                    stage="global_execution",
                    error=error,
                )
            )
            reason = "Batch stopped because target execution returned an invalid result."
            outcomes.extend(
                _not_attempted_outcome(target, reason=reason)
                for target in reviewed_targets[index + 1 :]
            )
            break

        outcomes.append(_outcome_from_generation_result(refreshed, generation_result))

    result = MultiClassGenerationResult(generation_id, tuple(outcomes))
    for outcome in result.outcomes:
        if outcome.clean_success:
            try_emit_diagnostic_event(
                plan.workspace_root,
                component="generation",
                workflow="generate_multi_class_answer_sheets",
                stage="verify_record",
                outcome="success",
                code="generation_verified",
                class_id=outcome.target.class_id,
                assignment_id=outcome.target.assignment_id,
            )
        elif outcome.partial_success:
            try_emit_diagnostic_event(
                plan.workspace_root,
                component="generation",
                workflow="generate_multi_class_answer_sheets",
                stage="post_write_verify",
                outcome="partial_success",
                code="generation_partial_success",
                class_id=outcome.target.class_id,
                assignment_id=outcome.target.assignment_id,
            )
    return result
