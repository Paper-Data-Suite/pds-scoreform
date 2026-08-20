from __future__ import annotations

import json
from pathlib import Path

import pytest
from pds_core.routes import class_roster_path

from scoreform import cli, cli_help
from scoreform.cli_assignment_copy import run_assignment_copy
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


def _write_source(
    root: Path,
    class_id: str = "english10_p2",
    assignment_id: str = "unit_1_quiz",
) -> Path:
    paths = scoreform_work_paths(root, class_id, assignment_id)
    paths.work_root.mkdir(parents=True)
    paths.assignment_path.write_text(
        json.dumps(_assignment(assignment_id), indent=2) + "\n",
        encoding="utf-8",
    )
    return paths.assignment_path


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


def _base_args(*targets: str) -> list[str]:
    args = [
        "--source-class-id",
        "english10_p2",
        "--source-assignment-id",
        "unit_1_quiz",
        "--target-assignment-id",
        "unit_1_quiz",
    ]
    for target in targets:
        args.extend(["--target-class-id", target])
    return args


def test_plan_only_cli_is_non_mutating_and_complete(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_source(tmp_path)
    _write_roster(tmp_path, "english10_p4", "4")

    status = run_assignment_copy(
        _base_args("english10_p4"),
        workspace_root=tmp_path,
    )

    assert status == 0
    target = scoreform_work_paths(tmp_path, "english10_p4", "unit_1_quiz")
    assert not target.work_root.exists()

    output = capsys.readouterr().out
    assert "Mode: PLAN ONLY" in output
    assert "Q1: A" in output
    assert "Q2: B" in output
    assert "Q3: C" in output
    assert "english10_p4/unit_1_quiz" in output
    assert "students: 2" in output
    assert "periods: 4" in output
    assert "roster/student state" in output
    assert "No changes were made." in output
    assert "student_1" not in output
    assert "Synthetic" not in output


def test_apply_cli_creates_only_fresh_assignment_state(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_source(tmp_path)
    _write_roster(tmp_path, "english10_p4", "4")

    status = run_assignment_copy(
        [*_base_args("english10_p4"), "--apply"],
        workspace_root=tmp_path,
    )

    assert status == 0
    target = scoreform_work_paths(tmp_path, "english10_p4", "unit_1_quiz")
    assert target.assignment_path.is_file()
    assert not target.results_path.exists()
    assert not target.answer_sheets_dir.exists()
    assert not target.exports_dir.exists()
    assert not (target.work_root / "routes").exists()

    output = capsys.readouterr().out
    assert "Created 1 fresh assignment copy." in output
    assert "english10_p4/unit_1_quiz" in output


def test_cli_supports_multiple_target_classes_in_order(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_source(tmp_path)
    _write_roster(tmp_path, "english10_p6", "6")
    _write_roster(tmp_path, "english10_p4", "4")

    status = run_assignment_copy(
        _base_args("english10_p6", "english10_p4"),
        workspace_root=tmp_path,
    )

    assert status == 0
    output = capsys.readouterr().out
    assert output.index("english10_p6/unit_1_quiz") < output.index(
        "english10_p4/unit_1_quiz"
    )


def test_cli_title_override_is_reviewed_and_applied(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_source(tmp_path)
    _write_roster(tmp_path, "english10_p4", "4")

    args = [
        *_base_args("english10_p4"),
        "--title",
        "Unit 1 Quiz - Period 4",
    ]
    assert run_assignment_copy(args, workspace_root=tmp_path) == 0
    assert "Unit 1 Quiz - Period 4" in capsys.readouterr().out

    assert run_assignment_copy(
        [*args, "--apply"],
        workspace_root=tmp_path,
    ) == 0
    target = scoreform_work_paths(tmp_path, "english10_p4", "unit_1_quiz")
    persisted = json.loads(target.assignment_path.read_text(encoding="utf-8"))
    assert persisted["title"] == "Unit 1 Quiz - Period 4"


def test_cli_collision_returns_nonzero_without_overwrite(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_source(tmp_path)
    _write_roster(tmp_path, "english10_p4", "4")
    target = scoreform_work_paths(tmp_path, "english10_p4", "unit_1_quiz")
    target.work_root.mkdir(parents=True)
    marker = target.work_root / "keep.txt"
    marker.write_text("keep", encoding="utf-8")

    status = run_assignment_copy(
        [*_base_args("english10_p4"), "--apply"],
        workspace_root=tmp_path,
    )

    assert status == 1
    assert "work root already exists" in capsys.readouterr().out
    assert marker.read_text(encoding="utf-8") == "keep"


@pytest.mark.parametrize("flag", ["--overwrite", "--force"])
def test_cli_explicitly_rejects_unsafe_bypass_flags(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    flag: str,
) -> None:
    status = run_assignment_copy(
        [*_base_args("english10_p4"), flag],
        workspace_root=tmp_path,
    )

    assert status == 1
    output = capsys.readouterr().out
    assert "create-only" in output


def test_cli_rejects_unknown_and_missing_arguments(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert run_assignment_copy(["--wat"], workspace_root=tmp_path) == 1
    assert "Unknown copy-assignment argument" in capsys.readouterr().out

    assert run_assignment_copy(
        ["--source-class-id", "english10_p2"],
        workspace_root=tmp_path,
    ) == 1
    assert "Missing required argument" in capsys.readouterr().out


def test_copy_assignment_help_is_non_mutating_and_successful(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert run_assignment_copy(["--help"], workspace_root=tmp_path) == 0
    output = capsys.readouterr().out
    assert "Without --apply" in output
    assert "There is no overwrite or force mode." in output
    assert list(tmp_path.iterdir()) == []


def test_top_level_cli_dispatches_copy_assignment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[list[str]] = []

    def fake_copy(args):
        observed.append(list(args))
        return 17

    monkeypatch.setattr(cli, "run_assignment_copy", fake_copy)

    assert cli._main(["copy-assignment", "--help"], default_to_menu=False) == 17
    assert observed == [["--help"]]


def test_top_level_help_advertises_copy_assignment(
    capsys: pytest.CaptureFixture[str],
) -> None:
    cli_help.print_help()

    output = capsys.readouterr().out
    assert "scoreform copy-assignment" in output
    assert "copy-assignment" in output
