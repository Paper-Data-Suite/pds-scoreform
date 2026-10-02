"""Issue #219 Slice 4: safe post-export local-open actions."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from scoreform import results_report_workflow as workflow
from scoreform.generated_output_opening import (
    ScoreFormGeneratedOutputOpenError,
)
from scoreform.page_scoring import ScoredAnswer
from scoreform.results import (
    ScoreFormRoutedResult,
    ScoreFormRoutedResultHistoryRow,
)
from scoreform.work_paths import scoreform_work_paths

GENERATED = datetime(2026, 10, 1, 22, 30, 0, tzinfo=timezone.utc)


def _assignment() -> dict[str, object]:
    return {
        "assignment_id": "quiz1",
        "title": "Post-Export Open Actions",
        "question_count": 2,
        "choices": ["A", "B", "C", "D"],
        "answer_key": {1: "A", 2: "B"},
        "standards": {"1": ["STD.A"], "2": []},
    }


def _history() -> tuple[ScoreFormRoutedResultHistoryRow, ...]:
    scored = (
        ScoredAnswer(1, "A", True),
        ScoredAnswer(2, "BLANK", False),
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
        1,
        2,
        scored,
        source_file="plain_paper_manual_entry",
    )
    return (
        ScoreFormRoutedResultHistoryRow(
            result,
            1,
            "2026-10-01T20:00:00+00:00",
        ),
    )


def _workspace(tmp_path):
    paths = scoreform_work_paths(tmp_path, "class1", "quiz1")
    paths.work_root.mkdir(parents=True)
    return paths


def _input(values):
    iterator = iter(values)
    return lambda _prompt: next(iterator)


def test_pdf_can_open_exact_created_report_file(tmp_path, monkeypatch):
    _workspace(tmp_path)
    file_calls: list[tuple[Path, Path]] = []
    folder_calls: list[tuple[Path, Path]] = []

    monkeypatch.setattr(
        workflow,
        "open_generated_output_file",
        lambda root, path: file_calls.append((Path(root), Path(path)))
        or (Path(root) / Path(path)),
    )
    monkeypatch.setattr(
        workflow,
        "open_generated_output_folder",
        lambda root, path: folder_calls.append((Path(root), Path(path)))
        or (Path(root) / Path(path)),
    )

    result = workflow.launch_results_export_menu(
        _history(),
        _assignment(),
        class_id="class1",
        assignment_id="quiz1",
        workspace_root=tmp_path,
        input_fn=_input(("1", "3", "GENERATE", "1")),
        clear_screen_fn=lambda: None,
        now_fn=lambda: GENERATED,
    )

    expected_relative = Path(
        "classes/class1/modules/scoreform/work/quiz1/exports/"
        "results_analysis/class_analysis_pdf_20261001T223000Z/"
        "results_analysis.pdf"
    )
    assert result == 0
    assert file_calls == [(tmp_path, expected_relative)]
    assert folder_calls == []
    assert (tmp_path / expected_relative).is_file()


def test_json_can_open_exact_created_report_folder(tmp_path, monkeypatch):
    _workspace(tmp_path)
    file_calls: list[tuple[Path, Path]] = []
    folder_calls: list[tuple[Path, Path]] = []

    monkeypatch.setattr(
        workflow,
        "open_generated_output_file",
        lambda root, path: file_calls.append((Path(root), Path(path)))
        or (Path(root) / Path(path)),
    )
    monkeypatch.setattr(
        workflow,
        "open_generated_output_folder",
        lambda root, path: folder_calls.append((Path(root), Path(path)))
        or (Path(root) / Path(path)),
    )

    result = workflow.launch_results_export_menu(
        _history(),
        _assignment(),
        class_id="class1",
        assignment_id="quiz1",
        workspace_root=tmp_path,
        input_fn=_input(("1", "2", "GENERATE", "2")),
        clear_screen_fn=lambda: None,
        now_fn=lambda: GENERATED,
    )

    expected_relative = Path(
        "classes/class1/modules/scoreform/work/quiz1/exports/"
        "results_analysis/class_analysis_json_20261001T223000Z"
    )
    assert result == 0
    assert file_calls == []
    assert folder_calls == [(tmp_path, expected_relative)]
    assert (tmp_path / expected_relative / "results_analysis.json").is_file()


def test_csv_offers_folder_action_without_file_open(tmp_path, monkeypatch, capsys):
    _workspace(tmp_path)
    file_calls: list[tuple[Path, Path]] = []
    folder_calls: list[tuple[Path, Path]] = []

    monkeypatch.setattr(
        workflow,
        "open_generated_output_file",
        lambda root, path: file_calls.append((Path(root), Path(path)))
        or (Path(root) / Path(path)),
    )
    monkeypatch.setattr(
        workflow,
        "open_generated_output_folder",
        lambda root, path: folder_calls.append((Path(root), Path(path)))
        or (Path(root) / Path(path)),
    )

    result = workflow.launch_results_export_menu(
        _history(),
        _assignment(),
        class_id="class1",
        assignment_id="quiz1",
        workspace_root=tmp_path,
        input_fn=_input(("1", "1", "GENERATE", "1")),
        clear_screen_fn=lambda: None,
        now_fn=lambda: GENERATED,
    )

    expected_relative = Path(
        "classes/class1/modules/scoreform/work/quiz1/exports/"
        "results_analysis/class_analysis_csv_20261001T223000Z"
    )
    assert result == 0
    assert file_calls == []
    assert folder_calls == [(tmp_path, expected_relative)]
    output = capsys.readouterr().out
    assert "1. Open report folder" in output
    assert "2. Open report folder" not in output


def test_return_after_success_performs_no_open_action(tmp_path, monkeypatch):
    _workspace(tmp_path)
    opened: list[Path] = []

    monkeypatch.setattr(
        workflow,
        "open_generated_output_file",
        lambda _root, path: opened.append(Path(path)),
    )
    monkeypatch.setattr(
        workflow,
        "open_generated_output_folder",
        lambda _root, path: opened.append(Path(path)),
    )

    result = workflow.launch_results_export_menu(
        _history(),
        _assignment(),
        class_id="class1",
        assignment_id="quiz1",
        workspace_root=tmp_path,
        input_fn=_input(("1", "3", "GENERATE", "B")),
        clear_screen_fn=lambda: None,
        now_fn=lambda: GENERATED,
    )

    assert result == 0
    assert opened == []


def test_open_failure_is_fail_soft_after_successful_export(
    tmp_path,
    monkeypatch,
    capsys,
):
    _workspace(tmp_path)

    def fail_open(_root, _path):
        raise ScoreFormGeneratedOutputOpenError("viewer failed")

    monkeypatch.setattr(
        workflow,
        "open_generated_output_file",
        fail_open,
    )

    result = workflow.launch_results_export_menu(
        _history(),
        _assignment(),
        class_id="class1",
        assignment_id="quiz1",
        workspace_root=tmp_path,
        input_fn=_input(("1", "3", "GENERATE", "1", "")),
        clear_screen_fn=lambda: None,
        now_fn=lambda: GENERATED,
    )

    report = (
        tmp_path
        / "classes/class1/modules/scoreform/work/quiz1/exports/"
        "results_analysis/class_analysis_pdf_20261001T223000Z/"
        "results_analysis.pdf"
    )
    output = capsys.readouterr().out
    assert result == 0
    assert report.is_file()
    assert "Report was created" in output
    assert "could not open report" in output
    assert "viewer failed" in output


def test_cancel_before_generation_never_reaches_open_boundary(
    tmp_path,
    monkeypatch,
):
    _workspace(tmp_path)
    opened: list[Path] = []

    monkeypatch.setattr(
        workflow,
        "open_generated_output_file",
        lambda _root, path: opened.append(Path(path)),
    )
    monkeypatch.setattr(
        workflow,
        "open_generated_output_folder",
        lambda _root, path: opened.append(Path(path)),
    )

    result = workflow.launch_results_export_menu(
        _history(),
        _assignment(),
        class_id="class1",
        assignment_id="quiz1",
        workspace_root=tmp_path,
        input_fn=_input(("1", "3", "BACK")),
        clear_screen_fn=lambda: None,
        now_fn=lambda: GENERATED,
    )

    assert result == 0
    assert opened == []
