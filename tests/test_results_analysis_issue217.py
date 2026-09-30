"""Focused Slice 1 coverage for ScoreForm Issue #217 analysis models."""

from copy import deepcopy

import pytest

from scoreform.page_scoring import ScoredAnswer
from scoreform.results import (
    ScoreFormRoutedResult,
    ScoreFormRoutedResultHistoryRow,
)
from scoreform.results_analysis import (
    ATTEMPT_DISPLAY_BASIS,
    PERCENT_ROUNDING_RULE,
    STANDARDS_ALIGNMENT_BASIS,
    ResultsAnalysisError,
    analyze_class_results,
    analyze_student_attempt,
    rounded_percent,
    select_recent_display_attempts,
    select_student_attempts,
)


def _assignment():
    return {
        "assignment_id": "quiz1",
        "title": "Issue 217 Synthetic Assessment",
        "question_count": 4,
        "choices": ["A", "B", "C", "D"],
        "layout_id": "standard_15q_abcd_v1",
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
    attempt_number,
    timestamp,
    answers,
    last_name="Student",
    first_name="Synthetic",
    class_id="class1",
    assignment_id="quiz1",
):
    scored = tuple(
        ScoredAnswer(number, selected, correct)
        for number, selected, correct in answers
    )
    result = ScoreFormRoutedResult(
        result_origin="plain_paper_manual",
        class_id=class_id,
        assignment_id=assignment_id,
        student_id=student_id,
        last_name=last_name,
        first_name=first_name,
        period="1",
        page_display="manual",
        score=sum(answer.correct for answer in scored),
        total_points=len(scored),
        answers=scored,
        source_file="plain_paper_manual_entry",
    )
    return ScoreFormRoutedResultHistoryRow(
        result=result,
        attempt_number=attempt_number,
        scan_timestamp=timestamp,
    )


def _history():
    older_high_score = _row(
        student_id="1001",
        attempt_number=1,
        timestamp="2026-09-01T09:00:00-04:00",
        answers=(
            (1, "A", True),
            (2, "B", True),
            (3, "C", True),
            (4, "D", True),
        ),
        last_name="Doe",
        first_name="Jane",
    )
    recent_lower_score = _row(
        student_id="1001",
        attempt_number=2,
        timestamp="2026-09-02T09:00:00-04:00",
        answers=(
            (1, "A", True),
            (2, "A", False),
            (3, "BLANK", False),
            (4, "AMBIGUOUS", False),
        ),
        last_name="Doe",
        first_name="Jane",
    )
    second_student = _row(
        student_id="1002",
        attempt_number=1,
        timestamp="2026-09-01T10:00:00-04:00",
        answers=(
            (1, "B", False),
            (2, "B", True),
            (3, "C", True),
            (4, "D", True),
        ),
        last_name="Smith",
        first_name="John",
    )
    return older_high_score, recent_lower_score, second_student


def test_recent_display_selection_matches_overview_not_highest_score():
    older_high, recent_low, second = _history()

    selections = select_recent_display_attempts((older_high, recent_low, second))

    assert tuple(item.student_id for item in selections) == ("1001", "1002")
    assert selections[0].row == recent_low
    assert selections[0].attempt_count == 2
    assert selections[0].row.result.score == 1
    assert selections[1].row == second


def test_student_attempt_selection_preserves_every_attempt_chronologically():
    older_high, recent_low, second = _history()

    attempts = select_student_attempts(
        (recent_low, second, older_high),
        "1001",
    )

    assert attempts == (older_high, recent_low)


def test_student_detail_distinguishes_all_response_states_and_standards():
    _, recent_low, _ = _history()

    detail = analyze_student_attempt(
        recent_low,
        _assignment(),
        class_id="class1",
        attempt_count=2,
    )

    assert detail.student_id == "1001"
    assert detail.attempt_number == 2
    assert detail.attempt_count == 2
    assert detail.score == 1
    assert tuple(question.outcome for question in detail.questions) == (
        "correct",
        "incorrect",
        "blank",
        "ambiguous",
    )
    assert tuple(question.selected_answer for question in detail.questions) == (
        "A",
        "A",
        "BLANK",
        "AMBIGUOUS",
    )
    assert tuple(question.keyed_answer for question in detail.questions) == (
        "A",
        "B",
        "C",
        "D",
    )
    assert detail.questions[1].standard_ids == ("STD.A", "STD.B")

    by_standard = {item.standard_id: item for item in detail.standards}
    assert by_standard["STD.A"].correct == 1
    assert by_standard["STD.A"].responses == 2
    assert by_standard["STD.A"].percent_correct == 50
    assert by_standard["STD.A"].question_numbers == (1, 2)
    assert by_standard["STD.B"].correct == 0
    assert by_standard["STD.B"].responses == 2
    assert by_standard["STD.B"].percent_correct == 0

    assert detail.unaligned.correct == 0
    assert detail.unaligned.responses == 1
    assert detail.unaligned.question_numbers == (4,)


def test_class_analysis_uses_one_recent_attempt_and_reconciles_question_counts():
    history = _history()

    analysis = analyze_class_results(
        history,
        _assignment(),
        class_id="class1",
    )

    assert analysis.attempt_basis == ATTEMPT_DISPLAY_BASIS
    assert analysis.standards_basis == STANDARDS_ALIGNMENT_BASIS
    assert analysis.students_represented == 2
    assert tuple(student.attempt_number for student in analysis.students) == (2, 1)

    for question in analysis.questions:
        assert question.total == (
            question.correct
            + question.incorrect
            + question.blank
            + question.ambiguous
        )
        assert question.total == 2

    q1, q2, q3, q4 = analysis.questions
    assert (q1.correct, q1.incorrect, q1.blank, q1.ambiguous) == (1, 1, 0, 0)
    assert (q2.correct, q2.incorrect, q2.blank, q2.ambiguous) == (1, 1, 0, 0)
    assert (q3.correct, q3.incorrect, q3.blank, q3.ambiguous) == (1, 0, 1, 0)
    assert (q4.correct, q4.incorrect, q4.blank, q4.ambiguous) == (1, 0, 0, 1)
    assert tuple(item.response for item in q3.response_distribution) == (
        "A",
        "B",
        "C",
        "D",
        "BLANK",
        "AMBIGUOUS",
    )
    assert tuple(item.count for item in q3.response_distribution) == (0, 0, 1, 0, 1, 0)
    assert [item.response for item in q3.response_distribution if item.is_keyed_answer] == ["C"]


def test_class_standards_count_multi_standard_questions_once_per_standard():
    analysis = analyze_class_results(
        _history(),
        _assignment(),
        class_id="class1",
    )

    by_standard = {item.standard_id: item for item in analysis.standards}
    assert by_standard["STD.A"].question_numbers == (1, 2)
    assert by_standard["STD.A"].correct == 2
    assert by_standard["STD.A"].responses == 4
    assert by_standard["STD.A"].percent_correct == 50

    assert by_standard["STD.B"].question_numbers == (2, 3)
    assert by_standard["STD.B"].correct == 2
    assert by_standard["STD.B"].responses == 4
    assert by_standard["STD.B"].percent_correct == 50

    assert analysis.unaligned.question_numbers == (4,)
    assert analysis.unaligned.correct == 1
    assert analysis.unaligned.responses == 2
    assert analysis.unaligned.percent_correct == 50


def test_analysis_is_read_only_for_assignment_and_history():
    history = _history()
    assignment = _assignment()
    before_assignment = deepcopy(assignment)
    before_history = tuple(history)

    analyze_class_results(history, assignment, class_id="class1")

    assert assignment == before_assignment
    assert history == before_history


@pytest.mark.parametrize(
    ("correct", "responses", "expected"),
    (
        (0, 0, None),
        (0, 3, 0),
        (1, 8, 13),
        (2, 3, 67),
        (1, 2, 50),
        (3, 3, 100),
    ),
)
def test_percent_rounding_is_shared_deterministic_half_up(correct, responses, expected):
    assert PERCENT_ROUNDING_RULE == "nearest whole percent, halves rounded up"
    assert rounded_percent(correct, responses) == expected


def test_analysis_rejects_incompatible_result_identity():
    row = _row(
        student_id="1001",
        attempt_number=1,
        timestamp="2026-09-01T09:00:00-04:00",
        assignment_id="other_quiz",
        answers=(
            (1, "A", True),
            (2, "B", True),
            (3, "C", True),
            (4, "D", True),
        ),
    )

    with pytest.raises(ResultsAnalysisError, match="assignment identity"):
        analyze_class_results((row,), _assignment(), class_id="class1")


def test_analysis_rejects_special_response_marked_correct():
    row = _row(
        student_id="1001",
        attempt_number=1,
        timestamp="2026-09-01T09:00:00-04:00",
        answers=(
            (1, "BLANK", True),
            (2, "B", True),
            (3, "C", True),
            (4, "D", True),
        ),
    )

    with pytest.raises(ResultsAnalysisError, match="BLANK response cannot be marked correct"):
        analyze_class_results((row,), _assignment(), class_id="class1")
