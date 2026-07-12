import csv
import json

from scoreform import assignment_workflows, menu_manual_entry


def _prepare_workspace(tmp_path):
    class_dir = tmp_path / "classes" / "class_a"
    assignment_dir = class_dir / "assignments" / "quiz"
    assignment_dir.mkdir(parents=True)
    (class_dir / "roster.csv").write_text(
        "class_id,student_id,last_name,first_name,period\n"
        "class_a,0001,Johnson,Mack,2\n"
        "class_a,0002,Brown,Taylor,2\n",
        encoding="utf-8",
    )
    (assignment_dir / "assignment.json").write_text(
        json.dumps({
            "assignment_id": "quiz",
            "title": "Coming-of-Age Quiz",
            "question_count": 3,
            "choices": ["A", "B", "C", "D"],
            "layout_id": "standard_15q_abcd_v1",
            "answer_key": {"1": "A", "2": "B", "3": "C"},
        }),
        encoding="utf-8",
    )
    return assignment_dir


def test_manual_entry_workflow_reprompts_writes_and_returns_to_students(
    tmp_path, monkeypatch, capsys
):
    assignment_dir = _prepare_workspace(tmp_path)
    responses = iter(["1", "1", "1", "E", "a", "blank", "amb", "yes", "b"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    assert menu_manual_entry.launch_manual_entry_menu() == 0
    with (assignment_dir / "results.csv").open(newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))

    assert len(rows) == 1
    assert rows[0]["student_id"] == "0001"
    assert rows[0]["Score"] == "1"
    assert rows[0]["Q2"] == "BLANK"
    assert rows[0]["Q3"] == "AMBIGUOUS"
    output = capsys.readouterr().out
    assert "Invalid response" in output
    assert "Review Plain-Paper Result" in output
    assert output.count("Select Student:") == 2
    assert "Result written for Johnson, Mack." in output


def test_manual_entry_cancel_writes_nothing(tmp_path, monkeypatch, capsys):
    assignment_dir = _prepare_workspace(tmp_path)
    responses = iter(["1", "1", "1", "q", "b"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    assert menu_manual_entry.launch_manual_entry_menu() == 0
    assert not (assignment_dir / "results.csv").exists()
    assert "Cancelled: result was not written." in capsys.readouterr().out


def test_manual_entry_declined_confirmation_writes_nothing(tmp_path, monkeypatch):
    assignment_dir = _prepare_workspace(tmp_path)
    responses = iter(["1", "1", "1", "A", "B", "C", "no", "b"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    assert menu_manual_entry.launch_manual_entry_menu() == 0
    assert not (assignment_dir / "results.csv").exists()


def test_assignment_menu_option_8_launches_manual_entry(monkeypatch, capsys):
    calls = []
    responses = iter(["8", "b"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))
    monkeypatch.setattr(
        assignment_workflows.menu_manual_entry,
        "launch_manual_entry_menu",
        lambda: calls.append(True) or 0,
    )

    assert assignment_workflows.launch_assignment_menu() == 0
    assert calls == [True]
    assert "8. Enter Plain-Paper Results" in capsys.readouterr().out


def test_assignment_menu_option_9_still_launches_scan_review(monkeypatch):
    calls = []
    responses = iter(["9", "b"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))
    monkeypatch.setattr(
        assignment_workflows.menu_scan_review,
        "launch_scan_review_menu",
        lambda: calls.append(True) or 0,
    )

    assert assignment_workflows.launch_assignment_menu() == 0
    assert calls == [True]
