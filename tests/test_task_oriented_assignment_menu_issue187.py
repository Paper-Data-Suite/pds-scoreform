"""Task-oriented Assignment Management acceptance for ScoreForm issue #187."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu

from scoreform import menu_assignment_tasks

Action = Callable[..., None]


TOP_LEVEL = (
    "1. Create / Copy / Edit Assessments",
    "2. Print Answer Sheets",
    "3. Process Scans",
    "4. Review Results",
    "5. Enter Plain-Paper Results",
    "6. Share Results",
    "7. Advanced Tools",
)

OLD_PEERS = (
    "1. Create an assignment",
    "2. Edit an assignment",
    "3. Validate an assignment file",
    "4. Generate answer sheets",
    "5. Score scanned responses",
    "6. View assignment results",
    "7. Decode QR from a file",
    "8. Enter Plain-Paper Results",
    "9. Resolve scan review items",
    "10. Academic Work Registration",
    "11. Academic Result Manifests",
    "12. Academic Result Publications",
    "13. Copy an assignment",
    "14. Assessment setup presets",
)


def _no_screen() -> None:
    return None


def _run_assignment_menu(
    monkeypatch: pytest.MonkeyPatch,
    responses: list[str],
) -> int:
    provided = iter(responses)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(provided))
    return menu_assignment_tasks.launch_assignment_menu(
        clear_screen_fn=_no_screen,
        pause_for_user_fn=_no_screen,
    )


def test_assignment_management_is_bounded_and_teacher_task_oriented(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert _run_assignment_menu(monkeypatch, ["b"]) == 0

    output = capsys.readouterr().out
    for expected in TOP_LEVEL:
        assert expected in output
    for old_peer in OLD_PEERS:
        assert old_peer not in output
    assert output.count("B. Back") == 1
    assert output.count("M. Main Menu") == 1
    assert output.count("Q. Quit") == 1


def test_create_copy_edit_group_contains_completed_definition_workflows(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert _run_assignment_menu(monkeypatch, ["1", "b", "b"]) == 0

    output = capsys.readouterr().out
    assert "Create / Copy / Edit Assessments" in output
    assert "1. Create an assignment" in output
    assert "2. Copy an assignment" in output
    assert "3. Edit an assignment" in output
    assert "4. Assessment setup presets" in output


def test_process_scans_group_contains_only_current_scan_operations(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert _run_assignment_menu(monkeypatch, ["3", "b", "b"]) == 0

    output = capsys.readouterr().out
    assert "Process Scans" in output
    assert "1. Score scanned responses" in output
    assert "2. Resolve scan review items" in output
    assert "guided scan-to-results" not in output.lower()


def test_share_results_is_explicit_about_existing_publication_steps(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert _run_assignment_menu(monkeypatch, ["6", "b", "b"]) == 0

    output = capsys.readouterr().out
    assert "Share Results" in output
    assert "1. Share Results with Meridian" in output
    assert "2. Academic Work Registration" in output
    assert "3. Academic Result Manifests" in output
    assert "4. Academic Result Publications" in output
    assert "publishes ScoreForm evidence through Core" in output
    assert "does not automatically send results to Meridian" not in output


def test_advanced_tools_contains_validation_and_qr_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert _run_assignment_menu(monkeypatch, ["7", "b", "b"]) == 0

    output = capsys.readouterr().out
    assert "Advanced Tools" in output
    assert "1. Validate an assignment file" in output
    assert "2. Decode QR from a file" in output


@pytest.mark.parametrize(
    ("menu", "title"),
    [
        (
            menu_assignment_tasks.launch_assessment_definition_menu,
            "Create / Copy / Edit Assessments",
        ),
        (menu_assignment_tasks.launch_process_scans_menu, "Process Scans"),
        (menu_assignment_tasks.launch_share_results_menu, "Share Results"),
        (menu_assignment_tasks.launch_advanced_tools_menu, "Advanced Tools"),
    ],
)
def test_subgroup_back_returns_locally(
    menu: Callable[..., int],
    title: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("builtins.input", lambda _prompt="": "b")

    assert menu(clear_screen_fn=_no_screen, pause_for_user_fn=_no_screen) == 0
    output = capsys.readouterr().out
    assert title in output
    assert "B. Back" in output
    assert "M. Main Menu" in output
    assert "Q. Quit" in output


@pytest.mark.parametrize(
    "menu",
    [
        menu_assignment_tasks.launch_assignment_menu,
        menu_assignment_tasks.launch_assessment_definition_menu,
        menu_assignment_tasks.launch_process_scans_menu,
        menu_assignment_tasks.launch_share_results_menu,
        menu_assignment_tasks.launch_advanced_tools_menu,
    ],
)
def test_every_new_group_uses_shared_main_and_quit_exceptions(
    menu: Callable[..., int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for choice, exception in (("m", ReturnToMainMenu), ("q", QuitPDS)):
        monkeypatch.setattr("builtins.input", lambda _prompt="", value=choice: value)
        with pytest.raises(exception):
            menu(clear_screen_fn=_no_screen, pause_for_user_fn=_no_screen)


def test_invalid_input_uses_shared_navigation_hint(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert _run_assignment_menu(monkeypatch, ["not-a-choice", "b"]) == 0

    output = capsys.readouterr().out
    assert "Please choose a listed option, B, M, or Q." in output


def test_navigation_only_grouping_is_side_effect_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    before = tuple(tmp_path.rglob("*"))

    assert _run_assignment_menu(
        monkeypatch,
        ["1", "b", "3", "b", "6", "b", "7", "b", "b"],
    ) == 0

    assert tuple(tmp_path.rglob("*")) == before


@pytest.mark.parametrize(
    ("responses", "action_name"),
    [
        (["1", "1", "b", "b"], "_run_create_assignment"),
        (["1", "2", "b", "b"], "_run_copy_assignment"),
        (["1", "3", "b", "b"], "_run_edit_assignment"),
        (["1", "4", "b", "b"], "_run_assignment_presets"),
        (["2", "b"], "_run_print_answer_sheets"),
        (["3", "1", "b", "b"], "_run_score_scans"),
        (["3", "2", "b", "b"], "_run_scan_review"),
        (["4", "b"], "_run_review_results"),
        (["5", "b"], "_run_plain_paper_results"),
        (["6", "1", "b", "b"], "_run_share_results_with_meridian"),
        (["6", "2", "b", "b"], "_run_academic_work_registration"),
        (["6", "3", "b", "b"], "_run_academic_result_manifests"),
        (["6", "4", "b", "b"], "_run_academic_result_publications"),
        (["7", "1", "b", "b"], "_run_validate_assignment_file"),
        (["7", "2", "b", "b"], "_run_decode_qr_file"),
    ],
)
def test_every_existing_operation_is_reachable_through_exactly_one_task_route(
    responses: list[str],
    action_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def record(**_kwargs: object) -> None:
        calls.append(action_name)

    monkeypatch.setattr(menu_assignment_tasks, action_name, record)

    assert _run_assignment_menu(monkeypatch, responses) == 0
    assert calls == [action_name]
