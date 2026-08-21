from __future__ import annotations

import json
from pathlib import Path

import pytest
from pds_core.standards import StandardDefinition, StandardsLibrary, StandardsProfile

from scoreform import cli
from scoreform.assignment import load_assignment
from scoreform.cli_assignment_bulk import run_assignment_bulk
from scoreform.work_paths import scoreform_work_paths


def _assignment(*, with_standards: bool = False) -> dict[str, object]:
    assignment: dict[str, object] = {
        "assignment_id": "unit_quiz",
        "title": "Unit Quiz",
        "question_count": 3,
        "choices": ["A", "B", "C", "D"],
        "layout_id": "standard_15q_abcd_v1",
        "answer_key": {"1": "A", "2": "B", "3": "C"},
        "standards": {"1": [], "2": [], "3": []},
    }
    if with_standards:
        assignment["standards_profile_id"] = "english10"
        assignment["standards"] = {
            "1": ["std_a"],
            "2": [],
            "3": [],
        }
    return assignment


def _standards_library() -> StandardsLibrary:
    return StandardsLibrary(
        standards=(
            StandardDefinition(
                standard_id="std_a",
                code="A",
                source="Synthetic",
                short_name="A",
                description="Synthetic standard A.",
            ),
            StandardDefinition(
                standard_id="std_b",
                code="B",
                source="Synthetic",
                short_name="B",
                description="Synthetic standard B.",
            ),
        ),
        profiles=(
            StandardsProfile(profile_id="english10", standards=("std_a", "std_b")),
            StandardsProfile(profile_id="english10_alt", standards=("std_b",)),
        ),
    )


def _write_assignment(
    root: Path,
    *,
    with_standards: bool = False,
) -> tuple[Path, bytes]:
    paths = scoreform_work_paths(root, "class1", "unit_quiz")
    paths.work_root.mkdir(parents=True, exist_ok=True)
    payload = _assignment(with_standards=with_standards)
    data = (json.dumps(payload, indent=2) + "\n").encode("utf-8")
    paths.assignment_path.write_bytes(data)
    return paths.assignment_path, data


def test_bulk_cli_help_is_discoverable() -> None:
    assert run_assignment_bulk(["--help"], workspace_root="unused") == 0


def test_cli_dispatches_bulk_edit_assignment_help() -> None:
    assert cli._main(["bulk-edit-assignment", "--help"], default_to_menu=False) == 0


@pytest.mark.parametrize(
    "args",
    [
        ["--class-id", "class1", "--assignment-id", "unit_quiz"],
        [
            "--class-id",
            "class1",
            "--assignment-id",
            "unit_quiz",
            "--answer-key-text",
            "A B C",
            "--answer-key-json",
            "key.json",
        ],
        [
            "--class-id",
            "class1",
            "--assignment-id",
            "unit_quiz",
            "--answer-key-text",
            "A B C",
            "--standards-profile-id",
            "english10",
        ],
        [
            "--class-id",
            "class1",
            "--assignment-id",
            "unit_quiz",
            "--answer-key-text",
            "A B C",
            "--force",
        ],
    ],
)
def test_bulk_cli_rejects_invalid_source_contract(
    tmp_path: Path,
    args: list[str],
) -> None:
    _write_assignment(tmp_path)
    before = scoreform_work_paths(tmp_path, "class1", "unit_quiz").assignment_path.read_bytes()

    assert run_assignment_bulk(args, workspace_root=tmp_path) == 1
    assert scoreform_work_paths(tmp_path, "class1", "unit_quiz").assignment_path.read_bytes() == before


def test_plan_only_complete_key_is_non_mutating(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assignment_path, before = _write_assignment(tmp_path)

    result = run_assignment_bulk(
        [
            "--class-id",
            "class1",
            "--assignment-id",
            "unit_quiz",
            "--answer-key-text",
            "d c b",
        ],
        workspace_root=tmp_path,
    )

    assert result == 0
    assert assignment_path.read_bytes() == before
    output = capsys.readouterr().out
    assert "Mode: PLAN ONLY" in output
    assert "Q1: D" in output
    assert "Q2: C" in output
    assert "Q3: B" in output
    assert "No changes were made." in output


def test_apply_complete_key_replaces_only_assignment_definition(
    tmp_path: Path,
) -> None:
    assignment_path, _before = _write_assignment(tmp_path)
    paths = scoreform_work_paths(tmp_path, "class1", "unit_quiz")
    paths.results_path.write_text("synthetic historical results\n", encoding="utf-8")
    results_before = paths.results_path.read_bytes()

    result = run_assignment_bulk(
        [
            "--class-id",
            "class1",
            "--assignment-id",
            "unit_quiz",
            "--answer-key-text",
            "d c b",
            "--apply",
        ],
        workspace_root=tmp_path,
    )

    assert result == 0
    saved = load_assignment(assignment_path)
    assert saved is not None
    assert saved["answer_key"] == {1: "D", 2: "C", 3: "B"}
    assert saved["title"] == "Unit Quiz"
    assert paths.results_path.read_bytes() == results_before
    assert not paths.class_packet_path.exists()
    assert not (paths.work_root / "routes").exists()


def test_invalid_answer_key_reports_diagnostics_without_mutation(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assignment_path, before = _write_assignment(tmp_path)

    result = run_assignment_bulk(
        [
            "--class-id",
            "class1",
            "--assignment-id",
            "unit_quiz",
            "--answer-key-text",
            "A X",
            "--apply",
        ],
        workspace_root=tmp_path,
    )

    assert result == 1
    assert assignment_path.read_bytes() == before
    output = capsys.readouterr().out
    assert "Answer key input is invalid" in output
    assert "Traceback" not in output


def test_explicit_csv_file_is_read_only_and_plan_only(
    tmp_path: Path,
) -> None:
    assignment_path, before = _write_assignment(tmp_path)
    source = tmp_path.parent / "teacher-key.csv"
    source.write_text("question,answer\n3,D\n1,B\n2,A\n", encoding="utf-8")
    source_before = source.read_bytes()

    try:
        result = run_assignment_bulk(
            [
                "--class-id",
                "class1",
                "--assignment-id",
                "unit_quiz",
                "--answer-key-csv",
                str(source),
            ],
            workspace_root=tmp_path,
        )
        source_after = source.read_bytes()
    finally:
        source.unlink(missing_ok=True)

    assert result == 0
    assert assignment_path.read_bytes() == before
    assert source_after == source_before


def test_bulk_file_rejects_wrong_suffix_and_directory(tmp_path: Path) -> None:
    assignment_path, before = _write_assignment(tmp_path)
    wrong = tmp_path / "key.txt"
    wrong.write_text("question,answer\n1,A\n2,B\n3,C\n", encoding="utf-8")

    assert (
        run_assignment_bulk(
            [
                "--class-id",
                "class1",
                "--assignment-id",
                "unit_quiz",
                "--answer-key-csv",
                str(wrong),
            ],
            workspace_root=tmp_path,
        )
        == 1
    )
    assert (
        run_assignment_bulk(
            [
                "--class-id",
                "class1",
                "--assignment-id",
                "unit_quiz",
                "--answer-key-json",
                str(tmp_path),
            ],
            workspace_root=tmp_path,
        )
        == 1
    )
    assert assignment_path.read_bytes() == before


def test_alignment_plan_retains_current_profile_and_does_not_mutate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assignment_path, before = _write_assignment(tmp_path, with_standards=True)
    monkeypatch.setattr(
        "scoreform.cli_assignment_bulk.load_standards_for_selection",
        lambda _root: _standards_library(),
    )

    result = run_assignment_bulk(
        [
            "--class-id",
            "class1",
            "--assignment-id",
            "unit_quiz",
            "--alignment-text",
            "1=std_b;2=-;3=std_a",
        ],
        workspace_root=tmp_path,
    )

    assert result == 0
    assert assignment_path.read_bytes() == before
    output = capsys.readouterr().out
    assert "Standards profile: english10" in output
    assert "Q1: std_b" in output
    assert "Q2: (unaligned)" in output
    assert "Q3: std_a" in output


def test_alignment_apply_can_deliberately_replace_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assignment_path, _before = _write_assignment(tmp_path, with_standards=True)
    monkeypatch.setattr(
        "scoreform.cli_assignment_bulk.load_standards_for_selection",
        lambda _root: _standards_library(),
    )

    result = run_assignment_bulk(
        [
            "--class-id",
            "class1",
            "--assignment-id",
            "unit_quiz",
            "--alignment-text",
            "1=std_b;2=-;3=std_b",
            "--standards-profile-id",
            "english10_alt",
            "--apply",
        ],
        workspace_root=tmp_path,
    )

    assert result == 0
    saved = load_assignment(assignment_path)
    assert saved is not None
    assert saved["standards_profile_id"] == "english10_alt"
    assert saved["standards"] == {
        "1": ["std_b"],
        "2": [],
        "3": ["std_b"],
    }


def test_invalid_alignment_never_partially_applies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assignment_path, before = _write_assignment(tmp_path, with_standards=True)
    monkeypatch.setattr(
        "scoreform.cli_assignment_bulk.load_standards_for_selection",
        lambda _root: _standards_library(),
    )

    result = run_assignment_bulk(
        [
            "--class-id",
            "class1",
            "--assignment-id",
            "unit_quiz",
            "--answer-key-text",
            "D D D",
            "--alignment-text",
            "1=std_b;2=missing;3=-",
            "--apply",
        ],
        workspace_root=tmp_path,
    )

    assert result == 1
    assert assignment_path.read_bytes() == before
