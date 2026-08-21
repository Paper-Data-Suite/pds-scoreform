from __future__ import annotations

import json
from pathlib import Path

import pytest

from scoreform import cli
from scoreform import multi_class_generation as multi
from scoreform.answer_sheet_persistence import load_answer_sheet_issuance
from scoreform.cli_multi_class_generation import (
    parse_generation_target_spec,
    run_generate_batch,
)
from scoreform.multi_class_generation import MultiClassGenerationValidationError
from scoreform.work_paths import scoreform_work_paths


@pytest.fixture(autouse=True)
def _skip_preview_dependency_import_preflight(monkeypatch: pytest.MonkeyPatch) -> None:
    # Execution still runs the exact low-level dependency preflight. This only keeps
    # read-only planning tests independent of optional import probing.
    monkeypatch.setattr(multi, "preflight_generation_dependencies", lambda: None)


def _assignment(assignment_id: str, *, question_count: int = 3) -> dict[str, object]:
    return {
        "assignment_id": assignment_id,
        "title": "Synthetic Unit Quiz",
        "question_count": question_count,
        "choices": ["A", "B", "C", "D"],
        "layout_id": "standard_15q_abcd_v1",
        "answer_key": {
            str(number): "ABCD"[(number - 1) % 4]
            for number in range(1, question_count + 1)
        },
        "standards": {str(number): [] for number in range(1, question_count + 1)},
    }


def _write_target(
    root: Path,
    class_id: str,
    assignment_id: str,
    *,
    student_count: int = 1,
) -> None:
    paths = scoreform_work_paths(root, class_id, assignment_id)
    paths.roster_path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        "class_id,student_id,last_name,first_name,period",
        *[
            f"{class_id},student_{index},Student{index},Synthetic,{index}"
            for index in range(1, student_count + 1)
        ],
    ]
    paths.roster_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    paths.work_root.mkdir(parents=True, exist_ok=True)
    paths.assignment_path.write_text(
        json.dumps(_assignment(assignment_id), indent=2) + "\n",
        encoding="utf-8",
    )


def _tree_snapshot(root: Path) -> tuple[tuple[str, str, bytes | None], ...]:
    snapshot: list[tuple[str, str, bytes | None]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(root).as_posix()
        if path.is_file():
            snapshot.append((relative, "file", path.read_bytes()))
        elif path.is_dir():
            snapshot.append((relative, "dir", None))
    return tuple(snapshot)


def test_generate_batch_help_is_discoverable(capsys: pytest.CaptureFixture[str]) -> None:
    assert run_generate_batch(["--help"], workspace_root="unused") == 0
    output = capsys.readouterr().out
    assert "scoreform generate-batch --target" in output
    assert "Without --apply" in output
    assert "no force, overwrite" in output.lower()


def test_cli_dispatches_generate_batch_help() -> None:
    assert cli._main(["generate-batch", "--help"], default_to_menu=False) == 0


@pytest.mark.parametrize(
    "value",
    (
        "class1",
        "class1/",
        "/quiz1",
        "class1/quiz1/extra",
        " class1/quiz1",
        "class one/quiz1",
        "class1/quiz one",
    ),
)
def test_target_spec_rejects_malformed_or_unsafe_values(value: str) -> None:
    with pytest.raises(MultiClassGenerationValidationError):
        parse_generation_target_spec(value)


def test_target_spec_returns_exact_pair() -> None:
    target = parse_generation_target_spec("english10_p2/unit_2_quiz")
    assert target.class_id == "english10_p2"
    assert target.assignment_id == "unit_2_quiz"


@pytest.mark.parametrize(
    "args",
    (
        (),
        ("--target",),
        ("--target", "class1/quiz1", "--force"),
        ("--target", "class1/quiz1", "--overwrite"),
        ("--target", "class1/quiz1", "--apply", "--apply"),
    ),
)
def test_invalid_cli_contract_is_nonzero(args: tuple[str, ...]) -> None:
    assert run_generate_batch(args, workspace_root="unused") == 1


def test_plan_only_preserves_order_and_writes_nothing(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_target(tmp_path, "english10_p2", "quiz", student_count=2)
    _write_target(tmp_path, "english10_p4", "quiz", student_count=1)
    before = _tree_snapshot(tmp_path)

    result = run_generate_batch(
        [
            "--target",
            "english10_p4/quiz",
            "--target",
            "english10_p2/quiz",
        ],
        workspace_root=tmp_path,
    )

    assert result == 0
    assert _tree_snapshot(tmp_path) == before
    output = capsys.readouterr().out
    assert "Mode: PLAN ONLY" in output
    assert output.index("Class: english10_p4") < output.index("Class: english10_p2")
    assert "Students: 1" in output
    assert "Students: 2" in output
    assert "Expected PDS2 routes:" in output
    assert "No changes were made." in output


def test_duplicate_exact_target_is_rejected_without_generation(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_target(tmp_path, "class1", "quiz")
    before = _tree_snapshot(tmp_path)

    result = run_generate_batch(
        ["--target", "class1/quiz", "--target", "class1/quiz", "--apply"],
        workspace_root=tmp_path,
    )

    assert result == 1
    assert _tree_snapshot(tmp_path) == before
    assert "Duplicate generation target" in capsys.readouterr().out


def test_blocked_plan_reports_all_context_and_does_not_execute(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_target(tmp_path, "class1", "quiz")
    missing = scoreform_work_paths(tmp_path, "class2", "quiz")
    missing.work_root.mkdir(parents=True, exist_ok=True)
    missing.assignment_path.write_text(
        json.dumps(_assignment("quiz")) + "\n", encoding="utf-8"
    )
    before = _tree_snapshot(tmp_path)
    monkeypatch.setattr(
        "scoreform.cli_multi_class_generation.execute_multi_class_generation",
        lambda *_args, **_kwargs: pytest.fail("blocked plan must not execute"),
    )

    result = run_generate_batch(
        ["--target", "class1/quiz", "--target", "class2/quiz", "--apply"],
        workspace_root=tmp_path,
    )

    assert result == 1
    assert _tree_snapshot(tmp_path) == before
    output = capsys.readouterr().out
    assert "Class: class1" in output
    assert "Class: class2" in output
    assert "BLOCKED" in output
    assert "No changes were made." in output


def test_apply_generates_two_classes_without_prompts_or_viewer_launches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_target(tmp_path, "english10_p2", "quiz")
    _write_target(tmp_path, "english10_p4", "quiz")
    monkeypatch.setattr(
        "builtins.input", lambda _prompt="": pytest.fail("generate-batch must not prompt")
    )
    monkeypatch.setattr(
        "scoreform.generated_output_opening.open_generated_output_file",
        lambda *_args, **_kwargs: pytest.fail("generate-batch must not open a file"),
    )
    monkeypatch.setattr(
        "scoreform.generated_output_opening.open_generated_output_folder",
        lambda *_args, **_kwargs: pytest.fail("generate-batch must not open a folder"),
    )

    result = run_generate_batch(
        [
            "--target",
            "english10_p2/quiz",
            "--target",
            "english10_p4/quiz",
            "--apply",
        ],
        workspace_root=tmp_path,
    )

    assert result == 0
    output = capsys.readouterr().out
    assert "Mode: APPLY" in output
    assert "Clean successes: 2" in output
    assert "Failed: 0" in output
    assert "Not attempted: 0" in output

    all_issuance_ids: set[str] = set()
    all_page_ids: set[str] = set()
    all_route_ids: set[str] = set()
    for class_id in ("english10_p2", "english10_p4"):
        paths = scoreform_work_paths(tmp_path, class_id, "quiz")
        assert paths.class_packet_path.is_file()
        assert tuple(paths.individual_templates_dir.glob("*.pdf"))
        issuances = tuple(paths.answer_sheet_issuances_dir.glob("*.json"))
        assert len(issuances) == 2
        for path in issuances:
            issuance = load_answer_sheet_issuance(tmp_path, paths.work_ref, path.stem)
            assert issuance.issuance_id not in all_issuance_ids
            all_issuance_ids.add(issuance.issuance_id)
            for page_id in issuance.page_ids:
                assert page_id not in all_page_ids
                all_page_ids.add(page_id)
        route_files = tuple((paths.work_root / "routes").glob("*.json"))
        assert len(route_files) == 2
        for path in route_files:
            assert path.stem not in all_route_ids
            all_route_ids.add(path.stem)

    assert len(all_issuance_ids) == 4
    assert len(all_page_ids) == 4
    assert len(all_route_ids) == 4
