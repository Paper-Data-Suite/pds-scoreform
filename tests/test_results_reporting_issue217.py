"""Report snapshot and zero-write export preparation tests for Issue #217 Slice 4."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from scoreform.page_scoring import ScoredAnswer
from scoreform.results import (
    ScoreFormRoutedResult,
    ScoreFormRoutedResultHistoryRow,
)
from scoreform.results_reporting import (
    CLASS_ATTEMPT_BASIS_STATEMENT,
    REPORT_BASIS_STATEMENT,
    REPORT_CONFIRMATION_TOKEN,
    RESULTS_ANALYSIS_REPORT_SCHEMA,
    STANDARDS_BASIS_STATEMENT,
    ResultsReportingError,
    confirm_results_report_plan,
    format_results_report_preview,
    prepare_results_report_plan,
    prepare_results_report_snapshot,
    snapshot_assignment_for_report,
)

GENERATED = datetime(
    2026,
    9,
    30,
    18,
    30,
    45,
    tzinfo=timezone(timedelta(hours=-4)),
)


def _assignment():
    return {
        "assignment_id": "quiz1",
        "title": "Issue 217 Synthetic Assessment",
        "question_count": 3,
        "choices": ["A", "B", "C", "D"],
        "answer_key": {1: "A", 2: "B", 3: "C"},
        "standards": {
            "1": ["STD.A"],
            "2": ["STD.A", "STD.B"],
            "3": [],
        },
        "standards_profile_id": "synthetic_profile",
    }


def _row(
    *,
    student_id,
    attempt,
    timestamp,
    answers,
    last_name="Student",
    first_name="Synthetic",
):
    scored = tuple(
        ScoredAnswer(number, selected, correct)
        for number, selected, correct in answers
    )
    result = ScoreFormRoutedResult(
        "plain_paper_manual",
        "class1",
        "quiz1",
        student_id,
        last_name,
        first_name,
        "1",
        "manual",
        sum(answer.correct for answer in scored),
        3,
        scored,
        source_file="plain_paper_manual_entry",
    )
    return ScoreFormRoutedResultHistoryRow(result, attempt, timestamp)


def _history():
    older_high = _row(
        student_id="1001",
        attempt=1,
        timestamp="2026-09-01T09:00:00-04:00",
        answers=(
            (1, "A", True),
            (2, "B", True),
            (3, "C", True),
        ),
        last_name="Doe",
        first_name="Jane",
    )
    recent_low = _row(
        student_id="1001",
        attempt=2,
        timestamp="2026-09-02T09:00:00-04:00",
        answers=(
            (1, "B", False),
            (2, "B", True),
            (3, "BLANK", False),
        ),
        last_name="Doe",
        first_name="Jane",
    )
    second = _row(
        student_id="1002",
        attempt=1,
        timestamp="2026-09-01T10:00:00-04:00",
        answers=(
            (1, "A", True),
            (2, "AMBIGUOUS", False),
            (3, "D", False),
        ),
        last_name="Smith",
        first_name="John",
    )
    return older_high, recent_low, second


def test_assignment_report_snapshot_is_immutable_interpretation_context():
    assignment = _assignment()
    snapshot = snapshot_assignment_for_report(assignment)

    assert snapshot.assignment_id == "quiz1"
    assert snapshot.question_count == 3
    assert snapshot.choices == ("A", "B", "C", "D")
    assert snapshot.answer_key == ("A", "B", "C")
    assert snapshot.standards_profile_id == "synthetic_profile"
    assert snapshot.standards_by_question == (
        ("STD.A",),
        ("STD.A", "STD.B"),
        (),
    )

    assignment["answer_key"][1] = "D"
    assignment["standards"]["1"] = []
    assert snapshot.answer_key == ("A", "B", "C")
    assert snapshot.standards_by_question[0] == ("STD.A",)


def test_class_snapshot_freezes_recent_display_basis_without_student_rows_by_default():
    snapshot = prepare_results_report_snapshot(
        _history(),
        _assignment(),
        class_id="class1",
        scope="class_analysis",
        generated_at=GENERATED,
    )

    assert snapshot.schema_version == RESULTS_ANALYSIS_REPORT_SCHEMA
    assert snapshot.generated_at == "2026-09-30T22:30:45Z"
    assert snapshot.scope == "class_analysis"
    assert snapshot.student_detail is None
    assert snapshot.class_analysis is not None
    assert snapshot.class_analysis.students_represented == 2
    assert tuple(
        student.attempt_number for student in snapshot.class_analysis.students
    ) == (2, 1)
    assert snapshot.include_individual_response_rows is False
    assert snapshot.basis_statements == (
        REPORT_BASIS_STATEMENT,
        CLASS_ATTEMPT_BASIS_STATEMENT,
        STANDARDS_BASIS_STATEMENT,
    )


def test_student_snapshot_selects_exact_attempt_not_recent_or_highest_implicitly():
    snapshot = prepare_results_report_snapshot(
        _history(),
        _assignment(),
        class_id="class1",
        scope="student_detail",
        student_id="1001",
        attempt_number=1,
        generated_at=GENERATED,
    )

    assert snapshot.scope == "student_detail"
    assert snapshot.class_analysis is None
    assert snapshot.student_detail is not None
    assert snapshot.student_detail.student_id == "1001"
    assert snapshot.student_detail.attempt_number == 1
    assert snapshot.student_detail.attempt_count == 2
    assert snapshot.student_detail.score == 3
    assert snapshot.include_individual_response_rows is True
    assert snapshot.basis_statements == (
        REPORT_BASIS_STATEMENT,
        STANDARDS_BASIS_STATEMENT,
    )


@pytest.mark.parametrize("output_format", ("csv", "json", "pdf"))
def test_export_plan_supports_all_issue217_formats_and_preview(output_format):
    snapshot = prepare_results_report_snapshot(
        _history(),
        _assignment(),
        class_id="class1",
        scope="class_analysis",
        generated_at=GENERATED,
    )
    plan = prepare_results_report_plan(
        snapshot,
        output_format=output_format,
    )

    preview = format_results_report_preview(plan)

    assert "Export Results Report" in preview
    assert "Scope: Class Analysis" in preview
    assert "Students represented: 2" in preview
    assert "Includes individual response rows: No" in preview
    assert f"Format: {output_format.upper()}" in preview
    assert f"Type {REPORT_CONFIRMATION_TOKEN} to create the report." in preview


def test_student_preview_names_exact_student_and_attempt():
    snapshot = prepare_results_report_snapshot(
        _history(),
        _assignment(),
        class_id="class1",
        scope="student_detail",
        student_id="1001",
        attempt_number=2,
        generated_at=GENERATED,
    )
    plan = prepare_results_report_plan(snapshot, output_format="pdf")

    preview = format_results_report_preview(plan)

    assert "Scope: Student Detail" in preview
    assert "Student: Doe, Jane (1001)" in preview
    assert "Attempt: 2 of 2" in preview
    assert "Includes student identity: Yes" in preview
    assert "Includes individual response rows: Yes" in preview


def test_confirmation_is_exact_and_zero_write(tmp_path):
    snapshot = prepare_results_report_snapshot(
        _history(),
        _assignment(),
        class_id="class1",
        scope="class_analysis",
        generated_at=GENERATED,
    )
    plan = prepare_results_report_plan(snapshot, output_format="json")
    before = tuple(tmp_path.iterdir())

    assert confirm_results_report_plan(plan, "generate") is None
    assert confirm_results_report_plan(plan, "BACK") is None
    assert confirm_results_report_plan(plan, "") is None
    confirmed = confirm_results_report_plan(plan, "GENERATE")

    assert confirmed is not None
    assert confirmed.plan is plan
    assert tuple(tmp_path.iterdir()) == before


def test_snapshot_preparation_is_read_only():
    history = _history()
    assignment = _assignment()
    before_history = tuple(history)
    before_assignment = deepcopy(assignment)

    prepare_results_report_snapshot(
        history,
        assignment,
        class_id="class1",
        scope="class_analysis",
        generated_at=GENERATED,
    )

    assert history == before_history
    assert assignment == before_assignment


def test_scope_contract_rejects_implicit_or_cross_scope_student_selection():
    with pytest.raises(
        ResultsReportingError,
        match="does not accept student attempt selection",
    ):
        prepare_results_report_snapshot(
            _history(),
            _assignment(),
            class_id="class1",
            scope="class_analysis",
            student_id="1001",
            attempt_number=1,
            generated_at=GENERATED,
        )

    with pytest.raises(
        ResultsReportingError,
        match="requires student_id and attempt_number",
    ):
        prepare_results_report_snapshot(
            _history(),
            _assignment(),
            class_id="class1",
            scope="student_detail",
            generated_at=GENERATED,
        )


def test_student_scope_rejects_nonexistent_attempt():
    with pytest.raises(
        ResultsReportingError,
        match="exactly one preserved row",
    ):
        prepare_results_report_snapshot(
            _history(),
            _assignment(),
            class_id="class1",
            scope="student_detail",
            student_id="1001",
            attempt_number=3,
            generated_at=GENERATED,
        )


def test_generated_timestamp_must_be_timezone_aware():
    with pytest.raises(ResultsReportingError, match="timezone-aware"):
        prepare_results_report_snapshot(
            _history(),
            _assignment(),
            class_id="class1",
            scope="class_analysis",
            generated_at=datetime(2026, 9, 30, 18, 30, 45),
        )
