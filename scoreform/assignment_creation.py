"""Durable create-only installation of a native ScoreForm assignment.

The managed-work layout must exist before this function is called.  Existing
assignment updates belong to assignment_bulk_mutation; this writer can never
replace an existing assignment.json, even under a concurrent race.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Mapping
from pathlib import Path

from scoreform.assignment import AssignmentJsonBytesError, assignment_from_json_bytes
from scoreform.assignment_bulk_mutation import (
    AssignmentBulkMutationValidationError,
    serialize_assignment_bulk_candidate,
)


class AssignmentCreationError(RuntimeError):
    """Base error for create-only assignment persistence."""


class AssignmentCreationValidationError(AssignmentCreationError, ValueError):
    """Candidate or path does not satisfy the native assignment contract."""


class AssignmentCreationConflictError(AssignmentCreationError):
    """Another file already owns the requested canonical destination."""


class AssignmentCreationWriteError(AssignmentCreationError):
    """Failed durable creation; partial=True means the target may exist."""

    def __init__(self, message: str, *, partial: bool = False) -> None:
        super().__init__(message)
        self.partial = partial


def _exists(path: Path) -> bool:
    """Recognize dangling symlinks, which Path.exists() does not."""
    return os.path.lexists(os.fspath(path))


def _check_target(path: Path) -> None:
    """Reject redirected ancestry and existing canonical targets."""
    for parent in reversed(path.parent.parents):
        if _exists(parent) and (parent.is_symlink() or not parent.is_dir()):
            raise AssignmentCreationValidationError(
                "Assignment path ancestry must consist of real directories."
            )
    for parent in (path.parent,):
        if not parent.is_dir() or parent.is_symlink():
            raise AssignmentCreationValidationError(
                "Assignment directory must exist as a real directory."
            )
    if _exists(path):
        raise AssignmentCreationConflictError(
            "Assignment already exists; create-only installation cannot replace it."
        )


def _strict_candidate(value: Mapping[str, object]) -> tuple[bytes, dict[str, object]]:
    try:
        encoded = serialize_assignment_bulk_candidate(value)
        normalized = assignment_from_json_bytes(encoded)
    except (AssignmentBulkMutationValidationError, AssignmentJsonBytesError) as error:
        raise AssignmentCreationValidationError(
            "Assignment candidate failed strict native validation."
        ) from error
    return encoded, normalized


def _validate_staged(path: Path, expected: bytes, normalized: dict[str, object]) -> None:
    if path.is_symlink() or not path.is_file():
        raise AssignmentCreationWriteError("Staged assignment is not a regular file.")
    if path.read_bytes() != expected:
        raise AssignmentCreationWriteError("Staged assignment bytes changed before commit.")
    try:
        actual = assignment_from_json_bytes(expected)
    except AssignmentJsonBytesError as error:
        raise AssignmentCreationWriteError("Staged assignment is invalid.") from error
    if actual != normalized:
        raise AssignmentCreationWriteError("Staged assignment model changed.")


def commit_new_assignment(
    destination: str | Path, assignment: Mapping[str, object]
) -> Path:
    """Stage and verify a complete assignment, then install without replacement.

    Same-directory hard-link creation is the atomic create-if-absent commit. An
    unsupported filesystem fails closed; falling back to rename (which replaces
    files on POSIX) or writing at the target would lose this guarantee.
    """
    path = Path(os.path.abspath(os.fspath(destination)))
    if not isinstance(assignment, Mapping):
        raise AssignmentCreationValidationError("Assignment must be a mapping.")
    encoded, normalized = _strict_candidate(assignment)
    if normalized.get("assignment_id") != path.parent.name:
        # Managed work paths end in /<assignment_id>/assignment.json.
        raise AssignmentCreationValidationError(
            "Assignment ID does not match its managed-work directory."
        )
    if path.name != "assignment.json":
        raise AssignmentCreationValidationError(
            "Create-only writer requires canonical assignment.json."
        )
    _check_target(path)

    staged: Path | None = None
    published = False
    try:
        descriptor, staged_name = tempfile.mkstemp(
            dir=path.parent, prefix=".assignment.json.", suffix=".tmp"
        )
        staged = Path(staged_name)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        _validate_staged(staged, encoded, normalized)
        _check_target(path)
        # Atomic create-only commit; a concurrent writer wins without damage.
        try:
            os.link(staged, path)
            published = True
        except FileExistsError as error:
            raise AssignmentCreationConflictError(
                "Assignment appeared during creation; nothing was replaced."
            ) from error
        except OSError as error:
            # Some OS errors can arrive after a successful filesystem change.
            if _exists(path):
                raise AssignmentCreationWriteError(
                    "Assignment publication outcome is uncertain; inspect the "
                    "canonical destination before retrying.", partial=True
                ) from error
            raise AssignmentCreationWriteError(
                "Create-only installation failed; filesystem may not support "
                "atomic same-directory hard links."
            ) from error
        # Verify exact bytes again, without mutating the committed destination.
        try:
            if path.read_bytes() != encoded:
                raise AssignmentCreationWriteError(
                    "Published assignment differed from the staged candidate; "
                    "inspect before retrying.", partial=True
                )
        except OSError as error:
            raise AssignmentCreationWriteError(
                "Published assignment could not be verified; inspect before retrying.",
                partial=True,
            ) from error
        return path
    except (AssignmentCreationError, OSError) as error:
        if isinstance(error, AssignmentCreationError):
            raise
        raise AssignmentCreationWriteError(
            "Assignment staging failed; no successful publication was reported.",
            partial=published,
        ) from error
    finally:
        if staged is not None:
            try:
                staged.unlink(missing_ok=True)
            except OSError:
                # Committed destination is independent of this hard link. Do not
                # destroy it or report a failed commit because cleanup failed.
                pass
