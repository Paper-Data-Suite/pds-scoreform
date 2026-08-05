"""Canonical, side-effect-free paths for ScoreForm-managed work."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pds_core.publication_records import validate_publication_manifest_path
from pds_core.routes import (
    class_roster_path,
    module_work_collection_dir,
    module_work_dir,
    safe_module_work_descendant,
)
from pds_core.routing_models import ModuleWorkRef, validate_module_work_ref

from scoreform.pds_contract import SCOREFORM_MODULE_ID


def answer_sheet_issuance_path(
    workspace_root: str | Path,
    work_ref: ModuleWorkRef,
    issuance_id: str,
) -> Path:
    """Return one exact issuance path without touching the filesystem."""
    from scoreform.answer_sheet_records import validate_issuance_id

    work_ref = validate_module_work_ref(work_ref)
    if work_ref.module_id != SCOREFORM_MODULE_ID:
        raise ValueError('work_ref.module_id must be "scoreform".')
    validated_id = validate_issuance_id(issuance_id)
    return safe_module_work_descendant(
        workspace_root,
        work_ref,
        f"answer_sheets/issuances/{validated_id}.json",
    )


def answer_sheet_page_path(
    workspace_root: str | Path,
    work_ref: ModuleWorkRef,
    page_id: str,
) -> Path:
    """Return one exact immutable page path without touching the filesystem."""
    from scoreform.answer_sheet_records import validate_page_id

    work_ref = validate_module_work_ref(work_ref)
    if work_ref.module_id != SCOREFORM_MODULE_ID:
        raise ValueError('work_ref.module_id must be "scoreform".')
    validated_id = validate_page_id(page_id)
    return safe_module_work_descendant(
        workspace_root,
        work_ref,
        f"answer_sheets/pages/{validated_id}.json",
    )


@dataclass(frozen=True, slots=True)
class ScoreFormWorkPaths:
    """All canonical shared and ScoreForm-owned paths for one assignment."""

    work_ref: ModuleWorkRef
    roster_path: Path
    work_root: Path
    assignment_path: Path
    answer_sheets_dir: Path
    answer_sheet_issuances_dir: Path
    answer_sheet_pages_dir: Path
    templates_dir: Path
    individual_templates_dir: Path
    class_packet_path: Path
    scans_dir: Path
    results_path: Path
    debug_dir: Path
    exports_dir: Path
    manifest_exports_dir: Path
    academic_result_manifests_dir: Path


def _positive_revision(revision: object) -> int:
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise ValueError("revision must be a positive integer.")
    return revision


def academic_result_manifest_relative_path(
    work_ref: ModuleWorkRef,
    revision: int,
) -> str:
    """Return one Core-valid workspace-relative manifest revision path."""
    work_ref = validate_module_work_ref(work_ref)
    if work_ref.module_id != SCOREFORM_MODULE_ID:
        raise ValueError('work_ref.module_id must be "scoreform".')
    value = _positive_revision(revision)
    relative_path = (
        f"classes/{work_ref.class_id}/modules/{work_ref.module_id}/work/"
        f"{work_ref.work_id}/exports/manifests/academic_results/{value}.json"
    )
    return validate_publication_manifest_path(work_ref, relative_path)


def academic_result_manifest_revision_path(
    workspace_root: str | Path,
    work_ref: ModuleWorkRef,
    revision: int,
) -> Path:
    """Return one immutable manifest target without touching the filesystem."""
    work_ref = validate_module_work_ref(work_ref)
    if work_ref.module_id != SCOREFORM_MODULE_ID:
        raise ValueError('work_ref.module_id must be "scoreform".')
    value = _positive_revision(revision)
    return safe_module_work_descendant(
        workspace_root,
        work_ref,
        f"exports/manifests/academic_results/{value}.json",
    )


def scoreform_work_ref(class_id: str, assignment_id: str) -> ModuleWorkRef:
    """Return ScoreForm's complete module-qualified identity for an assignment."""
    return ModuleWorkRef(
        module_id=SCOREFORM_MODULE_ID,
        class_id=class_id,
        work_id=assignment_id,
    )


def scoreform_work_collection_dir(workspace_root: str | Path, class_id: str) -> Path:
    """Return the exact ScoreForm work collection without touching the filesystem."""
    return module_work_collection_dir(
        workspace_root,
        class_id,
        SCOREFORM_MODULE_ID,
    )


def scoreform_work_paths(
    workspace_root: str | Path,
    class_id: str,
    assignment_id: str,
) -> ScoreFormWorkPaths:
    """Build canonical paths for one managed assignment without filesystem access."""
    work_ref = scoreform_work_ref(class_id, assignment_id)

    def descendant(relative_path: str) -> Path:
        return safe_module_work_descendant(
            workspace_root,
            work_ref,
            relative_path,
        )

    return ScoreFormWorkPaths(
        work_ref=work_ref,
        roster_path=class_roster_path(workspace_root, class_id),
        work_root=module_work_dir(workspace_root, work_ref),
        assignment_path=descendant("assignment.json"),
        answer_sheets_dir=descendant("answer_sheets"),
        answer_sheet_issuances_dir=descendant("answer_sheets/issuances"),
        answer_sheet_pages_dir=descendant("answer_sheets/pages"),
        templates_dir=descendant("templates"),
        individual_templates_dir=descendant("templates/individual"),
        class_packet_path=descendant("templates/class_packet.pdf"),
        scans_dir=descendant("scans"),
        results_path=descendant("results.csv"),
        debug_dir=descendant("debug"),
        exports_dir=descendant("exports"),
        manifest_exports_dir=descendant("exports/manifests"),
        academic_result_manifests_dir=descendant(
            "exports/manifests/academic_results"
        ),
    )


def build_scoreform_work_paths(
    workspace_root: str | Path,
    class_id: str,
    assignment_id: str,
) -> ScoreFormWorkPaths:
    """Named constructor alias for callers that prefer an explicit build verb."""
    return scoreform_work_paths(workspace_root, class_id, assignment_id)


def initialize_managed_work_layout(paths: ScoreFormWorkPaths) -> ScoreFormWorkPaths:
    """Create only the ScoreForm-owned directories required for managed work.

    Every required path is preflighted before mutation. Existing compatible
    directories and files outside this directory set are preserved.
    """
    required_directories = (
        paths.work_root,
        paths.templates_dir,
        paths.individual_templates_dir,
        paths.scans_dir,
        paths.debug_dir,
    )
    for directory in required_directories:
        if directory.is_symlink() or (
            directory.exists() and not directory.is_dir()
        ):
            raise FileExistsError(
                f"Required ScoreForm directory exists as another filesystem type: "
                f"{directory}"
            )

    for directory in required_directories:
        directory.mkdir(parents=True, exist_ok=True)

    return paths


def initialize_scoreform_work_layout(
    workspace_root: str | Path,
    class_id: str,
    assignment_id: str,
) -> ScoreFormWorkPaths:
    """Build, preflight, and initialize one ScoreForm-owned work layout."""
    return initialize_managed_work_layout(
        scoreform_work_paths(workspace_root, class_id, assignment_id)
    )
