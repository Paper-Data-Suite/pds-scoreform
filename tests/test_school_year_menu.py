from datetime import datetime

from pds_core.school_years import get_active_school_year, open_school_year

import scoreform.cli


def test_workspace_settings_routes_to_school_year_settings(monkeypatch, capsys):
    responses = iter(["4", "4", "6"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    assert scoreform.cli.launch_workspace_menu() == 0

    output = capsys.readouterr().out
    assert "ScoreForm\nWorkspace Settings" in output
    assert "4. School year settings" in output
    assert "ScoreForm\nSchool Year Settings" in output
    assert "1. Show school year status" in output
    assert "2. Open school year" in output
    assert "3. Close school year" in output
    assert "4. Back" in output


def test_school_year_menu_show_displays_status(monkeypatch, capsys):
    responses = iter(["1", "", "4"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    assert scoreform.cli.launch_school_year_menu() == 0

    output = capsys.readouterr().out
    assert "School Year Status" in output
    assert "No school year has been opened" in output


def test_school_year_menu_open_and_close_workflows(tmp_path, monkeypatch, capsys):
    responses = iter(["2", "2026-2027", "", "3", "CLOSE", "", "4"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    assert scoreform.cli.launch_school_year_menu() == 0

    output = capsys.readouterr().out
    assert "Opened school year: 2026-2027" in output
    assert "Active school year: 2026-2027" in output
    assert "Closed school year: 2026-2027" in output
    assert get_active_school_year(tmp_path) is None


def test_school_year_menu_overwrite_requires_exact_confirmation(
    tmp_path,
    monkeypatch,
    capsys,
):
    open_school_year(
        tmp_path,
        "2026-2027",
        opened_at=datetime.fromisoformat("2020-08-28T09:00:00-04:00"),
    )
    responses = iter(["2", "2027-2028", "overwrite", "", "4"])
    prompts = []

    def fake_input(prompt=""):
        prompts.append(prompt)
        return next(responses)

    monkeypatch.setattr("builtins.input", fake_input)

    assert scoreform.cli.launch_school_year_menu() == 0

    output = capsys.readouterr().out
    assert "Type OVERWRITE to confirm: " in prompts
    assert "Cancelled: School-year overwrite not confirmed." in output
    assert get_active_school_year(tmp_path) == "2026-2027"


def test_school_year_menu_overwrite_exact_confirmation_replaces_active_year(
    tmp_path,
    monkeypatch,
    capsys,
):
    open_school_year(
        tmp_path,
        "2026-2027",
        opened_at=datetime.fromisoformat("2020-08-28T09:00:00-04:00"),
    )
    responses = iter(["2", "2027-2028", "OVERWRITE", "", "4"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    assert scoreform.cli.launch_school_year_menu() == 0

    output = capsys.readouterr().out
    assert "A different school year is already open: 2026-2027" in output
    assert "This will not delete or archive any data." in output
    assert "Replaced active school year with: 2027-2028" in output
    assert get_active_school_year(tmp_path) == "2027-2028"


def test_school_year_menu_close_requires_exact_confirmation(
    tmp_path,
    monkeypatch,
    capsys,
):
    open_school_year(
        tmp_path,
        "2026-2027",
        opened_at=datetime.fromisoformat("2020-08-28T09:00:00-04:00"),
    )
    responses = iter(["3", "close", "", "4"])
    prompts = []

    def fake_input(prompt=""):
        prompts.append(prompt)
        return next(responses)

    monkeypatch.setattr("builtins.input", fake_input)

    assert scoreform.cli.launch_school_year_menu() == 0

    output = capsys.readouterr().out
    assert "Active school year: 2026-2027" in output
    assert "Type CLOSE to confirm: " in prompts
    assert "Cancelled: School-year close not confirmed." in output
    assert get_active_school_year(tmp_path) == "2026-2027"


def test_school_year_menu_close_without_open_year_does_not_prompt(
    monkeypatch,
    capsys,
):
    responses = iter(["3", "", "4"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    assert scoreform.cli.launch_school_year_menu() == 0

    output = capsys.readouterr().out
    assert "No school year is currently open." in output
    assert "Type CLOSE to confirm" not in output

