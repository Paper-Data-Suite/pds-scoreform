"""Silent, read-only discovery of canonical ScoreForm managed work."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pds_core.classes import list_class_folders
from pds_core.routing_models import ModuleWorkRef

from scoreform.assignment import AssignmentJsonBytesError, assignment_from_json_bytes
from scoreform.work_paths import scoreform_work_collection_dir, scoreform_work_paths


class ScoreFormAttentionDiscoveryError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ScoreFormWorkDiscovery:
    work_refs: tuple[ModuleWorkRef, ...]
    warning_count: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.work_refs, tuple):
            raise TypeError("work_refs must be an immutable tuple.")
        if any(work_ref.module_id != "scoreform" for work_ref in self.work_refs):
            raise ValueError("discovered work must belong to ScoreForm.")
        if (
            isinstance(self.warning_count, bool)
            or not isinstance(self.warning_count, int)
            or self.warning_count < 0
        ):
            raise ValueError("warning_count must be a nonnegative integer.")


def discover_scoreform_class_ids(
    workspace_root: str | Path,
    requested_class_id: str | None,
) -> tuple[str, ...]:
    if requested_class_id is not None:
        return (requested_class_id,)
    return tuple(
        folder.class_id for folder in list_class_folders(workspace_root)
    )


def discover_scoreform_work(
    workspace_root: str | Path,
    class_id: str,
) -> ScoreFormWorkDiscovery:
    root = Path(workspace_root)
    collection = scoreform_work_collection_dir(root, class_id)

    try:
        if not collection.exists():
            return ScoreFormWorkDiscovery(())
        if collection.is_symlink() or not collection.is_dir():
            raise ScoreFormAttentionDiscoveryError(
                "ScoreForm work collection is not a safe ordinary directory."
            )
        entries = tuple(sorted(collection.iterdir(), key=lambda item: item.name))
    except ScoreFormAttentionDiscoveryError:
        raise
    except OSError as error:
        raise ScoreFormAttentionDiscoveryError(
            "ScoreForm work collection could not be inspected safely."
        ) from error

    work_refs: list[ModuleWorkRef] = []
    warnings = 0
    for entry in entries:
        try:
            if entry.is_symlink() or not entry.is_dir():
                warnings += 1
                continue
            paths = scoreform_work_paths(root, class_id, entry.name)
            assignment_path = paths.assignment_path
            if assignment_path.is_symlink() or not assignment_path.is_file():
                warnings += 1
                continue
            assignment = assignment_from_json_bytes(assignment_path.read_bytes())
            if assignment.get("assignment_id") != paths.work_ref.work_id:
                warnings += 1
                continue
        except (
            AssignmentJsonBytesError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
        ):
            warnings += 1
            continue
        work_refs.append(paths.work_ref)

    return ScoreFormWorkDiscovery(
        tuple(work_refs),
        warning_count=warnings,
    )


__all__ = [
    "ScoreFormAttentionDiscoveryError",
    "ScoreFormWorkDiscovery",
    "discover_scoreform_class_ids",
    "discover_scoreform_work",
]
