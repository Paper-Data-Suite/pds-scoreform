"""Coordinate Core class files with durable intent and bounded recovery.

The two Core writes remain independent. An intent journal permits explicit
interruption recovery, and uncertain changes fail closed instead of guessing.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

from pds_core.class_metadata import (
    create_class_metadata,
    load_class_metadata_for_class,
    write_class_metadata_for_class,
)
from pds_core.classes import (
    load_class_roster,
    write_class_roster,
)
from pds_core.rosters import create_roster
from pds_core.routes import class_metadata_path, class_roster_path, classes_dir

from scoreform.class_pair_recovery import (
    ClassPairIntent,
    ClassPairRecoveryError,
    clear_intent,
    create_intent,
    inspect_class_pair_recovery,
    intent_path,
    metadata_fingerprint,
    roster_fingerprint,
)


class ClassPairCommitError(RuntimeError):
    """Class-file update failed; ``partial`` requires operator reconciliation."""

    def __init__(self, message: str, *, partial: bool = False) -> None:
        super().__init__(message)
        self.partial = partial


def _snapshot(path: Path) -> bytes | None:
    """Read an existing canonical file, refusing links and non-files."""
    if path.is_symlink():
        raise ClassPairCommitError("Canonical class file is a symbolic link.")
    if not path.exists():
        return None
    if not path.is_file():
        raise ClassPairCommitError("Canonical class path is not a regular file.")
    try:
        return path.read_bytes()
    except OSError as error:
        raise ClassPairCommitError("Could not inspect existing class file.") from error


def _check_ancestry(root: Path, class_id: str) -> None:
    """Refuse an existing redirected workspace/classes/class folder."""
    class_folder = classes_dir(root) / class_id
    for path in (root, classes_dir(root), class_folder):
        if path.is_symlink():
            raise ClassPairCommitError("Canonical class directory is a symbolic link.")
        if path.exists() and not path.is_dir():
            raise ClassPairCommitError("Canonical class directory is not a directory.")


def _restore_if_unchanged(
    path: Path, *, previous: bytes | None, committed: bytes
) -> None:
    """Revert only a known successful write, never another writer's changes."""
    if _snapshot(path) != committed:
        raise ClassPairCommitError(
            "Class metadata changed during recovery; manual reconciliation required.",
            partial=True,
        )
    if previous is None:
        path.unlink()
        return

    staged: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.restore-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            staged = Path(handle.name)
            handle.write(previous)
            handle.flush()
            os.fsync(handle.fileno())
        # A final check protects against observed intervening changes. It is
        # still not a substitute for locking writers that do not coordinate.
        if _snapshot(path) != committed:
            raise ClassPairCommitError(
                "Class metadata changed during recovery; manual reconciliation required.",
                partial=True,
            )
        os.replace(staged, path)
        staged = None
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)


def commit_class_pair(
    *,
    workspace_root: str | Path,
    class_id: str,
    period: str,
    students: Sequence[Mapping[str, str]],
    school_year: str,
    overwrite: bool = False,
) -> dict[str, str]:
    """Preflight both Core files, then commit with bounded compensation.

    A metadata failure cannot alter the roster. A subsequent roster failure
    restores the metadata *only* when its newly committed bytes are unchanged.
    An uncertain roster write or failed rollback is reported as partial state.
    """
    root = Path(workspace_root).expanduser().absolute()
    rows = [
        {
            "student_id": student["student_id"],
            "last_name": student["last_name"],
            "first_name": student["first_name"],
            "period": period,
        }
        for student in students
    ]
    roster = create_roster(class_id, rows)
    roster_path = class_roster_path(root, class_id)
    metadata_path = class_metadata_path(root, class_id)
    _check_ancestry(root, class_id)
    if intent_path(root, class_id).is_symlink() or intent_path(root, class_id).exists():
        raise ClassPairCommitError(
            "Unresolved or active class-pair recovery journal exists; "
            "recovery is required before another update.",
            partial=True,
        )
    old_roster = _snapshot(roster_path)
    old_metadata = _snapshot(metadata_path)
    if not overwrite and (old_roster is not None or old_metadata is not None):
        raise ClassPairCommitError("Class files already exist; overwrite was not authorized.")

    # Invalid existing data must be investigated, not silently overwritten.
    if old_roster is not None:
        load_class_roster(root, class_id)
    old_model = (
        load_class_metadata_for_class(root, class_id)
        if old_metadata is not None
        else None
    )
    now = datetime.now(timezone.utc)
    metadata = create_class_metadata(
        class_id,
        school_year,
        created_at=old_model.created_at if old_model is not None else now,
        updated_at=(
            max(now, old_model.updated_at) if old_model is not None else now
        ),
        module_details=(old_model.module_details if old_model is not None else None),
    )

    intent = ClassPairIntent(
        class_id=class_id,
        old_roster_sha256=(
            hashlib.sha256(old_roster).hexdigest() if old_roster is not None else None
        ),
        old_metadata_sha256=(
            hashlib.sha256(old_metadata).hexdigest() if old_metadata is not None else None
        ),
        expected_roster_fingerprint=roster_fingerprint(roster),
        expected_metadata_fingerprint=metadata_fingerprint(metadata),
        old_metadata_bytes=old_metadata,
    )
    try:
        create_intent(root, intent)
    except ClassPairRecoveryError as error:
        raise ClassPairCommitError(str(error), partial=True) from error

    # Metadata first: failure of this initial writer leaves the roster intact.
    try:
        if _snapshot(metadata_path) != old_metadata:
            raise ClassPairCommitError("Class metadata changed during preflight.")
        write_class_metadata_for_class(root, metadata, overwrite=overwrite)
    except Exception as error:
        if _snapshot(metadata_path) != old_metadata:
            raise ClassPairCommitError(
                "Class metadata may have been committed before failure; "
                "manual reconciliation required.",
                partial=True,
            ) from error
        try:
            if inspect_class_pair_recovery(root, class_id) != "unchanged":
                raise ClassPairRecoveryError("Class state changed during failed write.")
            clear_intent(root, intent)
        except ClassPairRecoveryError as recovery_error:
            raise ClassPairCommitError(
                "PARTIAL CLASS UPDATE: metadata failure left uncertain state; "
                "manual reconciliation required.", partial=True,
            ) from recovery_error
        raise ClassPairCommitError("Class metadata write failed; roster unchanged.") from error

    try:
        committed_metadata = _snapshot(metadata_path)
    except Exception as error:
        raise ClassPairCommitError(
            "PARTIAL CLASS UPDATE: committed metadata cannot be inspected; "
            "manual reconciliation required.",
            partial=True,
        ) from error
    if committed_metadata is None:
        raise ClassPairCommitError(
            "PARTIAL CLASS UPDATE: metadata writer returned without a committed "
            "file; manual reconciliation required.",
            partial=True,
        )
    try:
        if (metadata_fingerprint(load_class_metadata_for_class(root, class_id))
                != intent.expected_metadata_fingerprint):
            raise ClassPairCommitError(
                "PARTIAL CLASS UPDATE: committed class metadata differs from "
                "the intended model; manual reconciliation required.", partial=True,
            )
    except ClassPairCommitError:
        raise
    except Exception as error:
        raise ClassPairCommitError(
            "PARTIAL CLASS UPDATE: committed metadata could not be validated; "
            "manual reconciliation required.", partial=True,
        ) from error
    try:
        if _snapshot(roster_path) != old_roster:
            raise ClassPairCommitError("Class roster changed before its write.")
        write_class_roster(root, roster, overwrite=overwrite)
    except Exception as error:
        # Core writes each file atomically, but writers can fail *after*
        # committing. If the roster changed, leave the new metadata intact:
        # reverting it would create a mismatched pair with the new roster.
        try:
            roster_changed = _snapshot(roster_path) != old_roster
        except Exception as inspection_error:
            raise ClassPairCommitError(
                "PARTIAL CLASS UPDATE: roster state cannot be inspected; "
                "manual reconciliation required.",
                partial=True,
            ) from inspection_error
        if roster_changed:
            raise ClassPairCommitError(
                "PARTIAL CLASS UPDATE: roster may have committed before the "
                "failure; metadata was retained for reconciliation.",
                partial=True,
            ) from error
        try:
            _restore_if_unchanged(
                metadata_path, previous=old_metadata, committed=committed_metadata
            )
        except Exception as recovery_error:
            raise ClassPairCommitError(
                "PARTIAL CLASS UPDATE: metadata recovery failed; manual "
                "reconciliation required.",
                partial=True,
            ) from recovery_error
        try:
            if inspect_class_pair_recovery(root, class_id) != "unchanged":
                raise ClassPairRecoveryError("Class state changed during restoration.")
            clear_intent(root, intent)
        except ClassPairRecoveryError as recovery_error:
            raise ClassPairCommitError(
                "PARTIAL CLASS UPDATE: restored metadata could not be finalized; "
                "manual reconciliation required.", partial=True,
            ) from recovery_error
        raise ClassPairCommitError(
            "Class roster write failed; prior metadata was restored."
        ) from error

    try:
        if inspect_class_pair_recovery(root, class_id) != "completed":
            raise ClassPairRecoveryError("Committed pair does not match intended state.")
        clear_intent(root, intent)
    except ClassPairRecoveryError as error:
        raise ClassPairCommitError(
            "PARTIAL CLASS UPDATE: final pair could not be verified; "
            "manual reconciliation required.", partial=True,
        ) from error

    return {
        "roster_path": os.fspath(roster_path),
        "metadata_path": os.fspath(metadata_path),
    }
