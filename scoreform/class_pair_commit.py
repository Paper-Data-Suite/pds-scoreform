"""Bounded ScoreForm coordination of Core's two independent class-file writers.

This stage covers normal write failures and detects uncertain partial success. It
is not a cross-file atomic transaction or a crash-recovery protocol.
"""

from __future__ import annotations

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
        raise ClassPairCommitError(
            "Class roster write failed; prior metadata was restored."
        ) from error

    return {
        "roster_path": os.fspath(roster_path),
        "metadata_path": os.fspath(metadata_path),
    }
