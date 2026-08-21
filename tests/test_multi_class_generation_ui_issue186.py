from __future__ import annotations

from pathlib import Path

import pytest

import scoreform.multi_class_generation_ui as ui
from scoreform import generate_workflows
from scoreform.multi_class_generation import (
    GenerationTargetDiagnostic,
    GenerationTargetOutcome,
    GenerationTargetPlan,
    GenerationTargetRef,
    MultiClassGenerationPlan,
    MultiClassGenerationResult,
)
from scoreform.work_paths import scoreform_work_paths


def _target_plan(
    root: Path,
    class_id: str,
    assignment_id: str = "unit_2_quiz",
    *,
    ready: bool = True,
    student_count: int = 2,
) -> GenerationTargetPlan:
    paths = scoreform_work_paths(root, class_id, assignment_id)
    diagnostics = () if ready else (
        GenerationTargetDiagnostic("roster_not_ready", "Synthetic roster blocker."),
    )
    return GenerationTargetPlan(
        target=GenerationTargetRef(class_id, assignment_id),
        work_paths=paths,
        assignment_snapshot=None,
        roster_snapshot=None,
        lineage_snapshot=None,
        title="Unit 2 Quiz",
        layout_id="standard_15q_abcd_v1",
        question_count=20,
        student_count=student_count,
        pages_per_student=2,
        individual_pdf_count=student_count,
        individual_physical_page_count=student_count * 2,
        class_packet_pdf_count=1,
        class_packet_physical_page_count=student_count * 2,
        total_pdf_artifact_count=student_count + 1,
        total_physical_page_count=student_count * 4,
        expected_route_count=student_count * 4,
        generation_state="initial",
        current_predecessor_count=0,
        diagnostics=diagnostics,
    )


def _plan(root: Path, *, blocked_second: bool = False) -> MultiClassGenerationPlan:
    return MultiClassGenerationPlan(
        root,
        (
            _target_plan(root, "english10_p2"),
            _target_plan(root, "english10_p4", ready=not blocked_second),
        ),
    )


def _result(root: Path, *, success: bool = True) -> MultiClassGenerationResult:
    outcomes = []
    for target in _plan(root).targets:
        paths = target.work_paths
        assert paths is not None
        outcomes.append(
            GenerationTargetOutcome(
                target=target.target,
                status="clean_success" if success else "failed",
                generation_result=None,
                class_packet_path=str(paths.class_packet_path),
                individual_templates_dir=str(paths.individual_templates_dir),
                failure_stage=None if success else "target_execution",
                error=None if success else "synthetic failure",
            )
        )
    return MultiClassGenerationResult("gen_" + "1" * 32, tuple(outcomes))


def _discovery(monkeypatch, root: Path) -> None:
    classes = [
        {"class_id": "english10_p2"},
        {"class_id": "english10_p4"},
    ]
    monkeypatch.setattr(ui, "discover_class_rosters", lambda **_kwargs: classes)

    def assignments(class_id, **_kwargs):
        return [
            {
                "assignment_id": "unit_2_quiz",
                "assignment": {"title": f"Unit 2 Quiz {class_id}"},
            }
        ]

    monkeypatch.setattr(ui, "discover_class_assignments", assignments)
    monkeypatch.setattr(ui, "clear_screen", lambda: None)
    monkeypatch.setattr(ui, "pause_for_user", lambda: None)


def test_complete_plan_preview_contains_required_workload_and_no_student_rows(
    tmp_path: Path,
) -> None:
    text = ui.format_multi_class_generation_plan(_plan(tmp_path))

    assert "english10_p2" in text and "english10_p4" in text
    assert "Title: Unit 2 Quiz" in text
    assert "Layout: standard_15q_abcd_v1" in text
    assert "Questions: 20" in text
    assert "Students: 2" in text
    assert "Pages per student: 2" in text
    assert "Individual PDFs: 2" in text
    assert "Individual physical pages: 4" in text
    assert "Class-packet PDFs: 1" in text
    assert "Class-packet physical pages: 4" in text
    assert "Total physical-page copies: 8" in text
    assert "Expected PDS2 routes: 8" in text
    assert "Generation state: initial" in text
    assert str(tmp_path) not in text
    assert "classes" in text
    assert "student_id" not in text
    assert "last_name" not in text


def test_blocked_preview_names_every_blocker_and_disables_generation_message(
    tmp_path: Path,
) -> None:
    text = ui.format_multi_class_generation_plan(_plan(tmp_path, blocked_second=True))

    assert "Target 2 — BLOCKED" in text
    assert "[roster_not_ready] Synthetic roster blocker." in text
    assert "Generation cannot start while any selected target is blocked." in text


def test_teacher_can_build_two_class_basket_and_cancel_at_exact_confirmation(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    _discovery(monkeypatch, tmp_path)
    planned = _plan(tmp_path)
    monkeypatch.setattr(ui, "plan_multi_class_generation", lambda *_args: planned)
    monkeypatch.setattr(
        ui,
        "execute_multi_class_generation",
        lambda *_args: pytest.fail("generation must not start without exact GENERATE"),
    )
    responses = iter(("1", "1", "1", "1", "2", "1", "3", "generate"))
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    assert ui.launch_multi_class_generation_menu(tmp_path) == 0

    output = capsys.readouterr().out
    assert "1. english10_p2 / unit_2_quiz" in output
    assert "2. english10_p4 / unit_2_quiz" in output
    assert "Multi-Class Generation Plan" in output
    assert "Cancelled: answer-sheet generation was not started." in output


def test_exact_generate_executes_once_and_prints_consolidated_result(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    _discovery(monkeypatch, tmp_path)
    planned = _plan(tmp_path)
    expected = _result(tmp_path)
    monkeypatch.setattr(ui, "plan_multi_class_generation", lambda *_args: planned)
    calls = []

    def execute(plan):
        calls.append(plan)
        return expected

    monkeypatch.setattr(ui, "execute_multi_class_generation", execute)
    responses = iter(("1", "1", "1", "1", "2", "1", "3", "GENERATE"))
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    assert ui.launch_multi_class_generation_menu(tmp_path) == 0
    assert calls == [planned]

    output = capsys.readouterr().out
    assert "Multi-Class Generation Results" in output
    assert "Targets selected: 2" in output
    assert "Clean successes: 2" in output
    assert output.count("CLEAN SUCCESS") == 2
    assert "english10_p2" in output and "english10_p4" in output


def test_blocked_plan_never_reaches_confirmation_or_execution(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    _discovery(monkeypatch, tmp_path)
    planned = _plan(tmp_path, blocked_second=True)
    monkeypatch.setattr(ui, "plan_multi_class_generation", lambda *_args: planned)
    monkeypatch.setattr(
        ui,
        "execute_multi_class_generation",
        lambda *_args: pytest.fail("blocked plan must not execute"),
    )
    responses = iter(("1", "1", "1", "1", "2", "1", "3", "4"))
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    assert ui.launch_multi_class_generation_menu(tmp_path) == 0

    output = capsys.readouterr().out
    assert "Target 2 — BLOCKED" in output
    assert "Generation cannot start while any selected target is blocked." in output
    assert "Cancelled: answer-sheet generation was not started." in output


def test_duplicate_exact_target_is_not_added_twice(tmp_path: Path, monkeypatch, capsys) -> None:
    _discovery(monkeypatch, tmp_path)
    responses = iter(("1", "1", "1", "1", "1", "1", "4"))
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    assert ui.launch_multi_class_generation_menu(tmp_path) == 0

    output = capsys.readouterr().out
    assert "already selected" in output
    assert "Selected targets:\n1. english10_p2 / unit_2_quiz" in output
    assert "2. english10_p2 / unit_2_quiz" not in output


def test_remove_target_preserves_remaining_order(tmp_path: Path, monkeypatch, capsys) -> None:
    _discovery(monkeypatch, tmp_path)
    responses = iter(("1", "1", "1", "1", "2", "1", "2", "1", "4"))
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    assert ui.launch_multi_class_generation_menu(tmp_path) == 0

    output = capsys.readouterr().out
    final_selected = output.rsplit("Selected targets:", 1)[-1]
    assert "1. english10_p4 / unit_2_quiz" in final_selected
    assert "english10_p2 / unit_2_quiz" not in final_selected


def test_batch_failure_returns_nonzero_and_reports_each_target_once(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    _discovery(monkeypatch, tmp_path)
    planned = _plan(tmp_path)
    failed = _result(tmp_path, success=False)
    monkeypatch.setattr(ui, "plan_multi_class_generation", lambda *_args: planned)
    monkeypatch.setattr(ui, "execute_multi_class_generation", lambda _plan: failed)
    responses = iter(("1", "1", "1", "1", "2", "1", "3", "GENERATE"))
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    assert ui.launch_multi_class_generation_menu(tmp_path) == 1

    output = capsys.readouterr().out
    assert "Failed: 2" in output
    assert output.count("Target 1 — FAILED") == 1
    assert output.count("Target 2 — FAILED") == 1


def test_generate_submenu_option_three_delegates_to_multi_class_workflow(
    monkeypatch, capsys
) -> None:
    calls = []
    monkeypatch.setattr(generate_workflows, "clear_screen", lambda: None)
    monkeypatch.setattr(
        generate_workflows,
        "launch_multi_class_generation_menu",
        lambda: calls.append(True) or 0,
        raising=False,
    )
    monkeypatch.setattr("builtins.input", lambda _prompt="": "3")

    assert generate_workflows.launch_generate_menu() == 0
    assert calls == [True]
    assert "3. Plan generation for multiple classes/assignments" in capsys.readouterr().out
