"""Issue #225 Slice 9: strict, non-persistent recovered-attempt planning."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from pds_core.pds2 import serialize_pds2_payload
from pds_core.scan_failure_metadata import (
    RoutingFailureMetadata,
    write_routing_failure_metadata,
)
from pds_core.scan_retention import retain_source_scan
from reportlab.pdfgen import canvas
from test_issue225_scan_recovery_dispatch import _scoring_registry
from test_issue225_scan_recovery_preflight import _record_route, _snapshot, _workspace

from scoreform.answer_sheet_persistence import (
    transition_answer_sheet_issuance,
    write_answer_sheet_record_set,
)
from scoreform.answer_sheet_records import build_answer_sheet_record_set
from scoreform.answer_sheet_routes import (
    persist_answer_sheet_route_set,
    plan_answer_sheet_route_set,
)
from scoreform.folders import setup_assignment_folder
from scoreform.pds2_scan_dispatch import Pds2ScanDispatchResult, Pds2ScanPageOutcome
from scoreform.qr_scan_recovery_assembly import (
    ScoreFormRecoveryAssemblyError,
    prepare_scoreform_recovery_assembly,
)
from scoreform.qr_scan_recovery_dispatch import (
    dispatch_prepared_scoreform_scan_recovery,
)
from scoreform.qr_scan_recovery_preflight import prepare_scoreform_scan_recovery
from scoreform.results import export_scoreform_result_models
from scoreform.scan_review_details import scoreform_failure_details


def _dispatch(root, route, monkeypatch, failure_id="failure1"):
    registry = _scoring_registry(monkeypatch, [])
    prepared = prepare_scoreform_scan_recovery(
        root, failure_id, route_locator=route.locator
    )
    return dispatch_prepared_scoreform_scan_recovery(
        root, prepared, registry=registry
    )


def _two_page_workspace(root: Path):
    assignment = {
        "assignment_id": "quiz1", "title": "Two Page Check", "question_count": 30,
        "choices": ["A", "B", "C", "D"], "layout_id": "standard_15q_abcd_v1",
        "answer_key": {str(n): "A" for n in range(1, 31)},
        "standards": {str(n): [] for n in range(1, 31)},
    }
    student = {
        "class_id": "class1", "student_id": "student1", "last_name": "Synthetic",
        "first_name": "Student", "period": "4",
    }
    setup = setup_assignment_folder(
        {"class_id": "class1", "students": [student]}, assignment, workspace_root=root
    )
    assert setup is not None
    work = setup["paths"].work_ref
    records = build_answer_sheet_record_set(
        "class1", assignment, student,
        generation_id="gen_00000000000000000000000000000001",
        artifact_id="art_00000000000000000000000000000002",
        output_kind="individual_pdf", reason="initial",
        issuance_id="iss_00000000000000000000000000000003",
        page_ids=("pg_" + "4" * 32, "pg_" + "6" * 32),
        clock=lambda: "2026-07-15T12:00:00+00:00",
    )
    routes = iter(("rt_" + "5" * 32, "rt_" + "7" * 32))
    planned = plan_answer_sheet_route_set(
        work, records, route_id_generator=lambda: next(routes)
    )
    write_answer_sheet_record_set(root, work, records)
    persist_answer_sheet_route_set(root, work, records, planned)
    transition_answer_sheet_issuance(
        root, work, records.issuance.issuance_id, expected_revision=1,
        new_status="issued", timestamp="2026-07-15T12:01:00+00:00",
    )
    source = root / "two_pages.pdf"
    document = canvas.Canvas(str(source), pagesize=(360, 360))
    for i in range(2):
        document.drawString(20, 200, f"Synthetic page {i + 1}")
        document.showPage()
    document.save()
    retained = retain_source_scan(root, source)
    for number in (1, 2):
        metadata = RoutingFailureMetadata(
            schema_version="2", failure_id=f"failure{number}", scope="page",
            stage="payload_detection", created_at="2026-01-01T00:00:00+00:00",
            failure_category="payload_missing", failure_message="No QR was detected.",
            source_filename=retained.source_filename, source_scan_id=retained.source_scan_id,
            source_sha256=retained.source_sha256,
            retained_source_path=retained.retained_source_relative_path,
            review_copy_path=None, source_page_number=number, detected_payload=None,
            route_locator=None, target=None,
            module_details=scoreform_failure_details(
                origin="page_decode", category="qr_detection"
            ),
        )
        write_routing_failure_metadata(root, metadata)
    return planned, retained


def test_single_recovery_prepares_complete_attempt_read_only(tmp_path, monkeypatch):
    route, page, _retained, _failure = _workspace(tmp_path)
    recovered = _dispatch(tmp_path, route, monkeypatch)
    before = _snapshot(tmp_path)
    result = prepare_scoreform_recovery_assembly(tmp_path, (recovered,))
    assert result.status == "ready_to_persist"
    assert result.missing_logical_pages == ()
    assert result.assembled_attempt is not None
    assert result.assembled_attempt.routed_result.page_ids == (page.page_id,)
    assert result.assembled_attempt.routed_result.score == 15
    assert not list(tmp_path.rglob("results.csv"))
    assert _snapshot(tmp_path) == before


def test_historical_route_selection_is_eligible(tmp_path, monkeypatch):
    route, page, _retained, failure = _workspace(tmp_path)
    _record_route(tmp_path, route, page, failure)
    registry = _scoring_registry(monkeypatch, [])
    prepared = prepare_scoreform_scan_recovery(tmp_path, "failure1", use_recorded_route=True)
    recovered = dispatch_prepared_scoreform_scan_recovery(tmp_path, prepared, registry=registry)
    result = prepare_scoreform_recovery_assembly(tmp_path, (recovered,))
    assert result.status == "ready_to_persist"
    assert len(list((tmp_path / "scans" / "review" / "resolutions").glob("*.json"))) == 1


def test_identical_persisted_attempt_is_detected_without_writing(tmp_path, monkeypatch):
    route, _page, _retained, _failure = _workspace(tmp_path)
    recovered = _dispatch(tmp_path, route, monkeypatch)
    first = prepare_scoreform_recovery_assembly(tmp_path, (recovered,))
    assert first.assembled_attempt is not None
    exported = export_scoreform_result_models(
        (first.assembled_attempt.routed_result,), workspace_root=tmp_path
    )
    assert not exported.failures
    before = _snapshot(tmp_path)
    result = prepare_scoreform_recovery_assembly(tmp_path, (recovered,))
    assert result.status == "already_persisted"
    assert result.prior_attempt_number == 1
    assert _snapshot(tmp_path) == before


def test_changed_score_for_existing_source_requires_review(tmp_path, monkeypatch):
    route, _page, _retained, _failure = _workspace(tmp_path)
    recovered = _dispatch(tmp_path, route, monkeypatch)
    original = prepare_scoreform_recovery_assembly(tmp_path, (recovered,))
    assert original.assembled_attempt is not None
    exported = export_scoreform_result_models(
        (original.assembled_attempt.routed_result,), workspace_root=tmp_path
    )
    assert not exported.failures
    # A fully internally consistent alternate scoring result must still not
    # bypass a prior result under the same source-and-issuance content key.
    changed_page = replace(
        recovered.page_result,
        score=0,
        answers=tuple(replace(answer, correct=False) for answer in recovered.page_result.answers),
    )
    changed_success = replace(recovered.success, module_result=changed_page)
    changed = replace(recovered, page_result=changed_page, success=changed_success)
    result = prepare_scoreform_recovery_assembly(tmp_path, (changed,))
    assert result.status == "review_required"
    assert result.assembled_attempt is None


def test_duplicate_physical_recovery_is_not_assembled(tmp_path, monkeypatch):
    route, _page, _retained, _failure = _workspace(tmp_path)
    recovered = _dispatch(tmp_path, route, monkeypatch)
    result = prepare_scoreform_recovery_assembly(tmp_path, (recovered, recovered))
    assert result.status == "review_required"
    assert result.assembled_attempt is None


def test_invalid_recovery_inputs_fail_closed(tmp_path):
    _workspace(tmp_path)
    with pytest.raises(ScoreFormRecoveryAssemblyError, match="At least one"):
        prepare_scoreform_recovery_assembly(tmp_path, ())
    with pytest.raises(ScoreFormRecoveryAssemblyError, match="Only verified"):
        prepare_scoreform_recovery_assembly(tmp_path, (object(),))


def test_mutated_retained_source_is_rejected_at_assembly(tmp_path, monkeypatch):
    route, _page, _retained, _failure = _workspace(tmp_path)
    recovered = _dispatch(tmp_path, route, monkeypatch)
    recovered.prepared.retained_source.retained_source_path.write_bytes(b"bad scan")
    with pytest.raises(ScoreFormRecoveryAssemblyError, match="no longer passes"):
        prepare_scoreform_recovery_assembly(tmp_path, (recovered,))


def test_two_page_issuance_needs_both_pages(tmp_path, monkeypatch):
    routes, _retained = _two_page_workspace(tmp_path)
    recovered = _dispatch(tmp_path, routes[0], monkeypatch)
    result = prepare_scoreform_recovery_assembly(tmp_path, (recovered,))
    assert result.status == "needs_pages"
    assert result.missing_logical_pages == (2,)
    assert result.assembled_attempt is None


def test_two_recovered_pages_assemble_one_complete_issuance(tmp_path, monkeypatch):
    routes, _retained = _two_page_workspace(tmp_path)
    first = _dispatch(tmp_path, routes[0], monkeypatch, "failure1")
    second = _dispatch(tmp_path, routes[1], monkeypatch, "failure2")
    result = prepare_scoreform_recovery_assembly(tmp_path, (second, first))
    assert result.status == "ready_to_persist"
    assert result.assembled_attempt is not None
    assert result.assembled_attempt.routed_result.total_points == 30
    assert result.assembled_attempt.routed_result.logical_pages == (1, 2)
    assert result.source_page_numbers == (1, 2)


def test_recovered_page_and_ordinary_batch_sibling_complete_issuance(tmp_path, monkeypatch):
    routes, retained = _two_page_workspace(tmp_path)
    recovered = _dispatch(tmp_path, routes[0], monkeypatch, "failure1")
    other = _dispatch(tmp_path, routes[1], monkeypatch, "failure2")
    ordinary = Pds2ScanDispatchResult(
        retained_source=other.request.retained_source,
        pages=(
            Pds2ScanPageOutcome(
                source_page_number=1, failure_stage="qr_detection",
                error=ValueError("QR unreadable"),
            ),
            Pds2ScanPageOutcome(
                source_page_number=2,
                raw_payload_text=serialize_pds2_payload(routes[1].locator),
                locator=routes[1].locator, decode_method="opencv",
                dispatch_request=other.request, dispatch_outcome=other.success,
            ),
        ),
        registry_module_ids=("scoreform",),
    )
    assert ordinary.retained_source == retained
    result = prepare_scoreform_recovery_assembly(
        tmp_path, (recovered,), original_batch=ordinary
    )
    assert result.status == "ready_to_persist"
    assert result.assembled_attempt is not None
    assert result.assembled_attempt.routed_result.total_points == 30


def test_ordinary_batch_success_on_recovered_physical_page_requires_review(tmp_path, monkeypatch):
    route, _page, _retained, _failure = _workspace(tmp_path)
    recovered = _dispatch(tmp_path, route, monkeypatch)
    batch = Pds2ScanDispatchResult(
        retained_source=recovered.request.retained_source,
        pages=(Pds2ScanPageOutcome(
            source_page_number=1,
            raw_payload_text=serialize_pds2_payload(route.locator),
            locator=route.locator, dispatch_request=recovered.request,
            dispatch_outcome=recovered.success,
        ),), registry_module_ids=("scoreform",),
    )
    result = prepare_scoreform_recovery_assembly(
        tmp_path, (recovered,), original_batch=batch
    )
    assert result.status == "review_required"


def test_cross_source_batch_fails_closed(tmp_path, monkeypatch):
    route, _page, _retained, _failure = _workspace(tmp_path)
    recovered = _dispatch(tmp_path, route, monkeypatch)
    other = tmp_path / "different.png"
    other.write_bytes(b"distinct")
    second_source = retain_source_scan(tmp_path, other)
    batch = Pds2ScanDispatchResult(retained_source=second_source)
    with pytest.raises(ScoreFormRecoveryAssemblyError, match="another retained scan"):
        prepare_scoreform_recovery_assembly(tmp_path, (recovered,), original_batch=batch)


def test_forged_core_page_identity_fails_closed(tmp_path, monkeypatch):
    route, _page, _retained, _failure = _workspace(tmp_path)
    recovered = _dispatch(tmp_path, route, monkeypatch)
    forged_page = replace(recovered.page_result, student_id="otherstudent")
    forged = replace(
        recovered, page_result=forged_page,
        success=replace(recovered.success, module_result=forged_page),
    )
    with pytest.raises(ScoreFormRecoveryAssemblyError, match="current registered issuance"):
        prepare_scoreform_recovery_assembly(tmp_path, (forged,))
