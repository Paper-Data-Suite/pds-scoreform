import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run_main_command(*args):
    return subprocess.run(
        [sys.executable, "main.py", *map(str, args)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )


def combined_output(result):
    return result.stdout + result.stderr


def assert_failed_with(result, *fragments):
    assert result.returncode != 0
    output = combined_output(result)
    assert any(fragment in output for fragment in fragments)


def test_invalid_command_returns_nonzero_with_unknown_command_message():
    result = run_main_command("definitely-not-a-command")

    assert_failed_with(result, "Unknown command", "Usage")


def test_validate_assignment_nonexistent_file_returns_nonzero():
    result = run_main_command("validate-assignment", "path/to/missing_assignment.json")

    assert_failed_with(result, "Error", "not found")


def test_validate_roster_nonexistent_file_returns_nonzero():
    result = run_main_command("validate-roster", "path/to/missing_roster.csv")

    assert_failed_with(result, "Error", "not found")


def test_validate_assignment_malformed_json_returns_nonzero(tmp_path):
    assignment_path = tmp_path / "malformed_assignment.json"
    assignment_path.write_text("{ invalid json", encoding="utf-8")

    result = run_main_command("validate-assignment", assignment_path)

    assert_failed_with(result, "Failed to parse", "Error")


def test_validate_assignment_invalid_schema_returns_nonzero(tmp_path):
    assignment_path = tmp_path / "invalid_assignment.json"
    assignment_path.write_text(json.dumps({"title": "Missing ID"}), encoding="utf-8")

    result = run_main_command("validate-assignment", assignment_path)

    assert_failed_with(result, "assignment_id", "Error")


def test_validate_roster_missing_required_columns_returns_nonzero(tmp_path):
    roster_path = tmp_path / "missing_columns.csv"
    roster_path.write_text(
        "student_id,last_name,first_name,period\n"
        "1001,Doe,Jane,2\n",
        encoding="utf-8",
    )

    result = run_main_command("validate-roster", roster_path)

    assert_failed_with(result, "missing required columns", "Error")


def test_validate_roster_empty_required_field_returns_nonzero(tmp_path):
    roster_path = tmp_path / "empty_required_field.csv"
    roster_path.write_text(
        "class_id,student_id,last_name,first_name,period\n"
        "english9_p2,1001,,Jane,2\n",
        encoding="utf-8",
    )

    result = run_main_command("validate-roster", roster_path)

    assert_failed_with(result, "Missing last_name", "Error")


def test_score_nonexistent_input_file_returns_nonzero(tmp_path):
    output_path = tmp_path / "score_results.csv"

    result = run_main_command(
        "score",
        tmp_path / "missing_scan.pdf",
        output_path,
        "examples/answer_key.json",
    )

    assert_failed_with(result, "Error", "not found")


def test_score_nonexistent_input_file_does_not_create_output_csv(tmp_path):
    output_path = tmp_path / "score_results.csv"

    result = run_main_command(
        "score",
        tmp_path / "missing_scan.pdf",
        output_path,
        "examples/answer_key.json",
    )

    assert result.returncode != 0
    assert not output_path.exists()
