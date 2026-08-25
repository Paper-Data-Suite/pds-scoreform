"""Safe planning primitives for copying managed ScoreForm assignments."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from pds_core.academic_work_registration_storage import (
    AcademicWorkRegistrationStorageError,
    list_academic_work_registration_revisions,
)
from pds_core.class_metadata import (
    ClassMetadataError,
    class_metadata_path,
    load_class_metadata_for_class,
)
from pds_core.classes import load_class_roster
from pds_core.publication_storage import (
    PublicationStorageError,
    list_publication_records,
)
from pds_core.rosters import RosterError
from pds_core.routing_models import ModuleWorkRef
from pds_core.standards import StandardsLibrary

from scoreform.assignment import (
    AssignmentJsonBytesError,
    AssignmentStandardsAlignmentError,
    assignment_from_json_bytes,
    validate_assignment_data,
    validate_assignment_standard_alignments,
)
from scoreform.diagnostic_events import try_emit_diagnostic_event
from scoreform.work_paths import ScoreFormWorkPaths, scoreform_work_paths


class AssignmentCopyError(Exception):
    """Base error for safe assignment-copy planning."""


class AssignmentCopyValidationError(AssignmentCopyError, ValueError):
    """Raised when source or requested target configuration is invalid."""


class AssignmentCopyNotFoundError(AssignmentCopyError):
    """Raised when a required canonical source or target roster is missing."""


class AssignmentCopyConflictError(AssignmentCopyError):
    """Raised when source and target identities conflict."""


class AssignmentCopyWriteError(AssignmentCopyError):
    """Raised when one target cannot be created safely."""

    def __init__(
        self,
        message: str,
        *,
        residue_paths: Sequence[Path] = (),
    ) -> None:
        super().__init__(message)
        self.residue_paths = tuple(residue_paths)


@dataclass(frozen=True, slots=True)
class AssignmentCopyDefinition:
    """Immutable allowlisted assignment-definition snapshot."""

    assignment_id: str
    title: str
    question_count: int
    choices: tuple[str, ...]
    layout_id: str
    answer_key: tuple[tuple[int, str], ...]
    standards: tuple[tuple[int, tuple[str, ...]], ...]
    standards_profile_id: str | None

    def build_candidate(
        self,
        *,
        assignment_id: str,
        title: str | None = None,
    ) -> dict[str, object]:
        """Build one independent target assignment from allowlisted fields only."""
        candidate: dict[str, object] = {
            "assignment_id": assignment_id,
            "title": self.title if title is None else title,
            "question_count": self.question_count,
            "choices": list(self.choices),
            "layout_id": self.layout_id,
            "answer_key": {
                question_number: answer
                for question_number, answer in self.answer_key
            },
            "standards": {
                str(question_number): list(standard_ids)
                for question_number, standard_ids in self.standards
            },
        }
        if self.standards_profile_id is not None:
            candidate["standards_profile_id"] = self.standards_profile_id

        diagnostics = io.StringIO()
        with contextlib.redirect_stdout(diagnostics):
            normalized = validate_assignment_data(candidate)
        if normalized is None:
            detail = diagnostics.getvalue().strip()
            raise AssignmentCopyValidationError(
                detail or "Target assignment configuration is invalid."
            )
        return normalized


@dataclass(frozen=True, slots=True)
class AssignmentCopySource:
    """Exact canonical source assignment snapshot reviewed for copying."""

    work: ModuleWorkRef
    work_root: Path
    assignment_path: Path
    assignment_sha256: str
    assignment_bytes: bytes
    definition: AssignmentCopyDefinition


@dataclass(frozen=True, slots=True)
class AssignmentCopyRosterSummary:
    """Privacy-minimal Core roster context for one target class."""

    class_id: str
    student_count: int
    periods: tuple[str, ...]
    school_year: str | None
    metadata_warning: str | None


@dataclass(frozen=True, slots=True)
class AssignmentCopyTarget:
    """One canonical class-qualified target in a non-mutating copy plan."""

    work: ModuleWorkRef
    work_root: Path
    assignment_path: Path
    roster: AssignmentCopyRosterSummary


@dataclass(frozen=True, slots=True)
class AssignmentCopyPlan:
    """Immutable non-persistent plan for one assignment-copy operation."""

    source: AssignmentCopySource
    candidate: dict[str, object]
    candidate_sha256: str
    targets: tuple[AssignmentCopyTarget, ...]


@dataclass(frozen=True, slots=True)
class AssignmentCopyCreatedTarget:
    """One target assignment durably created and revalidated."""

    work: ModuleWorkRef
    assignment_path: Path


@dataclass(frozen=True, slots=True)
class AssignmentCopyTargetFailure:
    """Truthful failure state for one target attempted during commit."""

    target: AssignmentCopyTarget
    message: str
    residue_paths: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class AssignmentCopyResult:
    """Commit outcome; runtime failure never erases earlier durable success."""

    source: AssignmentCopySource
    candidate: dict[str, object]
    created: tuple[AssignmentCopyCreatedTarget, ...]
    failures: tuple[AssignmentCopyTargetFailure, ...]
    not_attempted: tuple[AssignmentCopyTarget, ...]

    @property
    def complete(self) -> bool:
        return not self.failures and not self.not_attempted


def _definition_from_assignment(
    assignment: dict[str, object],
) -> AssignmentCopyDefinition:
    answer_key = assignment["answer_key"]
    standards = assignment["standards"]
    if not isinstance(answer_key, dict) or not isinstance(standards, dict):
        raise AssignmentCopyValidationError(
            "Validated assignment did not contain normalized key/alignment mappings."
        )

    question_count = assignment["question_count"]
    if not isinstance(question_count, int):
        raise AssignmentCopyValidationError(
            "Validated assignment question_count is not an integer."
        )

    choices = assignment["choices"]
    if not isinstance(choices, list) or any(
        not isinstance(choice, str) for choice in choices
    ):
        raise AssignmentCopyValidationError(
            "Validated assignment choices are not normalized strings."
        )

    normalized_key: list[tuple[int, str]] = []
    normalized_standards: list[tuple[int, tuple[str, ...]]] = []
    for question_number in range(1, question_count + 1):
        answer = answer_key.get(question_number)
        if not isinstance(answer, str):
            raise AssignmentCopyValidationError(
                f"Validated assignment is missing answer key question {question_number}."
            )
        normalized_key.append((question_number, answer))

        values = standards.get(str(question_number), [])
        if not isinstance(values, list) or any(
            not isinstance(value, str) for value in values
        ):
            raise AssignmentCopyValidationError(
                "Validated assignment standards are not normalized strings."
            )
        normalized_standards.append((question_number, tuple(values)))

    standards_profile_id = assignment.get("standards_profile_id")
    if standards_profile_id is not None and not isinstance(
        standards_profile_id, str
    ):
        raise AssignmentCopyValidationError(
            "Validated standards_profile_id is not a string."
        )

    assignment_id = assignment["assignment_id"]
    if not isinstance(assignment_id, str):
        raise AssignmentCopyValidationError(
            "Validated assignment_id is not a normalized string."
        )

    title = assignment["title"]
    if not isinstance(title, str):
        raise AssignmentCopyValidationError(
            "Validated assignment title is not a normalized string."
        )

    layout_id = assignment["layout_id"]
    if not isinstance(layout_id, str):
        raise AssignmentCopyValidationError(
            "Validated assignment layout_id is not a normalized string."
        )

    return AssignmentCopyDefinition(
        assignment_id=assignment_id,
        title=title,
        question_count=question_count,
        choices=tuple(choices),
        layout_id=layout_id,
        answer_key=tuple(normalized_key),
        standards=tuple(normalized_standards),
        standards_profile_id=standards_profile_id,
    )


def _requires_standards_library(assignment: dict[str, object]) -> bool:
    if assignment.get("standards_profile_id") is not None:
        return True
    standards = assignment.get("standards")
    return isinstance(standards, dict) and any(bool(values) for values in standards.values())


def load_assignment_copy_source(
    workspace_root: str | Path,
    source_class_id: str,
    source_assignment_id: str,
    *,
    standards_library: StandardsLibrary | None = None,
) -> AssignmentCopySource:
    """Load one exact canonical source assignment without reading work descendants."""
    try:
        paths = scoreform_work_paths(
            workspace_root,
            source_class_id,
            source_assignment_id,
        )
    except (TypeError, ValueError) as error:
        raise AssignmentCopyValidationError(str(error)) from error

    if paths.work_root.is_symlink():
        raise AssignmentCopyValidationError(
            f"Source work root must not be a symbolic link: {paths.work_root}"
        )
    if not paths.work_root.exists() or not paths.work_root.is_dir():
        raise AssignmentCopyNotFoundError(
            f"Source work root does not exist: {paths.work_root}"
        )
    _preflight_source_directory_chain(workspace_root, paths.work_root)
    if paths.assignment_path.is_symlink():
        raise AssignmentCopyValidationError(
            f"Source assignment.json must not be a symbolic link: {paths.assignment_path}"
        )
    if not paths.assignment_path.exists() or not paths.assignment_path.is_file():
        raise AssignmentCopyNotFoundError(
            f"Source assignment.json does not exist: {paths.assignment_path}"
        )

    try:
        assignment_bytes = paths.assignment_path.read_bytes()
    except OSError as error:
        raise AssignmentCopyValidationError(
            f"Could not read source assignment.json: {error}"
        ) from error

    try:
        assignment = assignment_from_json_bytes(assignment_bytes)
    except AssignmentJsonBytesError as error:
        raise AssignmentCopyValidationError(
            f"Source assignment.json is invalid: {error}"
        ) from error

    if assignment["assignment_id"] != paths.work_ref.work_id:
        raise AssignmentCopyValidationError(
            "Source assignment_id does not match its canonical managed work identity."
        )

    if _requires_standards_library(assignment) and standards_library is None:
        raise AssignmentCopyValidationError(
            "A current PDS Core standards library is required to copy this assignment."
        )
    if standards_library is not None:
        try:
            validate_assignment_standard_alignments(assignment, standards_library)
        except AssignmentStandardsAlignmentError as error:
            raise AssignmentCopyValidationError(
                f"Source standards configuration is not currently valid: {error}"
            ) from error

    return AssignmentCopySource(
        work=paths.work_ref,
        work_root=paths.work_root,
        assignment_path=paths.assignment_path,
        assignment_sha256=hashlib.sha256(assignment_bytes).hexdigest(),
        assignment_bytes=assignment_bytes,
        definition=_definition_from_assignment(assignment),
    )


def build_assignment_copy_candidate(
    source: AssignmentCopySource,
    *,
    target_assignment_id: str,
    title: str | None = None,
) -> dict[str, object]:
    """Build a normalized independent target assignment without filesystem writes."""
    if not isinstance(source, AssignmentCopySource):
        raise AssignmentCopyValidationError(
            "source must be an AssignmentCopySource snapshot."
        )
    return source.definition.build_candidate(
        assignment_id=target_assignment_id,
        title=title,
    )


def _target_roster_summary(
    workspace_root: str | Path,
    class_id: str,
) -> AssignmentCopyRosterSummary:
    try:
        roster = load_class_roster(workspace_root, class_id)
    except RosterError as error:
        raise AssignmentCopyNotFoundError(
            f"Target class '{class_id}' does not have a valid Core roster: {error}"
        ) from error

    periods = tuple(sorted({student.period for student in roster.students}))
    school_year: str | None = None
    metadata_warning: str | None = None
    metadata_path = class_metadata_path(workspace_root, class_id)

    if metadata_path.is_symlink():
        metadata_warning = "Class metadata path is a symbolic link and was not read."
    elif metadata_path.is_file():
        try:
            metadata = load_class_metadata_for_class(workspace_root, class_id)
        except ClassMetadataError as error:
            metadata_warning = str(error)
        else:
            school_year = metadata.school_year

    return AssignmentCopyRosterSummary(
        class_id=class_id,
        student_count=len(roster.students),
        periods=periods,
        school_year=school_year,
        metadata_warning=metadata_warning,
    )


def _target_paths(
    workspace_root: str | Path,
    class_id: str,
    assignment_id: str,
) -> ScoreFormWorkPaths:
    try:
        return scoreform_work_paths(workspace_root, class_id, assignment_id)
    except (TypeError, ValueError) as error:
        raise AssignmentCopyValidationError(str(error)) from error



def _candidate_sha256(candidate: dict[str, object]) -> str:
    try:
        payload = json.dumps(
            candidate,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise AssignmentCopyValidationError(
            f"Copy candidate is not deterministic JSON data: {error}"
        ) from error
    return hashlib.sha256(payload).hexdigest()


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
        raise AssignmentCopyValidationError(
            f"Target path escapes the workspace: {descendant}"
        ) from error

    current = root
    chain: list[Path] = []
    for component in relative.parts:
        current = current / component
        chain.append(current)
    return tuple(chain)


def _preflight_source_directory_chain(
    workspace_root: str | Path,
    source_work_root: Path,
) -> None:
    for entry in _workspace_descendant_chain(workspace_root, source_work_root):
        if not _lexists(entry):
            raise AssignmentCopyNotFoundError(
                f"Source path component disappeared: {entry}"
            )
        if entry.is_symlink():
            raise AssignmentCopyValidationError(
                f"Source path chain contains a symbolic link: {entry}"
            )
        if not entry.is_dir():
            raise AssignmentCopyValidationError(
                f"Source path chain contains a non-directory entry: {entry}"
            )


def _preflight_target_parent_chain(
    workspace_root: str | Path,
    target: AssignmentCopyTarget,
) -> None:
    for entry in _workspace_descendant_chain(
        workspace_root,
        target.work_root.parent,
    ):
        if not _lexists(entry):
            continue
        if entry.is_symlink():
            raise AssignmentCopyConflictError(
                f"Target path chain contains a symbolic link: {entry}"
            )
        if not entry.is_dir():
            raise AssignmentCopyConflictError(
                f"Target path chain contains a non-directory entry: {entry}"
            )


def _preflight_target_shared_core_state(
    workspace_root: str | Path,
    target: AssignmentCopyTarget,
) -> None:
    try:
        registration_revisions = list_academic_work_registration_revisions(
            workspace_root,
            target.work,
        )
    except AcademicWorkRegistrationStorageError as error:
        raise AssignmentCopyConflictError(
            "Could not prove the target Academic Work Registration state is clean: "
            f"{error}"
        ) from error
    if registration_revisions:
        raise AssignmentCopyConflictError(
            "Target work identity already has Core Academic Work Registration history."
        )

    try:
        publications = list_publication_records(workspace_root)
    except PublicationStorageError as error:
        raise AssignmentCopyConflictError(
            "Could not prove the target publication state is clean: "
            f"{error}"
        ) from error
    if any(publication.work == target.work for publication in publications):
        raise AssignmentCopyConflictError(
            "Target work identity already has Core Publication Record history."
        )


def _preflight_target_destination(
    workspace_root: str | Path,
    target: AssignmentCopyTarget,
) -> None:
    _preflight_target_parent_chain(workspace_root, target)
    if _lexists(target.work_root):
        raise AssignmentCopyConflictError(
            f"Target ScoreForm work root already exists: {target.work_root}"
        )
    _preflight_target_shared_core_state(workspace_root, target)


def _revalidate_source_for_commit(
    workspace_root: str | Path,
    source: AssignmentCopySource,
    *,
    standards_library: StandardsLibrary | None,
) -> None:
    try:
        _preflight_source_directory_chain(workspace_root, source.work_root)
    except AssignmentCopyError as error:
        raise AssignmentCopyConflictError(
            "Source path became unsafe after the copy preview: "
            f"{error}"
        ) from error

    if source.assignment_path.is_symlink():
        raise AssignmentCopyConflictError(
            "Source assignment.json became a symbolic link after the copy preview."
        )
    if not source.assignment_path.exists() or not source.assignment_path.is_file():
        raise AssignmentCopyConflictError(
            "Source assignment.json is no longer a regular file after the copy preview."
        )

    try:
        current_bytes = source.assignment_path.read_bytes()
    except OSError as error:
        raise AssignmentCopyConflictError(
            f"Could not re-read the reviewed source assignment: {error}"
        ) from error

    current_sha256 = hashlib.sha256(current_bytes).hexdigest()
    if (
        current_sha256 != source.assignment_sha256
        or current_bytes != source.assignment_bytes
    ):
        raise AssignmentCopyConflictError(
            "Source assignment changed after the copy preview; build a new plan."
        )

    try:
        assignment = assignment_from_json_bytes(current_bytes)
    except AssignmentJsonBytesError as error:
        raise AssignmentCopyConflictError(
            f"Source assignment is no longer valid: {error}"
        ) from error
    if assignment["assignment_id"] != source.work.work_id:
        raise AssignmentCopyConflictError(
            "Source assignment identity changed after the copy preview."
        )

    if _requires_standards_library(assignment) and standards_library is None:
        raise AssignmentCopyValidationError(
            "A current PDS Core standards library is required to commit this copy."
        )
    if standards_library is not None:
        try:
            validate_assignment_standard_alignments(
                assignment,
                standards_library,
            )
        except AssignmentStandardsAlignmentError as error:
            raise AssignmentCopyConflictError(
                "Source standards configuration changed or is no longer valid: "
                f"{error}"
            ) from error


def _revalidate_plan_before_commit(
    workspace_root: str | Path,
    plan: AssignmentCopyPlan,
    *,
    standards_library: StandardsLibrary | None,
) -> None:
    if not isinstance(plan, AssignmentCopyPlan):
        raise AssignmentCopyValidationError(
            "plan must be an AssignmentCopyPlan."
        )
    if _candidate_sha256(plan.candidate) != plan.candidate_sha256:
        raise AssignmentCopyConflictError(
            "Copy candidate changed after preview; build a new plan."
        )
    if not plan.targets:
        raise AssignmentCopyValidationError(
            "Copy plan must contain at least one target."
        )

    target_assignment_id = plan.targets[0].work.work_id
    title = plan.candidate.get("title")
    if not isinstance(title, str):
        raise AssignmentCopyConflictError(
            "Copy candidate title changed after preview."
        )
    expected = plan.source.definition.build_candidate(
        assignment_id=target_assignment_id,
        title=title,
    )
    if expected != plan.candidate:
        raise AssignmentCopyConflictError(
            "Copy candidate no longer matches the reviewed source projection."
        )

    _revalidate_source_for_commit(
        workspace_root,
        plan.source,
        standards_library=standards_library,
    )

    seen: set[ModuleWorkRef] = set()
    for target in plan.targets:
        if target.work in seen:
            raise AssignmentCopyConflictError(
                f"Duplicate target work identity in copy plan: {target.work}"
            )
        seen.add(target.work)

        if target.work == plan.source.work:
            raise AssignmentCopyConflictError(
                "The exact source assignment cannot be its own copy target."
            )
        if target.work.work_id != target_assignment_id:
            raise AssignmentCopyConflictError(
                "All targets in one copy plan must use the reviewed target assignment ID."
            )

        current_roster = _target_roster_summary(
            workspace_root,
            target.work.class_id,
        )
        if current_roster != target.roster:
            raise AssignmentCopyConflictError(
                f"Target roster/class context changed after preview for "
                f"'{target.work.class_id}'; build a new plan."
            )

        _preflight_target_destination(workspace_root, target)


def _ensure_target_parent_directories(
    workspace_root: str | Path,
    target: AssignmentCopyTarget,
) -> list[Path]:
    created: list[Path] = []
    for entry in _workspace_descendant_chain(
        workspace_root,
        target.work_root.parent,
    ):
        if _lexists(entry):
            if entry.is_symlink() or not entry.is_dir():
                raise AssignmentCopyWriteError(
                    f"Target parent path became unsafe during commit: {entry}",
                    residue_paths=created,
                )
            continue
        try:
            entry.mkdir()
        except FileExistsError:
            if entry.is_symlink() or not entry.is_dir():
                raise AssignmentCopyWriteError(
                    f"Target parent path became unsafe during commit: {entry}",
                    residue_paths=created,
                )
        except OSError as error:
            raise AssignmentCopyWriteError(
                f"Could not create target parent directory {entry}: {error}",
                residue_paths=created,
            ) from error
        else:
            created.append(entry)
    return created


def _cleanup_empty_created_directories(
    directories: Sequence[Path],
) -> tuple[Path, ...]:
    residue: list[Path] = []
    for directory in reversed(tuple(directories)):
        try:
            directory.rmdir()
        except FileNotFoundError:
            continue
        except OSError:
            residue.append(directory)
    return tuple(reversed(residue))


def _persist_assignment_copy_target(
    workspace_root: str | Path,
    target: AssignmentCopyTarget,
    candidate: dict[str, object],
) -> AssignmentCopyCreatedTarget:
    created_directories: list[Path] = []
    try:
        created_directories.extend(
            _ensure_target_parent_directories(workspace_root, target)
        )

        try:
            target.work_root.mkdir()
        except FileExistsError as error:
            raise AssignmentCopyWriteError(
                f"Target work root appeared during commit: {target.work_root}"
            ) from error
        except OSError as error:
            raise AssignmentCopyWriteError(
                f"Could not create target work root {target.work_root}: {error}"
            ) from error
        created_directories.append(target.work_root)

        for directory in (
            target.work_root / "templates",
            target.work_root / "templates" / "individual",
            target.work_root / "scans",
            target.work_root / "debug",
        ):
            try:
                directory.mkdir()
            except OSError as error:
                raise AssignmentCopyWriteError(
                    f"Could not create target managed directory {directory}: {error}"
                ) from error
            created_directories.append(directory)

        try:
            content = (
                json.dumps(
                    candidate,
                    indent=2,
                    ensure_ascii=False,
                    allow_nan=False,
                )
                + "\n"
            ).encode("utf-8")
        except (TypeError, ValueError) as error:
            raise AssignmentCopyWriteError(
                f"Could not serialize target assignment: {error}"
            ) from error

        try:
            with target.assignment_path.open("xb") as assignment_file:
                assignment_file.write(content)
                assignment_file.flush()
                os.fsync(assignment_file.fileno())
        except FileExistsError as error:
            raise AssignmentCopyWriteError(
                f"Target assignment appeared during commit: {target.assignment_path}",
                residue_paths=(target.assignment_path,),
            ) from error
        except OSError as error:
            residue = (
                (target.assignment_path,)
                if _lexists(target.assignment_path)
                else ()
            )
            raise AssignmentCopyWriteError(
                f"Could not exclusively write target assignment "
                f"{target.assignment_path}: {error}",
                residue_paths=residue,
            ) from error

        try:
            persisted_bytes = target.assignment_path.read_bytes()
            persisted = assignment_from_json_bytes(persisted_bytes)
        except (OSError, AssignmentJsonBytesError) as error:
            raise AssignmentCopyWriteError(
                f"Could not verify target assignment {target.assignment_path}: {error}",
                residue_paths=(target.assignment_path,),
            ) from error
        if persisted != candidate:
            raise AssignmentCopyWriteError(
                f"Persisted target assignment differs from the reviewed candidate: "
                f"{target.assignment_path}",
                residue_paths=(target.assignment_path,),
            )
        if persisted["assignment_id"] != target.work.work_id:
            raise AssignmentCopyWriteError(
                f"Persisted target assignment identity does not match its work path: "
                f"{target.assignment_path}",
                residue_paths=(target.assignment_path,),
            )

        return AssignmentCopyCreatedTarget(
            work=target.work,
            assignment_path=target.assignment_path,
        )
    except AssignmentCopyWriteError as error:
        cleanup_residue = _cleanup_empty_created_directories(created_directories)
        combined = tuple(dict.fromkeys((*error.residue_paths, *cleanup_residue)))
        raise AssignmentCopyWriteError(
            str(error),
            residue_paths=combined,
        ) from error
    except Exception as error:
        cleanup_residue = _cleanup_empty_created_directories(created_directories)
        raise AssignmentCopyWriteError(
            f"Unexpected target persistence failure for {target.work}: {error}",
            residue_paths=cleanup_residue,
        ) from error


def commit_assignment_copy(
    workspace_root: str | Path,
    plan: AssignmentCopyPlan,
    *,
    standards_library: StandardsLibrary | None = None,
) -> AssignmentCopyResult:
    """Revalidate and create targets sequentially without rolling back success."""
    try:
        _revalidate_plan_before_commit(
            workspace_root,
            plan,
            standards_library=standards_library,
        )
    except AssignmentCopyConflictError as error:
        try_emit_diagnostic_event(
            workspace_root,
            component="assignment",
            workflow="copy_assignment",
            stage="validate_input",
            outcome="blocked",
            code="assignment_copy_conflict",
            class_id=plan.source.work.class_id,
            assignment_id=plan.source.work.work_id,
            exception=error,
        )
        raise

    created: list[AssignmentCopyCreatedTarget] = []
    failures: list[AssignmentCopyTargetFailure] = []
    not_attempted: tuple[AssignmentCopyTarget, ...] = ()

    for index, target in enumerate(plan.targets):
        try:
            created_target = _persist_assignment_copy_target(
                workspace_root,
                target,
                plan.candidate,
            )
        except AssignmentCopyWriteError as error:
            failures.append(
                AssignmentCopyTargetFailure(
                    target=target,
                    message=str(error),
                    residue_paths=error.residue_paths,
                )
            )
            not_attempted = plan.targets[index + 1 :]
            break
        created.append(created_target)

    result = AssignmentCopyResult(
        source=plan.source,
        candidate=plan.candidate,
        created=tuple(created),
        failures=tuple(failures),
        not_attempted=not_attempted,
    )
    for created_target in result.created:
        try_emit_diagnostic_event(
            workspace_root,
            component="assignment",
            workflow="copy_assignment",
            stage="verify_record",
            outcome="success",
            code="assignment_copy_verified",
            class_id=created_target.work.class_id,
            assignment_id=created_target.work.work_id,
        )
    if result.created and result.failures:
        failure = result.failures[0]
        try_emit_diagnostic_event(
            workspace_root,
            component="assignment",
            workflow="copy_assignment",
            stage="post_write_verify",
            outcome="partial_success",
            code="assignment_write_partial_success",
            class_id=failure.target.work.class_id,
            assignment_id=failure.target.work.work_id,
        )
    return result

def plan_assignment_copy(
    workspace_root: str | Path,
    source: AssignmentCopySource,
    *,
    target_class_ids: Sequence[str],
    target_assignment_id: str,
    title: str | None = None,
) -> AssignmentCopyPlan:
    """Build a deterministic, non-mutating multi-class assignment-copy plan."""
    if not isinstance(source, AssignmentCopySource):
        raise AssignmentCopyValidationError(
            "source must be an AssignmentCopySource snapshot."
        )
    if isinstance(target_class_ids, (str, bytes)) or not target_class_ids:
        raise AssignmentCopyValidationError(
            "Select at least one target class."
        )

    candidate = build_assignment_copy_candidate(
        source,
        target_assignment_id=target_assignment_id,
        title=title,
    )

    targets: list[AssignmentCopyTarget] = []
    seen_class_ids: set[str] = set()
    for class_id in target_class_ids:
        if not isinstance(class_id, str) or not class_id.strip():
            raise AssignmentCopyValidationError(
                "Target class IDs must be non-empty strings."
            )
        if class_id in seen_class_ids:
            raise AssignmentCopyValidationError(
                f"Target class '{class_id}' was selected more than once."
            )
        seen_class_ids.add(class_id)

        paths = _target_paths(
            workspace_root,
            class_id,
            target_assignment_id,
        )
        if paths.work_ref == source.work:
            raise AssignmentCopyConflictError(
                "The exact source assignment cannot be used as its own copy target."
            )

        roster = _target_roster_summary(workspace_root, class_id)
        target = AssignmentCopyTarget(
            work=paths.work_ref,
            work_root=paths.work_root,
            assignment_path=paths.assignment_path,
            roster=roster,
        )
        _preflight_target_destination(workspace_root, target)
        targets.append(target)

    return AssignmentCopyPlan(
        source=source,
        candidate=candidate,
        candidate_sha256=_candidate_sha256(candidate),
        targets=tuple(targets),
    )
