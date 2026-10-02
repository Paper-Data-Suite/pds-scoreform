"""Interactive Student Detail menu tests for ScoreForm Issue #217 Slice 2."""

from scoreform.page_scoring import ScoredAnswer
from scoreform.results import ScoreFormRoutedResult, ScoreFormRoutedResultHistoryRow
from scoreform.results_analysis_menu import launch_student_detail_menu


def _assignment():
    return {
        "assignment_id": "quiz1",
        "question_count": 2,
        "choices": ["A", "B", "C", "D"],
        "answer_key": {1: "A", 2: "B"},
        "standards": {"1": ["STD.A"], "2": ["STD.A"]},
    }


def _row(*, attempt, timestamp, score, responses):
    answers = tuple(
        ScoredAnswer(number, selected, correct)
        for number, selected, correct in responses
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
        score,
        2,
        answers,
        source_file="plain_paper_manual_entry",
    )
    return ScoreFormRoutedResultHistoryRow(result, attempt, timestamp)


def _history():
    older_high = _row(
        attempt=1,
        timestamp="2026-09-01T09:00:00-04:00",
        score=2,
        responses=((1, "A", True), (2, "B", True)),
    )
    recent_low = _row(
        attempt=2,
        timestamp="2026-09-02T09:00:00-04:00",
        score=0,
        responses=((1, "B", False), (2, "BLANK", False)),
    )
    return older_high, recent_low


def _inputs(values):
    iterator = iter(values)

    def prompt(_message):
        return next(iterator)

    return prompt


def test_student_detail_defaults_to_recent_not_highest_attempt(capsys):
    code = launch_student_detail_menu(
        _history(),
        _assignment(),
        class_id="class1",
        clear_screen_fn=lambda: None,
        input_fn=_inputs(
            (
                "1",  # student
                "",   # most recent display attempt
                "B",  # back from detail
            )
        ),
    )

    assert code == 0
    output = capsys.readouterr().out
    assert "Attempt: 2 of 2" in output
    assert "Overall: 0 / 2" in output


def test_student_detail_allows_explicit_historical_attempt(capsys):
    code = launch_student_detail_menu(
        _history(),
        _assignment(),
        class_id="class1",
        clear_screen_fn=lambda: None,
        input_fn=_inputs(
            (
                "1",  # student
                "1",  # historical attempt
                "B",  # back from detail
            )
        ),
    )

    assert code == 0
    output = capsys.readouterr().out
    assert "Attempt: 1 of 2" in output
    assert "Overall: 2 / 2" in output


def test_student_detail_standard_drilldown_is_read_only_and_exact(capsys):
    history = _history()
    code = launch_student_detail_menu(
        history,
        _assignment(),
        class_id="class1",
        clear_screen_fn=lambda: None,
        input_fn=_inputs(
            (
                "1",  # student
                "",   # recent attempt
                "1",  # Standard Detail
                "1",  # STD.A
                "",   # return to detail
                "B",  # back
            )
        ),
    )

    assert code == 0
    output = capsys.readouterr().out
    assert "Standard: STD.A" in output
    assert "Q1" in output
    assert "Q2" in output
    assert history == _history()
