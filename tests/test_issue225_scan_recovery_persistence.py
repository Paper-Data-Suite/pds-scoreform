"""Issue #225 Slice 10: schema-v2 persistence, retries, and write barriers."""

from __future__ import annotations

from dataclasses import replace

import pytest
from test_issue225_scan_recovery_assembly import (
    _dispatch,
    _two_page_workspace,
)
from test_issue225_scan_recovery_dispatch import _scoring_registry
from test_issue225_scan_recovery_preflight import _record_route, _snapshot, _workspace

import scoreform.qr_scan_recovery_persistence as persistence_service
from scoreform.qr_scan_recovery_assembly import prepare_scoreform_recovery_assembly
from scoreform.qr_scan_recovery_dispatch import (
    dispatch_prepared_scoreform_scan_recovery,
)
from scoreform.qr_scan_recovery_persistence import (
    ScoreFormRecoveryPersistenceError,
    ScoreFormRecoveryPersistenceUncertainError,
    persist_scoreform_recovery_attempt,
)
from scoreform.qr_scan_recovery_preflight import prepare_scoreform_scan_recovery
from scoreform.results import (
    ScoreFormAttemptExportBatch,
    export_scoreform_result_models,
    load_routed_results_history,
    pds2_results_semantically_equivalent,
)


def _single(root, monkeypatch):
    route, _page, _retained, _failure = _workspace(root)
    recovered = _dispatch(root, route, monkeypatch)
    preview = prepare_scoreform_recovery_assembly(root, (recovered,))
    assert preview.status == "ready_to_persist"
    return recovered, preview


def test_completed_recovery_appends_exactly_one_durable_v2_attempt(tmp_path, monkeypatch):
    recovered, preview = _single(tmp_path, monkeypatch)
    result = persist_scoreform_recovery_attempt(tmp_path, preview, (recovered,))
    assert result.status == "appended"
    assert result.attempt_number == 1
    assert result.recovered_failure_ids == ("failure1",)
    assert result.output_path.is_file()
    rows = load_routed_results_history(result.output_path)
    assert len(rows) == 1
    assert rows[0].result.result_origin == "pds2_scan"
    assert pds2_results_semantically_equivalent(
        rows[0].result, result.assembled_attempt.routed_result
    )
    assert not (tmp_path / "scans" / "review" / "resolutions").exists()


def test_retry_with_original_approved_preview_is_idempotent(tmp_path, monkeypatch):
    recovered, preview = _single(tmp_path, monkeypatch)
    initial = persist_scoreform_recovery_attempt(tmp_path, preview, (recovered,))
    before = _snapshot(tmp_path)
    repeat = persist_scoreform_recovery_attempt(tmp_path, preview, (recovered,))
    assert repeat.status == "already_present"
    assert repeat.attempt_number == initial.attempt_number
    assert _snapshot(tmp_path) == before
    assert len(load_routed_results_history(repeat.output_path)) == 1


def test_preexisting_equivalent_plan_never_invokes_writer(tmp_path, monkeypatch):
    recovered, preview = _single(tmp_path, monkeypatch)
    persist_scoreform_recovery_attempt(tmp_path, preview, (recovered,))
    already = prepare_scoreform_recovery_assembly(tmp_path, (recovered,))
    before = _snapshot(tmp_path)
    monkeypatch.setattr(
        persistence_service,
        "export_scoreform_result_models",
        lambda *_a, **_k: pytest.fail("existing result must not be rewritten"),
    )
    result = persist_scoreform_recovery_attempt(tmp_path, already, (recovered,))
    assert result.status == "already_present"
    assert _snapshot(tmp_path) == before


def test_recorded_historical_route_persists_result_without_review_mutation(
    tmp_path, monkeypatch
):
    route, page, _retained, failure = _workspace(tmp_path)
    resolution = _record_route(tmp_path, route, page, failure)
    prepared = prepare_scoreform_scan_recovery(
        tmp_path, "failure1", use_recorded_route=True
    )
    recovered = dispatch_prepared_scoreform_scan_recovery(
        tmp_path, prepared, registry=_scoring_registry(monkeypatch, [])
    )
    plan = prepare_scoreform_recovery_assembly(tmp_path, (recovered,))
    resolution_path = (
        tmp_path / "scans" / "review" / "resolutions" / f"{resolution.resolution_id}.json"
    )
    original_resolution_bytes = resolution_path.read_bytes()
    written = persist_scoreform_recovery_attempt(tmp_path, plan, (recovered,))
    assert written.status == "appended"
    assert resolution_path.read_bytes() == original_resolution_bytes
    assert len(list(resolution_path.parent.glob("*.json"))) == 1


def test_two_page_issuance_requires_complete_set_before_write(tmp_path, monkeypatch):
    routes, _retained = _two_page_workspace(tmp_path)
    one = _dispatch(tmp_path, routes[0], monkeypatch, "failure1")
    incomplete = prepare_scoreform_recovery_assembly(tmp_path, (one,))
    before = _snapshot(tmp_path)
    with pytest.raises(ScoreFormRecoveryPersistenceError, match="Incomplete"):
        persist_scoreform_recovery_attempt(tmp_path, incomplete, (one,))
    assert _snapshot(tmp_path) == before
    two = _dispatch(tmp_path, routes[1], monkeypatch, "failure2")
    complete = prepare_scoreform_recovery_assembly(tmp_path, (one, two))
    result = persist_scoreform_recovery_attempt(tmp_path, complete, (one, two))
    assert result.status == "appended"
    assert result.recovered_failure_ids == ("failure1", "failure2")
    rows = load_routed_results_history(result.output_path)
    assert len(rows) == 1
    assert rows[0].result.total_points == 30
    assert rows[0].result.logical_pages == (1, 2)


def test_forged_preview_never_attempts_writer(tmp_path, monkeypatch):
    recovered, preview = _single(tmp_path, monkeypatch)
    altered = replace(preview, issuance_id="iss_" + "f" * 32)
    monkeypatch.setattr(
        persistence_service,
        "export_scoreform_result_models",
        lambda *_a, **_k: pytest.fail("writer must not run"),
    )
    with pytest.raises(ScoreFormRecoveryPersistenceError, match="changed"):
        persist_scoreform_recovery_attempt(tmp_path, altered, (recovered,))
    assert not list(tmp_path.rglob("results.csv"))


def test_stale_approved_score_rejected_before_writer(tmp_path, monkeypatch):
    recovered, preview = _single(tmp_path, monkeypatch)
    changed_page = replace(
        recovered.page_result, score=0,
        answers=tuple(replace(answer, correct=False) for answer in recovered.page_result.answers),
    )
    changed = replace(
        recovered,
        page_result=changed_page,
        success=replace(recovered.success, module_result=changed_page),
    )
    with pytest.raises(ScoreFormRecoveryPersistenceError, match="changed"):
        persist_scoreform_recovery_attempt(tmp_path, preview, (changed,))
    assert not list(tmp_path.rglob("results.csv"))


def test_changed_source_blocks_persistence(tmp_path, monkeypatch):
    recovered, preview = _single(tmp_path, monkeypatch)
    recovered.prepared.retained_source.retained_source_path.write_bytes(b"changed")
    with pytest.raises(ScoreFormRecoveryPersistenceError, match="no longer"):
        persist_scoreform_recovery_attempt(tmp_path, preview, (recovered,))
    assert not list(tmp_path.rglob("results.csv"))


def test_wrong_type_and_missing_evidence_refused(tmp_path, monkeypatch):
    recovered, preview = _single(tmp_path, monkeypatch)
    with pytest.raises(ScoreFormRecoveryPersistenceError, match="exact"):
        persist_scoreform_recovery_attempt(tmp_path, object(), (recovered,))
    with pytest.raises(ScoreFormRecoveryPersistenceError, match="evidence"):
        persist_scoreform_recovery_attempt(tmp_path, preview, ())
    assert not list(tmp_path.rglob("results.csv"))


def test_writer_silent_nonconfirmation_reports_uncertain_and_does_not_resolve(
    tmp_path, monkeypatch
):
    recovered, preview = _single(tmp_path, monkeypatch)
    monkeypatch.setattr(
        persistence_service, "export_scoreform_result_models",
        lambda *_a, **_k: ScoreFormAttemptExportBatch(),
    )
    with pytest.raises(ScoreFormRecoveryPersistenceUncertainError) as caught:
        persist_scoreform_recovery_attempt(tmp_path, preview, (recovered,))
    assert caught.value.row_verified is False
    assert caught.value.attempt_number is None
    assert not list(tmp_path.rglob("results.csv"))


def test_write_then_exception_reports_verified_durable_row_and_retry_succeeds(
    tmp_path, monkeypatch
):
    recovered, preview = _single(tmp_path, monkeypatch)
    original_writer = export_scoreform_result_models

    def write_then_fail(results, *, workspace_root):
        response = original_writer(results, workspace_root=workspace_root)
        assert not response.failures and len(response.appended_attempts) == 1
        raise OSError("interrupted after v2 write")

    monkeypatch.setattr(
        persistence_service, "export_scoreform_result_models", write_then_fail
    )
    with pytest.raises(ScoreFormRecoveryPersistenceUncertainError) as caught:
        persist_scoreform_recovery_attempt(tmp_path, preview, (recovered,))
    assert caught.value.row_verified is True
    assert caught.value.attempt_number == 1
    monkeypatch.setattr(
        persistence_service, "export_scoreform_result_models",
        lambda *_a, **_k: pytest.fail("retry must not append"),
    )
    retry = persist_scoreform_recovery_attempt(tmp_path, preview, (recovered,))
    assert retry.status == "already_present"
    assert len(load_routed_results_history(retry.output_path)) == 1


def test_replacing_result_history_invalidates_prior_already_saved_preview(
    tmp_path, monkeypatch
):
    recovered, preview = _single(tmp_path, monkeypatch)
    first = persist_scoreform_recovery_attempt(tmp_path, preview, (recovered,))
    already = prepare_scoreform_recovery_assembly(tmp_path, (recovered,))
    first.output_path.unlink()
    with pytest.raises(ScoreFormRecoveryPersistenceError, match="changed"):
        persist_scoreform_recovery_attempt(tmp_path, already, (recovered,))
    assert not first.output_path.exists()


def test_result_writer_persistence_failure_preserves_prior_records(tmp_path, monkeypatch):
    recovered, preview = _single(tmp_path, monkeypatch)
    original = _snapshot(tmp_path)

    def deny_writer(*_args, **_kwargs):
        raise OSError("unable to save")

    monkeypatch.setattr(persistence_service, "export_scoreform_result_models", deny_writer)
    with pytest.raises(ScoreFormRecoveryPersistenceUncertainError) as caught:
        persist_scoreform_recovery_attempt(tmp_path, preview, (recovered,))
    assert caught.value.row_verified is False
    assert _snapshot(tmp_path) == original
