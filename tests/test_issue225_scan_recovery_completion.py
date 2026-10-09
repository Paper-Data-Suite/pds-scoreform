"""Issue #225 Slice 11: durable, read-only completion and review-state checks."""

from __future__ import annotations

from dataclasses import replace

import pytest
from pds_core.scan_resolution_metadata import (
    create_scan_resolution_metadata,
    write_scan_resolution_metadata,
)
from test_issue225_scan_recovery_assembly import (
    _dispatch,
    _two_page_workspace,
)
from test_issue225_scan_recovery_preflight import _record_route, _snapshot, _workspace

from scoreform.qr_scan_recovery_assembly import prepare_scoreform_recovery_assembly
from scoreform.qr_scan_recovery_completion import (
    ScoreFormRecoveryCompletionError,
    confirm_scoreform_recovery_completion,
    inspect_scoreform_recovery_completion,
)
from scoreform.qr_scan_recovery_persistence import persist_scoreform_recovery_attempt
from scoreform.results import (
    export_scoreform_result_models,
    load_routed_results_history,
)
from scoreform.scan_review_details import scoreform_resolution_details
from scoreform.scan_review_resolution import resolve_scan_review_item


def _saved(root, monkeypatch, *, record_route: bool = True):
    route, page, retained, failure = _workspace(root)
    if record_route:
        _record_route(root, route, page, failure)
    recovered = _dispatch(root, route, monkeypatch)
    plan = prepare_scoreform_recovery_assembly(root, (recovered,))
    written = persist_scoreform_recovery_attempt(root, plan, (recovered,))
    return route, page, retained, failure, recovered, written


def test_requires_recorded_teacher_route_before_calling_recovery_complete(tmp_path, monkeypatch):
    _route, _page, _retained, _failure, recovered, written = _saved(
        tmp_path, monkeypatch, record_route=False
    )
    before = _snapshot(tmp_path)
    outcome = inspect_scoreform_recovery_completion(tmp_path, "failure1")
    assert outcome.status == "route_selection_needed"
    assert not outcome.verified
    statuses = confirm_scoreform_recovery_completion(
        tmp_path, written, (recovered,)
    )
    assert len(statuses) == 1 and statuses[0].status == "route_selection_needed"
    assert _snapshot(tmp_path) == before
    assert len(load_routed_results_history(written.output_path)) == 1


def test_saved_result_and_historical_route_derive_complete_without_writing(tmp_path, monkeypatch):
    route, page, _retained, failure, recovered, written = _saved(tmp_path, monkeypatch)
    before = _snapshot(tmp_path)
    outcome = inspect_scoreform_recovery_completion(tmp_path, "failure1")
    assert outcome.verified
    assert outcome.status == "verified_complete"
    assert outcome.issuance_id == page.issuance_id
    assert outcome.source_page_number == 1
    assert outcome.attempt_number == written.attempt_number
    assert outcome.output_path == written.output_path
    assert outcome.historical_resolution_id is not None
    assert confirm_scoreform_recovery_completion(tmp_path, written, (recovered,)) == (outcome,)
    assert _snapshot(tmp_path) == before
    assert route.locator.route_id == written.assembled_attempt.routed_result.route_ids[0]
    assert len(list((tmp_path / "scans" / "review" / "resolutions").glob("*.json"))) == 1


def test_route_recorded_but_result_missing_is_not_completion(tmp_path):
    route, page, _retained, failure = _workspace(tmp_path)
    _record_route(tmp_path, route, page, failure)
    before = _snapshot(tmp_path)
    status = inspect_scoreform_recovery_completion(tmp_path, "failure1")
    assert status.status == "result_missing"
    assert status.attempt_number is None
    assert not status.verified
    assert _snapshot(tmp_path) == before


def test_no_route_and_no_result_needs_selection(tmp_path):
    _workspace(tmp_path)
    before = _snapshot(tmp_path)
    status = inspect_scoreform_recovery_completion(tmp_path, "failure1")
    assert status.status == "route_selection_needed"
    assert _snapshot(tmp_path) == before


def test_teacher_can_record_route_after_score_was_saved(tmp_path, monkeypatch):
    route, page, _retained, failure, _recovered, _written = _saved(
        tmp_path, monkeypatch, record_route=False
    )
    assert inspect_scoreform_recovery_completion(tmp_path, "failure1").status == "route_selection_needed"
    _record_route(tmp_path, route, page, failure)
    assert inspect_scoreform_recovery_completion(tmp_path, "failure1").verified


def test_deferral_after_historical_selection_revokes_automatic_completion(tmp_path, monkeypatch):
    _saved(tmp_path, monkeypatch)
    assert inspect_scoreform_recovery_completion(tmp_path, "failure1").verified
    resolve_scan_review_item(tmp_path, "failure1", "defer")
    check = inspect_scoreform_recovery_completion(tmp_path, "failure1")
    assert check.status == "route_selection_needed"
    assert not check.verified


def test_original_source_tampering_blocks_durable_completion(tmp_path, monkeypatch):
    _route, _page, retained, _failure, recovered, written = _saved(tmp_path, monkeypatch)
    retained.retained_source_path.write_bytes(b"altered original")
    status = inspect_scoreform_recovery_completion(tmp_path, "failure1")
    assert status.status == "review_required"
    with pytest.raises(ScoreFormRecoveryCompletionError):
        confirm_scoreform_recovery_completion(tmp_path, written, (recovered,))


def test_invalid_saved_history_blocks_durable_completion(tmp_path, monkeypatch):
    _route, _page, _retained, _failure, _recovered, written = _saved(tmp_path, monkeypatch)
    written.output_path.write_bytes(b"invalid,history\n")
    status = inspect_scoreform_recovery_completion(tmp_path, "failure1")
    assert status.status == "review_required"


def test_wrong_saved_source_scan_identity_not_accepted(tmp_path, monkeypatch):
    route, page, _retained, failure = _workspace(tmp_path)
    _record_route(tmp_path, route, page, failure)
    recovered = _dispatch(tmp_path, route, monkeypatch)
    plan = prepare_scoreform_recovery_assembly(tmp_path, (recovered,))
    assert plan.assembled_attempt is not None
    forged = replace(
        plan.assembled_attempt.routed_result,
        source_scan_id="scan_wrong_registered_event",
    )
    export = export_scoreform_result_models((forged,), workspace_root=tmp_path)
    assert not export.failures
    outcome = inspect_scoreform_recovery_completion(tmp_path, "failure1")
    assert outcome.status == "review_required"


def test_multi_page_result_requires_exact_page_mapping(tmp_path, monkeypatch):
    routes, _retained = _two_page_workspace(tmp_path)
    first = _dispatch(tmp_path, routes[0], monkeypatch, "failure1")
    second = _dispatch(tmp_path, routes[1], monkeypatch, "failure2")
    plan = prepare_scoreform_recovery_assembly(tmp_path, (first, second))
    written = persist_scoreform_recovery_attempt(tmp_path, plan, (first, second))
    assert written.attempt_number == 1
    assert inspect_scoreform_recovery_completion(tmp_path, "failure1").status == "route_selection_needed"
    # A successful grade does not establish either physical-page decision.
    from scoreform.scan_review_resolution import discover_scan_review_items

    items = {
        item.failure_id: item for item in
        discover_scan_review_items(tmp_path, include_resolved=True).items
    }
    _record_route(
        tmp_path, routes[0], routes[0].page, items["failure1"].metadata
    )
    assert inspect_scoreform_recovery_completion(tmp_path, "failure1").verified
    assert inspect_scoreform_recovery_completion(tmp_path, "failure2").status == "route_selection_needed"

    second = routes[1].page
    fields = {
        "class_id": second.class_id,
        "assignment_id": second.assignment_id,
        "student_id": second.student_id,
        "route_id": routes[1].locator.route_id,
        "page_id": second.page_id,
        "issuance_id": second.issuance_id,
        "logical_page": second.logical_page,
        "total_pages": second.total_pages,
    }
    recorded = create_scan_resolution_metadata(
        items["failure2"].metadata,
        resolution_id="resolution_two",
        resolution_status="resolved",
        resolution_action="route_selected",
        resolved_at="2026-10-01T00:00:00+00:00",
        resolution_message="Teacher selected exact second issued page.",
        route_locator=routes[1].locator,
        target=routes[1].registration.target,
        module_details=scoreform_resolution_details(
            teacher_action="route_selected", identity_source="validated_target",
            identity=fields,
        ),
    )
    write_scan_resolution_metadata(tmp_path, recorded)
    assert inspect_scoreform_recovery_completion(tmp_path, "failure2").verified
    assert len(load_routed_results_history(written.output_path)) == 1


def test_wrong_receipt_type_and_failure_tuple_are_rejected(tmp_path, monkeypatch):
    _route, _page, _retained, _failure, recovered, written = _saved(tmp_path, monkeypatch)
    with pytest.raises(ScoreFormRecoveryCompletionError, match="receipt"):
        confirm_scoreform_recovery_completion(tmp_path, object(), (recovered,))
    with pytest.raises(
    ScoreFormRecoveryCompletionError, match="recovered-page evidence"
    ):
        confirm_scoreform_recovery_completion(tmp_path, written, ())


def test_changed_attempt_number_in_receipt_is_not_verified(tmp_path, monkeypatch):
    _route, _page, _retained, _failure, recovered, written = _saved(tmp_path, monkeypatch)
    forged = replace(written, attempt_number=written.attempt_number + 1)
    with pytest.raises(ScoreFormRecoveryCompletionError, match="could not be verified"):
        confirm_scoreform_recovery_completion(tmp_path, forged, (recovered,))


def test_no_duplicate_completion_events_on_repeat_inspection(tmp_path, monkeypatch):
    _saved(tmp_path, monkeypatch)
    before = _snapshot(tmp_path)
    for _ in range(3):
        assert inspect_scoreform_recovery_completion(tmp_path, "failure1").verified
    assert _snapshot(tmp_path) == before
    assert len(list((tmp_path / "scans" / "review" / "resolutions").glob("*.json"))) == 1


def test_unknown_failure_is_not_silently_created(tmp_path):
    tmp_path.mkdir(exist_ok=True)
    before = _snapshot(tmp_path)
    with pytest.raises(ScoreFormRecoveryCompletionError, match="No unique"):
        inspect_scoreform_recovery_completion(tmp_path, "unknown_failure")
    assert _snapshot(tmp_path) == before
