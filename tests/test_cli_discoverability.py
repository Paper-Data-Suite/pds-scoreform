import re
import subprocess
import sys
from pathlib import Path

import scoreform.cli


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run_main_command(*args, input_text=None):
    return subprocess.run(
        [sys.executable, "main.py", *map(str, args)],
        cwd=PROJECT_ROOT,
        input=input_text,
        capture_output=True,
        text=True,
    )


def combined_output(result):
    return result.stdout + result.stderr


def assert_help_output(result):
    assert result.returncode == 0
    output = combined_output(result)
    assert "ScoreForm" in output
    assert "Commands:" in output
    assert "scoreform generate" in output
    assert "scoreform score <scan.pdf>" in output
    assert "QR-aware scoring" in output
    assert "Legacy/manual scoring" in output
    assert "python main.py remains supported" in output


def test_help_flag_prints_cli_help():
    assert_help_output(run_main_command("--help"))


def test_short_help_flag_prints_cli_help():
    assert_help_output(run_main_command("-h"))


def test_help_command_prints_cli_help():
    assert_help_output(run_main_command("help"))


def assert_version_output(result):
    assert result.returncode == 0
    output = combined_output(result)
    assert "ScoreForm" in output
    assert re.search(r"0\.7\.0\.dev0", output)


def test_version_flag_prints_package_version():
    assert_version_output(run_main_command("--version"))


def test_version_command_prints_package_version():
    assert_version_output(run_main_command("version"))


def test_get_version_prefers_local_pyproject_over_installed_metadata(monkeypatch):
    monkeypatch.setattr(scoreform.cli, "version", lambda package_name: "0.4.0")

    assert scoreform.cli.get_version() == "0.7.0.dev0"


def test_menu_help_can_return_to_menu_and_exit():
    result = run_main_command("menu", input_text="9\n10\n")

    assert result.returncode == 0
    output = combined_output(result)
    assert "ScoreForm help" in output
    assert "Typical workflow:" in output
    assert "classes/<class_id>/assignments/<assignment_id>/results.csv" in output
    assert "Goodbye." in output
