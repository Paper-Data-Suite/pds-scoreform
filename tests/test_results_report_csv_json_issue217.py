"""Deterministic CSV/JSON renderer tests for ScoreForm Issue #217 Slice 5."""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone

import pytest

from scoreform.page_scoring import ScoredAnswer
from scoreform.results import (
    ScoreFormRoutedResult,
    ScoreFormRoutedResultHistoryRow,
)
from scoreform.results_report_csv import (
    CLASS_CSV_FILENAMES,
    STUDENT_CSV_FILENAMES,
    render_results_report_csv,
)
from scoreform.results_report_json import render_results_report_json
from scoreform.results_reporting import (
    REPORT_CONFIRMATION_TOKEN,
    ResultsReportingError,
    confirm_results_report_plan,
    prepare_results_report_plan,
    prepare_results_report_snapshot,
)

GENERATED = datetime(2026, 9, 30, 22, 0, 0, tzinfo=timezone.utc)


def _assignment():
    return {
        "assignment_id": "quiz1",
        "title": 'Synthetic, "Quoted" Assessment',
        "question_count": 4,
        "choices": ["A", "B", "C", "D"],
        "answer_key": {1: "A", 2: "B", 3: "C", 4: "D"},
        "standards": {
            "1": ["STD.A"],
            "2": ["STD.A", "STD.B"],
            "3": ["STD.B"],
            "4": [],
        },
        "standards_profile_id": "synthetic_profile",
    }


def _row(
    *,
    student_id,
    attempt,
    timestamp,
    answers,
    last_name,
    first_name,
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
        4,
        scored,
        source_file="plain_paper_manual_entry",
    )
    return ScoreFormRoutedResultHistoryRow(result, attempt, timestamp)


def _history():
    older_high = _row(
        student_id="1001",
        attempt=1,
        timestamp="2026-09-01T09:00:00+00:00",
        answers=(
            (1, "A", True),
            (2, "B", True),
            (3, "C", True),
            (4, "D", True),
        ),
        last_name="Doe",
        first_name='Jane, "J."',
    )
    recent_low = _row(
        student_id="1001",
        attempt=2,
        timestamp="2026-09-02T09:00:00+00:00",
        answers=(
            (1, "B", False),
            (2, "B", True),
            (3, "BLANK", False),
            (4, "AMBIGUOUS", False),
        ),
        last_name="Doe",
        first_name='Jane, "J."',
    )
    second = _row(
        student_id="1002",
        attempt=1,
        timestamp="2026-09-01T10:00:00+00:00",
        answers=(
            (1, "A", True),
            (2, "A", False),
            (3, "D", False),
            (4, "D", True),
        ),
        last_name="Smith",
        first_name="John",
    )
    return older_high, recent_low, second


def _confirmed(scope, output_format, *, student_id=None, attempt_number=None):
    snapshot = prepare_results_report_snapshot(
        _history(),
        _assignment(),
        class_id="class1",
        scope=scope,
        generated_at=GENERATED,
        student_id=student_id,
        attempt_number=attempt_number,
    )
    plan = prepare_results_report_plan(
        snapshot,
        output_format=output_format,
    )
    confirmed = confirm_results_report_plan(
        plan,
        REPORT_CONFIRMATION_TOKEN,
    )
    assert confirmed is not None
    return confirmed


def _csv_rows(report, filename):
    text = report.artifact(filename).content.decode("utf-8")
    return list(csv.DictReader(io.StringIO(text)))


def test_class_csv_set_is_bounded_and_omits_full_student_response_rows():
    report = render_results_report_csv(_confirmed("class_analysis", "csv"))

    assert report.output_format == "csv"
    assert report.scope == "class_analysis"
    assert tuple(artifact.filename for artifact in report.artifacts) == (
        CLASS_CSV_FILENAMES
    )
    assert "student_responses.csv" not in CLASS_CSV_FILENAMES

    overview = _csv_rows(report, "assignment_overview.csv")
    assert [row["student_id"] for row in overview] == ["1001", "1002"]
    assert [row["attempt_number"] for row in overview] == ["2", "1"]
    assert overview[0]["name"] == 'Doe, Jane, "J."'


def test_class_csv_preserves_question_states_and_distribution_order():
    report = render_results_report_csv(_confirmed("class_analysis", "csv"))

    questions = _csv_rows(report, "question_analysis.csv")
    q3 = questions[2]
    assert q3 == {
        "question_number": "3",
        "correct": "0",
        "incorrect": "1",
        "blank": "1",
        "ambiguous": "0",
        "total": "2",
        "percent_correct": "0",
    }

    distribution = _csv_rows(report, "response_distribution.csv")
    q3_distribution = [
        row for row in distribution if row["question_number"] == "3"
    ]
    assert [row["response"] for row in q3_distribution] == [
        "A",
        "B",
        "C",
        "D",
        "BLANK",
        "AMBIGUOUS",
    ]
    assert [row["count"] for row in q3_distribution] == [
        "0",
        "0",
        "0",
        "1",
        "1",
        "0",
    ]
    assert q3_distribution[2]["is_keyed_answer"] == "true"


def test_student_csv_preserves_response_state_without_fake_selected_answer():
    report = render_results_report_csv(
        _confirmed(
            "student_detail",
            "csv",
            student_id="1001",
            attempt_number=2,
        )
    )

    assert tuple(artifact.filename for artifact in report.artifacts) == (
        STUDENT_CSV_FILENAMES
    )
    responses = _csv_rows(report, "student_responses.csv")

    assert responses[0]["response_state"] == "SELECTED"
    assert responses[0]["selected_answer"] == "B"
    assert responses[0]["correct"] == "false"

    assert responses[2]["response_state"] == "BLANK"
    assert responses[2]["selected_answer"] == ""
    assert responses[2]["correct"] == "false"

    assert responses[3]["response_state"] == "AMBIGUOUS"
    assert responses[3]["selected_answer"] == ""
    assert responses[3]["correct"] == "false"


def test_csv_standard_rows_fall_back_to_durable_id_and_keep_unaligned_separate():
    report = render_results_report_csv(_confirmed("class_analysis", "csv"))

    standards = _csv_rows(report, "standards_analysis.csv")
    assert [row["standard_id"] for row in standards] == ["STD.A", "STD.B"]
    assert [row["display_label"] for row in standards] == ["STD.A", "STD.B"]
    assert standards[0]["question_numbers"] == "1|2"

    unaligned = _csv_rows(report, "unaligned_analysis.csv")
    assert unaligned == [
        {
            "correct": "1",
            "responses": "2",
            "percent_correct": "50",
            "question_numbers": "4",
        }
    ]
    assert all(row["standard_id"] != "Unaligned" for row in standards)


def test_csv_metadata_reports_attempt_and_alignment_basis_explicitly():
    report = render_results_report_csv(_confirmed("class_analysis", "csv"))
    metadata = {
        row["field"]: row["value"]
        for row in _csv_rows(report, "report_metadata.csv")
    }

    assert metadata["scope"] == "class_analysis"
    assert metadata["include_individual_response_rows"] == "false"
    assert (
        metadata["attempt_basis"]
        == "most recent scored attempt per student for display"
    )
    assert metadata["standards_basis"] == "current assignment alignment"
    assert metadata["students_represented"] == "2"


def test_csv_output_is_deterministic_for_identical_confirmed_snapshot():
    confirmed = _confirmed("class_analysis", "csv")

    first = render_results_report_csv(confirmed)
    second = render_results_report_csv(confirmed)

    assert first == second
    assert tuple(artifact.sha256_hex for artifact in first.artifacts) == tuple(
        artifact.sha256_hex for artifact in second.artifacts
    )


def test_class_json_is_versioned_deterministic_and_privacy_bounded():
    confirmed = _confirmed("class_analysis", "json")

    first = render_results_report_json(confirmed)
    second = render_results_report_json(confirmed)

    assert first == second
    assert len(first.artifacts) == 1
    assert first.artifacts[0].filename == "results_analysis.json"

    payload = json.loads(first.artifacts[0].content)
    assert payload["schema_version"] == "scoreform_results_analysis_v1"
    assert payload["scope"] == "class_analysis"
    assert payload["generated_at"] == "2026-09-30T22:00:00Z"
    assert payload["report_basis"]["include_individual_response_rows"] is False
    assert (
        payload["report_basis"]["attempt_basis"]
        == "most recent scored attempt per student for display"
    )

    overview = payload["class_analysis"]["assignment_overview"]
    assert [row["attempt_number"] for row in overview] == [2, 1]
    assert all("questions" not in row for row in overview)
    assert "student_detail" not in payload


def test_student_json_contains_only_selected_attempt_full_detail():
    report = render_results_report_json(
        _confirmed(
            "student_detail",
            "json",
            student_id="1001",
            attempt_number=1,
        )
    )
    payload = json.loads(report.artifacts[0].content)

    assert payload["scope"] == "student_detail"
    assert "class_analysis" not in payload
    detail = payload["student_detail"]
    assert detail["student_id"] == "1001"
    assert detail["attempt_number"] == 1
    assert detail["attempt_count"] == 2
    assert detail["score"] == 4
    assert [question["selected_answer"] for question in detail["questions"]] == [
        "A",
        "B",
        "C",
        "D",
    ]


def test_json_preserves_blank_ambiguous_and_report_basis_statements():
    report = render_results_report_json(
        _confirmed(
            "student_detail",
            "json",
            student_id="1001",
            attempt_number=2,
        )
    )
    payload = json.loads(report.artifacts[0].content)
    detail = payload["student_detail"]

    assert detail["questions"][2]["response_state"] == "BLANK"
    assert detail["questions"][2]["selected_answer"] == "BLANK"
    assert detail["questions"][3]["response_state"] == "AMBIGUOUS"
    assert detail["questions"][3]["selected_answer"] == "AMBIGUOUS"
    statements = payload["report_basis"]["statements"]
    assert any("not proficiency or Grade determinations" in value for value in statements)
    assert any("current question alignment" in value for value in statements)


def test_csv_and_json_question_analysis_are_semantically_consistent():
    csv_report = render_results_report_csv(_confirmed("class_analysis", "csv"))
    json_report = render_results_report_json(
        _confirmed("class_analysis", "json")
    )

    csv_questions = _csv_rows(csv_report, "question_analysis.csv")
    json_questions = json.loads(
        json_report.artifacts[0].content
    )["class_analysis"]["question_analysis"]

    assert [
        (
            int(row["question_number"]),
            int(row["correct"]),
            int(row["incorrect"]),
            int(row["blank"]),
            int(row["ambiguous"]),
            int(row["total"]),
            int(row["percent_correct"]),
        )
        for row in csv_questions
    ] == [
        (
            row["question_number"],
            row["correct"],
            row["incorrect"],
            row["blank"],
            row["ambiguous"],
            row["total"],
            row["percent_correct"],
        )
        for row in json_questions
    ]


@pytest.mark.parametrize(
    ("renderer", "confirmed"),
    (
        (
            render_results_report_csv,
            lambda: _confirmed("class_analysis", "json"),
        ),
        (
            render_results_report_json,
            lambda: _confirmed("class_analysis", "csv"),
        ),
    ),
)
def test_renderers_reject_mismatched_confirmed_format(renderer, confirmed):
    with pytest.raises(ResultsReportingError, match="format is not"):
        renderer(confirmed())


def test_renderers_do_not_write_files(tmp_path):
    before = tuple(tmp_path.iterdir())

    render_results_report_csv(_confirmed("class_analysis", "csv"))
    render_results_report_json(_confirmed("class_analysis", "json"))

    assert tuple(tmp_path.iterdir()) == before
