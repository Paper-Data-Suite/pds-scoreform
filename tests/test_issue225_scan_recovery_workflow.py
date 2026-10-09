"""Issue #225 Slice 12: teacher-confirmed route-to-completion coordination."""

from __future__ import annotations

from dataclasses import replace

import pytest
from pds_core.pds2 import serialize_pds2_payload
from test_issue225_scan_recovery_assembly import (
    _two_page_workspace,
)
from test_issue225_scan_recovery_dispatch import _scoring_registry
from test_issue225_scan_recovery_preflight import _snapshot, _workspace

import scoreform.qr_scan_recovery_workflow as workflow_service
from scoreform.pds2_scan_dispatch import Pds2ScanDispatchResult
from scoreform.qr_scan_recovery_completion import inspect_scoreform_recovery_completion
from scoreform.qr_scan_recovery_workflow import (
    ScoreFormRecoveryRouteSelection,
    ScoreFormRecoveryWorkflowError,
    execute_approved_scoreform_recovery_workflow,
    preview_scoreform_recovery_workflow,
)
from scoreform.results import load_routed_results_history
from scoreform.scan_review_resolution import resolve_scan_review_item


def _one(root):
    route, _page, _source, _failure = _workspace(root)
    choice = ScoreFormRecoveryRouteSelection("failure1", route.locator)
    return route, (choice,)


def _resolutions(root):
    location = root / "scans" / "review" / "resolutions"
    return sorted(location.glob("*.json")) if location.exists() else []


def _run(root, preview, monkeypatch):
    return execute_approved_scoreform_recovery_workflow(
        root, preview, teacher_confirmed=True,
        registry=_scoring_registry(monkeypatch, []),
    )


def test_preview_reads_registered_route_and_writes_nothing(tmp_path):
    _route, choices = _one(tmp_path)
    before = _snapshot(tmp_path)
    plan = preview_scoreform_recovery_workflow(tmp_path, choices)
    assert plan.issuance_id == plan.prepared_pages[0].issuance_id
    assert plan.route_decisions_needed == ("failure1",)
    assert plan.source_page_numbers == (1,)
    assert _snapshot(tmp_path) == before


def test_explicit_confirmation_required_before_any_write(tmp_path):
    _route, choices = _one(tmp_path)
    plan = preview_scoreform_recovery_workflow(tmp_path, choices)
    before = _snapshot(tmp_path)
    with pytest.raises(ScoreFormRecoveryWorkflowError, match="confirmation"):
        execute_approved_scoreform_recovery_workflow(tmp_path, plan, teacher_confirmed=False)
    assert _snapshot(tmp_path) == before


def test_new_route_selected_then_score_saved_then_completion_verified(tmp_path, monkeypatch):
    route, choices = _one(tmp_path)
    preview = preview_scoreform_recovery_workflow(tmp_path, choices)
    outcome = _run(tmp_path, preview, monkeypatch)
    assert outcome.status == "verified_complete"
    assert outcome.verified
    assert outcome.recorded_route_failure_ids == ("failure1",)
    assert len(_resolutions(tmp_path)) == 1
    assert outcome.persisted is not None and outcome.persisted.status == "appended"
    assert outcome.persisted.assembled_attempt.routed_result.route_ids == (route.locator.route_id,)
    assert outcome.completion[0].verified
    assert inspect_scoreform_recovery_completion(tmp_path, "failure1").verified
    assert len(load_routed_results_history(outcome.persisted.output_path)) == 1


def test_retry_reuses_decision_and_recorded_result_without_rescoring(tmp_path, monkeypatch):
    _route, choices = _one(tmp_path)
    first = _run(tmp_path, preview_scoreform_recovery_workflow(tmp_path, choices), monkeypatch)
    assert first.verified
    before = _snapshot(tmp_path)
    newer = preview_scoreform_recovery_workflow(tmp_path, choices)
    assert newer.route_decisions_needed == ()
    monkeypatch.setattr(
        workflow_service, "dispatch_prepared_scoreform_scan_recovery",
        lambda *_a, **_k: pytest.fail("completed retry must not dispatch"),
    )
    again = execute_approved_scoreform_recovery_workflow(
        tmp_path, newer, teacher_confirmed=True
    )
    assert again.status == "already_complete"
    assert again.verified
    assert again.persisted is None
    assert again.recorded_route_failure_ids == ()
    assert _snapshot(tmp_path) == before
    assert len(_resolutions(tmp_path)) == 1



def test_already_recorded_route_skips_resolution_write(tmp_path, monkeypatch):
    route, _choices = _one(tmp_path)
    resolve_scan_review_item(
        tmp_path, "failure1", "route_selected",
        route_payload=serialize_pds2_payload(route.locator),
    )
    before_count = len(_resolutions(tmp_path))
    recorded = (ScoreFormRecoveryRouteSelection("failure1", use_recorded_route=True),)
    preview = preview_scoreform_recovery_workflow(tmp_path, recorded)
    assert preview.route_decisions_needed == ()
    out = _run(tmp_path, preview, monkeypatch)
    assert out.status == "verified_complete"
    assert out.recorded_route_failure_ids == ()
    assert len(_resolutions(tmp_path)) == before_count


def test_missing_page_records_route_but_never_saves_partial_score(tmp_path, monkeypatch):
    routes, _source = _two_page_workspace(tmp_path)
    first = (ScoreFormRecoveryRouteSelection("failure1", routes[0].locator),)
    outcome = _run(tmp_path, preview_scoreform_recovery_workflow(tmp_path, first), monkeypatch)
    assert outcome.status == "needs_pages"
    assert not outcome.verified
    assert outcome.missing_logical_pages == (2,)
    assert outcome.persisted is None
    assert not list(tmp_path.rglob("results.csv"))
    assert len(_resolutions(tmp_path)) == 1
    assert inspect_scoreform_recovery_completion(tmp_path, "failure1").status == "result_missing"


def test_second_page_can_finish_prior_incomplete_recovery(tmp_path, monkeypatch):
    routes, _source = _two_page_workspace(tmp_path)
    one = (ScoreFormRecoveryRouteSelection("failure1", routes[0].locator),)
    incomplete = _run(tmp_path, preview_scoreform_recovery_workflow(tmp_path, one), monkeypatch)
    assert incomplete.status == "needs_pages"
    both = (
        ScoreFormRecoveryRouteSelection("failure1", use_recorded_route=True),
        ScoreFormRecoveryRouteSelection("failure2", routes[1].locator),
    )
    complete = _run(tmp_path, preview_scoreform_recovery_workflow(tmp_path, both), monkeypatch)
    assert complete.status == "verified_complete"
    assert complete.verified
    assert complete.recorded_route_failure_ids == ("failure2",)
    assert len(complete.completion) == 2
    assert len(_resolutions(tmp_path)) == 2
    assert complete.persisted is not None
    assert len(load_routed_results_history(complete.persisted.output_path)) == 1


def test_stale_teacher_preview_rejected_before_writes(tmp_path):
    _route, choices = _one(tmp_path)
    preview = preview_scoreform_recovery_workflow(tmp_path, choices)
    resolve_scan_review_item(tmp_path, "failure1", "defer")
    before = _snapshot(tmp_path)
    with pytest.raises(ScoreFormRecoveryWorkflowError, match="stale"):
        execute_approved_scoreform_recovery_workflow(
            tmp_path, preview, teacher_confirmed=True
        )
    assert _snapshot(tmp_path) == before


def test_changed_original_source_rejected_before_writes(tmp_path):
    _route, choices = _one(tmp_path)
    preview = preview_scoreform_recovery_workflow(tmp_path, choices)
    preview.prepared_pages[0].retained_source.retained_source_path.write_bytes(b"tampered")
    before = _snapshot(tmp_path)
    with pytest.raises(ScoreFormRecoveryWorkflowError, match="preflight"):
        execute_approved_scoreform_recovery_workflow(
            tmp_path, preview, teacher_confirmed=True
        )
    assert _snapshot(tmp_path) == before
    assert not _resolutions(tmp_path)


def test_route_decision_survives_dispatch_failure_and_retry(tmp_path, monkeypatch):
    route, choices = _one(tmp_path)
    preview = preview_scoreform_recovery_workflow(tmp_path, choices)
    true_dispatch = workflow_service.dispatch_prepared_scoreform_scan_recovery

    def cannot_dispatch(*_args, **_kwargs):
        raise OSError("Synthetic image decoder interruption")

    monkeypatch.setattr(
        workflow_service, "dispatch_prepared_scoreform_scan_recovery", cannot_dispatch
    )
    with pytest.raises(ScoreFormRecoveryWorkflowError, match="dispatch") as captured:
        _run(tmp_path, preview, monkeypatch)
    assert captured.value.stage == "dispatch"
    assert len(_resolutions(tmp_path)) == 1
    assert not list(tmp_path.rglob("results.csv"))
    monkeypatch.setattr(
        workflow_service, "dispatch_prepared_scoreform_scan_recovery", true_dispatch
    )
    retry = (ScoreFormRecoveryRouteSelection("failure1", use_recorded_route=True),)
    complete = _run(tmp_path, preview_scoreform_recovery_workflow(tmp_path, retry), monkeypatch)
    assert complete.verified
    assert len(_resolutions(tmp_path)) == 1
    assert complete.persisted is not None
    assert complete.persisted.assembled_attempt.routed_result.route_ids == (route.locator.route_id,)


def test_writer_failure_keeps_route_decision_and_reports_stage(tmp_path, monkeypatch):
    _route, choices = _one(tmp_path)
    preview = preview_scoreform_recovery_workflow(tmp_path, choices)

    def deny_writer(*_args, **_kwargs):
        raise OSError("Synthetic writer failure")

    monkeypatch.setattr(workflow_service, "persist_scoreform_recovery_attempt", deny_writer)
    with pytest.raises(ScoreFormRecoveryWorkflowError, match="persistence") as caught:
        _run(tmp_path, preview, monkeypatch)
    assert caught.value.stage == "persistence"
    assert len(_resolutions(tmp_path)) == 1
    assert not list(tmp_path.rglob("results.csv"))


def test_recovery_does_not_overwrite_final_manual_decision(tmp_path):
    route, _choices = _one(tmp_path)
    resolve_scan_review_item(tmp_path, "failure1", "rescan_needed")
    selected = (ScoreFormRecoveryRouteSelection("failure1", route.locator),)
    before = _snapshot(tmp_path)
    with pytest.raises(ScoreFormRecoveryWorkflowError, match="preflight"):
        preview_scoreform_recovery_workflow(tmp_path, selected)
    assert _snapshot(tmp_path) == before


def test_preview_requires_explicit_correction_to_replace_recorded_route(tmp_path):
    route, _choices = _one(tmp_path)
    resolve_scan_review_item(
        tmp_path, "failure1", "route_selected",
        route_payload=serialize_pds2_payload(route.locator),
    )
    # The teacher must not be asked to append another event for the same route.
    same = (ScoreFormRecoveryRouteSelection("failure1", route.locator),)
    preview = preview_scoreform_recovery_workflow(tmp_path, same)
    assert preview.route_decisions_needed == ()


def test_repeated_failure_and_cross_source_selection_rejected(tmp_path):
    route, _choices = _one(tmp_path)
    duplicate = (
        ScoreFormRecoveryRouteSelection("failure1", route.locator),
        ScoreFormRecoveryRouteSelection("failure1", route.locator),
    )
    with pytest.raises(ScoreFormRecoveryWorkflowError, match="Duplicate"):
        preview_scoreform_recovery_workflow(tmp_path, duplicate)
    with pytest.raises(ScoreFormRecoveryWorkflowError, match="route selection"):
        preview_scoreform_recovery_workflow(tmp_path, ())


def test_malformed_preview_and_confirmation_fail_closed(tmp_path):
    _route, _choices = _one(tmp_path)
    with pytest.raises(ScoreFormRecoveryWorkflowError, match="preview"):
        execute_approved_scoreform_recovery_workflow(
            tmp_path, object(), teacher_confirmed=True
        )


def test_forged_approved_preview_fails_without_decision(tmp_path):
    _route, choices = _one(tmp_path)
    approved = preview_scoreform_recovery_workflow(tmp_path, choices)
    changed = replace(approved, source_scan_id="scan_forged")
    with pytest.raises(ScoreFormRecoveryWorkflowError, match="stale"):
        execute_approved_scoreform_recovery_workflow(
            tmp_path, changed, teacher_confirmed=True
        )
    assert not _resolutions(tmp_path)


def test_bad_original_batch_cannot_persist_a_result(tmp_path, monkeypatch):
    _route, choices = _one(tmp_path)
    preview = preview_scoreform_recovery_workflow(tmp_path, choices)
    bad_batch = Pds2ScanDispatchResult(retained_source=None, file_error=ValueError("bad batch"))
    with pytest.raises(ScoreFormRecoveryWorkflowError, match="assembly"):
        execute_approved_scoreform_recovery_workflow(
            tmp_path, preview, teacher_confirmed=True,
            original_batch=bad_batch,
            registry=_scoring_registry(monkeypatch, []),
        )
    assert len(_resolutions(tmp_path)) == 1
    assert not list(tmp_path.rglob("results.csv"))


def test_saved_result_without_route_becomes_complete_after_approved_selection(
    tmp_path, monkeypatch
):
    from test_issue225_scan_recovery_completion import _saved

    route, _page, _source, _failure, _recovered, receipt = _saved(
        tmp_path, monkeypatch, record_route=False
    )
    assert inspect_scoreform_recovery_completion(tmp_path, "failure1").status == "route_selection_needed"
    plan = preview_scoreform_recovery_workflow(
        tmp_path, (ScoreFormRecoveryRouteSelection("failure1", route.locator),)
    )
    monkeypatch.setattr(
        workflow_service, "dispatch_prepared_scoreform_scan_recovery",
        lambda *_a, **_k: pytest.fail("saved score needs route approval, not rescore"),
    )
    outcome = execute_approved_scoreform_recovery_workflow(
        tmp_path, plan, teacher_confirmed=True
    )
    assert outcome.status == "already_complete"
    assert outcome.verified
    assert outcome.recorded_route_failure_ids == ("failure1",)
    assert len(_resolutions(tmp_path)) == 1
    assert len(load_routed_results_history(receipt.output_path)) == 1
