from __future__ import annotations

import json
from pathlib import Path

from pds_core.routes import class_roster_path

from scoreform.assignment_presets import (
    assignment_preset_collection_dir,
    assignment_preset_path,
    load_assignment_preset,
)
from scoreform.cli import main
from scoreform.cli_assignment_presets import run_assignment_preset
from scoreform.work_paths import scoreform_work_paths


def _assignment(assignment_id: str = "source_quiz") -> dict[str, object]:
    return {
        "assignment_id": assignment_id,
        "title": "Source Quiz",
        "question_count": 3,
        "choices": ["A", "B", "C", "D"],
        "layout_id": "standard_15q_abcd_v1",
        "answer_key": {"1": "A", "2": "B", "3": "C"},
        "standards": {"1": [], "2": [], "3": []},
    }


def _write_source(
    root: Path,
    class_id: str = "english10_p2",
    assignment_id: str = "source_quiz",
) -> Path:
    paths = scoreform_work_paths(root, class_id, assignment_id)
    paths.work_root.mkdir(parents=True)
    paths.assignment_path.write_text(
        json.dumps(_assignment(assignment_id), indent=2) + "\n",
        encoding="utf-8",
    )
    return paths.assignment_path


def _write_roster(root: Path, class_id: str, period: str = "4") -> Path:
    path = class_roster_path(root, class_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "class_id,student_id,last_name,first_name,period",
                f"{class_id},student_1,Student1,Synthetic,{period}",
                f"{class_id},student_2,Student2,Synthetic,{period}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _save_preset(root: Path) -> None:
    _write_source(root)
    result = run_assignment_preset(
        [
            "save",
            "--preset-id",
            "short_quiz",
            "--source-class-id",
            "english10_p2",
            "--source-assignment-id",
            "source_quiz",
            "--apply",
        ],
        workspace_root=root,
    )
    assert result == 0


def test_preset_cli_help_is_dispatched_from_top_level(capsys) -> None:
    result = main(["preset", "--help"], default_to_menu=False)

    assert result == 0
    output = capsys.readouterr().out
    assert "scoreform preset list" in output
    assert "scoreform preset apply" in output


def test_preset_list_empty_is_read_only(tmp_path: Path, capsys) -> None:
    result = run_assignment_preset(["list"], workspace_root=tmp_path)

    assert result == 0
    assert not assignment_preset_collection_dir(tmp_path).exists()
    assert "(none)" in capsys.readouterr().out


def test_preset_save_plan_only_mutates_nothing(tmp_path: Path, capsys) -> None:
    source_path = _write_source(tmp_path)
    source_before = source_path.read_bytes()

    result = run_assignment_preset(
        [
            "save",
            "--preset-id",
            "short_quiz",
            "--source-class-id",
            "english10_p2",
            "--source-assignment-id",
            "source_quiz",
        ],
        workspace_root=tmp_path,
    )

    assert result == 0
    assert source_path.read_bytes() == source_before
    assert not assignment_preset_collection_dir(tmp_path).exists()
    output = capsys.readouterr().out
    assert "Mode: PLAN ONLY" in output
    assert "No changes were made." in output


def test_preset_save_apply_creates_exact_preset(tmp_path: Path, capsys) -> None:
    _write_source(tmp_path)

    result = run_assignment_preset(
        [
            "save",
            "--preset-id",
            "short_quiz",
            "--source-class-id",
            "english10_p2",
            "--source-assignment-id",
            "source_quiz",
            "--label",
            "Reusable Short Quiz",
            "--apply",
        ],
        workspace_root=tmp_path,
    )

    assert result == 0
    snapshot = load_assignment_preset(tmp_path, "short_quiz")
    assert snapshot.preset["label"] == "Reusable Short Quiz"
    assert "assignment_id" not in snapshot.preset
    assert "Saved assessment setup preset." in capsys.readouterr().out


def test_preset_show_prints_complete_configuration(tmp_path: Path, capsys) -> None:
    _save_preset(tmp_path)
    capsys.readouterr()

    result = run_assignment_preset(
        ["show", "--preset-id", "short_quiz"],
        workspace_root=tmp_path,
    )

    assert result == 0
    output = capsys.readouterr().out
    assert "preset_id: short_quiz" in output
    assert "Q1: A" in output
    assert "Q3: C" in output
    assert "Q1: (unaligned)" in output


def test_preset_list_reports_saved_preset(tmp_path: Path, capsys) -> None:
    _save_preset(tmp_path)
    capsys.readouterr()

    result = run_assignment_preset(["list"], workspace_root=tmp_path)

    assert result == 0
    assert "short_quiz: Source Quiz" in capsys.readouterr().out


def test_preset_apply_plan_only_creates_no_target(tmp_path: Path, capsys) -> None:
    _save_preset(tmp_path)
    _write_roster(tmp_path, "english10_p4")
    capsys.readouterr()

    result = run_assignment_preset(
        [
            "apply",
            "--preset-id",
            "short_quiz",
            "--target-assignment-id",
            "unit_2_quiz",
            "--title",
            "Unit 2 Quiz",
            "--target-class-id",
            "english10_p4",
        ],
        workspace_root=tmp_path,
    )

    assert result == 0
    target = scoreform_work_paths(tmp_path, "english10_p4", "unit_2_quiz")
    assert not target.work_root.exists()
    output = capsys.readouterr().out
    assert "Mode: PLAN ONLY" in output
    assert "Q1: A" in output
    assert "No changes were made." in output


def test_preset_apply_supports_multiple_target_classes(tmp_path: Path, capsys) -> None:
    _save_preset(tmp_path)
    for class_id in ("english10_p4", "english10_p6"):
        _write_roster(tmp_path, class_id)
    capsys.readouterr()

    result = run_assignment_preset(
        [
            "apply",
            "--preset-id",
            "short_quiz",
            "--target-assignment-id",
            "common_quiz",
            "--title",
            "Common Quiz",
            "--target-class-id",
            "english10_p4",
            "--target-class-id",
            "english10_p6",
            "--apply",
        ],
        workspace_root=tmp_path,
    )

    assert result == 0
    for class_id in ("english10_p4", "english10_p6"):
        target = scoreform_work_paths(tmp_path, class_id, "common_quiz")
        assert target.assignment_path.is_file()
    output = capsys.readouterr().out
    assert "Created 2 fresh assignments" in output


def test_preset_apply_never_creates_operational_history(tmp_path: Path) -> None:
    _save_preset(tmp_path)
    _write_roster(tmp_path, "english10_p4")

    result = run_assignment_preset(
        [
            "apply",
            "--preset-id",
            "short_quiz",
            "--target-assignment-id",
            "unit_2_quiz",
            "--title",
            "Unit 2 Quiz",
            "--target-class-id",
            "english10_p4",
            "--apply",
        ],
        workspace_root=tmp_path,
    )

    assert result == 0
    target = scoreform_work_paths(tmp_path, "english10_p4", "unit_2_quiz")
    names = {
        path.relative_to(target.work_root).as_posix()
        for path in target.work_root.rglob("*")
    }
    assert "assignment.json" in names
    assert "results.csv" not in names
    assert not any("manifest" in name for name in names)
    assert not any("publication" in name for name in names)


def test_preset_delete_plan_only_keeps_preset(tmp_path: Path, capsys) -> None:
    _save_preset(tmp_path)
    capsys.readouterr()

    result = run_assignment_preset(
        ["delete", "--preset-id", "short_quiz"],
        workspace_root=tmp_path,
    )

    assert result == 0
    assert assignment_preset_path(tmp_path, "short_quiz").is_file()
    assert "Mode: PLAN ONLY" in capsys.readouterr().out


def test_preset_delete_apply_removes_only_preset(tmp_path: Path, capsys) -> None:
    _save_preset(tmp_path)
    source = scoreform_work_paths(tmp_path, "english10_p2", "source_quiz")
    source_before = source.assignment_path.read_bytes()
    capsys.readouterr()

    result = run_assignment_preset(
        ["delete", "--preset-id", "short_quiz", "--apply"],
        workspace_root=tmp_path,
    )

    assert result == 0
    assert not assignment_preset_path(tmp_path, "short_quiz").exists()
    assert source.assignment_path.read_bytes() == source_before
    assert "Deleted assessment setup preset" in capsys.readouterr().out


def test_preset_cli_rejects_force_and_overwrite(tmp_path: Path, capsys) -> None:
    _write_source(tmp_path)

    for flag in ("--force", "--overwrite"):
        result = run_assignment_preset(
            [
                "save",
                "--preset-id",
                "short_quiz",
                "--source-class-id",
                "english10_p2",
                "--source-assignment-id",
                "source_quiz",
                flag,
            ],
            workspace_root=tmp_path,
        )
        assert result == 1
        assert "not supported" in capsys.readouterr().out


def test_preset_apply_requires_target_class(tmp_path: Path, capsys) -> None:
    _save_preset(tmp_path)
    capsys.readouterr()

    result = run_assignment_preset(
        [
            "apply",
            "--preset-id",
            "short_quiz",
            "--target-assignment-id",
            "unit_2_quiz",
            "--title",
            "Unit 2 Quiz",
        ],
        workspace_root=tmp_path,
    )

    assert result == 1
    assert "--target-class-id" in capsys.readouterr().out


def test_preset_unknown_command_is_bounded_error(tmp_path: Path, capsys) -> None:
    result = run_assignment_preset(["explode"], workspace_root=tmp_path)

    assert result == 1
    assert "Unknown preset command" in capsys.readouterr().out
