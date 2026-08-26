"""Privacy-minimal read-only ScoreForm readiness projection for Core operations."""

from __future__ import annotations

import stat
from pathlib import Path
from typing import Literal

from pds_core.classes import class_folder, load_class_roster
from pds_core.module_operations import (
    ModuleOperationsNotice,
    ModuleOperationsRequest,
    ModuleReadinessReport,
    validate_module_operations_request,
    validate_module_readiness_report,
)
from pds_core.rosters import RosterReadError, RosterValidationError
from pds_core.routes import classes_dir
from pds_core.workspace import WorkspaceRootError, inspect_workspace_root

from scoreform.pds_contract import SCOREFORM_MODULE_ID

READINESS_UNAVAILABLE_CODE = "scoreform_readiness_unavailable"
WORKSPACE_NOT_READY_CODE = "scoreform_workspace_not_ready"
CLASS_NOT_READY_CODE = "scoreform_class_not_ready"

READINESS_UNAVAILABLE_SUMMARY = (
    "ScoreForm readiness could not be evaluated for the supplied workspace context."
)
WORKSPACE_NOT_READY_SUMMARY = (
    "The supplied workspace is not currently usable for ScoreForm."
)
CLASS_NOT_READY_SUMMARY = (
    "The requested ScoreForm class context is unavailable or structurally invalid."
)


def _notice(code: str, summary: str) -> ModuleOperationsNotice:
    return ModuleOperationsNotice(code=code, summary=summary)


def _report(
    *,
    evaluation: Literal["evaluated", "unavailable"],
    ready: bool | None,
    notice: ModuleOperationsNotice | None = None,
) -> ModuleReadinessReport:
    report = ModuleReadinessReport(
        evaluation=evaluation,
        ready=ready,
        notices=() if notice is None else (notice,),
    )
    return validate_module_readiness_report(
        report,
        expected_module_id=SCOREFORM_MODULE_ID,
    )


def _unavailable() -> ModuleReadinessReport:
    return _report(
        evaluation="unavailable",
        ready=None,
        notice=_notice(READINESS_UNAVAILABLE_CODE, READINESS_UNAVAILABLE_SUMMARY),
    )


def _workspace_not_ready() -> ModuleReadinessReport:
    return _report(
        evaluation="evaluated",
        ready=False,
        notice=_notice(WORKSPACE_NOT_READY_CODE, WORKSPACE_NOT_READY_SUMMARY),
    )


def _class_not_ready() -> ModuleReadinessReport:
    return _report(
        evaluation="evaluated",
        ready=False,
        notice=_notice(CLASS_NOT_READY_CODE, CLASS_NOT_READY_SUMMARY),
    )


def _ready() -> ModuleReadinessReport:
    return _report(evaluation="evaluated", ready=True)


def _exact_class_readiness(root: Path, class_id: str) -> ModuleReadinessReport:
    """Inspect only the requested canonical Core class without mutating it."""

    try:
        shared_classes = classes_dir(root)
        if shared_classes.is_symlink():
            return _unavailable()
        try:
            classes_status = shared_classes.stat()
        except FileNotFoundError:
            classes_status = None
        if classes_status is not None and not stat.S_ISDIR(classes_status.st_mode):
            return _class_not_ready()

        folder = class_folder(root, class_id)
        if folder.class_dir.is_symlink():
            return _unavailable()
        try:
            class_status = folder.class_dir.stat()
        except FileNotFoundError:
            return _class_not_ready()
        if not stat.S_ISDIR(class_status.st_mode):
            return _class_not_ready()

        if folder.roster_path.is_symlink():
            return _unavailable()
        try:
            roster_status = folder.roster_path.stat()
        except FileNotFoundError:
            return _class_not_ready()
        if not stat.S_ISREG(roster_status.st_mode):
            return _class_not_ready()

        load_class_roster(root, class_id)
    except RosterValidationError:
        return _class_not_ready()
    except (OSError, RuntimeError, RosterReadError):
        return _unavailable()

    return _ready()


def evaluate_scoreform_readiness(
    request: ModuleOperationsRequest,
    /,
) -> ModuleReadinessReport:
    """Evaluate whether ScoreForm can operate in the exact supplied context.

    Readiness is deliberately narrower than Suite installation health and broader
    than readiness for any one assessment operation. ``active_school_year`` is
    validated by Core but does not independently change ScoreForm readiness.
    """

    request = validate_module_operations_request(request)
    if request.workspace_root is None:
        return _unavailable()

    raw_root = Path(request.workspace_root)
    try:
        if raw_root.is_symlink():
            return _unavailable()
        status = inspect_workspace_root(request.workspace_root)
    except (OSError, RuntimeError, WorkspaceRootError):
        return _unavailable()

    if not status.exists:
        return _unavailable()
    if not status.is_dir:
        return _workspace_not_ready()
    if status.root.is_symlink():
        return _unavailable()
    if not status.is_writable:
        return _workspace_not_ready()

    if request.class_id is not None:
        return _exact_class_readiness(status.root, request.class_id)
    return _ready()


__all__ = [
    "CLASS_NOT_READY_CODE",
    "CLASS_NOT_READY_SUMMARY",
    "READINESS_UNAVAILABLE_CODE",
    "READINESS_UNAVAILABLE_SUMMARY",
    "WORKSPACE_NOT_READY_CODE",
    "WORKSPACE_NOT_READY_SUMMARY",
    "evaluate_scoreform_readiness",
]
