"""Class analysis menu tests for ScoreForm Issue #217 Slice 3."""

from scoreform.page_scoring import ScoredAnswer
from scoreform.results import ScoreFormRoutedResult, ScoreFormRoutedResultHistoryRow
from scoreform.results_analysis_menu import (
    launch_class_standards_analysis_menu,
    launch_question_analysis_menu,
)


def _assignment():
    return {
        "assignment_id": "quiz1",
        "question_count": 2,
        "choices": ["A", "B", "C", "D"],
        "answer_key": {1: "A", 2: "B"},
        "standards": {
            "1": ["STD.A"],
            "2": ["STD.A", "STD.B"],
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
        2,
        scored,
        source_file="plain_paper_manual_entry",
    )
    return ScoreFormRoutedResultHistoryRow(
        result,
        1,
        "2026-09-01T09:00:00-04:00",
    )


def _history():
    return (
        _row("1001", ((1, "A", True), (2, "A", False))),
        _row("1002", ((1, "B", False), (2, "B", True))),
    )


def _inputs(values):
    iterator = iter(values)

    def prompt(_message):
        return next(iterator)

    return prompt


def test_question_analysis_drills_into_selected_question(capsys):
    code = launch_question_analysis_menu(
        _history(),
        _assignment(),
        class_id="class1",
        clear_screen_fn=lambda: None,
        input_fn=_inputs(
            (
                "2",
                "",
                "B",
            )
        ),
    )

    assert code == 0
    output = capsys.readouterr().out
    assert "Question Analysis" in output
    assert "Q2" in output
    assert "Correct answer: B" in output
    assert "Response" in output


def test_standards_analysis_drills_into_selected_standard(capsys):
    code = launch_class_standards_analysis_menu(
        _history(),
        _assignment(),
        class_id="class1",
        clear_screen_fn=lambda: None,
        input_fn=_inputs(
            (
                "1",
                "",
                "B",
            )
        ),
    )

    assert code == 0
    output = capsys.readouterr().out
    assert "Standards Analysis" in output
    assert "Standard: STD.A" in output
    assert "Q1" in output
    assert "Q2" in output
