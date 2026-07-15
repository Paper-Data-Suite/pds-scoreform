from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from scoreform.answer_sheet_persistence import AnswerSheetPageContext
from scoreform.answer_sheet_records import build_answer_sheet_record_set
from scoreform.module_errors import (
    ScoreFormAssignmentCompatibilityError,
    ScoreFormPageScoringError,
)
from scoreform.page_scoring import (
    ScoredAnswer,
    ScoreFormPageDispatchResult,
    score_authoritative_answer_sheet_page,
    validate_assignment_page_compatibility,
    validate_page_dispatch_result,
)


def _result() -> ScoreFormPageDispatchResult:
    return ScoreFormPageDispatchResult(
        route_id="rt_" + "1" * 32,
        page_id="pg_" + "2" * 32,
        issuance_id="iss_" + "3" * 32,
        generation_id="gen_" + "4" * 32,
        artifact_id="art_" + "5" * 32,
        class_id="class1",
        assignment_id="quiz1",
        student_id="student1",
        logical_page=1,
        total_pages=1,
        question_start=1,
        question_end=1,
        layout_id="standard_15q_abcd_v1",
        score=1,
        total_points=1,
        answers=(ScoredAnswer(1, "A", True),),
        source_scan_id="scan_one",
        source_page_number=1,
        retained_source_relative_path=(
            "scans/source/2026-01-02/retained.png"
        ),
        source_sha256="a" * 64,
        diagnostic_paths=(),
    )


def _validate(result):
    return validate_page_dispatch_result(
        result, valid_choices=("A", "B", "C", "D")
    )


def test_valid_result_is_returned_unchanged():
    result = _result()
    assert _validate(result) is result


@pytest.mark.parametrize(
    "change",
    (
        {"total_points": True},
        {"score": True},
        {"logical_page": True},
        {"source_page_number": True},
        {"answers": (ScoredAnswer(True, "A", True),)},
        {"diagnostic_paths": (Path("debug.png"),)},
        {"diagnostic_paths": ("debug.png", "debug.png")},
    ),
)
def test_boolean_and_diagnostic_contract_regressions_fail(change):
    with pytest.raises(ScoreFormPageScoringError):
        _validate(replace(_result(), **change))


def _compatibility_context():
    assignment = {
        "assignment_id": "quiz1",
        "title": "Printed title",
        "question_count": 2,
        "choices": ["A", "B", "C", "D"],
        "layout_id": "standard_15q_abcd_v1",
        "answer_key": {"1": "A", "2": "B"},
        "standards": {"1": [], "2": []},
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
    context = AnswerSheetPageContext(
        records.pages[0], records.issuance, records.pages
    )
    normalized = {
        **assignment,
        "answer_key": {1: "A", 2: "B"},
    }
    return context, normalized


def test_title_only_change_and_current_answer_key_change_are_compatible():
    context, assignment = _compatibility_context()
    changed = {
        **assignment,
        "title": "Corrected title",
        "answer_key": {1: "D", 2: "C"},
    }
    assert validate_assignment_page_compatibility(context, changed) is None


@pytest.mark.parametrize(
    "change",
    (
        {"question_count": 3, "answer_key": {1: "A", 2: "B", 3: "C"}},
        {"layout_id": "compact_25q_abcd_v1"},
        {"choices": ["A", "B", "C"]},
        {"answer_key": {1: "A"}},
    ),
)
def test_scoring_sensitive_assignment_changes_are_rejected(change):
    context, assignment = _compatibility_context()
    with pytest.raises(ScoreFormAssignmentCompatibilityError):
        validate_assignment_page_compatibility(
            context, {**assignment, **change}
        )


def test_inconsistent_page_question_range_is_rejected():
    context, assignment = _compatibility_context()
    forged_page = replace(context.page, question_end=1)
    forged_context = AnswerSheetPageContext(
        forged_page, context.issuance, (forged_page,)
    )
    with pytest.raises(ScoreFormAssignmentCompatibilityError):
        validate_assignment_page_compatibility(forged_context, assignment)


def test_image_source_page_one_can_score_logical_page_two(monkeypatch):
    assignment = {
        "assignment_id": "quiz1",
        "title": "Quiz",
        "question_count": 16,
        "choices": ["A", "B", "C", "D"],
        "layout_id": "standard_15q_abcd_v1",
        "answer_key": {str(number): "A" for number in range(1, 17)},
        "standards": {str(number): [] for number in range(1, 17)},
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
        page_ids=("pg_" + "4" * 32, "pg_" + "5" * 32),
        clock=lambda: "2026-01-01T00:00:00+00:00",
    )
    context = AnswerSheetPageContext(
        records.pages[1], records.issuance, records.pages
    )
    normalized = {
        **assignment,
        "answer_key": {number: "A" for number in range(1, 17)},
    }

    def fake_score(*args, **kwargs):
        assert kwargs["page_num"] == 1
        assert kwargs["question_start"] == 16
        assert kwargs["question_count"] == 1
        return {
            "score": 1,
            "total_points": 1,
            "answers": [{"Q": 16, "Answer": "A", "Correct": True}],
            "diagnostic_paths": (),
        }

    monkeypatch.setattr("scoreform.page_scoring.score_image", fake_score)
    result = score_authoritative_answer_sheet_page(
        np.full((20, 30, 3), 255, np.uint8),
        page_context=context,
        assignment=normalized,
        route_id="rt_" + "6" * 32,
        source_scan_id="scan_one",
        source_page_number=1,
        retained_source_relative_path=(
            "scans/source/2026-01-02/retained.png"
        ),
        source_sha256="a" * 64,
        debug_dir=None,
    )
    assert result.source_page_number == 1
    assert result.logical_page == 2
    assert (result.question_start, result.question_end) == (16, 16)
