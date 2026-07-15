"""Safe persistence for ScoreForm answer-sheet issuance and page records."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, NoReturn

from pds_core.rosters import RosterError, load_roster
from pds_core.routing_models import (
    ModuleWorkRef,
    RoutingModelError,
    validate_module_work_ref,
)

from scoreform.answer_sheet_records import (
    AnswerSheetIssuance,
    AnswerSheetLifecycleError,
    AnswerSheetPage,
    AnswerSheetRecordError,
    AnswerSheetRecordSet,
    answer_sheet_issuance_from_mapping,
    answer_sheet_issuance_to_mapping,
    answer_sheet_page_from_mapping,
    answer_sheet_page_to_mapping,
    transition_answer_sheet_lifecycle,
    validate_answer_sheet_issuance,
    validate_answer_sheet_record_set,
    validate_issuance_id,
    validate_page_id,
)
from scoreform.assignment import load_assignment
from scoreform.pds_contract import SCOREFORM_MODULE_ID
from scoreform.work_paths import (
    answer_sheet_issuance_path as canonical_answer_sheet_issuance_path,
)
from scoreform.work_paths import (
    answer_sheet_page_path as canonical_answer_sheet_page_path,
)
from scoreform.work_paths import scoreform_work_paths


class AnswerSheetPersistenceError(Exception):
    """Base class for typed answer-sheet persistence failures."""


class AnswerSheetWriteError(AnswerSheetPersistenceError):
    """Raised when exclusive record creation fails."""


class AnswerSheetCollisionError(AnswerSheetWriteError):
    """Raised when a destination identity already exists."""


class AnswerSheetReadError(AnswerSheetPersistenceError):
    """Raised when a record cannot be decoded or read."""


class AnswerSheetNotFoundError(AnswerSheetReadError):
    """Raised when an exact requested record is absent."""


class AnswerSheetIntegrityError(AnswerSheetPersistenceError):
    """Raised when persisted records are individually valid but inconsistent."""


class AnswerSheetLifecyclePersistenceError(AnswerSheetPersistenceError):
    """Raised when a lifecycle update cannot be safely persisted."""


class AnswerSheetRevisionConflictError(AnswerSheetLifecyclePersistenceError):
    """Raised when expected_revision is stale."""


@dataclass(frozen=True, slots=True)
class PersistedAnswerSheetRecordSet:
    record_set: AnswerSheetRecordSet
    issuance_path: Path
    page_paths: tuple[Path, ...]

    @property
    def issuance(self) -> AnswerSheetIssuance:
        return self.record_set.issuance

    @property
    def pages(self) -> tuple[AnswerSheetPage, ...]:
        return self.record_set.pages


@dataclass(frozen=True, slots=True)
class AnswerSheetPageContext:
    page: AnswerSheetPage
    issuance: AnswerSheetIssuance
    pages: tuple[AnswerSheetPage, ...]

    @property
    def record_set(self) -> AnswerSheetRecordSet:
        return AnswerSheetRecordSet(self.issuance, self.pages)


def _validated_work(work_ref: ModuleWorkRef) -> ModuleWorkRef:
    try:
        validated = validate_module_work_ref(work_ref)
    except (RoutingModelError, ValueError, TypeError) as error:
        raise AnswerSheetIntegrityError("Invalid ModuleWorkRef.") from error
    if validated.module_id != SCOREFORM_MODULE_ID:
        raise AnswerSheetIntegrityError('ModuleWorkRef.module_id must be "scoreform".')
    return validated


def answer_sheet_issuance_path(
    workspace_root: str | Path, work_ref: ModuleWorkRef, issuance_id: str
) -> Path:
    """Return one exact canonical issuance path without filesystem access."""
    work = _validated_work(work_ref)
    issuance_id = validate_issuance_id(issuance_id)
    return canonical_answer_sheet_issuance_path(workspace_root, work, issuance_id)


def answer_sheet_page_path(
    workspace_root: str | Path, work_ref: ModuleWorkRef, page_id: str
) -> Path:
    """Return one exact canonical page path without filesystem access."""
    work = _validated_work(work_ref)
    page_id = validate_page_id(page_id)
    return canonical_answer_sheet_page_path(workspace_root, work, page_id)


def _reject_filesystem_type(path: Path, *, directory: bool) -> None:
    if path.is_symlink():
        raise AnswerSheetWriteError(f"Symlinked answer-sheet path is not allowed: {path}")
    if path.exists() and (not path.is_dir() if directory else not path.is_file()):
        kind = "directory" if directory else "file"
        raise AnswerSheetWriteError(f"Expected {kind} filesystem entry: {path}")


def _json_duplicate_guard(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise AnswerSheetReadError(f"Duplicate JSON object key: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> NoReturn:
    raise AnswerSheetReadError(f"Non-standard JSON numeric constant: {value}")


def _read_json_object(path: Path) -> dict[str, object]:
    if path.is_symlink():
        raise AnswerSheetReadError(f"Refusing symlinked record: {path}")
    if not path.exists():
        raise AnswerSheetNotFoundError(f"Answer-sheet record not found: {path}")
    if not path.is_file():
        raise AnswerSheetReadError(f"Answer-sheet record is not a regular file: {path}")
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8", errors="strict")
        value = json.loads(
            text,
            object_pairs_hook=_json_duplicate_guard,
            parse_constant=_reject_json_constant,
        )
    except AnswerSheetReadError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AnswerSheetReadError(f"Could not read valid JSON record {path}: {error}") from error
    if not isinstance(value, dict):
        raise AnswerSheetReadError(f"Record must contain a top-level JSON object: {path}")
    return value


def _load_page_at(path: Path, requested_id: str) -> AnswerSheetPage:
    try:
        page = answer_sheet_page_from_mapping(_read_json_object(path))
    except AnswerSheetRecordError as error:
        raise AnswerSheetReadError(f"Invalid answer-sheet page {path}: {error}") from error
    if page.page_id != requested_id:
        raise AnswerSheetIntegrityError("Stored page_id does not match requested path identity.")
    return page


def _load_issuance_at(path: Path, requested_id: str) -> AnswerSheetIssuance:
    try:
        issuance = answer_sheet_issuance_from_mapping(_read_json_object(path))
    except AnswerSheetRecordError as error:
        raise AnswerSheetReadError(f"Invalid answer-sheet issuance {path}: {error}") from error
    if issuance.issuance_id != requested_id:
        raise AnswerSheetIntegrityError(
            "Stored issuance_id does not match requested path identity."
        )
    return issuance


def load_answer_sheet_page(
    workspace_root: str | Path, work_ref: ModuleWorkRef, page_id: str
) -> AnswerSheetPage:
    """Load one exact page; never searches or creates directories."""
    page_id = validate_page_id(page_id)
    page = _load_page_at(
        answer_sheet_page_path(workspace_root, work_ref, page_id), page_id
    )
    work = _validated_work(work_ref)
    if (page.class_id, page.assignment_id) != (work.class_id, work.work_id):
        raise AnswerSheetIntegrityError("Page identity does not match ModuleWorkRef.")
    return page


def load_answer_sheet_issuance(
    workspace_root: str | Path, work_ref: ModuleWorkRef, issuance_id: str
) -> AnswerSheetIssuance:
    """Load one exact issuance; never searches or creates directories."""
    issuance_id = validate_issuance_id(issuance_id)
    issuance = _load_issuance_at(
        answer_sheet_issuance_path(workspace_root, work_ref, issuance_id),
        issuance_id,
    )
    work = _validated_work(work_ref)
    if (issuance.class_id, issuance.assignment_id) != (work.class_id, work.work_id):
        raise AnswerSheetIntegrityError("Issuance identity does not match ModuleWorkRef.")
    return issuance


def load_answer_sheet_record_set(
    workspace_root: str | Path, work_ref: ModuleWorkRef, issuance_id: str
) -> AnswerSheetRecordSet:
    """Load and cross-validate one complete issuance aggregate."""
    issuance = load_answer_sheet_issuance(workspace_root, work_ref, issuance_id)
    pages = tuple(
        load_answer_sheet_page(workspace_root, work_ref, page_id)
        for page_id in issuance.page_ids
    )
    try:
        return validate_answer_sheet_record_set(AnswerSheetRecordSet(issuance, pages))
    except AnswerSheetRecordError as error:
        raise AnswerSheetIntegrityError(
            f"Incomplete or inconsistent issuance {issuance_id}: {error}"
        ) from error


def load_answer_sheet_page_context(
    workspace_root: str | Path, work_ref: ModuleWorkRef, page_id: str
) -> AnswerSheetPageContext:
    """Resolve an exact page to its complete, cross-validated issuance context."""
    page = load_answer_sheet_page(workspace_root, work_ref, page_id)
    record_set = load_answer_sheet_record_set(
        workspace_root, work_ref, page.issuance_id
    )
    occurrences = [candidate for candidate in record_set.pages if candidate.page_id == page_id]
    if len(occurrences) != 1 or occurrences[0] != page:
        raise AnswerSheetIntegrityError(
            "Requested page does not agree with its issuance membership."
        )
    return AnswerSheetPageContext(page, record_set.issuance, record_set.pages)


def _preflight_current_sources(
    workspace_root: str | Path,
    work_ref: ModuleWorkRef,
    record_set: AnswerSheetRecordSet,
) -> None:
    paths = scoreform_work_paths(workspace_root, work_ref.class_id, work_ref.work_id)
    if not paths.assignment_path.exists() or paths.assignment_path.is_symlink():
        raise AnswerSheetIntegrityError("Managed assignment is missing or symlinked.")
    assignment = load_assignment(paths.assignment_path)
    if assignment is None:
        raise AnswerSheetIntegrityError("Managed assignment is invalid.")
    issuance = record_set.issuance
    if assignment["assignment_id"] != work_ref.work_id:
        raise AnswerSheetIntegrityError("Managed assignment ID does not match work ID.")
    snapshot = issuance.assignment_snapshot
    structural = (
        assignment["title"], assignment["question_count"], assignment["layout_id"],
        tuple(assignment["choices"]),
    )
    if structural != (
        snapshot.title, snapshot.question_count, snapshot.layout_id, snapshot.choices
    ):
        raise AnswerSheetIntegrityError(
            "Managed assignment structure does not match issuance snapshot."
        )
    try:
        roster = load_roster(paths.roster_path)
    except RosterError as error:
        raise AnswerSheetIntegrityError("Shared roster is missing or invalid.") from error
    if roster.class_id != work_ref.class_id:
        raise AnswerSheetIntegrityError("Shared roster class does not match work class.")
    student = next(
        (item for item in roster.students if item.student_id == issuance.student_id),
        None,
    )
    if student is None:
        raise AnswerSheetIntegrityError("Issuance student is absent from shared roster.")
    if (student.last_name, student.first_name, student.period) != (
        issuance.student_snapshot.last_name,
        issuance.student_snapshot.first_name,
        issuance.student_snapshot.period,
    ):
        raise AnswerSheetIntegrityError(
            "Current roster values do not match the printed student snapshot."
        )


def _write_json_exclusive(path: Path, value: dict[str, object]) -> None:
    data = json.dumps(
        value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False
    ) + "\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor: int | None = None
    created_here = False
    try:
        descriptor = os.open(path, flags, 0o600)
        created_here = True
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            descriptor = None
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise AnswerSheetCollisionError(f"Record already exists: {path}") from error
    except (OSError, ValueError, TypeError) as error:
        if descriptor is not None:
            os.close(descriptor)
        cleanup_error: OSError | None = None
        if created_here:
            try:
                path.unlink()
            except OSError as caught_cleanup_error:
                cleanup_error = caught_cleanup_error
        if cleanup_error is not None:
            raise AnswerSheetWriteError(
                f"Could not exclusively write {path}: {error}; "
                f"could not remove the incomplete file: {cleanup_error}"
            ) from error
        raise AnswerSheetWriteError(f"Could not exclusively write {path}: {error}") from error


def write_answer_sheet_record_set(
    workspace_root: str | Path,
    work_ref: ModuleWorkRef,
    record_set: AnswerSheetRecordSet,
) -> PersistedAnswerSheetRecordSet:
    """Exclusively commit pages first and the aggregate issuance last."""
    work = _validated_work(work_ref)
    try:
        record_set = validate_answer_sheet_record_set(record_set)
    except AnswerSheetRecordError as error:
        raise AnswerSheetIntegrityError(f"Invalid record set: {error}") from error
    issuance = record_set.issuance
    if (issuance.class_id, issuance.assignment_id) != (work.class_id, work.work_id):
        raise AnswerSheetIntegrityError("Record set identity does not match ModuleWorkRef.")
    if issuance.lifecycle.status != "prepared" or issuance.lifecycle.revision != 1:
        raise AnswerSheetIntegrityError(
            "A newly persisted issuance must have its initial prepared lifecycle."
        )
    paths = scoreform_work_paths(workspace_root, work.class_id, work.work_id)
    collection_dirs = (
        paths.answer_sheets_dir,
        paths.answer_sheet_pages_dir,
        paths.answer_sheet_issuances_dir,
    )
    for directory in collection_dirs:
        _reject_filesystem_type(directory, directory=True)
    page_paths = tuple(
        answer_sheet_page_path(workspace_root, work, page.page_id)
        for page in record_set.pages
    )
    issuance_path = answer_sheet_issuance_path(
        workspace_root, work, issuance.issuance_id
    )
    for target in (*page_paths, issuance_path):
        if target.exists() or target.is_symlink():
            raise AnswerSheetCollisionError(f"Record identity already exists: {target}")
    _preflight_current_sources(workspace_root, work, record_set)
    if issuance.generation_context.predecessor_issuance_id is not None:
        predecessor = load_answer_sheet_issuance(
            workspace_root, work, issuance.generation_context.predecessor_issuance_id
        )
        if (predecessor.class_id, predecessor.assignment_id, predecessor.student_id) != (
            issuance.class_id, issuance.assignment_id, issuance.student_id
        ):
            raise AnswerSheetIntegrityError(
                "Regeneration predecessor has a different student or work identity."
            )
    for directory in collection_dirs:
        directory.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    try:
        for page, path in zip(record_set.pages, page_paths, strict=True):
            _write_json_exclusive(path, answer_sheet_page_to_mapping(page))
            created.append(path)
        _write_json_exclusive(
            issuance_path, answer_sheet_issuance_to_mapping(issuance)
        )
        created.append(issuance_path)
    except Exception as error:
        cleanup_errors: list[str] = []
        for path in reversed(created):
            try:
                path.unlink()
            except OSError as cleanup_error:
                cleanup_errors.append(f"{path}: {cleanup_error}")
        if cleanup_errors:
            raise AnswerSheetWriteError(
                f"Record-set write failed ({error}); rollback was incomplete: "
                + "; ".join(cleanup_errors)
            ) from error
        if isinstance(error, AnswerSheetPersistenceError):
            raise
        raise AnswerSheetWriteError(f"Record-set write failed: {error}") from error
    return PersistedAnswerSheetRecordSet(record_set, issuance_path, page_paths)


def _atomic_write_issuance(path: Path, issuance: AnswerSheetIssuance) -> None:
    temporary_path: Path | None = None
    try:
        data = json.dumps(
            answer_sheet_issuance_to_mapping(issuance),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        ) + "\n"
        descriptor, name = tempfile.mkstemp(
            prefix=f".{path.stem}.", suffix=".tmp", dir=path.parent
        )
        temporary_path = Path(name)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    except (OSError, ValueError, TypeError) as error:
        raise AnswerSheetLifecyclePersistenceError(
            f"Could not atomically update issuance {path}: {error}"
        ) from error
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError as cleanup_error:
                raise AnswerSheetLifecyclePersistenceError(
                    f"Could not clean abandoned lifecycle temporary file: {cleanup_error}"
                ) from cleanup_error


def transition_answer_sheet_issuance(
    workspace_root: str | Path,
    work_ref: ModuleWorkRef,
    issuance_id: str,
    *,
    expected_revision: int,
    new_status: str,
    timestamp: datetime | str,
    reason: str | None = None,
    replacement_issuance_id: str | None = None,
) -> AnswerSheetIssuance:
    """Revision-guard and atomically persist one controlled lifecycle update."""
    if isinstance(expected_revision, bool) or not isinstance(expected_revision, int):
        raise AnswerSheetRevisionConflictError("expected_revision must be an integer.")
    work = _validated_work(work_ref)
    issuance = load_answer_sheet_issuance(workspace_root, work, issuance_id)
    if issuance.lifecycle.revision != expected_revision:
        raise AnswerSheetRevisionConflictError(
            f"Expected revision {expected_revision}, found {issuance.lifecycle.revision}."
        )
    if new_status == "superseded":
        if replacement_issuance_id is None:
            raise AnswerSheetLifecyclePersistenceError(
                "Superseding requires replacement_issuance_id."
            )
        replacement = load_answer_sheet_issuance(
            workspace_root, work, replacement_issuance_id
        )
        if replacement.lifecycle.status != "issued":
            raise AnswerSheetLifecyclePersistenceError(
                "Replacement issuance must already be issued."
            )
        if (replacement.class_id, replacement.assignment_id, replacement.student_id) != (
            issuance.class_id, issuance.assignment_id, issuance.student_id
        ):
            raise AnswerSheetLifecyclePersistenceError(
                "Replacement issuance has a different student or work identity."
            )
    try:
        updated = transition_answer_sheet_lifecycle(
            issuance,
            new_status,
            timestamp=timestamp,
            reason=reason,
            replacement_issuance_id=replacement_issuance_id,
        )
        validate_answer_sheet_issuance(updated)
    except (AnswerSheetRecordError, AnswerSheetLifecycleError) as error:
        raise AnswerSheetLifecyclePersistenceError(str(error)) from error
    path = answer_sheet_issuance_path(workspace_root, work, issuance_id)
    if path.is_symlink() or not path.is_file():
        raise AnswerSheetLifecyclePersistenceError(
            "Issuance changed filesystem type before lifecycle update."
        )
    _atomic_write_issuance(path, updated)
    return updated
