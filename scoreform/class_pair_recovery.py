"""Durable, fail-closed recovery intent for ScoreForm's paired Core class files.

Only ScoreForm's paired workflow observes this journal. Other Core writers are
not automatically excluded: unexpected changes must block automatic recovery.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pds_core.class_metadata import ClassMetadata, load_class_metadata_for_class
from pds_core.classes import load_class_roster
from pds_core.rosters import Roster
from pds_core.routes import class_metadata_path, class_roster_path, classes_dir

JOURNAL_NAME = ".scoreform-class-pair.intent.json"
SCHEMA = "scoreform_class_pair_intent_v1"
_HEX = re.compile(r"[0-9a-f]{64}\Z")


class ClassPairRecoveryError(RuntimeError):
    """A journal is invalid, active, conflicted, or cannot be reconciled safely."""


@dataclass(frozen=True, slots=True)
class ClassPairIntent:
    class_id: str
    old_roster_sha256: str | None
    old_metadata_sha256: str | None
    expected_roster_fingerprint: str
    expected_metadata_fingerprint: str
    old_metadata_bytes: bytes | None


def _hash(content: bytes | None) -> str | None:
    return hashlib.sha256(content).hexdigest() if content is not None else None


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def roster_fingerprint(value: Roster) -> str:
    """Semantic fingerprint independent of CSV newline/quoting platform details."""
    return hashlib.sha256(_canonical_json({
        "class_id": value.class_id,
        "columns": list(value.columns),
        "students": [
            {
                "class_id": student.class_id,
                "student_id": student.student_id,
                "last_name": student.last_name,
                "first_name": student.first_name,
                "period": student.period,
                "extra_fields": dict(student.extra_fields),
            }
            for student in value.students
        ],
    })).hexdigest()


def metadata_fingerprint(value: ClassMetadata) -> str:
    return hashlib.sha256(_canonical_json({
        "class_id": value.class_id,
        "school_year": value.school_year,
        "created_at": value.created_at.isoformat(),
        "updated_at": value.updated_at.isoformat(),
        "module_details": dict(value.module_details),
    })).hexdigest()


def intent_path(root: Path, class_id: str) -> Path:
    # Core's canonical path factory validates class identity.
    return class_roster_path(root, class_id).parent / JOURNAL_NAME


def _payload(intent: ClassPairIntent) -> dict[str, object]:
    return {
        "schema": SCHEMA,
        "class_id": intent.class_id,
        "old_roster_sha256": intent.old_roster_sha256,
        "old_metadata_sha256": intent.old_metadata_sha256,
        "expected_roster_fingerprint": intent.expected_roster_fingerprint,
        "expected_metadata_fingerprint": intent.expected_metadata_fingerprint,
        "old_metadata_base64": (
            base64.b64encode(intent.old_metadata_bytes).decode("ascii")
            if intent.old_metadata_bytes is not None else None
        ),
    }


def _parse(raw: bytes, *, class_id: str) -> ClassPairIntent:
    try:
        value = json.loads(raw)
        if not isinstance(value, dict) or set(value) != set(_payload(ClassPairIntent(
            class_id="", old_roster_sha256=None,
            old_metadata_sha256=None, expected_roster_fingerprint="",
            expected_metadata_fingerprint="", old_metadata_bytes=None,
        ))):
            raise ValueError("wrong fields")
        if value["schema"] != SCHEMA or value["class_id"] != class_id:
            raise ValueError("wrong class identity or schema")
        for name in ("old_roster_sha256", "old_metadata_sha256",
                     "expected_roster_fingerprint", "expected_metadata_fingerprint"):
            digest = value[name]
            if digest is None and name.startswith("old_"):
                continue
            if not isinstance(digest, str) or _HEX.fullmatch(digest) is None:
                raise ValueError("invalid digest")
        encoded = value["old_metadata_base64"]
        if encoded is not None and not isinstance(encoded, str):
            raise ValueError("invalid encoded backup")
        previous = base64.b64decode(encoded, validate=True) if encoded is not None else None
        if _hash(previous) != value["old_metadata_sha256"]:
            raise ValueError("backup digest mismatch")
        return ClassPairIntent(
            class_id=value["class_id"],
            old_roster_sha256=value["old_roster_sha256"],
            old_metadata_sha256=value["old_metadata_sha256"],
            expected_roster_fingerprint=value["expected_roster_fingerprint"],
            expected_metadata_fingerprint=value["expected_metadata_fingerprint"],
            old_metadata_bytes=previous,
        )
    except (TypeError, ValueError, UnicodeDecodeError, binascii.Error) as error:
        raise ClassPairRecoveryError(
            "Class-pair recovery journal is invalid; manual inspection required."
        ) from error


def read_intent(root: Path, class_id: str) -> ClassPairIntent | None:
    path = intent_path(root, class_id)
    if path.is_symlink():
        raise ClassPairRecoveryError("Class-pair journal is a symbolic link.")
    if not path.exists():
        return None
    if not path.is_file():
        raise ClassPairRecoveryError("Class-pair journal is not a regular file.")
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise ClassPairRecoveryError("Could not inspect class-pair journal.") from error
    return _parse(raw, class_id=class_id)


def _sync_directory(directory: Path) -> None:
    """Durably register journal names where directory fsync is supported."""
    if os.name == "nt":
        # Windows directory fsync is not exposed by Python's portable API.
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(directory, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def create_intent(root: Path, intent: ClassPairIntent) -> None:
    """Create-only journal is also the exclusive ScoreForm pair-operation gate."""
    path = intent_path(root, intent.class_id)
    folder = path.parent
    if folder.is_symlink() or (folder.exists() and not folder.is_dir()):
        raise ClassPairRecoveryError("Class folder cannot hold recovery journal.")
    folder.mkdir(parents=True, exist_ok=True)
    data = _canonical_json(_payload(intent)) + b"\n"
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError as error:
        raise ClassPairRecoveryError(
            "Unresolved or active class-pair journal exists. "
            "Do not retry until inspected and recovered."
        ) from error
    except OSError as error:
        raise ClassPairRecoveryError("Could not reserve class-pair journal.") from error
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        _sync_directory(folder)
    except BaseException:
        # No class files have been modified yet; retain no incomplete intent
        # when this process is able to perform normal exception cleanup.
        try:
            path.unlink()
        except OSError:
            pass
        raise


def clear_intent(root: Path, intent: ClassPairIntent) -> None:
    path = intent_path(root, intent.class_id)
    if read_intent(root, intent.class_id) != intent:
        raise ClassPairRecoveryError("Class-pair journal changed; manual review required.")
    try:
        path.unlink()
        _sync_directory(path.parent)
    except OSError as error:
        raise ClassPairRecoveryError("Could not clear completed class-pair journal.") from error


def _file_bytes(path: Path) -> bytes | None:
    if path.is_symlink():
        raise ClassPairRecoveryError("Canonical class file is a symbolic link.")
    if not path.exists():
        return None
    if not path.is_file():
        raise ClassPairRecoveryError("Canonical class entry is not a regular file.")
    try:
        return path.read_bytes()
    except OSError as error:
        raise ClassPairRecoveryError("Could not inspect canonical class file.") from error


def _status(root: Path, intent: ClassPairIntent) -> tuple[str, str]:
    roster_path = class_roster_path(root, intent.class_id)
    metadata_path = class_metadata_path(root, intent.class_id)
    roster_raw = _file_bytes(roster_path)
    metadata_raw = _file_bytes(metadata_path)
    if _hash(roster_raw) == intent.old_roster_sha256:
        roster_state = "before"
    elif roster_raw is not None:
        try:
            roster_state = (
                "after" if roster_fingerprint(load_class_roster(root, intent.class_id))
                == intent.expected_roster_fingerprint else "conflict"
            )
        except Exception:
            roster_state = "conflict"
    else:
        roster_state = "conflict"

    if _hash(metadata_raw) == intent.old_metadata_sha256:
        metadata_state = "before"
    elif metadata_raw is not None:
        try:
            metadata_state = (
                "after" if metadata_fingerprint(
                    load_class_metadata_for_class(root, intent.class_id)
                ) == intent.expected_metadata_fingerprint else "conflict"
            )
        except Exception:
            metadata_state = "conflict"
    else:
        metadata_state = "conflict"
    return roster_state, metadata_state


def inspect_class_pair_recovery(
    workspace_root: str | Path, class_id: str
) -> Literal["none", "unchanged", "restore_metadata", "completed", "conflict"]:
    root = Path(workspace_root).expanduser().absolute()
    class_roster_path(root, class_id)  # Validate before inspecting any class path.
    # Refuse unexpected redirected ancestors, including the journal parent.
    for path in (root, classes_dir(root), classes_dir(root) / class_id):
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            raise ClassPairRecoveryError("Canonical class directory is not safe.")
    intent = read_intent(root, class_id)
    if intent is None:
        return "none"
    roster_state, metadata_state = _status(root, intent)
    if roster_state == "before" and metadata_state == "before":
        return "unchanged"
    if roster_state == "before" and metadata_state == "after":
        return "restore_metadata"
    if roster_state == "after" and metadata_state == "after":
        return "completed"
    if roster_state == "after" and metadata_state == "before":
        # A valid idempotent metadata update might preserve the original bytes.
        try:
            metadata = load_class_metadata_for_class(root, class_id)
            if metadata_fingerprint(metadata) == intent.expected_metadata_fingerprint:
                return "completed"
        except Exception:
            pass
    return "conflict"


def recover_class_pair(workspace_root: str | Path, class_id: str) -> str:
    """Explicit recovery; invoke only when all writers for this class are stopped.

    Returns a disposition, never guesses at a divergent/new roster state.
    """
    root = Path(workspace_root).expanduser().absolute()
    disposition = inspect_class_pair_recovery(root, class_id)
    if disposition == "none":
        return "none"
    if disposition == "conflict":
        raise ClassPairRecoveryError(
            "Class-pair files conflict with recovery fingerprints; "
            "no file was changed. Manual reconciliation required."
        )
    intent = read_intent(root, class_id)
    if intent is None:
        raise ClassPairRecoveryError("Class-pair journal disappeared during recovery.")
    if disposition == "restore_metadata":
        # Both status checks occur immediately before restoration. A writer
        # that ignores ScoreForm's journal can still race; manual coordination
        # is mandatory, and unexpected changes fail closed.
        if inspect_class_pair_recovery(root, class_id) != "restore_metadata":
            raise ClassPairRecoveryError("Class files changed during recovery.")
        from scoreform.class_pair_commit import _restore_if_unchanged

        current = _file_bytes(class_metadata_path(root, class_id))
        if current is None:
            raise ClassPairRecoveryError("Committed metadata disappeared.")
        try:
            _restore_if_unchanged(
                class_metadata_path(root, class_id),
                previous=intent.old_metadata_bytes,
                committed=current,
            )
        except Exception as error:
            raise ClassPairRecoveryError(
                "Class metadata restoration failed; journal retained for review."
            ) from error
        if inspect_class_pair_recovery(root, class_id) != "unchanged":
            raise ClassPairRecoveryError("Recovery restoration could not be verified.")
        clear_intent(root, intent)
        return "restored"
    if inspect_class_pair_recovery(root, class_id) != disposition:
        raise ClassPairRecoveryError("Class files changed during recovery.")
    clear_intent(root, intent)
    return "finalized" if disposition == "completed" else "unchanged"


__all__ = (
    "ClassPairIntent", "ClassPairRecoveryError", "JOURNAL_NAME", "SCHEMA",
    "clear_intent", "create_intent", "inspect_class_pair_recovery", "intent_path",
    "metadata_fingerprint", "read_intent", "recover_class_pair",
    "roster_fingerprint",
)
