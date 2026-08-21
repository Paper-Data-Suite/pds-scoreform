from __future__ import annotations

import json
from pathlib import Path

import pytest
from pds_core.routes import class_roster_path
from pds_core.standards import StandardDefinition, StandardsLibrary, StandardsProfile

from scoreform import assignment_workflows
from scoreform.assignment import load_assignment
from scoreform.assignment_presets import (
    assignment_preset_path,
    build_assignment_preset,
    commit_assignment_preset_mutation,
    load_assignment_preset,
    plan_create_assignment_preset,
)
from scoreform.menu_assignment_presets import (
    prompt_apply_preset,
    prompt_create_preset_manually,
    prompt_edit_preset,
)
from scoreform.work_paths import scoreform_work_paths


def _standards_library() -> StandardsLibrary:
    return StandardsLibrary(
        standards=(
            StandardDefinition(
                standard_id="nj_ela_2023_rl_cr_9_10_1",
                code="RL.CR.9-10.1",
                source="NJSLS-ELA 2023",
                short_name="Close Reading Evidence",
                description="Cite strong and thorough textual evidence.",
            ),
        ),
        profiles=(
            StandardsProfile(
                profile_id="english10_2023_njsls",
                standards=("nj_ela_2023_rl_cr_9_10_1",),
            ),
        ),
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


def _write_roster(root: Path, class_id: str = "english10_p4") -> None:
    path = class_roster_path(root, class_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "class_id,student_id,last_name,first_name,period",
                f"{class_id},student_1,Student1,Synthetic,4",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _write_existing_assignment(root: Path) -> tuple[Path, bytes]:
    paths = scoreform_work_paths(root, "english10_p4", "existing_quiz")
    paths.work_root.mkdir(parents=True, exist_ok=True)
    data = (
        json.dumps(
            {
                "assignment_id": "existing_quiz",
                "title": "Existing Quiz",
                "question_count": 2,
                "choices": ["A", "B", "C", "D"],
                "layout_id": "standard_15q_abcd_v1",
                "answer_key": {"1": "A", "2": "B"},
                "standards": {"1": [], "2": []},
            },
            indent=2,
        )
        + "\n"
    ).encode("utf-8")
    paths.assignment_path.write_bytes(data)
    return paths.assignment_path, data


@pytest.fixture
def workspace_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(
        "scoreform.menu_assignment_presets.workspace.get_scoreform_workspace_root",
        lambda: str(tmp_path),
    )
    monkeypatch.setattr(
        "scoreform.menu_assignment_presets.clear_screen",
        lambda: None,
    )
    monkeypatch.setattr(
        "scoreform.menu_assignment_presets.pause_for_user",
        lambda: None,
    )
    monkeypatch.setattr(assignment_workflows, "clear_screen", lambda: None)
    return tmp_path


def test_manual_preset_creation_uses_shared_bulk_answer_key_entry(
    workspace_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        assignment_workflows,
        "prompt_standards_alignment",
        lambda _root, question_count: (
            None,
            {str(number): [] for number in range(1, question_count + 1)},
        ),
    )
    responses = iter(
        [
            "bulk_manual",
            "Bulk Manual",
            "1",
            "3",
            "1",
            "a b c",
            "USE",
            "SAVE",
        ]
    )
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    assert prompt_create_preset_manually() == 0

    snapshot = load_assignment_preset(workspace_root, "bulk_manual")
    assert snapshot.preset["answer_key"] == {"1": "A", "2": "B", "3": "C"}
    output = capsys.readouterr().out
    assert "Complete normalized answer key:" in output
    assert "Q1: A" in output
    assert "Q2: B" in output
    assert "Q3: C" in output


def test_bulk_preset_answer_edit_does_not_change_existing_assignments(
    workspace_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _save_preset(workspace_root)
    existing_path, existing_before = _write_existing_assignment(workspace_root)
    responses = iter(
        [
            "1",  # select preset
            "2",  # edit answer key
            "1",  # paste complete key
            "d c",
            "USE",
            "5",  # save preset changes
            "UPDATE",
        ]
    )
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    assert prompt_edit_preset() == 0

    snapshot = load_assignment_preset(workspace_root, "short_quiz")
    assert snapshot.preset["answer_key"] == {"1": "D", "2": "C"}
    assert existing_path.read_bytes() == existing_before


def test_bulk_preset_standards_edit_uses_current_core_profile(
    workspace_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _save_preset(workspace_root)
    library = _standards_library()
    monkeypatch.setattr(
        "scoreform.menu_assignment_presets._load_optional_standards_library",
        lambda _root: (library, None),
    )
    monkeypatch.setattr(
        assignment_workflows,
        "_load_selection_library",
        lambda _root: library,
    )
    responses = iter(
        [
            "1",  # select preset
            "3",  # edit standards alignment
            "1",  # paste complete alignment
            "1",  # choose a Core profile
            "1",  # select profile
            "1 = nj_ela_2023_rl_cr_9_10_1; 2 = -",
            "USE",
            "5",  # save preset changes
            "UPDATE",
        ]
    )
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    assert prompt_edit_preset() == 0

    snapshot = load_assignment_preset(
        workspace_root,
        "short_quiz",
        standards_library=library,
        require_current_standards=True,
    )
    assert snapshot.preset["standards_profile_id"] == "english10_2023_njsls"
    assert snapshot.preset["standards"] == {
        "1": ["nj_ela_2023_rl_cr_9_10_1"],
        "2": [],
    }


def test_preset_application_bulk_edits_stage_only_until_create(
    workspace_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _save_preset(workspace_root)
    _write_roster(workspace_root)
    library = _standards_library()
    preset_before = assignment_preset_path(workspace_root, "short_quiz").read_bytes()
    monkeypatch.setattr(
        "scoreform.menu_assignment_presets._load_optional_standards_library",
        lambda _root: (library, None),
    )
    monkeypatch.setattr(
        assignment_workflows,
        "_load_selection_library",
        lambda _root: library,
    )
    responses = iter(
        [
            "1",  # select preset
            "1",  # select target class
            "unit_2_quiz",
            "Unit 2 Quiz",
            "2",  # edit staged assignment
            "2",  # edit answer key
            "1",  # paste complete key
            "d c",
            "USE",
            "3",  # edit standards alignment
            "1",  # paste complete alignment
            "1",  # choose a Core profile
            "1",  # select profile
            "1 = nj_ela_2023_rl_cr_9_10_1; 2 = -",
            "USE",
            "4",  # done editing staged assignment
            "CREATE",
        ]
    )
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    assert prompt_apply_preset() == 0

    target = scoreform_work_paths(workspace_root, "english10_p4", "unit_2_quiz")
    assignment = load_assignment(target.assignment_path)
    assert assignment is not None
    assert assignment["answer_key"] == {1: "D", 2: "C"}
    assert assignment["standards_profile_id"] == "english10_2023_njsls"
    assert assignment["standards"] == {
        "1": ["nj_ela_2023_rl_cr_9_10_1"],
        "2": [],
    }
    assert assignment_preset_path(workspace_root, "short_quiz").read_bytes() == preset_before
