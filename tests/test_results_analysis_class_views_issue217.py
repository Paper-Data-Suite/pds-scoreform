"""Class analysis presentation tests for ScoreForm Issue #217 Slice 3."""

from scoreform.page_scoring import ScoredAnswer
from scoreform.results import ScoreFormRoutedResult, ScoreFormRoutedResultHistoryRow
from scoreform.results_analysis import analyze_class_results
from scoreform.results_viewer import (
    format_class_standard_detail,
    format_class_standards_analysis,
    format_question_analysis_table,
    format_question_response_distribution,
)


def _assignment():
    return {
        "assignment_id": "quiz1",
        "question_count": 3,
        "choices": ["A", "B", "C", "D"],
        "answer_key": {1: "A", 2: "B", 3: "C"},
        "standards": {
            "1": ["STD.A"],
            "2": ["STD.A", "STD.B"],
            "3": [],
        },
    }


def _row(student_id, answers):
    scored = tuple(
        ScoredAnswer(number, selected, correct)
        for number, selected, correct in answers
    )
    result = ScoreFormRoutedResult(
        "plain_paper_manual",
        "class1",
        "quiz1",
        student_id,
        "Student",
        student_id,
        "1",
        "manual",
        sum(answer.correct for answer in scored),
        3,
        scored,
        source_file="plain_paper_manual_entry",
    )
    return ScoreFormRoutedResultHistoryRow(
        result,
        1,
        "2026-09-01T09:00:00-04:00",
    )


def _analysis():
    rows = (
        _row(
            "1001",
            (
                (1, "A", True),
                (2, "A", False),
                (3, "BLANK", False),
            ),
        ),
        _row(
            "1002",
            (
                (1, "B", False),
                (2, "B", True),
                (3, "AMBIGUOUS", False),
            ),
        ),
    )
    return analyze_class_results(rows, _assignment(), class_id="class1")


def test_question_analysis_table_preserves_all_descriptive_states():
    output = format_question_analysis_table(_analysis())

    assert "Question Analysis" in output
    assert "Students represented: 2" in output
    assert "most recent scored attempt per student for display" in output
    assert "Q1" in output
    assert "Q2" in output
    assert "Q3" in output
    assert "Blank" in output
    assert "Ambiguous" in output
    assert "% Correct" in output


def test_question_distribution_shows_choices_special_states_and_key():
    output = format_question_response_distribution(_analysis(), 3)

    assert "Q3" in output
    assert "Correct answer: C" in output
    for response in ("A", "B", "C", "D", "BLANK", "AMBIGUOUS"):
        assert response in output
    assert "Correct: 0 / 2 (0%)" in output


def test_class_standards_analysis_uses_responses_not_students():
    output = format_class_standards_analysis(_analysis())

    assert "Standards Analysis" in output
    assert "Responses" in output
    assert "STD.A" in output
    assert "STD.B" in output
    assert "Unaligned: 0 / 2 (0%)" in output
    assert "current assignment alignment" in output
    assert "not proficiency or Grade determinations" in output


def test_class_standard_detail_lists_exact_contributing_questions():
    output = format_class_standard_detail(_analysis(), "STD.A")

    assert "Standard: STD.A" in output
    assert "Correct responses: 2 / 4 (50%)" in output
    assert "Q1" in output
    assert "Q2" in output
    assert "Q3" not in output
