"""Interactive export workflow tests for ScoreForm Issue #217 Slice 7."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from scoreform.page_scoring import ScoredAnswer
from scoreform.results import (
    ScoreFormRoutedResult,
    ScoreFormRoutedResultHistoryRow,
)
from scoreform.results_report_workflow import launch_results_export_menu
from scoreform.work_paths import scoreform_work_paths

GENERATED = datetime(2026, 9, 30, 23, 45, 0, tzinfo=timezone.utc)


def _assignment():
    return {
        "assignment_id": "quiz1",
        "title": "Synthetic Assessment",
        "question_count": 3,
        "choices": ["A", "B", "C", "D"],
        "answer_key": {1: "A", 2: "B", 3: "C"},
        "standards": {
            "1": ["STD.A"],
            "2": ["STD.B"],
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
        3,
        scored,
        source_file="plain_paper_manual_entry",
    )
    return ScoreFormRoutedResultHistoryRow(result, attempt, timestamp)


def _history():
    return (
        _row(
            student_id="1001",
            attempt=1,
            timestamp="2026-09-01T09:00:00+00:00",
            answers=(
                (1, "A", True),
                (2, "B", True),
                (3, "C", True),
            ),
            last_name="Doe",
            first_name="Jane",
        ),
        _row(
            student_id="1001",
            attempt=2,
            timestamp="2026-09-02T09:00:00+00:00",
            answers=(
                (1, "B", False),
                (2, "B", True),
                (3, "BLANK", False),
            ),
            last_name="Doe",
            first_name="Jane",
        ),
        _row(
            student_id="1002",
            attempt=1,
            timestamp="2026-09-01T10:00:00+00:00",
            answers=(
                (1, "A", True),
                (2, "AMBIGUOUS", False),
                (3, "D", False),
            ),
            last_name="Smith",
            first_name="John",
        ),
    )


def _workspace(tmp_path):
    paths = scoreform_work_paths(tmp_path, "class1", "quiz1")
    paths.work_root.mkdir(parents=True)
    paths.assignment_path.write_text("assignment sentinel\n", encoding="utf-8")
    paths.results_path.write_text("results sentinel\n", encoding="utf-8")
    return paths


def _input(values):
    iterator = iter(values)
    return lambda _prompt: next(iterator)


def test_cancel_at_confirmation_writes_nothing(tmp_path, capsys):
    paths = _workspace(tmp_path)
    before = {path.relative_to(tmp_path) for path in tmp_path.rglob("*")}

    result = launch_results_export_menu(
        _history(),
        _assignment(),
        class_id="class1",
        assignment_id="quiz1",
        workspace_root=tmp_path,
        input_fn=_input(("1", "3", "BACK")),
        clear_screen_fn=lambda: None,
        now_fn=lambda: GENERATED,
    )

    after = {path.relative_to(tmp_path) for path in tmp_path.rglob("*")}
    assert result == 0
    assert after == before
    assert paths.assignment_path.read_text(encoding="utf-8") == "assignment sentinel\n"
    assert paths.results_path.read_text(encoding="utf-8") == "results sentinel\n"
    assert "Cancelled: report was not created." in capsys.readouterr().out


def test_class_pdf_export_writes_one_privacy_minimized_report(tmp_path, capsys):
    paths = _workspace(tmp_path)

    result = launch_results_export_menu(
        _history(),
        _assignment(),
        class_id="class1",
        assignment_id="quiz1",
        workspace_root=tmp_path,
        input_fn=_input(("1", "3", "GENERATE")),
        clear_screen_fn=lambda: None,
        now_fn=lambda: GENERATED,
    )

    expected_dir = (
        paths.exports_dir
        / "results_analysis"
        / "class_analysis_20260930T234500Z"
    )
    assert result == 0
    assert expected_dir.is_dir()
    files = tuple(expected_dir.iterdir())
    assert [path.name for path in files] == ["results_analysis.pdf"]
    assert files[0].read_bytes().startswith(b"%PDF-")
    assert "Doe" not in expected_dir.name
    assert "Jane" not in expected_dir.name
    output = capsys.readouterr().out
    assert "Results Report Created" in output
    lowered = output.lower()
    assert re.search(r"\bsent\b", lowered) is None
    assert re.search(r"\bshared\b", lowered) is None
    assert re.search(r"\bdelivered\b", lowered) is None
    assert re.search(r"\breceived\b", lowered) is None
    assert re.search(r"\bapproved\b", lowered) is None


def test_student_json_export_can_select_historical_attempt(tmp_path):
    paths = _workspace(tmp_path)

    result = launch_results_export_menu(
        _history(),
        _assignment(),
        class_id="class1",
        assignment_id="quiz1",
        workspace_root=tmp_path,
        input_fn=_input(
            (
                "2",
                "1",
                "1",
                "2",
                "GENERATE",
            )
        ),
        clear_screen_fn=lambda: None,
        now_fn=lambda: GENERATED,
    )

    expected = (
        paths.exports_dir
        / "results_analysis"
        / "student_detail_20260930T234500Z"
        / "results_analysis.json"
    )
    assert result == 0
    payload = json.loads(expected.read_text(encoding="utf-8"))
    assert payload["scope"] == "student_detail"
    assert payload["student_detail"]["student_id"] == "1001"
    assert payload["student_detail"]["attempt_number"] == 1
    assert payload["student_detail"]["score"] == 3


def test_class_csv_export_creates_only_bounded_report_set(tmp_path):
    paths = _workspace(tmp_path)

    result = launch_results_export_menu(
        _history(),
        _assignment(),
        class_id="class1",
        assignment_id="quiz1",
        workspace_root=tmp_path,
        input_fn=_input(("1", "1", "GENERATE")),
        clear_screen_fn=lambda: None,
        now_fn=lambda: GENERATED,
    )

    expected_dir = (
        paths.exports_dir
        / "results_analysis"
        / "class_analysis_20260930T234500Z"
    )
    assert result == 0
    assert sorted(path.name for path in expected_dir.iterdir()) == [
        "assignment_overview.csv",
        "question_analysis.csv",
        "report_metadata.csv",
        "response_distribution.csv",
        "standards_analysis.csv",
        "unaligned_analysis.csv",
    ]
    assert not (expected_dir / "student_responses.csv").exists()


def test_back_from_scope_selection_writes_nothing(tmp_path):
    _workspace(tmp_path)
    before = {path.relative_to(tmp_path) for path in tmp_path.rglob("*")}

    result = launch_results_export_menu(
        _history(),
        _assignment(),
        class_id="class1",
        assignment_id="quiz1",
        workspace_root=tmp_path,
        input_fn=_input(("B",)),
        clear_screen_fn=lambda: None,
        now_fn=lambda: GENERATED,
    )

    assert result == 0
    assert {path.relative_to(tmp_path) for path in tmp_path.rglob("*")} == before
