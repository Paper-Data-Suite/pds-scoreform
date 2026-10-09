"""Issue #225 Slice 8: authoritative Core dispatch of a preflighted page.

No QR re-decoding, attempted result assembly, result-row persistence, or Core
scan-resolution writes.  A dispatch success is NOT a completed recovery.
The original retained page is never copied/retained again.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pds_core.module_dispatch import (
    RouteDispatchRequest,
    RouteDispatchSuccess,
    dispatch_route,
)
from pds_core.module_profiles import ModuleRegistry

from scoreform.answer_sheet_persistence import load_answer_sheet_page_context
from scoreform.layouts import require_layout
from scoreform.page_scoring import (
    ScoreFormPageDispatchResult,
    validate_page_dispatch_result,
)
from scoreform.pds2_scan_dispatch import (
    build_scoreform_scan_registry,
    validate_scan_registry,
)
from scoreform.qr_scan_recovery_preflight import (
    PreparedScoreFormScanRecovery,
    ScoreFormScanRecoveryPreflightError,
    prepare_scoreform_scan_recovery,
)
from scoreform.route_handler import _authorize_diagnostic_paths
from scoreform.work_paths import scoreform_work_paths


class ScoreFormScanRecoveryDispatchError(RuntimeError):
    """A retained page could not be dispatched and checked authoritatively."""


@dataclass(frozen=True, slots=True)
class DispatchedScoreFormScanRecovery:
    """A verified scored page, *not* a persisted completed student attempt."""

    prepared: PreparedScoreFormScanRecovery
    request: RouteDispatchRequest
    success: RouteDispatchSuccess
    page_result: ScoreFormPageDispatchResult


def _reprepare(
    root: Path, prepared: PreparedScoreFormScanRecovery
) -> PreparedScoreFormScanRecovery:
    """Recheck durable state for both explicit and historical route decisions."""
    if prepared.route_origin == "recorded":
        return prepare_scoreform_scan_recovery(
            root, prepared.failure_id, use_recorded_route=True
        )
    if prepared.route_origin == "explicit":
        return prepare_scoreform_scan_recovery(
            root,
            prepared.failure_id,
            route_locator=prepared.route_locator,
            target=prepared.target,
            allow_route_correction=prepared.route_correction_confirmed,
        )
    raise ScoreFormScanRecoveryDispatchError("Unknown prepared recovery route origin.")


def _verify_success(
    root: Path,
    prepared: PreparedScoreFormScanRecovery,
    request: RouteDispatchRequest,
    success: RouteDispatchSuccess,
    registry: ModuleRegistry,
) -> ScoreFormPageDispatchResult:
    """Independently cross-check Core and ScoreForm's immutable page authority."""
    if type(success) is not RouteDispatchSuccess:
        raise ScoreFormScanRecoveryDispatchError(
            "Core did not return an exact dispatch success."
        )
    try:
        profile = registry.require("scoreform")
        if (
            success.request != request
            or success.profile is not profile
            or success.profile.module_id != "scoreform"
            or success.resolution.locator != prepared.route_locator
            or success.resolution.registration.locator != prepared.route_locator
            or success.resolution.registration.target != prepared.target
            or success.resolution.registration.status != "active"
        ):
            raise ScoreFormScanRecoveryDispatchError(
                "Core dispatch identity or registration contradicts recovery."
            )
        result = success.module_result
        if type(result) is not ScoreFormPageDispatchResult:
            raise ScoreFormScanRecoveryDispatchError(
                "Core did not return an exact ScoreForm page-scoring result."
            )
        context = load_answer_sheet_page_context(
            root, prepared.route_locator.work, prepared.target.record_id
        )
        page = context.page
        if context.issuance.lifecycle.status != "issued":
            raise ScoreFormScanRecoveryDispatchError(
                "The authoritative issuance is no longer issued."
            )
        validated = validate_page_dispatch_result(
            result, valid_choices=require_layout(page.layout_id).choices
        )
        expected = (
            prepared.route_locator.route_id,
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
            prepared.retained_source.source_scan_id,
            prepared.source_page_number,
            prepared.retained_source.retained_source_relative_path,
            prepared.retained_source.source_sha256,
        )
        actual = (
            validated.route_id,
            validated.page_id,
            validated.issuance_id,
            validated.generation_id,
            validated.artifact_id,
            validated.class_id,
            validated.assignment_id,
            validated.student_id,
            validated.logical_page,
            validated.total_pages,
            validated.question_start,
            validated.question_end,
            validated.layout_id,
            validated.source_scan_id,
            validated.source_page_number,
            validated.retained_source_relative_path,
            validated.source_sha256,
        )
        if actual != expected or (
            prepared.page_id != page.page_id
            or prepared.issuance_id != page.issuance_id
            or prepared.class_id != page.class_id
            or prepared.assignment_id != page.assignment_id
            or prepared.student_id != page.student_id
            or prepared.logical_page != page.logical_page
            or prepared.total_pages != page.total_pages
        ):
            raise ScoreFormScanRecoveryDispatchError(
                "Scored page identity or original scan provenance contradicts recovery."
            )
        _authorize_diagnostic_paths(
            validated.diagnostic_paths,
            debug_dir=scoreform_work_paths(
                root, prepared.class_id, prepared.assignment_id
            ).debug_dir,
        )
        return validated
    except ScoreFormScanRecoveryDispatchError:
        raise
    except Exception as error:
        raise ScoreFormScanRecoveryDispatchError(
            "Core or ScoreForm recovery result could not be verified."
        ) from error


def dispatch_prepared_scoreform_scan_recovery(
    workspace_root: str | Path,
    prepared: PreparedScoreFormScanRecovery,
    *,
    registry: ModuleRegistry | None = None,
) -> DispatchedScoreFormScanRecovery:
    """Re-preflight, dispatch one physical page via Core, verify and recheck.

    The optional registry is a test/integration seam. Production uses the
    installed registry. This operation does not append resolution or result
    records; a later slice must explicitly assemble and persist an attempt.
    """
    if type(prepared) is not PreparedScoreFormScanRecovery:
        raise ScoreFormScanRecoveryDispatchError(
            "An exact Slice 7 prepared recovery is required."
        )
    try:
        root = Path(workspace_root).resolve(strict=True)
        current = _reprepare(root, prepared)
    except (ScoreFormScanRecoveryPreflightError, OSError, ValueError, TypeError) as error:
        raise ScoreFormScanRecoveryDispatchError(
            "Recovery preflight no longer passes; prepare the page again."
        ) from error
    if current != prepared:
        raise ScoreFormScanRecoveryDispatchError(
            "Recovery preview is stale; prepare and confirm it again."
        )

    try:
        chosen = (
            build_scoreform_scan_registry() if registry is None else registry
        )
        chosen = validate_scan_registry(chosen)
    except Exception as error:
        raise ScoreFormScanRecoveryDispatchError(
            "The installed ScoreForm Core dispatch registry is unavailable."
        ) from error

    try:
        request = RouteDispatchRequest(
            locator=current.route_locator,
            retained_source=current.retained_source,
            source_page_number=current.source_page_number,
        )
        success = dispatch_route(root, chosen, request)
    except Exception as error:
        raise ScoreFormScanRecoveryDispatchError(
            "Core failed to dispatch the original retained ScoreForm page."
        ) from error

    result = _verify_success(root, current, request, success, chosen)
    try:
        afterward = _reprepare(root, current)
    except (ScoreFormScanRecoveryPreflightError, OSError, ValueError, TypeError) as error:
        raise ScoreFormScanRecoveryDispatchError(
            "Recovery authority changed during dispatch; prepare again."
        ) from error
    if afterward != current:
        raise ScoreFormScanRecoveryDispatchError(
            "Recovery source or route changed during dispatch; prepare again."
        )
    return DispatchedScoreFormScanRecovery(
        prepared=current,
        request=request,
        success=success,
        page_result=result,
    )


__all__ = [
    "DispatchedScoreFormScanRecovery",
    "ScoreFormScanRecoveryDispatchError",
    "dispatch_prepared_scoreform_scan_recovery",
]
