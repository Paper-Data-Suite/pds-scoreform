"""Issue #225 Slice 8: Core dispatch and immutable page-score qualification."""

from __future__ import annotations

from dataclasses import replace

import pytest
from pds_core.module_profiles import ModuleRegistry
from test_issue225_scan_recovery_preflight import (
    _incorrect_observed_route,
    _record_route,
    _workspace,
)

import scoreform.qr_scan_recovery_dispatch as recovery_dispatch
import scoreform.route_handler as route_handler
from scoreform.answer_sheet_persistence import transition_answer_sheet_issuance
from scoreform.page_scoring import ScoredAnswer, ScoreFormPageDispatchResult
from scoreform.pds_module import get_module_profile
from scoreform.qr_scan_recovery_dispatch import (
    ScoreFormScanRecoveryDispatchError,
    dispatch_prepared_scoreform_scan_recovery,
)
from scoreform.qr_scan_recovery_preflight import prepare_scoreform_scan_recovery


def _scoring_registry(monkeypatch, calls):
    """Real Core route handler, with only optical marking replaced by a fixture."""

    def score_image(_image, **kwargs):
        calls.append(kwargs["source_page_number"])
        page = kwargs["page_context"].page
        numbers = range(page.question_start, page.question_end + 1)
        answers = tuple(ScoredAnswer(number, "A", True) for number in numbers)
        return ScoreFormPageDispatchResult(
            route_id=kwargs["route_id"],
            page_id=page.page_id,
            issuance_id=page.issuance_id,
            generation_id=page.generation_id,
            artifact_id=page.artifact_id,
            class_id=page.class_id,
            assignment_id=page.assignment_id,
            student_id=page.student_id,
            logical_page=page.logical_page,
            total_pages=page.total_pages,
            question_start=page.question_start,
            question_end=page.question_end,
            layout_id=page.layout_id,
            score=len(answers),
            total_points=len(answers),
            answers=answers,
            source_scan_id=kwargs["source_scan_id"],
            source_page_number=kwargs["source_page_number"],
            retained_source_relative_path=kwargs["retained_source_relative_path"],
            source_sha256=kwargs["source_sha256"],
            diagnostic_paths=(),
        )

    monkeypatch.setattr(route_handler, "score_authoritative_answer_sheet_page", score_image)
    return ModuleRegistry((get_module_profile(),))


def _prepare(root, route):
    return prepare_scoreform_scan_recovery(root, "failure1", route_locator=route.locator)


def test_real_core_dispatch_produces_verified_page_without_result_or_resolution_writes(
    tmp_path, monkeypatch
):
    route, page, retained, _failure = _workspace(tmp_path)
    calls = []
    registry = _scoring_registry(monkeypatch, calls)
    prepared = _prepare(tmp_path, route)

    def no_qr(*_args, **_kwargs):
        pytest.fail("recovery must not decode QR")

    monkeypatch.setattr("scoreform.pds2_scan_dispatch.detect_qr_payload_text", no_qr)
    output = dispatch_prepared_scoreform_scan_recovery(
        tmp_path, prepared, registry=registry
    )
    assert output.prepared == prepared
    assert output.request.locator == route.locator
    assert output.request.retained_source == retained
    assert output.request.source_page_number == 1
    assert output.success.module_result is output.page_result
    assert output.page_result.page_id == page.page_id
    assert output.page_result.student_id == page.student_id
    assert output.page_result.score == 15
    assert calls == [1]
    assert not (tmp_path / "scans" / "review" / "resolutions").exists()
    assert not list(tmp_path.rglob("results.csv"))


def test_previously_resolved_route_dispatches_original_page(tmp_path, monkeypatch):
    route, page, _retained, failure = _workspace(tmp_path)
    recorded = _record_route(tmp_path, route, page, failure)
    registry = _scoring_registry(monkeypatch, [])
    prepared = prepare_scoreform_scan_recovery(
        tmp_path, "failure1", use_recorded_route=True
    )
    output = dispatch_prepared_scoreform_scan_recovery(
        tmp_path, prepared, registry=registry
    )
    assert output.prepared.historical_resolution_id == recorded.resolution_id
    assert output.page_result.issuance_id == page.issuance_id
    assert len(list((tmp_path / "scans" / "review" / "resolutions").glob("*.json"))) == 1
    assert not list(tmp_path.rglob("results.csv"))


def test_explicit_authorized_correction_is_preserved(tmp_path, monkeypatch):
    route, _page, _retained, failure = _workspace(tmp_path)
    _incorrect_observed_route(tmp_path, failure, route)
    registry = _scoring_registry(monkeypatch, [])
    prepared = prepare_scoreform_scan_recovery(
        tmp_path, "failure2", route_locator=route.locator,
        allow_route_correction=True,
    )
    result = dispatch_prepared_scoreform_scan_recovery(
        tmp_path, prepared, registry=registry
    )
    assert result.prepared.route_correction_confirmed is True
    assert result.page_result.route_id == route.locator.route_id


def test_forged_preview_fails_before_dispatch(tmp_path, monkeypatch):
    route, _page, _retained, _failure = _workspace(tmp_path)
    prepared = replace(_prepare(tmp_path, route), source_page_number=2)
    monkeypatch.setattr(recovery_dispatch, "dispatch_route", lambda *_a: pytest.fail("dispatch"))
    with pytest.raises(ScoreFormScanRecoveryDispatchError, match="stale"):
        dispatch_prepared_scoreform_scan_recovery(tmp_path, prepared)


def test_wrong_preview_type_fails_before_loading_registry(tmp_path, monkeypatch):
    monkeypatch.setattr(recovery_dispatch, "build_scoreform_scan_registry", lambda: pytest.fail("registry"))
    with pytest.raises(ScoreFormScanRecoveryDispatchError, match="exact"):
        dispatch_prepared_scoreform_scan_recovery(tmp_path, object())


def test_original_source_changed_after_preview_is_rejected(tmp_path, monkeypatch):
    route, _page, retained, _failure = _workspace(tmp_path)
    prepared = _prepare(tmp_path, route)
    retained.retained_source_path.write_bytes(b"tampered scan")
    monkeypatch.setattr(recovery_dispatch, "dispatch_route", lambda *_a: pytest.fail("dispatch"))
    with pytest.raises(ScoreFormScanRecoveryDispatchError, match="preflight"):
        dispatch_prepared_scoreform_scan_recovery(tmp_path, prepared)


def test_issuance_status_changed_after_preview_fails_before_dispatch(tmp_path, monkeypatch):
    route, page, _retained, _failure = _workspace(tmp_path)
    prepared = _prepare(tmp_path, route)
    transition_answer_sheet_issuance(
        tmp_path, route.locator.work, page.issuance_id,
        expected_revision=2, new_status="invalidated",
        timestamp="2026-10-08T12:00:00+00:00", reason="revoked",
    )
    monkeypatch.setattr(recovery_dispatch, "dispatch_route", lambda *_a: pytest.fail("dispatch"))
    with pytest.raises(ScoreFormScanRecoveryDispatchError, match="preflight"):
        dispatch_prepared_scoreform_scan_recovery(tmp_path, prepared)


def test_native_core_dispatch_failure_is_wrapped(tmp_path, monkeypatch):
    route, _page, _retained, _failure = _workspace(tmp_path)
    prepared = _prepare(tmp_path, route)
    registry = _scoring_registry(monkeypatch, [])

    def fail_dispatch(*_args):
        raise ValueError("sensitive raw payload")

    monkeypatch.setattr(recovery_dispatch, "dispatch_route", fail_dispatch)
    with pytest.raises(ScoreFormScanRecoveryDispatchError, match="Core failed") as caught:
        dispatch_prepared_scoreform_scan_recovery(tmp_path, prepared, registry=registry)
    assert "sensitive" not in str(caught.value)


def test_registry_must_have_scoreform_module(tmp_path):
    route, _page, _retained, _failure = _workspace(tmp_path)
    with pytest.raises(ScoreFormScanRecoveryDispatchError, match="registry"):
        dispatch_prepared_scoreform_scan_recovery(
            tmp_path, _prepare(tmp_path, route), registry=object()
        )


@pytest.mark.parametrize("field,bad_value", [
    ("student_id", "another_student"),
    ("source_page_number", 2),
    ("source_sha256", "f" * 64),
    ("route_id", "rt_" + "f" * 32),
])
def test_forged_core_scoring_result_is_rejected(tmp_path, monkeypatch, field, bad_value):
    route, _page, _retained, _failure = _workspace(tmp_path)
    prepared = _prepare(tmp_path, route)
    registry = _scoring_registry(monkeypatch, [])
    original_dispatch = recovery_dispatch.dispatch_route

    def falsify(root, reg, request):
        success = original_dispatch(root, reg, request)
        return replace(
            success,
            module_result=replace(success.module_result, **{field: bad_value}),
        )

    monkeypatch.setattr(recovery_dispatch, "dispatch_route", falsify)
    with pytest.raises(ScoreFormScanRecoveryDispatchError, match="contradicts"):
        dispatch_prepared_scoreform_scan_recovery(tmp_path, prepared, registry=registry)


def test_forged_core_dispatch_request_is_rejected(tmp_path, monkeypatch):
    route, _page, _retained, _failure = _workspace(tmp_path)
    prepared = _prepare(tmp_path, route)
    registry = _scoring_registry(monkeypatch, [])
    original_dispatch = recovery_dispatch.dispatch_route

    def falsify(root, reg, request):
        success = original_dispatch(root, reg, request)
        return replace(success, request=replace(request, source_page_number=2))

    monkeypatch.setattr(recovery_dispatch, "dispatch_route", falsify)
    with pytest.raises(ScoreFormScanRecoveryDispatchError, match="Core dispatch identity"):
        dispatch_prepared_scoreform_scan_recovery(tmp_path, prepared, registry=registry)


def test_core_success_must_contain_exact_page_result(tmp_path, monkeypatch):
    route, _page, _retained, _failure = _workspace(tmp_path)
    prepared = _prepare(tmp_path, route)
    registry = _scoring_registry(monkeypatch, [])
    original_dispatch = recovery_dispatch.dispatch_route

    def falsify(root, reg, request):
        success = original_dispatch(root, reg, request)
        return replace(success, module_result=object())

    monkeypatch.setattr(recovery_dispatch, "dispatch_route", falsify)
    with pytest.raises(ScoreFormScanRecoveryDispatchError, match="exact ScoreForm"):
        dispatch_prepared_scoreform_scan_recovery(tmp_path, prepared, registry=registry)


def test_original_source_mutated_during_core_dispatch_is_not_accepted(tmp_path, monkeypatch):
    route, _page, retained, _failure = _workspace(tmp_path)
    prepared = _prepare(tmp_path, route)
    registry = _scoring_registry(monkeypatch, [])
    original_dispatch = recovery_dispatch.dispatch_route

    def mutate_after_dispatch(root, reg, request):
        success = original_dispatch(root, reg, request)
        retained.retained_source_path.write_bytes(b"changed during dispatch")
        return success

    monkeypatch.setattr(recovery_dispatch, "dispatch_route", mutate_after_dispatch)
    with pytest.raises(ScoreFormScanRecoveryDispatchError, match="authority changed"):
        dispatch_prepared_scoreform_scan_recovery(tmp_path, prepared, registry=registry)


def test_recorded_route_decision_changed_since_preview_is_rejected(tmp_path, monkeypatch):
    route, page, _retained, failure = _workspace(tmp_path)
    recorded = _record_route(tmp_path, route, page, failure)
    prepared = prepare_scoreform_scan_recovery(
        tmp_path, "failure1", use_recorded_route=True
    )
    (tmp_path / "scans" / "review" / "resolutions" / f"{recorded.resolution_id}.json").unlink()
    monkeypatch.setattr(recovery_dispatch, "dispatch_route", lambda *_a: pytest.fail("dispatch"))
    with pytest.raises(ScoreFormScanRecoveryDispatchError, match="preflight"):
        dispatch_prepared_scoreform_scan_recovery(tmp_path, prepared)
