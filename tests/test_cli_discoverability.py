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
    result = run_main_command("menu", input_text="7\n8\n")

    assert result.returncode == 0
    output = combined_output(result)
    assert "ScoreForm help" in output
    assert "Typical workflow:" in output
    assert "classes/<class_id>/assignments/<assignment_id>/results.csv" in output
    assert "Goodbye." in output


def test_main_menu_is_compact_and_omits_top_level_validation_options():
    result = run_main_command("menu", input_text="8\n")

    assert result.returncode == 0
    output = combined_output(result)
    assert "1. Generate answer sheets" in output
    assert "2. Score scanned responses" in output
    assert "3. Decode QR from a file" in output
    assert "4. Set up assignment folders" in output
    assert "5. Roster management" in output
    assert "6. Assignment management" in output
    assert "7. Help" in output
    assert "8. Exit" in output
    assert "Validate an assignment file" not in output
    assert "Validate a roster file" not in output


def test_menu_selection_does_not_strip_quotes():
    result = run_main_command(
        "menu",
        input_text='"4"\n8\n',
    )

    assert result.returncode == 0
    output = combined_output(result)
    assert "Invalid selection" in output
    assert "Please enter a number from 1 to 8." in output
    assert "Goodbye." in output


def test_assignment_submenu_validate_assignment_accepts_quoted_path():
    result = run_main_command(
        "menu",
        input_text='6\n2\n"examples/sample_assignment.json"\n3\n8\n',
    )

    assert result.returncode == 0
    output = combined_output(result)
    assert "Assignment file is valid." in output
    assert "Goodbye." in output


def test_roster_submenu_validate_roster_accepts_quoted_path():
    result = run_main_command(
        "menu",
        input_text='5\n2\n"examples/sample_roster_english9_p2.csv"\n3\n8\n',
    )

    assert result.returncode == 0
    output = combined_output(result)
    assert "Roster file is valid." in output
    assert "Goodbye." in output


def test_direct_cli_validate_assignment_remains_available():
    result = run_main_command("validate-assignment", "examples/sample_assignment.json")

    assert result.returncode == 0
    assert "Assignment file is valid." in combined_output(result)


def test_direct_cli_validate_roster_remains_available():
    result = run_main_command("validate-roster", "examples/sample_roster_english9_p2.csv")

    assert result.returncode == 0
    assert "Roster file is valid." in combined_output(result)
