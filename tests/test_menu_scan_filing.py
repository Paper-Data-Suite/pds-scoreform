import json

from scoreform import cli
from scoreform.menu_scan_filing import launch_scan_filing_menu


def test_menu_displays_current_mode_and_sets_off(tmp_path, monkeypatch, capsys):
    responses = iter(["3", "", "b"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    assert launch_scan_filing_menu() == 0

    output = capsys.readouterr().out
    assert "Current mode: copy" in output
    assert "Scan filing mode set to: off" in output
    assert "Current mode: off" in output
    assert "archive" not in output.lower()
    settings = json.loads(
        (tmp_path / ".pds" / "scoreform.json").read_text(encoding="utf-8")
    )
    assert settings["scan_filing_mode"] == "off"


def test_menu_move_requires_exact_confirmation(tmp_path, monkeypatch, capsys):
    responses = iter(["2", "move", "", "b"])
    prompts = []

    def fake_input(prompt=""):
        prompts.append(prompt)
        return next(responses)

    monkeypatch.setattr("builtins.input", fake_input)

    assert launch_scan_filing_menu() == 0

    assert "Type MOVE to confirm: " in prompts
    assert not (tmp_path / ".pds" / "scoreform.json").exists()
    output = capsys.readouterr().out
    assert "previous mode is unchanged" in output


def test_menu_move_exact_confirmation_and_reset(tmp_path, monkeypatch, capsys):
    responses = iter(["2", "MOVE", "", "4", "", "b"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    assert launch_scan_filing_menu() == 0

    data = json.loads(
        (tmp_path / ".pds" / "scoreform.json").read_text(encoding="utf-8")
    )
    assert "scan_filing_mode" not in data
    output = capsys.readouterr().out
    assert "Scan filing mode set to: move" in output
    assert "Effective mode: copy" in output


def test_workspace_settings_opens_scan_filing_menu(monkeypatch, capsys):
    responses = iter(["s", "b", "b"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    assert cli.launch_workspace_menu() == 0

    output = capsys.readouterr().out
    assert "S. ScoreForm Scan Filing Mode" in output
    assert "Current mode: copy" in output
