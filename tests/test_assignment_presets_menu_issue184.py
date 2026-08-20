from __future__ import annotations

import json
from pathlib import Path

import pytest
from pds_core.routes import class_roster_path

from scoreform import assignment_workflows
from scoreform.assignment_presets import (
    assignment_preset_path,
    build_assignment_preset,
    commit_assignment_preset_mutation,
    load_assignment_preset,
    plan_create_assignment_preset,
)
from scoreform.menu_assignment_presets import (
    launch_assignment_presets_menu,
    prompt_apply_preset,
    prompt_create_preset_from_assignment,
    prompt_create_preset_manually,
    prompt_delete_preset,
    prompt_edit_preset,
    prompt_view_presets,
)
from scoreform.work_paths import scoreform_work_paths


def _write_source(
    root: Path,
    class_id: str = "english10_p2",
    assignment_id: str = "source_quiz",
) -> None:
    roster = class_roster_path(root, class_id)
    roster.parent.mkdir(parents=True, exist_ok=True)
    roster.write_text(
        "\n".join(
            [
                "class_id,student_id,last_name,first_name,period",
                f"{class_id},student_1,Student1,Synthetic,2",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    paths = scoreform_work_paths(root, class_id, assignment_id)
    paths.work_root.mkdir(parents=True)
    paths.assignment_path.write_text(
        json.dumps(
            {
                "assignment_id": assignment_id,
                "title": "Source Quiz",
                "question_count": 2,
                "choices": ["A", "B", "C", "D"],
                "layout_id": "standard_15q_abcd_v1",
                "answer_key": {"1": "A", "2": "B"},
                "standards": {"1": [], "2": []},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_roster(root: Path, class_id: str, period: str = "4") -> None:
    path = class_roster_path(root, class_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "class_id,student_id,last_name,first_name,period",
                f"{class_id},student_1,Student1,Synthetic,{period}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _save_preset(root: Path, preset_id: str = "short_quiz") -> None:
    preset = build_assignment_preset(
        preset_id=preset_id,
        label="Short Quiz",
        question_count=2,
        choices=["A", "B", "C", "D"],
        layout_id="standard_15q_abcd_v1",
        answer_key={"1": "A", "2": "B"},
        standards={"1": [], "2": []},
    )
    plan = plan_create_assignment_preset(root, preset)
    commit_assignment_preset_mutation(root, plan)


@pytest.fixture
def workspace_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(
        "scoreform.menu_assignment_presets.workspace.get_scoreform_workspace_root",
        lambda: str(tmp_path),
    )
    return tmp_path


def test_assignment_management_exposes_temporary_preset_option_14(
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    responses = iter(["14", "b", "b"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))
    monkeypatch.setattr(assignment_workflows, "clear_screen", lambda: None)
    monkeypatch.setattr(assignment_workflows, "pause_for_user", lambda: None)

    result = assignment_workflows.launch_assignment_menu()

    assert result == 0
    output = capsys.readouterr().out
    assert "14. Assessment setup presets" in output


def test_preset_submenu_lists_all_bounded_teacher_tasks(
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    monkeypatch.setattr("builtins.input", lambda _prompt="": "b")
    monkeypatch.setattr(
        "scoreform.menu_assignment_presets.clear_screen",
        lambda: None,
    )

    result = launch_assignment_presets_menu()

    assert result == 0
    output = capsys.readouterr().out
    assert "Create preset from an assignment" in output
    assert "Create preset manually" in output
    assert "View presets" in output
    assert "Edit preset" in output
    assert "Delete preset" in output
    assert "Create assignment from preset" in output


def test_create_from_assignment_can_cancel_before_mutation(
    workspace_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_source(workspace_root)
    responses = iter(["1", "1", "b"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))
    monkeypatch.setattr(
        "scoreform.menu_assignment_presets.clear_screen",
        lambda: None,
    )

    result = prompt_create_preset_from_assignment()

    assert result == 0
    assert not assignment_preset_path(workspace_root, "short_quiz").exists()


def test_create_from_assignment_requires_save_confirmation(
    workspace_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_source(workspace_root)
    responses = iter(["1", "1", "short_quiz", "", "NO"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))
    monkeypatch.setattr(
        "scoreform.menu_assignment_presets.clear_screen",
        lambda: None,
    )

    result = prompt_create_preset_from_assignment()

    assert result == 0
    assert not assignment_preset_path(workspace_root, "short_quiz").exists()


def test_create_from_assignment_saves_independent_preset(
    workspace_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_source(workspace_root)
    source = scoreform_work_paths(
        workspace_root,
        "english10_p2",
        "source_quiz",
    )
    source_before = source.assignment_path.read_bytes()
    responses = iter(["1", "1", "short_quiz", "", "SAVE"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))
    monkeypatch.setattr(
        "scoreform.menu_assignment_presets.clear_screen",
        lambda: None,
    )

    result = prompt_create_preset_from_assignment()

    assert result == 0
    snapshot = load_assignment_preset(workspace_root, "short_quiz")
    assert snapshot.preset["label"] == "Source Quiz"
    assert "assignment_id" not in snapshot.preset
    assert source.assignment_path.read_bytes() == source_before


def test_manual_preset_creation_does_not_require_class(
    workspace_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = iter(
        [
            "manual_quiz",
            "Manual Quiz",
            "1",
            "2",
            "A",
            "B",
            "SAVE",
        ]
    )
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))
    monkeypatch.setattr(
        "scoreform.menu_assignment_presets.clear_screen",
        lambda: None,
    )
    monkeypatch.setattr(
        assignment_workflows,
        "prompt_standards_alignment",
        lambda _root, question_count: (
            None,
            {str(number): [] for number in range(1, question_count + 1)},
        ),
    )

    result = prompt_create_preset_manually()

    assert result == 0
    snapshot = load_assignment_preset(workspace_root, "manual_quiz")
    assert snapshot.preset["question_count"] == 2
    assert snapshot.preset["answer_key"] == {"1": "A", "2": "B"}


def test_view_preset_shows_complete_key(
    workspace_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    _save_preset(workspace_root)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "1")
    monkeypatch.setattr(
        "scoreform.menu_assignment_presets.clear_screen",
        lambda: None,
    )

    result = prompt_view_presets()

    assert result == 0
    output = capsys.readouterr().out
    assert "Q1: A" in output
    assert "Q2: B" in output


def test_delete_preset_can_cancel_without_mutation(
    workspace_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _save_preset(workspace_root)
    responses = iter(["1", "NO"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))
    monkeypatch.setattr(
        "scoreform.menu_assignment_presets.clear_screen",
        lambda: None,
    )

    result = prompt_delete_preset()

    assert result == 0
    assert assignment_preset_path(workspace_root, "short_quiz").is_file()


def test_delete_preset_requires_exact_delete_confirmation(
    workspace_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _save_preset(workspace_root)
    responses = iter(["1", "DELETE"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))
    monkeypatch.setattr(
        "scoreform.menu_assignment_presets.clear_screen",
        lambda: None,
    )

    result = prompt_delete_preset()

    assert result == 0
    assert not assignment_preset_path(workspace_root, "short_quiz").exists()


def test_edit_preset_label_uses_update_confirmation(
    workspace_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _save_preset(workspace_root)
    responses = iter(["1", "1", "Updated Quiz", "5", "UPDATE"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))
    monkeypatch.setattr(
        "scoreform.menu_assignment_presets.clear_screen",
        lambda: None,
    )
    monkeypatch.setattr(
        "scoreform.menu_assignment_presets.pause_for_user",
        lambda: None,
    )

    result = prompt_edit_preset()

    assert result == 0
    snapshot = load_assignment_preset(workspace_root, "short_quiz")
    assert snapshot.preset["label"] == "Updated Quiz"


def test_apply_preset_cancels_before_create_confirmation(
    workspace_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _save_preset(workspace_root)
    _write_roster(workspace_root, "english10_p4")
    responses = iter(
        ["1", "1", "unit_2_quiz", "Unit 2 Quiz", "1", "NO"]
    )
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))
    monkeypatch.setattr(
        "scoreform.menu_assignment_presets.clear_screen",
        lambda: None,
    )

    result = prompt_apply_preset()

    assert result == 0
    target = scoreform_work_paths(
        workspace_root,
        "english10_p4",
        "unit_2_quiz",
    )
    assert not target.work_root.exists()


def test_apply_preset_creates_fresh_assignment_with_create_confirmation(
    workspace_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _save_preset(workspace_root)
    _write_roster(workspace_root, "english10_p4")
    responses = iter(
        ["1", "1", "unit_2_quiz", "Unit 2 Quiz", "1", "CREATE"]
    )
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))
    monkeypatch.setattr(
        "scoreform.menu_assignment_presets.clear_screen",
        lambda: None,
    )

    result = prompt_apply_preset()

    assert result == 0
    target = scoreform_work_paths(
        workspace_root,
        "english10_p4",
        "unit_2_quiz",
    )
    assert target.assignment_path.is_file()
    assert assignment_preset_path(workspace_root, "short_quiz").is_file()


def test_apply_preset_supports_multiple_classes(
    workspace_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _save_preset(workspace_root)
    _write_roster(workspace_root, "english10_p4")
    _write_roster(workspace_root, "english10_p6", "6")
    responses = iter(
        ["1", "1,2", "common_quiz", "Common Quiz", "1", "CREATE"]
    )
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))
    monkeypatch.setattr(
        "scoreform.menu_assignment_presets.clear_screen",
        lambda: None,
    )

    result = prompt_apply_preset()

    assert result == 0
    for class_id in ("english10_p4", "english10_p6"):
        assert scoreform_work_paths(
            workspace_root,
            class_id,
            "common_quiz",
        ).assignment_path.is_file()

def test_manual_preset_answer_prompt_uses_back_word_not_valid_b_answer(
    workspace_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = iter(
        [
            "cancelled_quiz",
            "Cancelled Quiz",
            "1",
            "2",
            "A",
            "BACK",
        ]
    )
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))
    monkeypatch.setattr(
        "scoreform.menu_assignment_presets.clear_screen",
        lambda: None,
    )

    result = prompt_create_preset_manually()

    assert result == 0
    assert not assignment_preset_path(
        workspace_root,
        "cancelled_quiz",
    ).exists()
