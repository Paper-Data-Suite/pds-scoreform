from __future__ import annotations

import json
from pathlib import Path

import pytest
from pds_core.routes import class_roster_path

from scoreform import assignment_workflows
from scoreform.menu_assignment_copy import prompt_copy_assignment
from scoreform.work_paths import scoreform_work_paths


def _assignment(assignment_id: str = "unit_1_quiz") -> dict[str, object]:
    return {
        "assignment_id": assignment_id,
        "title": "Unit 1 Quiz",
        "question_count": 3,
        "choices": ["A", "B", "C", "D"],
        "layout_id": "standard_15q_abcd_v1",
        "answer_key": {"1": "A", "2": "B", "3": "C"},
        "standards": {"1": [], "2": [], "3": []},
    }


def _write_roster(root: Path, class_id: str, period: str) -> Path:
    path = class_roster_path(root, class_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "class_id,student_id,last_name,first_name,period",
                f"{class_id},student_1,Synthetic,One,{period}",
                f"{class_id},student_2,Synthetic,Two,{period}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _write_source(root: Path) -> Path:
    paths = scoreform_work_paths(root, "english10_p2", "unit_1_quiz")
    paths.work_root.mkdir(parents=True)
    paths.assignment_path.write_text(
        json.dumps(_assignment(), indent=2) + "\n",
        encoding="utf-8",
    )
    return paths.assignment_path


def _workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_roster(tmp_path, "english10_p2", "2")
    _write_roster(tmp_path, "english10_p4", "4")
    _write_source(tmp_path)
    monkeypatch.setattr(
        "scoreform.menu_assignment_copy.workspace.get_scoreform_workspace_root",
        lambda: tmp_path,
    )
    monkeypatch.setattr(
        "scoreform.menu_assignment_copy.clear_screen",
        lambda: None,
    )


def test_teacher_copy_workflow_reviews_complete_definition_and_creates_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _workspace(tmp_path, monkeypatch)
    answers = iter(
        [
            "1",     # source class english10_p2
            "1",     # source assignment unit_1_quiz
            "2",     # target class english10_p4
            "",      # keep assignment_id
            "",      # keep title
            "COPY",  # explicit commit
        ]
    )
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    status = prompt_copy_assignment()

    assert status == 0
    target = scoreform_work_paths(tmp_path, "english10_p4", "unit_1_quiz")
    assert target.assignment_path.is_file()
    assert not target.results_path.exists()
    assert not target.answer_sheets_dir.exists()
    assert not target.exports_dir.exists()
    assert not (target.work_root / "routes").exists()

    output = capsys.readouterr().out
    assert "Review Assignment Copy" in output
    assert "Q1: A" in output
    assert "Q2: B" in output
    assert "Q3: C" in output
    assert "students: 2" in output
    assert "periods: 4" in output
    assert "students or roster state" in output
    assert "Academic Work Registration" in output
    assert "Created 1 fresh assignment copy." in output
    assert "student_1" not in output
    assert "Synthetic" not in output


@pytest.mark.parametrize(
    "answers",
    [
        ["B"],
        ["1", "B"],
        ["1", "1", "B"],
        ["1", "1", "2", "B"],
        ["1", "1", "2", "", "B"],
        ["1", "1", "2", "", "", ""],
        ["1", "1", "2", "", "", "not-copy"],
    ],
)
def test_teacher_cancellation_before_copy_writes_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    answers: list[str],
) -> None:
    _workspace(tmp_path, monkeypatch)
    provided = iter(answers)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(provided))

    assert prompt_copy_assignment() == 0

    target = scoreform_work_paths(tmp_path, "english10_p4", "unit_1_quiz")
    assert not target.work_root.exists()


def test_teacher_copy_workflow_allows_same_class_with_new_assignment_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _workspace(tmp_path, monkeypatch)
    answers = iter(
        [
            "1",
            "1",
            "1",
            "unit_1_quiz_makeup",
            "Unit 1 Quiz - Makeup",
            "COPY",
        ]
    )
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    assert prompt_copy_assignment() == 0

    target = scoreform_work_paths(
        tmp_path,
        "english10_p2",
        "unit_1_quiz_makeup",
    )
    assert target.assignment_path.is_file()
    persisted = json.loads(target.assignment_path.read_text(encoding="utf-8"))
    assert persisted["title"] == "Unit 1 Quiz - Makeup"


def test_teacher_copy_workflow_rejects_exact_source_as_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _workspace(tmp_path, monkeypatch)
    answers = iter(["1", "1", "1", "", ""])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    assert prompt_copy_assignment() == 1

    output = capsys.readouterr().out
    assert "own copy target" in output
    source = scoreform_work_paths(tmp_path, "english10_p2", "unit_1_quiz")
    assert source.assignment_path.is_file()


def test_teacher_copy_workflow_collision_fails_without_overwrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _workspace(tmp_path, monkeypatch)
    target = scoreform_work_paths(tmp_path, "english10_p4", "unit_1_quiz")
    target.work_root.mkdir(parents=True)
    marker = target.work_root / "keep.txt"
    marker.write_text("existing", encoding="utf-8")

    answers = iter(["1", "1", "2", "", ""])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    assert prompt_copy_assignment() == 1

    assert "work root already exists" in capsys.readouterr().out
    assert marker.read_text(encoding="utf-8") == "existing"
    assert not target.assignment_path.exists()


def test_assignment_menu_exposes_copy_without_renumbering_existing_actions(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    observed: list[str] = []
    inputs = iter(["13", "B"])

    monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
    monkeypatch.setattr(assignment_workflows, "clear_screen", lambda: None)
    monkeypatch.setattr(assignment_workflows, "pause_for_user", lambda: None)
    monkeypatch.setattr(
        assignment_workflows,
        "prompt_copy_assignment",
        lambda: observed.append("copy") or 0,
    )

    assert assignment_workflows.launch_assignment_menu() == 0

    assert observed == ["copy"]
    output = capsys.readouterr().out
    assert "1. Create an assignment" in output
    assert "12. Academic Result Publications" in output
    assert "13. Copy an assignment" in output
