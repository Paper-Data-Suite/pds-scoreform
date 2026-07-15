"""Defensive Core route handler for one authoritative ScoreForm page."""

from __future__ import annotations

import io
import os
from contextlib import redirect_stdout
from pathlib import Path

from pds_core.routes import class_dir, class_module_dir, module_work_dir
from pds_core.routing_models import (
    RouteResolution,
    RoutingModelError,
    validate_route_locator,
    validate_route_registration,
)
from pds_core.scan_retention import RetainedSourceScan

from scoreform.answer_sheet_persistence import (
    AnswerSheetPageContext,
    AnswerSheetPersistenceError,
    load_answer_sheet_page_context,
)
from scoreform.answer_sheet_records import (
    AnswerSheetRecordError,
    answer_sheet_page_target,
    validate_answer_sheet_issuance,
)
from scoreform.answer_sheet_routes import (
    answer_sheet_human_fallback,
    answer_sheet_module_details,
)
from scoreform.assignment import load_assignment
from scoreform.module_errors import (
    ScoreFormAssignmentCompatibilityError,
    ScoreFormIssuanceAuthorizationError,
    ScoreFormPageScoringError,
    ScoreFormRouteContextError,
    ScoreFormTargetIntegrityError,
)
from scoreform.page_scoring import (
    ScoreFormPageDispatchResult,
    score_authoritative_answer_sheet_page,
    validate_assignment_page_compatibility,
    validate_page_dispatch_result,
)
from scoreform.pds_contract import SCOREFORM_MODULE_ID
from scoreform.pds_module import validate_scoreform_registration
from scoreform.retained_page import (
    load_retained_source_page,
    validate_retained_source,
)
from scoreform.work_paths import scoreform_work_paths


def _validate_handler_arguments(
    resolution: RouteResolution,
    retained_source: RetainedSourceScan,
    source_page_number: int,
) -> None:
    if not isinstance(resolution, RouteResolution):
        raise ScoreFormRouteContextError("resolution must be a RouteResolution.")
    if not isinstance(retained_source, RetainedSourceScan):
        raise ScoreFormRouteContextError(
            "retained_source must be a RetainedSourceScan."
        )
    if (
        isinstance(source_page_number, bool)
        or not isinstance(source_page_number, int)
        or source_page_number < 1
    ):
        raise ScoreFormRouteContextError(
            "source_page_number must be an integer greater than or equal to one."
        )


def _validate_resolution(resolution: RouteResolution) -> None:
    try:
        validate_route_locator(resolution.locator)
        validate_route_registration(resolution.registration)
    except (RoutingModelError, TypeError, ValueError) as error:
        raise ScoreFormRouteContextError("Route resolution models are invalid.") from error
    if resolution.locator != resolution.registration.locator:
        raise ScoreFormRouteContextError(
            "Resolution locator must exactly equal registration.locator."
        )
    if resolution.locator.module_id != SCOREFORM_MODULE_ID:
        raise ScoreFormRouteContextError(
            'Resolution module identity must be "scoreform".'
        )


def _canonical_workspace_root(resolution: RouteResolution) -> Path:
    workspace_root = resolution.class_root.parent.parent
    locator = resolution.locator
    expected = (
        class_dir(workspace_root, locator.class_id),
        class_module_dir(workspace_root, locator.class_id, SCOREFORM_MODULE_ID),
        module_work_dir(workspace_root, locator.work),
    )
    actual = (resolution.class_root, resolution.module_root, resolution.work_root)
    if actual != expected:
        raise ScoreFormRouteContextError(
            "Resolution roots do not equal Core's canonical paths."
        )
    for label, path in zip(("class", "module", "work"), actual, strict=True):
        if path.is_symlink():
            raise ScoreFormRouteContextError(
                f"Symlinked {label} roots are not allowed."
            )
        if not path.exists() or not path.is_dir():
            raise ScoreFormRouteContextError(
                f"Canonical {label} root is missing or not a directory."
            )
    try:
        resolution.work_root.resolve(strict=True).relative_to(
            workspace_root.resolve(strict=True)
        )
    except (OSError, RuntimeError, ValueError) as error:
        raise ScoreFormRouteContextError(
            "Canonical work root escapes the derived workspace."
        ) from error
    return workspace_root


def _load_target(
    workspace_root: Path,
    resolution: RouteResolution,
) -> AnswerSheetPageContext:
    try:
        return load_answer_sheet_page_context(
            workspace_root,
            resolution.locator.work,
            resolution.registration.target.record_id,
        )
    except (AnswerSheetPersistenceError, AnswerSheetRecordError) as error:
        raise ScoreFormTargetIntegrityError(
            "The exact registered answer-sheet page context could not be loaded."
        ) from error


def _cross_validate_target(
    resolution: RouteResolution,
    context: AnswerSheetPageContext,
) -> None:
    registration = resolution.registration
    locator = resolution.locator
    page = context.page
    issuance = context.issuance
    if registration.target != answer_sheet_page_target(page):
        raise ScoreFormTargetIntegrityError(
            "Registration target does not exactly match the authoritative page."
        )
    if (locator.class_id, locator.work_id) != (
        page.class_id,
        page.assignment_id,
    ):
        raise ScoreFormTargetIntegrityError(
            "Locator work does not match the authoritative page."
        )
    if registration.created_at != page.created_at:
        raise ScoreFormTargetIntegrityError(
            "Registration timestamp does not match page creation."
        )
    if registration.module_details != answer_sheet_module_details(page):
        raise ScoreFormTargetIntegrityError(
            "Registration module_details do not match the authoritative page."
        )
    if registration.human_fallback != answer_sheet_human_fallback(page):
        raise ScoreFormTargetIntegrityError(
            "Registration human_fallback does not match the authoritative page."
        )
    if sum(candidate.page_id == page.page_id for candidate in context.pages) != 1:
        raise ScoreFormTargetIntegrityError(
            "Authoritative page membership is not unique in its issuance."
        )
    if (
        issuance.generation_id != page.generation_id
        or issuance.artifact_id != page.artifact_id
        or issuance.student_id != page.student_id
    ):
        raise ScoreFormTargetIntegrityError(
            "Authoritative page identity does not match its issuance."
        )


def _authorize_issuance(context: AnswerSheetPageContext) -> None:
    try:
        validate_answer_sheet_issuance(context.issuance)
    except AnswerSheetRecordError as error:
        raise ScoreFormIssuanceAuthorizationError(
            "Issuance lifecycle data is invalid."
        ) from error
    if context.issuance.lifecycle.status != "issued":
        raise ScoreFormIssuanceAuthorizationError(
            "Only an issuance with lifecycle status 'issued' is authorized for scoring."
        )


def _load_managed_assignment(workspace_root: Path, resolution: RouteResolution):
    paths = scoreform_work_paths(
        workspace_root,
        resolution.locator.class_id,
        resolution.locator.work_id,
    )
    path = paths.assignment_path
    if path.is_symlink():
        raise ScoreFormAssignmentCompatibilityError(
            "Symlinked managed assignments are not allowed."
        )
    if not path.exists() or not path.is_file() or not os.access(path, os.R_OK):
        raise ScoreFormAssignmentCompatibilityError(
            "Managed assignment is missing, unreadable, or not a regular file."
        )
    try:
        with redirect_stdout(io.StringIO()):
            assignment = load_assignment(path)
    except (OSError, TypeError, ValueError) as error:
        raise ScoreFormAssignmentCompatibilityError(
            "Managed assignment could not be loaded."
        ) from error
    if assignment is None:
        raise ScoreFormAssignmentCompatibilityError("Managed assignment is invalid.")
    if assignment["assignment_id"] != resolution.locator.work_id:
        raise ScoreFormAssignmentCompatibilityError(
            "Managed assignment ID does not match the routed work."
        )
    debug_dir = paths.debug_dir
    if debug_dir.is_symlink() or (debug_dir.exists() and not debug_dir.is_dir()):
        raise ScoreFormAssignmentCompatibilityError(
            "Managed diagnostic path is symlinked or has the wrong filesystem type."
        )
    return assignment, debug_dir


def _validate_handler_result(
    result: ScoreFormPageDispatchResult,
    *,
    resolution: RouteResolution,
    context: AnswerSheetPageContext,
    retained_source: RetainedSourceScan,
    source_page_number: int,
    debug_dir: Path,
    valid_choices: tuple[str, ...],
) -> ScoreFormPageDispatchResult:
    try:
        validate_page_dispatch_result(result, valid_choices=valid_choices)
    except ScoreFormPageScoringError as error:
        raise ScoreFormTargetIntegrityError(
            "Scoring result violates the immutable page-result contract."
        ) from error
    page = context.page
    expected_identity = (
        resolution.locator.route_id,
        page.page_id,
        page.issuance_id,
        page.generation_id,
        page.artifact_id,
        page.class_id,
        page.assignment_id,
        page.student_id,
        page.logical_page,
        page.total_pages,
        page.question_start,
        page.question_end,
        page.layout_id,
    )
    actual_identity = (
        result.route_id,
        result.page_id,
        result.issuance_id,
        result.generation_id,
        result.artifact_id,
        result.class_id,
        result.assignment_id,
        result.student_id,
        result.logical_page,
        result.total_pages,
        result.question_start,
        result.question_end,
        result.layout_id,
    )
    if actual_identity != expected_identity:
        raise ScoreFormTargetIntegrityError(
            "Scoring result identity does not match the authoritative route and page."
        )
    if (
        result.source_scan_id != retained_source.source_scan_id
        or result.source_page_number != source_page_number
        or result.retained_source_relative_path
        != retained_source.retained_source_relative_path
        or result.source_sha256 != retained_source.source_sha256
    ):
        raise ScoreFormTargetIntegrityError(
            "Scoring result provenance does not match the retained source."
        )
    _authorize_diagnostic_paths(result.diagnostic_paths, debug_dir=debug_dir)
    return result


def _authorize_diagnostic_paths(
    diagnostic_paths: tuple[str, ...],
    *,
    debug_dir: Path,
) -> None:
    try:
        debug_root = debug_dir.resolve(strict=True) if diagnostic_paths else None
        for diagnostic in diagnostic_paths:
            if not isinstance(diagnostic, str) or not diagnostic:
                raise ValueError("diagnostic path must be a nonempty string")
            assert debug_root is not None
            path = Path(diagnostic)
            path.resolve(strict=True).relative_to(debug_root)
            if path.is_symlink() or not path.is_file():
                raise ValueError("diagnostic is not a regular non-symlink file")
    except (OSError, RuntimeError, ValueError) as error:
        raise ScoreFormTargetIntegrityError(
            "Scoring diagnostics are missing or outside the managed debug directory."
        ) from error


def handle_scoreform_route(
    resolution: RouteResolution,
    retained_source: RetainedSourceScan,
    source_page_number: int,
    /,
) -> ScoreFormPageDispatchResult:
    """Validate, authorize, extract, and score one resolved ScoreForm page."""
    _validate_handler_arguments(resolution, retained_source, source_page_number)
    _validate_resolution(resolution)
    validate_scoreform_registration(resolution.registration)
    workspace_root = _canonical_workspace_root(resolution)
    context = _load_target(workspace_root, resolution)
    _cross_validate_target(resolution, context)
    _authorize_issuance(context)
    assignment, debug_dir = _load_managed_assignment(workspace_root, resolution)
    validate_assignment_page_compatibility(context, assignment)
    validate_retained_source(retained_source, workspace_root=workspace_root)
    retained_page = load_retained_source_page(
        retained_source,
        source_page_number,
        workspace_root=workspace_root,
    )
    try:
        result = score_authoritative_answer_sheet_page(
            retained_page.image,
            page_context=context,
            assignment=assignment,
            route_id=resolution.locator.route_id,
            source_scan_id=retained_page.source_scan_id,
            source_page_number=retained_page.source_page_number,
            retained_source_relative_path=(
                retained_page.retained_source_relative_path
            ),
            source_sha256=retained_page.source_sha256,
            debug_dir=debug_dir,
        )
    except ScoreFormPageScoringError as error:
        _authorize_diagnostic_paths(error.diagnostic_paths, debug_dir=debug_dir)
        raise
    return _validate_handler_result(
        result,
        resolution=resolution,
        context=context,
        retained_source=retained_source,
        source_page_number=source_page_number,
        debug_dir=debug_dir,
        valid_choices=tuple(assignment["choices"]),
    )
