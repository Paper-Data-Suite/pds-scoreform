"""Shared PDS navigation behavior in ScoreForm interactive menus."""

import pytest
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu

from scoreform import cli
from scoreform.assignment_workflows import launch_assignment_menu
from scoreform.roster_workflows import launch_roster_menu


@pytest.mark.parametrize("choice", ["Q", "q", "  q  "])
def test_main_menu_quit_is_case_insensitive(choice, monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _prompt="": choice)

    assert cli.launch_menu() == 0

    output = capsys.readouterr().out
    assert output.count("Q. Quit") == 1
    assert "5. Exit" not in output
    assert "Goodbye." in output


@pytest.mark.parametrize("launcher", [launch_assignment_menu, launch_roster_menu])
def test_management_menu_back_returns_locally(launcher, monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _prompt="": "b")

    assert launcher() == 0

    output = capsys.readouterr().out
    assert output.count("B. Back") == 1
    assert output.count("M. Main Menu") == 1
    assert output.count("Q. Quit") == 1


@pytest.mark.parametrize("launcher", [launch_assignment_menu, launch_roster_menu])
def test_management_menu_main_and_quit_raise_shared_exceptions(launcher, monkeypatch):
    responses = iter(["m", "q"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    with pytest.raises(ReturnToMainMenu):
        launcher()
    with pytest.raises(QuitPDS):
        launcher()


def test_assignment_menu_invalid_input_uses_shared_hint(monkeypatch, capsys):
    responses = iter(["invalid", "b"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))
    monkeypatch.setattr(
        "scoreform.assignment_workflows.pause_for_user", lambda: None
    )

    assert launch_assignment_menu() == 0
    assert "Please choose a listed option, B, M, or Q." in capsys.readouterr().out
