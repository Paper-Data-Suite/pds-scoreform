"""Issue #225 Slice 9: non-persistent, issuance-authoritative recovery assembly.

A recovered page is not an attempt. This service combines verified Core-scored
pages from ONE exact retained scan, verifies immutable issuance authority, and
checks managed result history before offering a candidate to a later writer.
It never changes a result, failure, resolution, or source file.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from pds_core.module_dispatch import RouteDispatchSuccess
from pds_core.pds2 import serialize_pds2_payload
from pds_core.route_registrations import resolve_route_registration
from pds_core.routing_models import RouteLocator
from pds_core.scan_retention import RetainedSourceScan

from scoreform.answer_sheet_persistence import (
    load_answer_sheet_page_context,
    load_answer_sheet_record_set,
)
from scoreform.answer_sheet_routes import (
    AnswerSheetPageRoute,
    validate_answer_sheet_page_route,
)
from scoreform.attempt_assembly import (
    ScoreFormAssembledAttempt,
    ScoreFormPageObservation,
)
from scoreform.layouts import require_layout
from scoreform.page_scoring import (
    ScoreFormPageDispatchResult,
    validate_page_dispatch_result,
)
from scoreform.pds2_scan_dispatch import Pds2ScanDispatchResult
from scoreform.pds_module import validate_scoreform_registration
from scoreform.qr_scan_recovery_dispatch import (
    DispatchedScoreFormScanRecovery,
    _reprepare,
)
from scoreform.results import (
    ScoreFormRoutedResult,
    load_routed_results_history,
    pds2_results_semantically_equivalent,
)
from scoreform.retained_page import retained_source_page_count
from scoreform.work_paths import scoreform_work_paths, scoreform_work_ref


class ScoreFormRecoveryAssemblyError(ValueError):
    """The supplied recovery evidence is ineligible for assembly."""


@dataclass(frozen=True, slots=True)
class ScoreFormRecoveryAssemblyPlan:
    """Advisory assessment, NEVER a write authorization or recovery resolution."""

    status: Literal["needs_pages", "review_required", "ready_to_persist", "already_persisted"]
    issuance_id: str
    source_scan_id: str
    source_page_numbers: tuple[int, ...]
    missing_logical_pages: tuple[int, ...]
    reason: str
    assembled_attempt: ScoreFormAssembledAttempt | None = None
    prior_attempt_number: int | None = None


def _current_recovery(root: Path, item: DispatchedScoreFormScanRecovery) -> None:
    if type(item) is not DispatchedScoreFormScanRecovery:
        raise ScoreFormRecoveryAssemblyError("Only verified Slice 8 dispatch values are accepted.")
    try:
        current = _reprepare(root, item.prepared)
    except Exception as error:
        raise ScoreFormRecoveryAssemblyError("Recovered source or route no longer passes preflight.") from error
    if current != item.prepared:
        raise ScoreFormRecoveryAssemblyError("Recovery preview is stale; dispatch again.")
    if (
        type(item.success) is not RouteDispatchSuccess
        or item.success.request != item.request
        or item.request.locator != item.prepared.route_locator
        or item.request.source_page_number != item.prepared.source_page_number
        or item.request.retained_source != item.prepared.retained_source
        or item.success.resolution.locator != item.prepared.route_locator
        or item.success.resolution.registration.target != item.prepared.target
        or item.success.profile.module_id != "scoreform"
        or item.success.module_result is not item.page_result
    ):
        raise ScoreFormRecoveryAssemblyError("Core recovery dispatch identity is inconsistent.")


def _validate_scored_page(
    root: Path,
    scored: ScoreFormPageDispatchResult,
    locator: RouteLocator,
    source: RetainedSourceScan,
    source_page_number: int,
) -> None:
    """Use the existing registration, issued-page and scoring contracts."""
    try:
        resolution = resolve_route_registration(root, locator)
        registration = resolution.registration
        validate_scoreform_registration(registration)
        context = load_answer_sheet_page_context(
            root, locator.work, registration.target.record_id
        )
        page = context.page
        validate_answer_sheet_page_route(
            AnswerSheetPageRoute(
                page, locator, registration, serialize_pds2_payload(locator)
            )
        )
        if context.issuance.lifecycle.status != "issued":
            raise ValueError("The page issuance is no longer issued.")
        validate_page_dispatch_result(
            scored, valid_choices=require_layout(page.layout_id).choices
        )
        actual = (
            scored.route_id, scored.page_id, scored.issuance_id,
            scored.generation_id, scored.artifact_id, scored.class_id,
            scored.assignment_id, scored.student_id, scored.logical_page,
            scored.total_pages, scored.question_start, scored.question_end,
            scored.layout_id, scored.source_scan_id, scored.source_page_number,
            scored.retained_source_relative_path, scored.source_sha256,
        )
        expected = (
            locator.route_id, page.page_id, page.issuance_id,
            page.generation_id, page.artifact_id, page.class_id,
            page.assignment_id, page.student_id, page.logical_page,
            page.total_pages, page.question_start, page.question_end,
            page.layout_id, source.source_scan_id, source_page_number,
            source.retained_source_relative_path, source.source_sha256,
        )
        if actual != expected:
            raise ValueError("Scored page contradicts its authoritative registered page.")
    except Exception as error:
        raise ScoreFormRecoveryAssemblyError(
            "A scored page does not match its current registered issuance authority."
        ) from error


def _plan(status, first, pages, *, missing=(), reason="", attempt=None, prior=None):
    return ScoreFormRecoveryAssemblyPlan(
        status=status, issuance_id=first.prepared.issuance_id,
        source_scan_id=first.prepared.retained_source.source_scan_id,
        source_page_numbers=tuple(sorted({p.source_page_number for p in pages})),
        missing_logical_pages=tuple(missing), reason=reason,
        assembled_attempt=attempt, prior_attempt_number=prior,
    )


def prepare_scoreform_recovery_assembly(
    workspace_root: str | Path,
    recovered_pages: tuple[DispatchedScoreFormScanRecovery, ...],
    *,
    original_batch: Pds2ScanDispatchResult | None = None,
) -> ScoreFormRecoveryAssemblyPlan:
    """Assess one issuance without writing results or mutating previous review.

    The optional original batch contributes *successful Core-verified ScoreForm*
    sibling pages, not QR guesses or failure pages. All inputs must originate
    from the same exact retained physical source. Multi-source aggregation is
    intentionally not supported by the existing PDS2 result contract.
    """
    if not isinstance(recovered_pages, tuple) or not recovered_pages:
        raise ScoreFormRecoveryAssemblyError("At least one recovered page is required.")
    try:
        root = Path(workspace_root).resolve(strict=True)
        if not root.is_dir():
            raise ValueError("Missing workspace directory.")
    except (OSError, ValueError, TypeError, RuntimeError) as error:
        raise ScoreFormRecoveryAssemblyError("Workspace is invalid.") from error

    for entry in recovered_pages:
        _current_recovery(root, entry)
    first = recovered_pages[0]
    source = first.prepared.retained_source
    issuance_id = first.prepared.issuance_id
    for entry in recovered_pages:
        if (
            entry.prepared.retained_source != source
            or entry.prepared.issuance_id != issuance_id
            or entry.prepared.class_id != first.prepared.class_id
            or entry.prepared.assignment_id != first.prepared.assignment_id
        ):
            raise ScoreFormRecoveryAssemblyError(
                "Recovered pages must belong to one issuance and retained source."
            )

    # Keep each independently verified Core outcome intact. Do not fabricate a
    # synthetic QR payload or impersonate ordinary scan-intake dispatch.
    candidates = [(entry.page_result, entry.prepared.route_locator,
                   entry.prepared.source_page_number) for entry in recovered_pages]
    recovered_numbers = [entry.prepared.source_page_number for entry in recovered_pages]
    if len(set(recovered_numbers)) != len(recovered_numbers):
        return _plan("review_required", first, tuple(row[0] for row in candidates),
                     reason="Duplicate recovery for one physical page requires review.")

    if original_batch is not None:
        if type(original_batch) is not Pds2ScanDispatchResult:
            raise ScoreFormRecoveryAssemblyError("Original batch has the wrong type.")
        if original_batch.file_error is not None or original_batch.retained_source != source:
            raise ScoreFormRecoveryAssemblyError(
                "Original batch is unavailable or belongs to another retained scan."
            )
        count = retained_source_page_count(source, workspace_root=root)
        if tuple(page.source_page_number for page in original_batch.pages) != tuple(range(1, count + 1)):
            raise ScoreFormRecoveryAssemblyError("Original batch lacks exact physical page coverage.")
        for wrapper in original_batch.pages:
            result = wrapper.scoreform_page_score
            if result is None:
                continue
            success = wrapper.dispatch_outcome
            # Preserve exact Core success-class validation while
            # narrowing its optional type for mypy.
            if type(success) is not RouteDispatchSuccess:
                raise ScoreFormRecoveryAssemblyError(
                    "Original batch contains a mismatched Core success."
                )
            # An exact runtime class guard above has already rejected all
            # other Core outcome variants, including None. Make that
            # postcondition explicit to mypy without changing behavior.
            verified_success = cast(RouteDispatchSuccess, success)
            if (
                wrapper.dispatch_request is None
                or wrapper.locator is None
                or verified_success.request != wrapper.dispatch_request
                or verified_success.resolution.locator != wrapper.locator
                or verified_success.resolution.registration.locator != wrapper.locator
                or verified_success.profile.module_id != "scoreform"
                or verified_success.module_result is not result
                or wrapper.dispatch_request.retained_source is not original_batch.retained_source
            ):
                raise ScoreFormRecoveryAssemblyError("Original batch contains a mismatched Core success.")
            if wrapper.source_page_number in recovered_numbers:
                return _plan("review_required", first, tuple(row[0] for row in candidates),
                             reason="A recovered physical page already had a successful Core result.")
            _validate_scored_page(root, result, wrapper.locator, source, wrapper.source_page_number)
            if result.issuance_id == issuance_id:
                candidates.append((result, wrapper.locator, wrapper.source_page_number))

    for result, locator, number in candidates:
        _validate_scored_page(root, result, locator, source, number)
        if result.issuance_id != issuance_id:
            raise ScoreFormRecoveryAssemblyError("Candidate crosses the selected issuance.")

    try:
        record_set = load_answer_sheet_record_set(
            root, scoreform_work_ref(first.prepared.class_id, first.prepared.assignment_id),
            issuance_id,
        )
        issuance = record_set.issuance
        if issuance.lifecycle.status != "issued":
            raise ValueError("Issuance is no longer issued.")
        if (issuance.class_id, issuance.assignment_id, issuance.student_id) != (
            first.prepared.class_id, first.prepared.assignment_id, first.prepared.student_id
        ):
            raise ValueError("Issuance work or student differs from recovery.")
    except Exception as error:
        raise ScoreFormRecoveryAssemblyError("The complete issuance is not authoritative.") from error

    observations = [item[0] for item in candidates]
    ids = [page.page_id for page in observations]
    routes = [page.route_id for page in observations]
    logical = [page.logical_page for page in observations]
    physical = [page.source_page_number for page in observations]
    if any(len(set(values)) != len(values) for values in (ids, routes, logical, physical)):
        return _plan("review_required", first, observations,
                     reason="Duplicate or conflicting page, route, or physical-page observations.")
    expected = set(issuance.page_ids)
    if any(page_id not in expected for page_id in ids):
        return _plan("review_required", first, observations,
                     reason="An observed page does not belong to the issuance.")
    missing = tuple(page.logical_page for page in record_set.pages if page.page_id not in ids)
    if missing:
        return _plan("needs_pages", first, observations, missing=missing,
                     reason="More authoritative page observations are required before scoring the attempt.")

    by_id = {page.page_id: page for page in observations}
    ordered = tuple(by_id[page_id] for page_id in issuance.page_ids)
    answers = tuple(answer for page in ordered for answer in page.answers)
    if (
        tuple(page.logical_page for page in ordered) != tuple(range(1, issuance.page_count + 1))
        or tuple(answer.question_number for answer in answers)
        != tuple(range(1, issuance.assignment_snapshot.question_count + 1))
        or sum(page.total_points for page in ordered) != issuance.assignment_snapshot.question_count
    ):
        return _plan("review_required", first, observations,
                     reason="Complete pages do not cover the issuance questions exactly once.")

    snap = issuance.student_snapshot
    try:
        routed = ScoreFormRoutedResult(
            result_origin="pds2_scan", class_id=issuance.class_id,
            assignment_id=issuance.assignment_id, student_id=issuance.student_id,
            last_name=snap.last_name, first_name=snap.first_name, period=snap.period,
            page_display=",".join(str(page.source_page_number) for page in ordered),
            score=sum(page.score for page in ordered),
            total_points=issuance.assignment_snapshot.question_count,
            answers=answers, issuance_id=issuance.issuance_id,
            generation_id=issuance.generation_id, artifact_id=issuance.artifact_id,
            page_ids=tuple(page.page_id for page in ordered),
            route_ids=tuple(page.route_id for page in ordered),
            logical_pages=tuple(page.logical_page for page in ordered),
            source_file=source.source_filename, source_scan_id=source.source_scan_id,
            source_page_numbers=tuple(page.source_page_number for page in ordered),
            retained_source_relative_path=source.retained_source_relative_path,
            source_sha256=source.source_sha256,
        )
        assembled = ScoreFormAssembledAttempt(
            routed, tuple(ScoreFormPageObservation(page) for page in ordered)
        )
    except Exception as error:
        raise ScoreFormRecoveryAssemblyError("Cannot construct a canonical complete attempt.") from error

    results_path = scoreform_work_paths(root, issuance.class_id, issuance.assignment_id).results_path
    try:
        rows = load_routed_results_history(results_path)
    except Exception as error:
        raise ScoreFormRecoveryAssemblyError("Existing results history is unreadable or invalid.") from error
    for row in rows:
        prior = row.result
        if prior.result_origin == "pds2_scan" and prior.issuance_id == issuance_id:
            if prior.source_sha256 == source.source_sha256:
                if pds2_results_semantically_equivalent(prior, routed):
                    return _plan("already_persisted", first, ordered, attempt=assembled,
                                 prior=row.attempt_number,
                                 reason="An equivalent complete attempt is already recorded.")
                return _plan("review_required", first, ordered,
                             reason="Existing source-and-issuance result differs from recovered answers.")
            return _plan("review_required", first, ordered,
                         reason="Issuance already has a result from a different retained scan.")
        if (prior.class_id, prior.assignment_id, prior.student_id) == (
            issuance.class_id, issuance.assignment_id, issuance.student_id
        ) and prior.result_origin in {"plain_paper_manual", "scan_review_manual"}:
            return _plan("review_required", first, ordered,
                         reason="An existing manual result requires teacher reconciliation.")

    # Preview can become stale after returning. The next writer must repeat the
    # full preflight, assembly, and history check immediately before mutation.
    for entry in recovered_pages:
        _current_recovery(root, entry)
    return _plan("ready_to_persist", first, ordered, attempt=assembled,
                 reason="Complete authoritative attempt; no matching managed result recorded.")


__all__ = [
    "ScoreFormRecoveryAssemblyError",
    "ScoreFormRecoveryAssemblyPlan",
    "prepare_scoreform_recovery_assembly",
]
