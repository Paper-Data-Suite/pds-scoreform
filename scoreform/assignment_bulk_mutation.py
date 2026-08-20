"""Guarded staging and atomic persistence for ScoreForm bulk assignment edits."""

from __future__ import annotations

import copy
import errno
import hashlib
import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from pds_core.standards import StandardsLibrary

from scoreform.assignment import (
    AssignmentJsonBytesError,
    AssignmentStandardsAlignmentError,
    assignment_from_json_bytes,
    validate_assignment_standard_alignments,
)
from scoreform.assignment_bulk_entry import BulkAnswerKey, BulkStandardsAlignment
from scoreform.work_paths import scoreform_work_paths

_MUTABLE_ASSIGNMENT_FIELDS = frozenset(
    {"answer_key", "standards", "standards_profile_id"}
)
_EDITABLE_ASSIGNMENT_FIELDS = frozenset(
    {"title", "answer_key", "standards", "standards_profile_id"}
)
_IMMUTABLE_ASSIGNMENT_FIELDS = (
    "assignment_id",
    "question_count",
    "choices",
    "layout_id",
)


class AssignmentBulkMutationError(Exception):
    """Base error for guarded bulk assignment mutation."""


class AssignmentBulkMutationValidationError(AssignmentBulkMutationError, ValueError):
    """Raised when a source or candidate violates the assignment contract."""


class AssignmentBulkMutationNotFoundError(AssignmentBulkMutationError):
    """Raised when the exact canonical assignment is unavailable."""


class AssignmentBulkMutationConflictError(AssignmentBulkMutationError):
    """Raised when reviewed assignment state changed or became unsafe."""


class AssignmentBulkMutationWriteError(AssignmentBulkMutationError):
    """Raised when atomic assignment replacement cannot complete safely."""


@dataclass(frozen=True, slots=True)
class AssignmentBulkSnapshot:
    """Exact canonical assignment bytes plus normalized and preserved JSON data."""

    class_id: str
    assignment_id: str
    work_root: Path
    assignment_path: Path
    assignment_bytes: bytes
    assignment_sha256: str
    payload: dict[str, object]
    assignment: dict[str, object]


@dataclass(frozen=True, slots=True)
class AssignmentBulkMutationPlan:
    """One fully reviewed, non-mutating replacement plan."""

    snapshot: AssignmentBulkSnapshot
    candidate_payload: dict[str, object]
    candidate_assignment: dict[str, object]
    candidate_bytes: bytes
    candidate_sha256: str
    allowed_fields: frozenset[str] = _MUTABLE_ASSIGNMENT_FIELDS


def load_assignment_bulk_snapshot(
    workspace_root: str | Path,
    class_id: str,
    assignment_id: str,
    *,
    standards_library: StandardsLibrary | None = None,
) -> AssignmentBulkSnapshot:
    """Load one exact canonical assignment without mutating workspace state."""

    try:
        paths = scoreform_work_paths(workspace_root, class_id, assignment_id)
    except (TypeError, ValueError) as error:
        raise AssignmentBulkMutationValidationError(str(error)) from error

    _preflight_assignment_path(
        workspace_root,
        paths.assignment_path,
        require_file=True,
    )
    try:
        assignment_bytes = paths.assignment_path.read_bytes()
    except OSError as error:
        raise AssignmentBulkMutationNotFoundError(
            f"Could not read canonical assignment: {paths.assignment_path}: {error}"
        ) from error
    _preflight_assignment_path(
        workspace_root,
        paths.assignment_path,
        require_file=True,
    )

    payload = _strict_assignment_payload(assignment_bytes)
    assignment = _normalized_assignment(assignment_bytes)
    normalized_id = assignment.get("assignment_id")
    if normalized_id != paths.work_ref.work_id:
        raise AssignmentBulkMutationValidationError(
            "Assignment identity does not match its canonical managed work identity."
        )

    _validate_current_standards(
        assignment,
        standards_library=standards_library,
    )
    return AssignmentBulkSnapshot(
        class_id=paths.work_ref.class_id,
        assignment_id=paths.work_ref.work_id,
        work_root=paths.work_root,
        assignment_path=paths.assignment_path,
        assignment_bytes=assignment_bytes,
        assignment_sha256=hashlib.sha256(assignment_bytes).hexdigest(),
        payload=payload,
        assignment=assignment,
    )


def build_assignment_bulk_candidate(
    snapshot: AssignmentBulkSnapshot,
    *,
    answer_key: BulkAnswerKey | None = None,
    standards_alignment: BulkStandardsAlignment | None = None,
    standards_library: StandardsLibrary | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    """Build a complete staged replacement while preserving unrelated source data."""

    if not isinstance(snapshot, AssignmentBulkSnapshot):
        raise AssignmentBulkMutationValidationError(
            "snapshot must be an AssignmentBulkSnapshot."
        )
    if answer_key is None and standards_alignment is None:
        raise AssignmentBulkMutationValidationError(
            "Bulk assignment mutation requires an answer key or standards alignment."
        )

    question_count = snapshot.assignment.get("question_count")
    choices = snapshot.assignment.get("choices")
    if not isinstance(question_count, int) or isinstance(question_count, bool):
        raise AssignmentBulkMutationValidationError(
            "Reviewed assignment question_count is not normalized."
        )
    if not isinstance(choices, list) or any(
        not isinstance(choice, str) for choice in choices
    ):
        raise AssignmentBulkMutationValidationError(
            "Reviewed assignment choices are not normalized."
        )

    candidate_payload = copy.deepcopy(snapshot.payload)
    if answer_key is not None:
        if answer_key.question_count != question_count:
            raise AssignmentBulkMutationValidationError(
                "Bulk answer key question count does not match the assignment."
            )
        if any(answer not in choices for answer in answer_key.answers):
            raise AssignmentBulkMutationValidationError(
                "Bulk answer key contains a choice not allowed by the assignment."
            )
        candidate_payload["answer_key"] = answer_key.as_assignment_mapping()

    if standards_alignment is not None:
        if standards_alignment.question_count != question_count:
            raise AssignmentBulkMutationValidationError(
                "Bulk standards alignment question count does not match the assignment."
            )
        candidate_payload["standards"] = standards_alignment.as_assignment_mapping()
        if standards_alignment.standards_profile_id is None:
            candidate_payload.pop("standards_profile_id", None)
        else:
            candidate_payload["standards_profile_id"] = (
                standards_alignment.standards_profile_id
            )

    _assert_payload_only_bulk_fields_changed(snapshot, candidate_payload)
    candidate_bytes = serialize_assignment_bulk_candidate(candidate_payload)
    candidate_assignment = _normalized_assignment(candidate_bytes)
    _assert_only_bulk_fields_changed(snapshot, candidate_assignment)
    _validate_current_standards(
        candidate_assignment,
        standards_library=standards_library,
    )
    return candidate_payload, candidate_assignment


def plan_assignment_bulk_mutation(
    snapshot: AssignmentBulkSnapshot,
    *,
    answer_key: BulkAnswerKey | None = None,
    standards_alignment: BulkStandardsAlignment | None = None,
    standards_library: StandardsLibrary | None = None,
) -> AssignmentBulkMutationPlan:
    """Stage one complete replacement plan; planning performs no writes."""

    candidate_payload, candidate_assignment = build_assignment_bulk_candidate(
        snapshot,
        answer_key=answer_key,
        standards_alignment=standards_alignment,
        standards_library=standards_library,
    )
    candidate_bytes = serialize_assignment_bulk_candidate(candidate_payload)
    return AssignmentBulkMutationPlan(
        snapshot=snapshot,
        candidate_payload=candidate_payload,
        candidate_assignment=candidate_assignment,
        candidate_bytes=candidate_bytes,
        candidate_sha256=hashlib.sha256(candidate_bytes).hexdigest(),
        allowed_fields=_MUTABLE_ASSIGNMENT_FIELDS,
    )


def plan_assignment_staged_replacement(
    snapshot: AssignmentBulkSnapshot,
    staged_assignment: Mapping[str, object],
    *,
    standards_library: StandardsLibrary | None = None,
) -> AssignmentBulkMutationPlan:
    """Plan one atomic replacement for the interactive staged assignment editor.

    The existing editor may change ``title`` alongside the bulk-owned answer-key and
    standards fields. Managed-work identity, question count, choices, layout, and
    unrelated future payload fields remain immutable and are preserved exactly.
    """

    if not isinstance(snapshot, AssignmentBulkSnapshot):
        raise AssignmentBulkMutationValidationError(
            "snapshot must be an AssignmentBulkSnapshot."
        )
    if not isinstance(staged_assignment, Mapping):
        raise AssignmentBulkMutationValidationError(
            "staged_assignment must be a mapping."
        )

    staged_bytes = serialize_assignment_bulk_candidate(staged_assignment)
    normalized_staged = _normalized_assignment(staged_bytes)
    for field in _IMMUTABLE_ASSIGNMENT_FIELDS:
        if normalized_staged.get(field) != snapshot.assignment.get(field):
            raise AssignmentBulkMutationValidationError(
                f"Staged assignment cannot change immutable field {field!r}."
            )

    candidate_payload = copy.deepcopy(snapshot.payload)
    candidate_payload["title"] = normalized_staged["title"]

    answer_key = normalized_staged.get("answer_key")
    standards = normalized_staged.get("standards")
    if not isinstance(answer_key, Mapping) or not isinstance(standards, Mapping):
        raise AssignmentBulkMutationValidationError(
            "Staged assignment key/alignment data was not normalized."
        )
    candidate_payload["answer_key"] = {
        str(question): answer for question, answer in answer_key.items()
    }
    candidate_payload["standards"] = {
        str(question): list(standard_ids)
        for question, standard_ids in standards.items()
    }
    profile_id = normalized_staged.get("standards_profile_id")
    if profile_id is None:
        candidate_payload.pop("standards_profile_id", None)
    else:
        candidate_payload["standards_profile_id"] = profile_id

    _assert_payload_only_fields_changed(
        snapshot,
        candidate_payload,
        allowed_fields=_EDITABLE_ASSIGNMENT_FIELDS,
        context="Staged assignment",
    )
    candidate_bytes = serialize_assignment_bulk_candidate(candidate_payload)
    candidate_assignment = _normalized_assignment(candidate_bytes)
    _assert_only_fields_changed(
        snapshot,
        candidate_assignment,
        allowed_fields=_EDITABLE_ASSIGNMENT_FIELDS,
        context="Staged assignment",
    )
    _validate_current_standards(
        candidate_assignment,
        standards_library=standards_library,
    )
    return AssignmentBulkMutationPlan(
        snapshot=snapshot,
        candidate_payload=candidate_payload,
        candidate_assignment=candidate_assignment,
        candidate_bytes=candidate_bytes,
        candidate_sha256=hashlib.sha256(candidate_bytes).hexdigest(),
        allowed_fields=_EDITABLE_ASSIGNMENT_FIELDS,
    )


def commit_assignment_bulk_mutation(
    workspace_root: str | Path,
    plan: AssignmentBulkMutationPlan,
    *,
    standards_library: StandardsLibrary | None = None,
) -> AssignmentBulkSnapshot:
    """Atomically replace the reviewed assignment after stale-state revalidation."""

    if not isinstance(plan, AssignmentBulkMutationPlan):
        raise AssignmentBulkMutationValidationError(
            "plan must be an AssignmentBulkMutationPlan."
        )

    try:
        expected = scoreform_work_paths(
            workspace_root,
            plan.snapshot.class_id,
            plan.snapshot.assignment_id,
        )
    except (TypeError, ValueError) as error:
        raise AssignmentBulkMutationValidationError(str(error)) from error
    if (
        expected.work_root != plan.snapshot.work_root
        or expected.assignment_path != plan.snapshot.assignment_path
    ):
        raise AssignmentBulkMutationConflictError(
            "Assignment mutation plan does not match this workspace."
        )

    candidate_payload, candidate_assignment, candidate_bytes = _revalidate_candidate(
        plan,
        standards_library=standards_library,
    )
    _revalidate_current_snapshot(
        workspace_root,
        plan.snapshot,
        standards_library=standards_library,
    )

    temporary_path: Path | None = None
    try:
        descriptor, raw_path = tempfile.mkstemp(
            dir=plan.snapshot.assignment_path.parent,
            prefix=f".{plan.snapshot.assignment_path.name}.",
            suffix=".tmp",
        )
        temporary_path = Path(raw_path)
        with os.fdopen(descriptor, "wb") as output:
            output.write(candidate_bytes)
            output.flush()
            _fsync_where_supported(output.fileno())

        _validate_temporary_candidate(
            temporary_path,
            expected_payload=candidate_payload,
            expected_assignment=candidate_assignment,
            expected_bytes=candidate_bytes,
            standards_library=standards_library,
        )
        _revalidate_current_snapshot(
            workspace_root,
            plan.snapshot,
            standards_library=standards_library,
        )
        os.replace(temporary_path, plan.snapshot.assignment_path)
        temporary_path = None
    except AssignmentBulkMutationError:
        raise
    except OSError as error:
        raise AssignmentBulkMutationWriteError(
            f"Could not replace assignment safely: {error}"
        ) from error
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass

    persisted = load_assignment_bulk_snapshot(
        workspace_root,
        plan.snapshot.class_id,
        plan.snapshot.assignment_id,
        standards_library=standards_library,
    )
    if (
        persisted.assignment_bytes != candidate_bytes
        or persisted.assignment_sha256 != plan.candidate_sha256
        or persisted.payload != candidate_payload
        or persisted.assignment != candidate_assignment
    ):
        raise AssignmentBulkMutationWriteError(
            "Persisted assignment does not match the reviewed bulk candidate."
        )
    return persisted


def serialize_assignment_bulk_candidate(payload: Mapping[str, object]) -> bytes:
    """Serialize a fully staged assignment candidate as deterministic UTF-8 JSON."""

    if not isinstance(payload, Mapping):
        raise AssignmentBulkMutationValidationError(
            "Assignment candidate payload must be a mapping."
        )
    try:
        return (
            json.dumps(
                dict(payload),
                indent=2,
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as error:
        raise AssignmentBulkMutationValidationError(
            f"Assignment candidate is not valid deterministic JSON data: {error}"
        ) from error


def _strict_assignment_payload(data: bytes) -> dict[str, object]:
    if not isinstance(data, bytes):
        raise AssignmentBulkMutationValidationError(
            "Assignment JSON input must be bytes."
        )
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise AssignmentBulkMutationValidationError(
            "Assignment JSON must be valid UTF-8."
        ) from error

    def duplicate_guard(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise AssignmentBulkMutationValidationError(
                    f"Assignment JSON contains duplicate object key {key!r}."
                )
            result[key] = value
        return result

    def reject_nonfinite(value: str) -> None:
        raise AssignmentBulkMutationValidationError(
            f"Assignment JSON contains nonfinite numeric constant {value!r}."
        )

    try:
        decoded = json.loads(
            text,
            object_pairs_hook=duplicate_guard,
            parse_constant=reject_nonfinite,
        )
    except AssignmentBulkMutationValidationError:
        raise
    except (ValueError, RecursionError) as error:
        raise AssignmentBulkMutationValidationError(
            "Assignment JSON is malformed."
        ) from error
    if not isinstance(decoded, dict):
        raise AssignmentBulkMutationValidationError(
            "Assignment JSON must contain one object."
        )
    return decoded


def _normalized_assignment(data: bytes) -> dict[str, object]:
    try:
        return assignment_from_json_bytes(data)
    except AssignmentJsonBytesError as error:
        raise AssignmentBulkMutationValidationError(str(error)) from error


def _assignment_requires_standards_library(
    assignment: Mapping[str, object],
) -> bool:
    if assignment.get("standards_profile_id") is not None:
        return True
    standards = assignment.get("standards")
    return isinstance(standards, Mapping) and any(
        bool(values) for values in standards.values()
    )


def _validate_current_standards(
    assignment: Mapping[str, object],
    *,
    standards_library: StandardsLibrary | None,
) -> None:
    if not _assignment_requires_standards_library(assignment):
        return
    if standards_library is None:
        raise AssignmentBulkMutationValidationError(
            "A current Core standards library is required for this assignment."
        )
    try:
        validate_assignment_standard_alignments(
            assignment,
            standards_library,
        )
    except AssignmentStandardsAlignmentError as error:
        raise AssignmentBulkMutationValidationError(
            f"Assignment standards are not currently valid: {error}"
        ) from error


def _assert_payload_only_fields_changed(
    snapshot: AssignmentBulkSnapshot,
    candidate_payload: Mapping[str, object],
    *,
    allowed_fields: frozenset[str],
    context: str,
) -> None:
    original_fields = set(snapshot.payload) - allowed_fields
    candidate_fields = set(candidate_payload) - allowed_fields
    if candidate_fields != original_fields:
        raise AssignmentBulkMutationValidationError(
            f"{context} cannot add or remove unrelated fields."
        )
    for field in sorted(original_fields):
        if candidate_payload.get(field) != snapshot.payload.get(field):
            raise AssignmentBulkMutationValidationError(
                f"{context} cannot change {field!r}."
            )


def _assert_only_fields_changed(
    snapshot: AssignmentBulkSnapshot,
    candidate_assignment: Mapping[str, object],
    *,
    allowed_fields: frozenset[str],
    context: str,
) -> None:
    for field, original_value in snapshot.assignment.items():
        if field in allowed_fields:
            continue
        if candidate_assignment.get(field) != original_value:
            raise AssignmentBulkMutationValidationError(
                f"{context} cannot change {field!r}."
            )
    for field in candidate_assignment:
        if field in allowed_fields or field in snapshot.assignment:
            continue
        raise AssignmentBulkMutationValidationError(
            f"{context} cannot introduce field {field!r}."
        )


def _assert_payload_only_bulk_fields_changed(
    snapshot: AssignmentBulkSnapshot,
    candidate_payload: Mapping[str, object],
) -> None:
    _assert_payload_only_fields_changed(
        snapshot,
        candidate_payload,
        allowed_fields=_MUTABLE_ASSIGNMENT_FIELDS,
        context="Bulk assignment mutation",
    )


def _assert_only_bulk_fields_changed(
    snapshot: AssignmentBulkSnapshot,
    candidate_assignment: Mapping[str, object],
) -> None:
    _assert_only_fields_changed(
        snapshot,
        candidate_assignment,
        allowed_fields=_MUTABLE_ASSIGNMENT_FIELDS,
        context="Bulk assignment mutation",
    )


def _revalidate_candidate(
    plan: AssignmentBulkMutationPlan,
    *,
    standards_library: StandardsLibrary | None,
) -> tuple[dict[str, object], dict[str, object], bytes]:
    candidate_bytes = serialize_assignment_bulk_candidate(plan.candidate_payload)
    candidate_payload = _strict_assignment_payload(candidate_bytes)
    candidate_assignment = _normalized_assignment(candidate_bytes)
    if plan.allowed_fields == _MUTABLE_ASSIGNMENT_FIELDS:
        context = "Bulk assignment mutation"
    elif plan.allowed_fields == _EDITABLE_ASSIGNMENT_FIELDS:
        context = "Staged assignment"
    else:
        raise AssignmentBulkMutationValidationError(
            "Assignment mutation plan contains unsupported editable fields."
        )
    _assert_payload_only_fields_changed(
        plan.snapshot,
        candidate_payload,
        allowed_fields=plan.allowed_fields,
        context=context,
    )
    _assert_only_fields_changed(
        plan.snapshot,
        candidate_assignment,
        allowed_fields=plan.allowed_fields,
        context=context,
    )
    _validate_current_standards(
        candidate_assignment,
        standards_library=standards_library,
    )
    digest = hashlib.sha256(candidate_bytes).hexdigest()
    if (
        candidate_payload != plan.candidate_payload
        or candidate_assignment != plan.candidate_assignment
        or candidate_bytes != plan.candidate_bytes
        or digest != plan.candidate_sha256
    ):
        raise AssignmentBulkMutationConflictError(
            "Bulk assignment candidate changed after preview; build a new plan."
        )
    return candidate_payload, candidate_assignment, candidate_bytes


def _revalidate_current_snapshot(
    workspace_root: str | Path,
    snapshot: AssignmentBulkSnapshot,
    *,
    standards_library: StandardsLibrary | None,
) -> None:
    try:
        current = load_assignment_bulk_snapshot(
            workspace_root,
            snapshot.class_id,
            snapshot.assignment_id,
            standards_library=standards_library,
        )
    except AssignmentBulkMutationNotFoundError as error:
        raise AssignmentBulkMutationConflictError(
            f"Assignment became unavailable after preview: {error}"
        ) from error
    except AssignmentBulkMutationValidationError as error:
        raise AssignmentBulkMutationConflictError(
            f"Assignment became unsafe or invalid after preview: {error}"
        ) from error
    if (
        current.work_root != snapshot.work_root
        or current.assignment_path != snapshot.assignment_path
        or current.assignment_bytes != snapshot.assignment_bytes
        or current.assignment_sha256 != snapshot.assignment_sha256
    ):
        raise AssignmentBulkMutationConflictError(
            "Assignment changed after preview; build a new bulk mutation plan."
        )


def _validate_temporary_candidate(
    path: Path,
    *,
    expected_payload: Mapping[str, object],
    expected_assignment: Mapping[str, object],
    expected_bytes: bytes,
    standards_library: StandardsLibrary | None,
) -> None:
    if path.is_symlink() or not path.is_file():
        raise AssignmentBulkMutationWriteError(
            "Temporary assignment candidate is not a regular file."
        )
    try:
        data = path.read_bytes()
    except OSError as error:
        raise AssignmentBulkMutationWriteError(
            f"Could not re-read temporary assignment candidate: {error}"
        ) from error
    if data != expected_bytes:
        raise AssignmentBulkMutationWriteError(
            "Temporary assignment candidate bytes changed before replacement."
        )
    payload = _strict_assignment_payload(data)
    assignment = _normalized_assignment(data)
    _validate_current_standards(
        assignment,
        standards_library=standards_library,
    )
    if payload != expected_payload or assignment != expected_assignment:
        raise AssignmentBulkMutationWriteError(
            "Temporary assignment candidate failed strict reload verification."
        )


def _preflight_assignment_path(
    workspace_root: str | Path,
    assignment_path: Path,
    *,
    require_file: bool,
) -> None:
    root = Path(os.path.abspath(os.fspath(workspace_root)))
    target = Path(os.path.abspath(os.fspath(assignment_path)))
    try:
        relative = target.relative_to(root)
    except ValueError as error:
        raise AssignmentBulkMutationValidationError(
            f"Assignment path escapes the workspace: {assignment_path}"
        ) from error

    if os.path.lexists(os.fspath(root)):
        if root.is_symlink():
            raise AssignmentBulkMutationValidationError(
                f"Workspace root is a symbolic link: {root}"
            )
        if not root.is_dir():
            raise AssignmentBulkMutationValidationError(
                f"Workspace root is not a directory: {root}"
            )

    current = root
    parts = relative.parts
    for index, component in enumerate(parts):
        current = current / component
        is_target = index == len(parts) - 1
        if not os.path.lexists(os.fspath(current)):
            if is_target and require_file:
                raise AssignmentBulkMutationNotFoundError(
                    f"Canonical assignment does not exist: {current}"
                )
            raise AssignmentBulkMutationNotFoundError(
                f"Assignment path component does not exist: {current}"
            )
        if current.is_symlink():
            raise AssignmentBulkMutationValidationError(
                f"Assignment path chain contains a symbolic link: {current}"
            )
        if is_target:
            if require_file and not current.is_file():
                raise AssignmentBulkMutationValidationError(
                    f"Canonical assignment is not a regular file: {current}"
                )
        elif not current.is_dir():
            raise AssignmentBulkMutationValidationError(
                f"Assignment path chain contains a non-directory entry: {current}"
            )


def _fsync_where_supported(descriptor: int) -> None:
    try:
        os.fsync(descriptor)
    except OSError as error:
        unsupported = {
            value
            for value in (
                getattr(errno, "EINVAL", None),
                getattr(errno, "ENOSYS", None),
                getattr(errno, "ENOTSUP", None),
            )
            if value is not None
        }
        if error.errno not in unsupported:
            raise
