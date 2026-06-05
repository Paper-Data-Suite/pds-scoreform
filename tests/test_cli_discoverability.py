import re
import subprocess
import sys
from pathlib import Path

import scoreform.cli
from scoreform import workflows


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
    assert re.search(r"0\.8\.0\.dev0", output)


def test_version_flag_prints_package_version():
    assert_version_output(run_main_command("--version"))


def test_version_command_prints_package_version():
    assert_version_output(run_main_command("version"))


def test_get_version_prefers_local_pyproject_over_installed_metadata(monkeypatch):
    monkeypatch.setattr(scoreform.cli, "version", lambda package_name: "0.4.0")

    assert scoreform.cli.get_version() == "0.8.0.dev0"


def test_menu_help_can_return_to_menu_and_exit():
    result = run_main_command("menu", input_text="7\n\n8\n")

    assert result.returncode == 0
    output = combined_output(result)
    assert "ScoreForm help" in output
    assert "Typical workflow:" in output
    assert "classes/<class_id>/assignments/<assignment_id>/results.csv" in output
    assert "Goodbye." in output


def test_menu_generate_existing_class_assignment_creates_expected_outputs(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    workflows.write_roster_csv(
        str(tmp_path / "classes" / "english_9_period_2" / "roster.csv"),
        "english_9_period_2",
        "2",
        [{"student_id": "1001", "last_name": "Doe", "first_name": "Jane"}],
    )
    workflows.write_assignment_json(
        str(tmp_path / "classes" / "english_9_period_2" / "assignments" / "act_1_quiz" / "assignment.json"),
        {
            "assignment_id": "act_1_quiz",
            "title": "Act 1 Quiz",
            "question_count": 1,
            "choices": ["A", "B", "C", "D"],
            "answer_key": {"1": "A"},
            "standards": {"1": []},
        },
    )

    def fake_student_pdf(output_path, _assignment, _student):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text("student pdf", encoding="utf-8")
        return True

    def fake_class_packet(output_path, _assignment, _roster):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text("class packet", encoding="utf-8")
        return True

    monkeypatch.setattr(scoreform.cli, "generate_student_pdf", fake_student_pdf)
    monkeypatch.setattr(scoreform.cli, "generate_class_packet_pdf", fake_class_packet)
    responses = iter(["1", "1", "1", "1", "y", "", "8"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    assert scoreform.cli.launch_menu() == 0

    output = capsys.readouterr().out
    assert "--- Generate Answer Sheets ---" in output
    assert "Generate answer sheets for an existing class assignment" in output
    assert "Available classes:" in output
    assert "english_9_period_2" in output
    assert "Available assignments for english_9_period_2:" in output
    assert "act_1_quiz" in output
    assert "Goodbye." in output
    assert (tmp_path / "classes" / "english_9_period_2" / "assignments" / "act_1_quiz" / "templates" / "class_packet.pdf").exists()
    assert (tmp_path / "classes" / "english_9_period_2" / "assignments" / "act_1_quiz" / "templates" / "individual" / "1001_doe_jane.pdf").exists()


def test_menu_generate_generic_template_remains_available(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    generated = []

    def fake_generate_template():
        generated.append(True)

    monkeypatch.setattr(scoreform.cli, "generate_template", fake_generate_template)
    responses = iter(["1", "2", "", "8"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    assert scoreform.cli.launch_menu() == 0

    output = capsys.readouterr().out
    assert "Generate a generic blank template" in output
    assert generated == [True]
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
        input_text='"4"\n\n8\n',
    )

    assert result.returncode == 0
    output = combined_output(result)
    assert "Invalid selection" in output
    assert "Please enter a number from 1 to 8." in output
    assert "Goodbye." in output


def test_assignment_submenu_validate_assignment_accepts_quoted_path():
    result = run_main_command(
        "menu",
        input_text='6\n2\n"examples/sample_assignment.json"\n\n3\n8\n',
    )

    assert result.returncode == 0
    output = combined_output(result)
    assert "Assignment file is valid." in output
    assert "Goodbye." in output


def test_roster_submenu_validate_roster_accepts_quoted_path():
    result = run_main_command(
        "menu",
        input_text='5\n3\n"examples/sample_roster_english9_p2.csv"\n\n4\n8\n',
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


def test_menu_clear_and_pause_helpers_are_used_for_help(monkeypatch):
    calls = []
    responses = iter(["7", "8"])

    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))
    monkeypatch.setattr(scoreform.cli, "clear_screen", lambda: calls.append("clear"))
    monkeypatch.setattr(scoreform.cli, "pause_for_user", lambda: calls.append("pause"))

    assert scoreform.cli.launch_menu() == 0

    assert calls.count("clear") >= 3
    assert "pause" in calls
    assert calls.index("pause") < len(calls) - 1


def test_menu_score_can_select_scan_from_inbox(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    scans_dir = tmp_path / "scans_inbox"
    scans_dir.mkdir()
    (scans_dir / "z_unsupported.txt").write_text("not a scan", encoding="utf-8")
    (scans_dir / "mixed_scan.pdf").write_text("synthetic scan", encoding="utf-8")
    (scans_dir / "class_packet_period2.jpg").write_text("synthetic scan", encoding="utf-8")

    run_score_calls = []
    responses = iter(["2", "1", "2", "1", "8"])

    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))
    monkeypatch.setattr(scoreform.cli, "pause_for_user", lambda: None)
    monkeypatch.setattr(scoreform.cli, "run_score", lambda args: run_score_calls.append(args) or 0)

    assert scoreform.cli.launch_menu() == 0

    output = capsys.readouterr().out
    assert "Score Scanned Responses" in output
    assert "Available scans in scans_inbox:" in output
    assert "1. class_packet_period2.jpg" in output
    assert "2. mixed_scan.pdf" in output
    assert "z_unsupported.txt" not in output
    assert "Selected scan:" in output
    assert "QR-aware routed scoring (recommended)" in output
    assert "Output CSV path (blank for routed QR-aware default):" not in output
    assert run_score_calls == [[str(Path("scans_inbox") / "mixed_scan.pdf")]]


def test_menu_score_invalid_inbox_selection_returns_to_scoring_input_menu(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    scans_dir = tmp_path / "scans_inbox"
    scans_dir.mkdir()
    (scans_dir / "class_packet.pdf").write_text("synthetic scan", encoding="utf-8")

    pauses = []
    run_score_calls = []
    responses = iter(["2", "1", "99", "2", "custom_scan.pdf", "1", "8"])

    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))
    monkeypatch.setattr(scoreform.cli, "pause_for_user", lambda: pauses.append("pause"))
    monkeypatch.setattr(scoreform.cli, "run_score", lambda args: run_score_calls.append(args) or 0)

    assert scoreform.cli.launch_menu() == 0

    output = capsys.readouterr().out
    assert "Error: Scan selection out of range: 99" in output
    assert output.count("Score Scanned Responses") >= 2
    assert pauses == ["pause", "pause"]
    assert run_score_calls == [["custom_scan.pdf"]]


def test_menu_score_manual_scoring_with_explicit_output_preserves_quoted_path_normalization(monkeypatch):
    run_score_calls = []
    responses = iter([
        "2",
        "2",
        '"Downloads/my scan.pdf"',
        "2",
        '"answer key.json"',
        '"results.csv"',
        "8",
    ])

    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))
    monkeypatch.setattr(scoreform.cli, "pause_for_user", lambda: None)
    monkeypatch.setattr(scoreform.cli, "run_score", lambda args: run_score_calls.append(args) or 0)

    assert scoreform.cli.launch_menu() == 0

    assert run_score_calls == [["Downloads/my scan.pdf", "results.csv", "answer key.json"]]


def test_menu_score_manual_scoring_with_answer_key_only(monkeypatch):
    run_score_calls = []
    responses = iter(["2", "2", "scan.pdf", "2", "answer_key.json", "", "8"])

    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))
    monkeypatch.setattr(scoreform.cli, "pause_for_user", lambda: None)
    monkeypatch.setattr(scoreform.cli, "run_score", lambda args: run_score_calls.append(args) or 0)

    assert scoreform.cli.launch_menu() == 0

    assert run_score_calls == [["scan.pdf", "answer_key.json"]]


def test_menu_score_manual_scoring_rejects_blank_answer_key(monkeypatch, capsys):
    pauses = []
    run_score_calls = []
    responses = iter(["2", "2", "scan.pdf", "2", "", "3", "8"])

    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))
    monkeypatch.setattr(scoreform.cli, "pause_for_user", lambda: pauses.append("pause"))
    monkeypatch.setattr(scoreform.cli, "run_score", lambda args: run_score_calls.append(args) or 0)

    assert scoreform.cli.launch_menu() == 0

    output = capsys.readouterr().out
    assert "Answer key JSON path is required for manual scoring." in output
    assert output.count("Scoring mode:") >= 2
    assert pauses == ["pause"]
    assert run_score_calls == []


def test_menu_score_invalid_scoring_mode_returns_to_mode_selection(monkeypatch, capsys):
    pauses = []
    run_score_calls = []
    responses = iter(["2", "2", "scan.pdf", "9", "3", "8"])

    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))
    monkeypatch.setattr(scoreform.cli, "pause_for_user", lambda: pauses.append("pause"))
    monkeypatch.setattr(scoreform.cli, "run_score", lambda args: run_score_calls.append(args) or 0)

    assert scoreform.cli.launch_menu() == 0

    output = capsys.readouterr().out
    assert "Invalid selection: 9. Please enter a number from 1 to 3." in output
    assert output.count("Scoring mode:") >= 2
    assert pauses == ["pause"]
    assert run_score_calls == []


def test_prompt_select_scan_from_inbox_handles_missing_and_empty_inbox(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    pauses = []
    monkeypatch.setattr(scoreform.cli, "pause_for_user", lambda: pauses.append("pause"))

    assert scoreform.cli.prompt_select_scan_from_inbox() is None

    scans_dir = tmp_path / "scans_inbox"
    scans_dir.mkdir()
    (scans_dir / "notes.txt").write_text("not a scan", encoding="utf-8")

    assert scoreform.cli.prompt_select_scan_from_inbox() is None

    output = capsys.readouterr().out
    assert output.count("No scans found in scans_inbox.") == 2
    assert "Place scanned PDFs or images in scans_inbox, then try again." in output
    assert pauses == ["pause", "pause"]


def test_direct_cli_score_does_not_invoke_scan_picker(monkeypatch):
    monkeypatch.setattr(
        scoreform.cli,
        "prompt_scoring_input_file",
        lambda: (_ for _ in ()).throw(AssertionError("scan picker should not be called")),
    )
    monkeypatch.setattr(
        scoreform.cli,
        "prompt_scoring_mode",
        lambda _input_file: (_ for _ in ()).throw(AssertionError("scoring mode menu should not be called")),
    )
    monkeypatch.setattr(
        scoreform.cli,
        "process_file_qr_aware",
        lambda _input_file: [],
    )

    assert scoreform.cli.main(["score", "scan.pdf"]) == 1


def test_direct_cli_subcommand_does_not_clear_or_pause(monkeypatch):
    monkeypatch.setattr(
        scoreform.cli,
        "clear_screen",
        lambda: (_ for _ in ()).throw(AssertionError("clear_screen should not be called")),
    )
    monkeypatch.setattr(
        scoreform.cli,
        "pause_for_user",
        lambda: (_ for _ in ()).throw(AssertionError("pause_for_user should not be called")),
    )

    assert scoreform.cli.main(["validate-assignment", "examples/sample_assignment.json"]) == 0
