"""Privacy-minimal read-only ScoreForm attention projection for Core operations."""

from __future__ import annotations

from pathlib import Path

from pds_core.module_operations import (
    ModuleAttentionReport,
    ModuleOperationsRequest,
    validate_module_attention_report,
    validate_module_operations_request,
)
from pds_core.workspace import WorkspaceRootError, inspect_workspace_root

from scoreform.attention_model import (
    MISSING_WORKSPACE_SUMMARY,
    UNSAFE_CLASS_SCOPE_SUMMARY,
    UNSAFE_WORKSPACE_SUMMARY,
    ScoreFormAttentionAccumulator,
    partial_notice,
    unavailable_notice,
)
from scoreform.attention_scan import project_scan_attention_fact
from scoreform.attention_share_results import project_share_results_attention
from scoreform.attention_work_discovery import (
    ScoreFormAttentionDiscoveryError,
    discover_scoreform_class_ids,
    discover_scoreform_work,
)
from scoreform.guided_share_results import (
    ScoreFormShareResultsPlanningError,
    plan_share_results_readiness,
)
from scoreform.pds_contract import SCOREFORM_MODULE_ID
from scoreform.scan_review_resolution import (
    ScanReviewError,
    discover_scan_review_items,
)


def _validated_report(report: ModuleAttentionReport) -> ModuleAttentionReport:
    return validate_module_attention_report(
        report,
        expected_module_id=SCOREFORM_MODULE_ID,
    )


def _unavailable(summary: str) -> ModuleAttentionReport:
    return _validated_report(
        ModuleAttentionReport(
            evaluation="unavailable",
            summaries=(),
            notices=(unavailable_notice(summary),),
        )
    )


def _safe_workspace(request: ModuleOperationsRequest) -> Path | None:
    if request.workspace_root is None:
        return None
    try:
        status = inspect_workspace_root(request.workspace_root)
        if (
            not status.exists
            or not status.is_dir
            or status.root.is_symlink()
        ):
            return None
    except (OSError, RuntimeError, WorkspaceRootError):
        return None
    return status.root


def _add_scan_attention(
    accumulator: ScoreFormAttentionAccumulator,
    root: Path,
    request: ModuleOperationsRequest,
) -> bool:
    """Add current open scan attention; return whether evaluation is partial."""

    try:
        discovery = discover_scan_review_items(
            root,
            class_id=request.class_id,
        )
    except (OSError, RuntimeError, ScanReviewError, ValueError):
        return True

    partial = discovery.warning_count > 0
    for item in discovery.items:
        try:
            fact = project_scan_attention_fact(item)
            accumulator.add(
                fact.code,
                1,
                class_id=fact.class_id,
                work_ref=fact.work_ref,
            )
        except Exception:
            # One unprojectable current review item must not erase unrelated
            # valid attention. Keep the shared report bounded and partial;
            # never expose the underlying exception text.
            partial = True
    return partial


def _add_share_results_attention(
    accumulator: ScoreFormAttentionAccumulator,
    root: Path,
    work_refs: tuple,
) -> bool:
    """Add assignment-level #191 Share Results attention."""

    partial = False
    for work_ref in work_refs:
        try:
            readiness = plan_share_results_readiness(
                root,
                work_ref.class_id,
                work_ref.work_id,
            )
            fact = project_share_results_attention(readiness)
            if fact is None:
                continue
            accumulator.add(
                fact.code,
                1,
                class_id=fact.work_ref.class_id,
                work_ref=fact.work_ref,
            )
        except (ScoreFormShareResultsPlanningError, OSError, TypeError, ValueError):
            partial = True
        except Exception:
            # Planner adapters are observational. Unexpected per-assignment
            # failures degrade only this source to a bounded partial result.
            partial = True
    return partial


def evaluate_scoreform_attention(
    request: ModuleOperationsRequest,
    /,
) -> ModuleAttentionReport:
    """Evaluate current ScoreForm teacher attention without writing state."""

    request = validate_module_operations_request(request)
    if request.workspace_root is None:
        return _unavailable(MISSING_WORKSPACE_SUMMARY)

    root = _safe_workspace(request)
    if root is None:
        return _unavailable(UNSAFE_WORKSPACE_SUMMARY)

    accumulator = ScoreFormAttentionAccumulator()
    partial = _add_scan_attention(accumulator, root, request)

    try:
        class_ids = discover_scoreform_class_ids(root, request.class_id)
    except OSError:
        return _unavailable(UNSAFE_CLASS_SCOPE_SUMMARY)

    for class_id in class_ids:
        try:
            discovery = discover_scoreform_work(root, class_id)
        except ScoreFormAttentionDiscoveryError:
            if request.class_id is not None:
                return _unavailable(UNSAFE_CLASS_SCOPE_SUMMARY)
            partial = True
            continue

        if discovery.warning_count:
            partial = True

        if _add_share_results_attention(
            accumulator,
            root,
            discovery.work_refs,
        ):
            partial = True

    notices = (partial_notice(),) if partial else ()
    return _validated_report(
        ModuleAttentionReport(
            evaluation="evaluated",
            summaries=accumulator.summaries(request),
            notices=notices,
        )
    )


__all__ = ["evaluate_scoreform_attention"]
