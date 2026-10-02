"""Focused Student Detail presentation tests for ScoreForm Issue #217 Slice 2."""

from scoreform.page_scoring import ScoredAnswer
from scoreform.results import ScoreFormRoutedResult, ScoreFormRoutedResultHistoryRow
from scoreform.results_analysis import analyze_student_attempt
from scoreform.results_viewer import (
    format_student_attempt_detail,
    format_student_standard_detail,
)


def _assignment():
    return {
        "assignment_id": "quiz1",
        "question_count": 4,
        "choices": ["A", "B", "C", "D"],
        "answer_key": {1: "A", 2: "B", 3: "C", 4: "D"},
        "standards": {
            "1": ["STD.A"],
            "2": ["STD.A", "STD.B"],
            "3": ["STD.B"],
            "4": [],
        },
    }


def _analysis():
    answers = (
        ScoredAnswer(1, "A", True),
        ScoredAnswer(2, "A", False),
        ScoredAnswer(3, "BLANK", False),
        ScoredAnswer(4, "AMBIGUOUS", False),
    )
    result = ScoreFormRoutedResult(
        "plain_paper_manual",
        "class1",
        "quiz1",
        "1001",
        "Doe",
        "Jane",
        "1",
        "manual",
        1,
        4,
        answers,
        source_file="plain_paper_manual_entry",
    )
    row = ScoreFormRoutedResultHistoryRow(
        result,
        2,
        "2026-09-02T09:00:00-04:00",
    )
    return analyze_student_attempt(
        row,
        _assignment(),
        class_id="class1",
        attempt_count=2,
    )


def test_student_detail_formats_exact_response_states_and_basis():
    output = format_student_attempt_detail(_analysis())

    assert "Student: Doe, Jane (1001)" in output
    assert "Attempt: 2 of 2" in output
    assert "Overall: 1 / 4" in output
    assert "Q1" in output and "Correct" in output
    assert "Q2" in output and "Incorrect" in output
    assert "Q3" in output and "BLANK" in output and "Blank" in output
    assert "Q4" in output and "AMBIGUOUS" in output and "Ambiguous" in output
    assert "STD.A, STD.B" in output
    assert "Student Standards Breakdown" in output
    assert "STD.A" in output and "1" in output and "2" in output and "50%" in output
    assert "Unaligned: 0 / 1 (0%)" in output
    assert "Standards basis: current assignment alignment." in output
    assert "not proficiency or Grade determinations" in output


def test_student_standard_detail_lists_only_contributing_questions():
    output = format_student_standard_detail(_analysis(), "STD.A")

    assert "Standard: STD.A" in output
    assert "Correct: 1 / 2 (50%)" in output
    assert "Q1" in output
    assert "Q2" in output
    assert "Q3" not in output
    assert "Q4" not in output
