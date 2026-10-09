"""Issue #225 Slice 11: derive recovery completion from durable authority.

A Core scan-resolution event records a teacher decision, not proof of scoring.
This reader never appends a generic Core 'resolved' event, changes a result,
or consumes diagnostic QR guesses. A verified completion can be recomputed after
an interruption solely from the original failure, latest recorded route choice,
registered issuance, retained source, and managed schema-v2 results history.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pds_core.pds2 import serialize_pds2_payload
from pds_core.route_registrations import resolve_route_registration
from pds_core.routing_models import RouteLocator

from scoreform.answer_sheet_persistence import load_answer_sheet_record_set
from scoreform.answer_sheet_routes import (
    AnswerSheetPageRoute,
    validate_answer_sheet_page_route,
)
from scoreform.pds2_scan_dispatch import Pds2ScanDispatchResult
from scoreform.pds_module import validate_scoreform_registration
from scoreform.qr_scan_recovery_assembly import prepare_scoreform_recovery_assembly
from scoreform.qr_scan_recovery_dispatch import DispatchedScoreFormScanRecovery
from scoreform.qr_scan_recovery_persistence import PersistedScoreFormRecovery
from scoreform.qr_scan_recovery_preflight import (
    PreparedScoreFormScanRecovery,
    prepare_scoreform_scan_recovery,
)
from scoreform.results import (
    ScoreFormRoutedResult,
    ScoreFormRoutedResultHistoryRow,
    load_routed_results_history,
)
from scoreform.scan_review_resolution import discover_scan_review_items
from scoreform.validation import is_safe_identifier
from scoreform.work_paths import scoreform_work_paths, scoreform_work_ref

RecoveryCompletionStatus = Literal[
    "route_selection_needed", "result_missing", "verified_complete", "review_required"
]
_ROUTE_ACTIONS = frozenset({"route_selected", "route_corrected"})


class ScoreFormRecoveryCompletionError(ValueError):
    """A completion query or its provided write receipt is invalid."""


@dataclass(frozen=True, slots=True)
class ScoreFormRecoveryCompletion:
    """Read-only status of ONE failed physical page, not a Core resolution event."""

    failure_id: str
    status: RecoveryCompletionStatus
    reason: str
    issuance_id: str | None = None
    source_page_number: int | None = None
    attempt_number: int | None = None
    output_path: Path | None = None
    historical_resolution_id: str | None = None

    @property
    def verified(self) -> bool:
        return self.status == "verified_complete"


def _state(
    failure_id: str,
    status: RecoveryCompletionStatus,
    reason: str,
    *,
    issuance_id: str | None = None,
    source_page_number: int | None = None,
    attempt_number: int | None = None,
    output_path: Path | None = None,
    historical_resolution_id: str | None = None,
) -> ScoreFormRecoveryCompletion:
    return ScoreFormRecoveryCompletion(
        failure_id=failure_id,
        status=status,
        reason=reason,
        issuance_id=issuance_id,
        source_page_number=source_page_number,
        attempt_number=attempt_number,
        output_path=output_path,
        historical_resolution_id=historical_resolution_id,
    )


def _require_complete_issuance(
    root: Path,
    *,
    prepared: PreparedScoreFormScanRecovery,
    stored: ScoreFormRoutedResult,
) -> None:
    """Read and cross-check every registered page, not just the recovered one."""
    work = scoreform_work_ref(prepared.class_id, prepared.assignment_id)
    records = load_answer_sheet_record_set(root, work, prepared.issuance_id)
    issuance = records.issuance
    if issuance.lifecycle.status != "issued":
        raise ValueError("Issuance is no longer issued.")
    if (
        issuance.class_id,
        issuance.assignment_id,
        issuance.student_id,
        issuance.generation_id,
        issuance.artifact_id,
        issuance.issuance_id,
    ) != (
        stored.class_id,
        stored.assignment_id,
        stored.student_id,
        stored.generation_id,
        stored.artifact_id,
        stored.issuance_id,
    ):
        raise ValueError("Saved attempt contradicts immutable issuance identity.")
    if (stored.last_name, stored.first_name, stored.period) != (
        issuance.student_snapshot.last_name,
        issuance.student_snapshot.first_name,
        issuance.student_snapshot.period,
    ):
        raise ValueError("Saved student display identity contradicts issuance.")
    if (
        stored.page_ids != issuance.page_ids
        or stored.logical_pages != tuple(range(1, issuance.page_count + 1))
        or len(stored.route_ids) != issuance.page_count
        or len(stored.source_page_numbers) != issuance.page_count
        or len(set(stored.source_page_numbers)) != issuance.page_count
        or any(
            page < 1 or page > prepared.source_page_count
            for page in stored.source_page_numbers
        )
        or stored.total_points != issuance.assignment_snapshot.question_count
        or stored.page_display
        != ",".join(str(value) for value in stored.source_page_numbers)
    ):
        raise ValueError("Saved attempt does not contain exactly the issued pages.")
    for page, route_id in zip(records.pages, stored.route_ids, strict=True):
        locator = RouteLocator(prepared.route_locator.schema, work, route_id)
        resolution = resolve_route_registration(root, locator)
        validate_scoreform_registration(resolution.registration)
        validate_answer_sheet_page_route(
            AnswerSheetPageRoute(
                page,
                locator,
                resolution.registration,
                serialize_pds2_payload(locator),
            )
        )
    # Each physical source page must unambiguously correspond to one issued
    # logical page. The selected teacher route must be the exact matching pair.
    selected = prepared.logical_page - 1
    if (
        stored.route_ids[selected] != prepared.route_locator.route_id
        or stored.page_ids[selected] != prepared.page_id
        or stored.source_page_numbers[selected] != prepared.source_page_number
    ):
        raise ValueError("Recorded teacher route is not the stored physical page.")


def inspect_scoreform_recovery_completion(
    workspace_root: str | Path, failure_id: str
) -> ScoreFormRecoveryCompletion:
    """Compute the current recovery status without writing or rescoring.

    A schema-v2 result alone does NOT establish teacher authorization for an
    unreadable QR. A current, validated Core route_selected/route_corrected
    decision must identify this exact failed physical page. Ordinary or manual
    result rows cannot silently close it.
    """
    if type(failure_id) is not str or not is_safe_identifier(failure_id):
        raise ScoreFormRecoveryCompletionError("Invalid scan-review failure ID.")
    try:
        root = Path(workspace_root).resolve(strict=True)
        if not root.is_dir():
            raise ValueError("Missing workspace directory.")
        discovery = discover_scan_review_items(root, include_resolved=True)
    except (TypeError, ValueError, OSError, RuntimeError) as error:
        raise ScoreFormRecoveryCompletionError("Cannot inspect scan-review workspace.") from error
    matches = [item for item in discovery.items if item.failure_id == failure_id]
    if len(matches) != 1:
        raise ScoreFormRecoveryCompletionError("No unique valid ScoreForm failure matches this ID.")
    item = matches[0]
    if item.metadata.scope != "page" or item.source_page_number is None:
        return _state(failure_id, "review_required", "Failure lacks an exact physical page.")
    if item.latest_resolution_action not in _ROUTE_ACTIONS:
        action = item.latest_resolution_action
        if action not in {None, "defer"}:
            return _state(
                failure_id, "review_required",
                "A different latest teacher decision cannot be overwritten by recovery.",
                source_page_number=item.source_page_number,
            )
        return _state(
            failure_id, "route_selection_needed",
            "No current validated teacher route decision establishes recovery authority.",
            source_page_number=item.source_page_number,
        )
    try:
        prepared = prepare_scoreform_scan_recovery(
            root, failure_id, use_recorded_route=True
        )
    except Exception:
        return _state(
            failure_id, "review_required",
            "Recorded route, original retained page, or issuance failed revalidation.",
            source_page_number=item.source_page_number,
        )
    base = {
        "issuance_id": prepared.issuance_id,
        "source_page_number": prepared.source_page_number,
        "historical_resolution_id": prepared.historical_resolution_id,
    }
    path = scoreform_work_paths(root, prepared.class_id, prepared.assignment_id).results_path
    try:
        rows = load_routed_results_history(path)
    except Exception:
        return _state(
            failure_id, "review_required", "Managed results history is unreadable or invalid.",
            output_path=path, **base,
        )
    # Manual scores are a separate fallback. They require explicit teacher
    # reconciliation, not a synthesized QR recovery completion.
    if any(
        row.result.result_origin in {"scan_review_manual", "plain_paper_manual"}
        and (row.result.class_id, row.result.assignment_id, row.result.student_id)
        == (prepared.class_id, prepared.assignment_id, prepared.student_id)
        for row in rows
    ):
        return _state(
            failure_id, "review_required",
            "Existing manual student result requires teacher reconciliation.",
            output_path=path, **base,
        )
    linked: list[ScoreFormRoutedResultHistoryRow] = [
        row for row in rows
        if row.result.result_origin == "pds2_scan"
        and row.result.issuance_id == prepared.issuance_id
    ]
    if not linked:
        return _state(
            failure_id, "result_missing",
            "Route decision exists, but no completed result for its issuance is saved.",
            output_path=path, **base,
        )
    if len(linked) != 1:
        return _state(
            failure_id, "review_required",
            "Multiple saved results refer to the same issued attempt.",
            output_path=path, **base,
        )
    recorded = linked[0]
    stored = recorded.result
    source = prepared.retained_source
    if (
        stored.source_scan_id != source.source_scan_id
        or stored.source_sha256 != source.source_sha256
        or stored.retained_source_relative_path != source.retained_source_relative_path
        or stored.source_file != source.source_filename
        or stored.class_id != prepared.class_id
        or stored.assignment_id != prepared.assignment_id
        or stored.student_id != prepared.student_id
    ):
        return _state(
            failure_id, "review_required",
            "Saved result identity or scan provenance contradicts the original failure.",
            output_path=path, **base,
        )
    try:
        _require_complete_issuance(root, prepared=prepared, stored=stored)
    except Exception:
        return _state(
            failure_id, "review_required",
            "Saved result cannot be verified against every registered issued page.",
            output_path=path, **base,
        )
    return _state(
        failure_id, "verified_complete",
        "Recorded teacher route and complete saved result match the original page.",
        attempt_number=recorded.attempt_number, output_path=path, **base,
    )


def confirm_scoreform_recovery_completion(
    workspace_root: str | Path,
    persisted: PersistedScoreFormRecovery,
    recovered_pages: tuple[DispatchedScoreFormScanRecovery, ...],
    *,
    original_batch: Pds2ScanDispatchResult | None = None,
) -> tuple[ScoreFormRecoveryCompletion, ...]:
    """Reverify a Slice 10 receipt and classify all linked physical failures.

    Does not create route decisions, modify Core resolution status, repeat QR
    detection, or append results. A valid stored grade with no recorded teacher
    decision remains `route_selection_needed`, not `verified_complete`.
    """
    if type(persisted) is not PersistedScoreFormRecovery:
        raise ScoreFormRecoveryCompletionError("An exact Slice 10 persistence receipt is required.")
    if type(recovered_pages) is not tuple or not recovered_pages:
        raise ScoreFormRecoveryCompletionError("The original recovered-page evidence is required.")
    failure_ids = tuple(page.prepared.failure_id for page in recovered_pages)
    if failure_ids != persisted.recovered_failure_ids:
        raise ScoreFormRecoveryCompletionError("Receipt and recovered failure IDs disagree.")
    try:
        root = Path(workspace_root).resolve(strict=True)
        fresh = prepare_scoreform_recovery_assembly(
            root, recovered_pages, original_batch=original_batch
        )
        if (
            fresh.status != "already_persisted"
            or fresh.assembled_attempt is None
            or fresh.prior_attempt_number != persisted.attempt_number
            or fresh.assembled_attempt != persisted.assembled_attempt
        ):
            raise ValueError("Persisted result no longer matches the recovery evidence.")
        expected_path = scoreform_work_paths(
            root,
            persisted.assembled_attempt.routed_result.class_id,
            persisted.assembled_attempt.routed_result.assignment_id,
        ).results_path
        if persisted.output_path != expected_path:
            raise ValueError("Receipt names a different results destination.")
        outcomes = tuple(
            inspect_scoreform_recovery_completion(root, failure_id)
            for failure_id in failure_ids
        )
        if any(
            outcome.status == "verified_complete" and (
                outcome.attempt_number != persisted.attempt_number
                or outcome.output_path != persisted.output_path
                or outcome.issuance_id != persisted.assembled_attempt.issuance_id
            )
            for outcome in outcomes
        ):
            raise ValueError("A completed review item refers to another result.")
        return outcomes
    except Exception as error:
        raise ScoreFormRecoveryCompletionError(
            "Recovery receipt or current result could not be verified."
        ) from error


__all__ = [
    "RecoveryCompletionStatus",
    "ScoreFormRecoveryCompletion",
    "ScoreFormRecoveryCompletionError",
    "confirm_scoreform_recovery_completion",
    "inspect_scoreform_recovery_completion",
]
