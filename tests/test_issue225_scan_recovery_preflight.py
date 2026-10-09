"""Issue #225 Slice 7: read-only teacher route recovery preflight."""

from __future__ import annotations

import hashlib

import cv2
import numpy as np
import pytest
from pds_core.scan_failure_metadata import (
    RoutingFailureMetadata,
    write_routing_failure_metadata,
)
from pds_core.scan_resolution_metadata import (
    create_scan_resolution_metadata,
    write_scan_resolution_metadata,
)
from pds_core.scan_retention import retain_source_scan

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
from scoreform.qr_scan_recovery_preflight import (
    ScoreFormScanRecoveryPreflightError,
    prepare_scoreform_scan_recovery,
)
from scoreform.scan_review_details import (
    scoreform_failure_details,
    scoreform_resolution_details,
)


def _workspace(tmp_path):
    assignment = {
        "assignment_id": "quiz1",
        "title": "One Page Check",
        "question_count": 15,
        "choices": ["A", "B", "C", "D"],
        "layout_id": "standard_15q_abcd_v1",
        "answer_key": {str(n): "A" for n in range(1, 16)},
        "standards": {str(n): [] for n in range(1, 16)},
    }
    student = {
        "class_id": "class1",
        "student_id": "student1",
        "last_name": "Synthetic",
        "first_name": "Student",
        "period": "4",
    }
    roster = {"class_id": "class1", "students": [student]}
    setup = setup_assignment_folder(roster, assignment, workspace_root=tmp_path)
    assert setup is not None
    work = setup["paths"].work_ref
    records = build_answer_sheet_record_set(
        "class1",
        assignment,
        student,
        generation_id="gen_00000000000000000000000000000001",
        artifact_id="art_00000000000000000000000000000002",
        output_kind="individual_pdf",
        reason="initial",
        issuance_id="iss_00000000000000000000000000000003",
        page_ids=("pg_00000000000000000000000000000004",),
        clock=lambda: "2026-07-15T12:00:00+00:00",
    )
    planned = plan_answer_sheet_route_set(
        work, records, route_id_generator=lambda: "rt_" + "1" * 32
    )
    write_answer_sheet_record_set(tmp_path, work, records)
    persist_answer_sheet_route_set(tmp_path, work, records, planned)
    transition_answer_sheet_issuance(
        tmp_path, work, records.issuance.issuance_id,
        expected_revision=1, new_status="issued",
        timestamp="2026-07-15T12:01:00+00:00",
    )
    route = planned[0]

    source = tmp_path / "original_scan.png"
    assert cv2.imwrite(str(source), np.full((90, 90, 3), 255, np.uint8))
    retained = retain_source_scan(tmp_path, source)
    failure = RoutingFailureMetadata(
        schema_version="2",
        failure_id="failure1",
        scope="page",
        stage="payload_detection",
        created_at="2026-01-01T00:00:00+00:00",
        failure_category="payload_missing",
        failure_message="No QR was detected.",
        source_filename=retained.source_filename,
        source_scan_id=retained.source_scan_id,
        source_sha256=retained.source_sha256,
        retained_source_path=retained.retained_source_relative_path,
        review_copy_path=None,
        source_page_number=1,
        detected_payload=None,
        route_locator=None,
        target=None,
        module_details=scoreform_failure_details(
            origin="page_decode", category="qr_detection"
        ),
    )
    write_routing_failure_metadata(tmp_path, failure)
    return route, records.pages[0], retained, failure


def _snapshot(root):
    return {
        item.relative_to(root).as_posix(): hashlib.sha256(item.read_bytes()).digest()
        for item in root.rglob("*")
        if item.is_file()
    }


def _record_route(root, route, page, failure, *, action="route_selected"):
    details = scoreform_resolution_details(
        teacher_action=action,
        identity_source="validated_target",
        identity={
            "class_id": page.class_id,
            "assignment_id": page.assignment_id,
            "student_id": page.student_id,
            "route_id": route.locator.route_id,
            "page_id": page.page_id,
            "issuance_id": page.issuance_id,
            "logical_page": page.logical_page,
            "total_pages": page.total_pages,
        },
    )
    saved = create_scan_resolution_metadata(
        failure,
        resolution_id="resolution_one",
        resolution_status="resolved",
        resolution_action=action,
        resolved_at="2026-10-01T00:00:00+00:00",
        resolution_message="Teacher selected the registered route.",
        route_locator=route.locator,
        target=route.registration.target,
        module_details=details,
    )
    write_scan_resolution_metadata(root, saved)
    return saved


def test_explicit_route_preflight_verifies_identity_without_any_writes(tmp_path):
    route, page, retained, _failure = _workspace(tmp_path)
    before = _snapshot(tmp_path)
    prepared = prepare_scoreform_scan_recovery(tmp_path, "failure1", route_locator=route.locator)
    assert prepared.route_origin == "explicit"
    assert prepared.route_locator == route.locator
    assert prepared.target == route.registration.target
    assert prepared.retained_source == retained
    assert prepared.source_page_number == prepared.source_page_count == 1
    assert prepared.student_id == page.student_id
    assert prepared.page_id == page.page_id
    assert prepared.issuance_id == page.issuance_id
    assert prepared.prior_review_action is None
    assert _snapshot(tmp_path) == before


def test_explicit_target_matches_exact_registration(tmp_path):
    route, _page, _retained, _failure = _workspace(tmp_path)
    prepared = prepare_scoreform_scan_recovery(
        tmp_path, "failure1", route_locator=route.locator,
        target=route.registration.target,
    )
    assert prepared.target == route.registration.target


def test_historical_route_decision_remains_eligible_and_read_only(tmp_path):
    route, page, _retained, failure = _workspace(tmp_path)
    resolution = _record_route(tmp_path, route, page, failure)
    before = _snapshot(tmp_path)
    prepared = prepare_scoreform_scan_recovery(tmp_path, "failure1", use_recorded_route=True)
    assert prepared.route_origin == "recorded"
    assert prepared.historical_resolution_id == resolution.resolution_id
    assert prepared.prior_review_action == "route_selected"
    assert prepared.target == route.registration.target
    assert _snapshot(tmp_path) == before


def test_recorded_reuse_rejects_absent_prior_route(tmp_path):
    _workspace(tmp_path)
    with pytest.raises(ScoreFormScanRecoveryPreflightError, match="decision"):
        prepare_scoreform_scan_recovery(tmp_path, "failure1", use_recorded_route=True)


def test_cannot_mix_recorded_and_explicit_selection(tmp_path):
    route, *_ = _workspace(tmp_path)
    with pytest.raises(ScoreFormScanRecoveryPreflightError, match="cannot include"):
        prepare_scoreform_scan_recovery(
            tmp_path, "failure1", route_locator=route.locator, use_recorded_route=True
        )


def test_retained_source_modified_after_failure_is_rejected(tmp_path):
    route, _page, retained, _failure = _workspace(tmp_path)
    retained.retained_source_path.write_bytes(b"changed scan")
    with pytest.raises(ScoreFormScanRecoveryPreflightError, match="SHA-256"):
        prepare_scoreform_scan_recovery(tmp_path, "failure1", route_locator=route.locator)


def test_source_page_beyond_original_file_is_rejected(tmp_path):
    route, _page, _retained, _failure = _workspace(tmp_path)
    # The original non-PDF file has only one physical source page.
    from scoreform.qr_scan_recovery_preflight import _verify_original_source
    prepared = prepare_scoreform_scan_recovery(tmp_path, "failure1", route_locator=route.locator)
    with pytest.raises(ScoreFormScanRecoveryPreflightError, match="exceeds"):
        _verify_original_source(tmp_path, prepared.retained_source, 2)


def test_wrong_target_is_not_silently_selected(tmp_path):
    route, _page, _retained, _failure = _workspace(tmp_path)
    from pds_core.routing_models import ModuleRecordRef
    target = ModuleRecordRef("scoreform", "answer_sheet_page", "pg_" + "a" * 32, "1")
    with pytest.raises(ScoreFormScanRecoveryPreflightError, match="target"):
        prepare_scoreform_scan_recovery(
            tmp_path, "failure1", route_locator=route.locator, target=target
        )


def test_unknown_failure_is_rejected_without_creating_a_record(tmp_path):
    route, _page, _retained, _failure = _workspace(tmp_path)
    before = _snapshot(tmp_path)
    with pytest.raises(ScoreFormScanRecoveryPreflightError, match="No unique"):
        prepare_scoreform_scan_recovery(
            tmp_path, "not_a_failure", route_locator=route.locator
        )
    assert _snapshot(tmp_path) == before


def test_untrusted_non_scoreform_route_is_rejected(tmp_path):
    route, _page, _retained, _failure = _workspace(tmp_path)
    from pds_core.routing_models import ModuleWorkRef, RouteLocator
    locator = RouteLocator("PDS2", ModuleWorkRef("quillan", "class1", "quiz1"), route.locator.route_id)
    with pytest.raises(ScoreFormScanRecoveryPreflightError, match="ScoreForm"):
        prepare_scoreform_scan_recovery(tmp_path, "failure1", route_locator=locator)


def test_recorded_route_cannot_be_accompanied_by_correction_flag(tmp_path):
    route, page, _retained, failure = _workspace(tmp_path)
    _record_route(tmp_path, route, page, failure)
    with pytest.raises(ScoreFormScanRecoveryPreflightError, match="cannot include"):
        prepare_scoreform_scan_recovery(
            tmp_path, "failure1", use_recorded_route=True, allow_route_correction=True
        )


def _incorrect_observed_route(root, source_failure, route):
    """Represent a syntactically valid but unregistered observed QR locator."""
    from pds_core.routing_models import RouteLocator

    incorrect = RouteLocator(route.locator.schema, route.locator.work, "rt_" + "2" * 32)
    failure = RoutingFailureMetadata(
        schema_version="2",
        failure_id="failure2",
        scope="page",
        stage="route_resolution",
        created_at="2026-01-01T00:00:00+00:00",
        failure_category="route_unknown",
        failure_message="Observed route does not exist.",
        source_filename=source_failure.source_filename,
        source_scan_id=source_failure.source_scan_id,
        source_sha256=source_failure.source_sha256,
        retained_source_path=source_failure.retained_source_path,
        review_copy_path=None,
        source_page_number=1,
        detected_payload=None,
        route_locator=incorrect,
        target=None,
        module_details=scoreform_failure_details(
            origin="core_dispatch", category="route_unknown"
        ),
    )
    write_routing_failure_metadata(root, failure)
    return failure


def test_observed_route_correction_requires_explicit_intent(tmp_path):
    route, _page, _retained, failure = _workspace(tmp_path)
    _incorrect_observed_route(tmp_path, failure, route)
    with pytest.raises(ScoreFormScanRecoveryPreflightError, match="correction"):
        prepare_scoreform_scan_recovery(
            tmp_path, "failure2", route_locator=route.locator
        )
    preview = prepare_scoreform_scan_recovery(
        tmp_path, "failure2", route_locator=route.locator,
        allow_route_correction=True,
    )
    assert preview.route_correction_confirmed


def test_historical_corrected_route_is_explicit_authority(tmp_path):
    route, page, _retained, failure = _workspace(tmp_path)
    incorrect = _incorrect_observed_route(tmp_path, failure, route)
    _record_route(tmp_path, route, page, incorrect, action="route_corrected")
    prepared = prepare_scoreform_scan_recovery(
        tmp_path, "failure2", use_recorded_route=True
    )
    assert prepared.route_origin == "recorded"
    assert prepared.route_correction_confirmed
    assert prepared.prior_review_action == "route_corrected"


def test_issued_lifecycle_is_required(tmp_path):
    route, page, _retained, _failure = _workspace(tmp_path)
    from scoreform.work_paths import scoreform_work_ref

    transition_answer_sheet_issuance(
        tmp_path, scoreform_work_ref(page.class_id, page.assignment_id),
        page.issuance_id, expected_revision=2, new_status="invalidated",
        timestamp="2026-07-15T12:02:00+00:00", reason="Test invalidation",
    )
    with pytest.raises(ScoreFormScanRecoveryPreflightError, match="issued"):
        prepare_scoreform_scan_recovery(tmp_path, "failure1", route_locator=route.locator)
