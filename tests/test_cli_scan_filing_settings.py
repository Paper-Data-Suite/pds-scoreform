import json

from scoreform import cli


def test_scan_filing_cli_show_default(tmp_path, capsys):
    assert cli.main(["scan-filing", "show"]) == 0

    output = capsys.readouterr().out
    assert "ScoreForm scan filing mode: copy" in output
    assert str(tmp_path / ".pds" / "scoreform.json") in output
    assert "Using the default mode" in output
    assert "archive" not in output.lower()


def test_scan_filing_cli_set_each_mode_and_reset(tmp_path, capsys):
    path = tmp_path / ".pds" / "scoreform.json"
    for mode in ("copy", "move", "off"):
        assert cli.main(["scan-filing", "set", mode]) == 0
        assert json.loads(path.read_text(encoding="utf-8"))["scan_filing_mode"] == mode
    assert cli.main(["scan-filing", "reset"]) == 0
    assert "scan_filing_mode" not in json.loads(path.read_text(encoding="utf-8"))

    output = capsys.readouterr().out
    assert "direct child of scans_inbox" in output
    assert "Effective scan filing mode: copy" in output
    assert "archive" not in output.lower()


def test_scan_filing_cli_invalid_usage_is_concise(capsys):
    assert cli.main(["scan-filing"]) == 1
    assert cli.main(["scan-filing", "set"]) == 1
    assert cli.main(["scan-filing", "set", "delete"]) == 1
    assert cli.main(["scan-filing", "unknown"]) == 1

    output = capsys.readouterr().out
    assert "scoreform scan-filing set <copy|move|off>" in output
    assert "archive" not in output.lower()


def test_scan_filing_show_malformed_settings_falls_back(tmp_path, capsys):
    path = tmp_path / ".pds" / "scoreform.json"
    path.parent.mkdir()
    path.write_text("{bad json", encoding="utf-8")

    assert cli.main(["scan-filing", "show"]) == 0

    output = capsys.readouterr().out
    assert "Warning: ScoreForm settings could not be read safely." in output
    assert "Effective scan filing mode: copy" in output
