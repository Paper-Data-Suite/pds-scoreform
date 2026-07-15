from __future__ import annotations

import json
from dataclasses import replace

import cv2
import numpy as np
import pytest
from pds_core.route_registrations import resolve_route_registration
from pds_core.routing_models import ModuleRecordRef, RouteRegistration, RouteResolution
from pds_core.scan_retention import retain_source_scan
from PIL import Image

from scoreform.answer_sheet_persistence import (
    AnswerSheetPageContext,
    transition_answer_sheet_issuance,
    write_answer_sheet_record_set,
)
from scoreform.answer_sheet_records import (
    build_answer_sheet_record_set,
    transition_answer_sheet_lifecycle,
)
from scoreform.answer_sheet_routes import (
    build_answer_sheet_page_route,
    persist_answer_sheet_route_set,
)
from scoreform.folders import setup_assignment_folder
from scoreform.module_errors import (
    ScoreFormIssuanceAuthorizationError,
    ScoreFormPageScoringError,
    ScoreFormTargetIntegrityError,
)
from scoreform.page_scoring import ScoredAnswer, ScoreFormPageDispatchResult
from scoreform.route_handler import _authorize_issuance, handle_scoreform_route


def test_handler_uses_core_resolution_and_retained_source(tmp_path, monkeypatch):
    assignment = {
        "assignment_id": "quiz1",
        "title": "Printed title",
        "question_count": 1,
        "choices": ["A", "B", "C", "D"],
        "layout_id": "standard_15q_abcd_v1",
        "answer_key": {"1": "A"},
        "standards": {"1": []},
    }
    student = {
        "class_id": "class1",
        "student_id": "student1",
        "last_name": "Doe",
        "first_name": "Jane",
        "period": "1",
    }
    setup = setup_assignment_folder(
        {"class_id": "class1", "students": [student]},
        assignment,
        workspace_root=tmp_path,
    )
    assert setup is not None
    paths = setup["paths"]
    records = build_answer_sheet_record_set(
        "class1",
        assignment,
        student,
        generation_id="gen_" + "1" * 32,
        artifact_id="art_" + "2" * 32,
        output_kind="individual_pdf",
        reason="initial",
        issuance_id="iss_" + "3" * 32,
        page_ids=("pg_" + "4" * 32,),
        clock=lambda: "2026-01-01T00:00:00+00:00",
    )
    write_answer_sheet_record_set(tmp_path, paths.work_ref, records)
    route = build_answer_sheet_page_route(
        paths.work_ref,
        records.pages[0],
        route_id="rt_" + "5" * 32,
    )
    persist_answer_sheet_route_set(tmp_path, paths.work_ref, records, (route,))
    current_assignment = {
        **assignment,
        "title": "Current title",
        "answer_key": {"1": "B"},
    }
    paths.assignment_path.write_text(
        json.dumps(current_assignment), encoding="utf-8"
    )
    incoming = tmp_path / "incoming.png"
    assert cv2.imwrite(str(incoming), np.full((20, 30, 3), 255, np.uint8))
    retained = retain_source_scan(
        tmp_path,
        incoming,
        intake_timestamp=None,
    )
    resolution = resolve_route_registration(tmp_path, route.locator)

    with monkeypatch.context() as blocked:
        blocked.setattr(
            "scoreform.route_handler.load_retained_source_page",
            lambda *args, **kwargs: pytest.fail(
                "source extraction ran before lifecycle authorization"
            ),
        )
        blocked.setattr(
            "scoreform.route_handler.score_authoritative_answer_sheet_page",
            lambda *args, **kwargs: pytest.fail(
                "scoring ran before lifecycle authorization"
            ),
        )
        with pytest.raises(ScoreFormIssuanceAuthorizationError, match="issued"):
            handle_scoreform_route(resolution, retained, 1)

    transition_answer_sheet_issuance(
        tmp_path,
        paths.work_ref,
        records.issuance.issuance_id,
        expected_revision=1,
        new_status="issued",
        timestamp="2026-01-01T00:01:00+00:00",
    )

    registration = resolution.registration

    def changed_registration(**changes):
        values = {
            "schema_version": registration.schema_version,
            "locator": registration.locator,
            "target": registration.target,
            "created_at": registration.created_at,
            "status": registration.status,
            "human_fallback": registration.human_fallback,
            "module_details": registration.module_details,
        }
        values.update(changes)
        return RouteRegistration(**values)

    other_page = "pg_" + "6" * 32
    diagnostic_mismatches = (
        changed_registration(created_at="2026-01-01T00:00:30+00:00"),
        changed_registration(
            module_details={
                **registration.module_details,
                "issuance_id": "iss_" + "9" * 32,
            }
        ),
        changed_registration(
            human_fallback=registration.human_fallback.replace(
                "student=student1", "student=student2"
            )
        ),
        changed_registration(
            target=ModuleRecordRef(
                "scoreform", "answer_sheet_page", other_page, "1"
            ),
            human_fallback=registration.human_fallback.replace(
                records.pages[0].page_id, other_page
            ),
        ),
    )
    for mismatched_registration in diagnostic_mismatches:
        mismatched_resolution = RouteResolution(
            locator=resolution.locator,
            registration=mismatched_registration,
            class_root=resolution.class_root,
            module_root=resolution.module_root,
            work_root=resolution.work_root,
        )
        with pytest.raises(ScoreFormTargetIntegrityError):
            handle_scoreform_route(mismatched_resolution, retained, 1)

    result_override = {}

    def fake_score(image, **kwargs):
        context = kwargs["page_context"]
        page = context.page
        assert image.shape == (20, 30, 3)
        assert kwargs["assignment"]["answer_key"] == {1: "B"}
        result = ScoreFormPageDispatchResult(
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
            score=1,
            total_points=1,
            answers=(ScoredAnswer(1, "B", True),),
            source_scan_id=kwargs["source_scan_id"],
            source_page_number=kwargs["source_page_number"],
            retained_source_relative_path=kwargs[
                "retained_source_relative_path"
            ],
            source_sha256=kwargs["source_sha256"],
            diagnostic_paths=(),
        )
        return replace(result, **result_override)

    monkeypatch.setattr(
        "scoreform.route_handler.score_authoritative_answer_sheet_page",
        fake_score,
    )
    result = handle_scoreform_route(resolution, retained, 1)
    assert result.route_id == route.locator.route_id
    assert result.page_id == records.pages[0].page_id
    assert result.source_scan_id == retained.source_scan_id
    assert result.student_id == records.pages[0].student_id

    result_override.clear()
    incoming_pdf = tmp_path / "incoming.pdf"
    incoming_pdf.write_bytes(b"test PDF placeholder")
    retained_pdf = retain_source_scan(tmp_path, incoming_pdf)
    monkeypatch.setattr(
        "pdf2image.convert_from_path",
        lambda *args, **kwargs: [
            Image.fromarray(np.full((20, 30, 3), 255, np.uint8), "RGB")
        ],
    )
    pdf_result = handle_scoreform_route(resolution, retained_pdf, 2)
    assert pdf_result.source_page_number == 2
    assert pdf_result.logical_page == 1
    assert (pdf_result.question_start, pdf_result.question_end) == (1, 1)

    mismatches = (
        {"route_id": "rt_" + "6" * 32},
        {"page_id": "pg_" + "6" * 32},
        {"issuance_id": "iss_" + "6" * 32},
        {"generation_id": "gen_" + "6" * 32},
        {"artifact_id": "art_" + "6" * 32},
        {"class_id": "class2"},
        {"assignment_id": "quiz2"},
        {"student_id": "student2"},
        {"logical_page": 2, "total_pages": 2},
        {"total_pages": 2},
        {"question_start": 2, "question_end": 2},
        {"question_end": 2, "total_points": 2, "answers": (
            ScoredAnswer(1, "B", True), ScoredAnswer(2, "B", True)
        ), "score": 2},
        {"layout_id": "compact_25q_abcd_v1"},
        {"source_scan_id": "scan_other"},
        {"source_page_number": 2},
        {"retained_source_relative_path": (
            "scans/source/2026-01-02/other.png"
        )},
        {"source_sha256": "b" * 64},
        {"logical_page": True},
        {"source_page_number": True},
    )
    for mismatch in mismatches:
        result_override.clear()
        result_override.update(mismatch)
        with pytest.raises(ScoreFormTargetIntegrityError):
            handle_scoreform_route(resolution, retained, 1)

    evidence = paths.debug_dir / "failure-evidence.png"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_bytes(b"diagnostic")

    def fail_with_evidence(*args, **kwargs):
        raise ScoreFormPageScoringError(
            "registration failure", diagnostic_paths=(str(evidence),)
        )

    monkeypatch.setattr(
        "scoreform.route_handler.score_authoritative_answer_sheet_page",
        fail_with_evidence,
    )
    with pytest.raises(ScoreFormPageScoringError) as caught:
        handle_scoreform_route(resolution, retained, 1)
    assert caught.value.diagnostic_paths == (str(evidence),)

    outside = tmp_path / "outside.png"
    outside.write_bytes(b"not managed evidence")

    def fail_outside(*args, **kwargs):
        raise ScoreFormPageScoringError(
            "registration failure", diagnostic_paths=(str(outside),)
        )

    monkeypatch.setattr(
        "scoreform.route_handler.score_authoritative_answer_sheet_page",
        fail_outside,
    )
    with pytest.raises(ScoreFormTargetIntegrityError, match="outside"):
        handle_scoreform_route(resolution, retained, 1)


@pytest.mark.parametrize("status", ("prepared", "cancelled", "superseded", "invalidated"))
def test_only_issued_lifecycle_is_authorized(status):
    assignment = {
        "assignment_id": "quiz1",
        "title": "Quiz",
        "question_count": 1,
        "choices": ["A", "B", "C", "D"],
        "layout_id": "standard_15q_abcd_v1",
        "answer_key": {"1": "A"},
        "standards": {"1": []},
    }
    student = {
        "class_id": "class1",
        "student_id": "student1",
        "last_name": "Doe",
        "first_name": "Jane",
        "period": "1",
    }
    records = build_answer_sheet_record_set(
        "class1",
        assignment,
        student,
        generation_id="gen_" + "1" * 32,
        artifact_id="art_" + "2" * 32,
        output_kind="individual_pdf",
        reason="initial",
        issuance_id="iss_" + "3" * 32,
        page_ids=("pg_" + "4" * 32,),
        clock=lambda: "2026-01-01T00:00:00+00:00",
    )
    issuance = records.issuance
    if status != "prepared":
        first_status = "issued" if status == "superseded" else status
        issuance = transition_answer_sheet_lifecycle(
            issuance,
            first_status,
            timestamp="2026-01-01T00:01:00+00:00",
            reason=None if first_status == "issued" else "not authorized",
        )
        if status == "superseded":
            issuance = transition_answer_sheet_lifecycle(
                issuance,
                "superseded",
                timestamp="2026-01-01T00:02:00+00:00",
                reason="replaced",
                replacement_issuance_id="iss_" + "9" * 32,
            )
    context = AnswerSheetPageContext(records.pages[0], issuance, records.pages)
    with pytest.raises(ScoreFormIssuanceAuthorizationError, match="issued"):
        _authorize_issuance(context)


def test_issued_lifecycle_is_authorized():
    assignment = {
        "assignment_id": "quiz1",
        "title": "Quiz",
        "question_count": 1,
        "choices": ["A", "B", "C", "D"],
        "layout_id": "standard_15q_abcd_v1",
        "answer_key": {"1": "A"},
        "standards": {"1": []},
    }
    student = {
        "class_id": "class1",
        "student_id": "student1",
        "last_name": "Doe",
        "first_name": "Jane",
        "period": "1",
    }
    records = build_answer_sheet_record_set(
        "class1",
        assignment,
        student,
        generation_id="gen_" + "1" * 32,
        artifact_id="art_" + "2" * 32,
        output_kind="individual_pdf",
        reason="initial",
        issuance_id="iss_" + "3" * 32,
        page_ids=("pg_" + "4" * 32,),
        clock=lambda: "2026-01-01T00:00:00+00:00",
    )
    issuance = transition_answer_sheet_lifecycle(
        records.issuance,
        "issued",
        timestamp="2026-01-01T00:01:00+00:00",
    )
    context = AnswerSheetPageContext(records.pages[0], issuance, records.pages)
    assert _authorize_issuance(context) is None
