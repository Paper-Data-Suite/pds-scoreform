import ast
import re
import subprocess
import sys
from pathlib import Path

import scoreform.cli
import scoreform.cli_help
import scoreform.cli_score
from scoreform import (
    assignment_workflows,
    generate_workflows,
    menu_scoring,
    qr_workflows,
    workflows,
)

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


def test_assignment_workflows_do_not_import_menu_actions_from_cli():
    source = (PROJECT_ROOT / "scoreform" / "assignment_workflows.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)

    assert all(
        not (
            isinstance(node, ast.ImportFrom)
            and node.module == "scoreform.cli"
            and any(
                alias.name
                in {
                    "launch_generate_menu",
                    "prompt_scoring_input_file",
                    "prompt_scoring_mode",
                    "run_decode_qr",
                }
                for alias in node.names
            )
        )
        for node in ast.walk(tree)
    )


def test_production_code_does_not_use_transitional_sync_bridges():
    forbidden_patterns = {
        'sys.modules.get("scoreform.cli")',
        'sys.modules["scoreform.cli"]',
        'sys.modules.get("scoreform.workflows")',
        'sys.modules["scoreform.workflows"]',
        "_sync_compat_from_cli_if_loaded",
        "_sync_menu_scoring_compat",
        "_sync_shared_helpers_from_workflows",
        "_patched_cli_function",
        "globals()[",
    }
    production_files = sorted((PROJECT_ROOT / "scoreform").glob("*.py"))
    offenders = []

    for path in production_files:
        source = path.read_text(encoding="utf-8")
        for pattern in forbidden_patterns:
            if pattern in source:
                offenders.append(f"{path.relative_to(PROJECT_ROOT)}: {pattern}")

    assert offenders == []


def assert_help_output(result):
    assert result.returncode == 0
    output = combined_output(result)
    assert "ScoreForm" in output
    assert "Commands:" in output
    assert "scoreform generate" in output
    assert "scoreform score <scan.pdf>" in output
    assert "scoreform workspace show" in output
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
    assert re.search(r"^ScoreForm 0\.8\.1$", output, re.MULTILINE)


def test_version_flag_prints_package_version():
    assert_version_output(run_main_command("--version"))


def test_version_command_prints_package_version():
    assert_version_output(run_main_command("version"))


def test_get_version_prefers_local_pyproject_over_installed_metadata(monkeypatch):
    monkeypatch.setattr(scoreform.cli_help, "version", lambda package_name: "0.4.0")

    assert scoreform.cli.get_version() == "0.8.1"


def test_main_without_args_can_print_help_without_launching_menu(capsys):
    assert scoreform.cli.main([], default_to_menu=False) == 1

    output = capsys.readouterr().out
    assert "ScoreForm" in output
    assert "Commands:" in output
    assert "Running scoreform with no arguments launches the terminal menu." in output


def test_menu_help_can_return_to_menu_and_exit():
    result = run_main_command("menu", input_text="4\n\n5\n")

    assert result.returncode == 0
    output = combined_output(result)
    assert "ScoreForm\nHelp" in output
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

    monkeypatch.setattr(generate_workflows, "generate_student_pdf", fake_student_pdf)
    monkeypatch.setattr(
        generate_workflows,
        "generate_class_packet_pdf",
        fake_class_packet,
    )
    responses = iter(["1", "4", "1", "1", "1", "y", "", "8", "5"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    assert scoreform.cli.launch_menu() == 0

    output = capsys.readouterr().out
    assert "ScoreForm\nGenerate Answer Sheets" in output
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

    monkeypatch.setattr(generate_workflows, "generate_template", fake_generate_template)
    responses = iter(["1", "4", "2", "", "8", "5"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    assert scoreform.cli.launch_menu() == 0

    output = capsys.readouterr().out
    assert "Generate a generic blank template" in output
    assert generated == [True]
    assert "Goodbye." in output


def test_menu_view_assignment_results_displays_selected_assignment_results(
    tmp_path,
    monkeypatch,
    capsys,
):
    monkeypatch.chdir(tmp_path)
    workflows.write_roster_csv(
        str(tmp_path / "classes" / "english12_p3" / "roster.csv"),
        "english12_p3",
        "3",
        [{"student_id": "1001", "last_name": "Doe", "first_name": "Jane"}],
    )
    workflows.write_assignment_json(
        str(tmp_path / "classes" / "english12_p3" / "assignments" / "final_exam" / "assignment.json"),
        {
            "assignment_id": "final_exam",
            "title": "Final Exam",
            "question_count": 1,
            "choices": ["A", "B", "C", "D"],
            "answer_key": {"1": "A"},
            "standards": {"1": []},
        },
    )
    results_path = (
        tmp_path
        / "classes"
        / "english12_p3"
        / "assignments"
        / "final_exam"
        / "results.csv"
    )
    results_path.write_text(
        "\n".join([
            "Page,class_id,assignment_id,student_id,last_name,first_name,period,source_file,attempt_number,scan_timestamp,Score,Total,Q1,Q1_Correct",
            "1,english12_p3,final_exam,1001,Doe,Jane,3,scan.pdf,1,2026-06-17 09:30:00,13,15,A,True",
            "",
        ]),
        encoding="utf-8",
    )

    responses = iter(["1", "6", "1", "1", "8", "5"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))
    monkeypatch.setattr(assignment_workflows, "pause_for_user", lambda: None)

    assert scoreform.cli.launch_menu() == 0

    output = capsys.readouterr().out
    assert "View Assignment Results" in output
    assert "Available classes:" in output
    assert "Available assignments for english12_p3:" in output
    assert "Results for: english12_p3 / final_exam" in output
    assert f"Source: {results_path}" in output
    assert "Student ID" in output
    assert "Recent" in output
    assert "Attempts" in output
    assert "1001" in output
    assert "Doe, Jane" in output
    assert "13" in output


def test_menu_view_assignment_results_reports_missing_results_csv(
    tmp_path,
    monkeypatch,
    capsys,
):
    monkeypatch.chdir(tmp_path)
    workflows.write_roster_csv(
        str(tmp_path / "classes" / "english12_p3" / "roster.csv"),
        "english12_p3",
        "3",
        [{"student_id": "1001", "last_name": "Doe", "first_name": "Jane"}],
    )
    workflows.write_assignment_json(
        str(tmp_path / "classes" / "english12_p3" / "assignments" / "final_exam" / "assignment.json"),
        {
            "assignment_id": "final_exam",
            "title": "Final Exam",
            "question_count": 1,
            "choices": ["A", "B", "C", "D"],
            "answer_key": {"1": "A"},
            "standards": {"1": []},
        },
    )

    responses = iter(["1", "6", "1", "1", "8", "5"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))
    monkeypatch.setattr(assignment_workflows, "pause_for_user", lambda: None)

    assert scoreform.cli.launch_menu() == 0

    output = capsys.readouterr().out
    assert "Results for: english12_p3 / final_exam" in output
    assert "No results have been recorded for this assignment yet." in output


def test_main_menu_is_teacher_centered_and_omits_assignment_operations():
    result = run_main_command("menu", input_text="5\n")

    assert result.returncode == 0
    output = combined_output(result)
    assert "ScoreForm" in output
    assert "Main Menu" in output
    assert "\x1b[" not in output
    assert "1. Assignment Management" in output
    assert "2. Roster Management" in output
    assert "3. Workspace Settings" in output
    assert "4. Help" in output
    assert output.count("Q. Quit") == 1
    assert "B. Back" not in output
    assert "M. Main Menu" not in output
    assert "5. Exit" not in output
    assert "Generate answer sheets" not in output
    assert "Score scanned responses" not in output
    assert "Decode QR from a file" not in output
    assert "Set up assignment folders" not in output
    assert "Validate an assignment file" not in output
    assert "Validate a roster file" not in output


def test_assignment_management_menu_contains_teacher_workflows():
    result = run_main_command("menu", input_text="1\n8\n5\n")

    assert result.returncode == 0
    output = combined_output(result)
    assert "Assignment Management" in output
    assert "ScoreForm\nAssignment Management" in output
    assert "1. Create an assignment" in output
    assert "2. Edit an assignment" in output
    assert "3. Validate an assignment file" in output
    assert "4. Generate answer sheets" in output
    assert "5. Score scanned responses" in output
    assert "6. View assignment results" in output
    assert "7. Decode QR from a file" in output
    assert output.count("B. Back") == 1
    assert output.count("M. Main Menu") == 1
    assert output.count("Q. Quit") == 3  # initial main, submenu, redrawn main
    assert "Set up assignment folders" not in output


def test_roster_management_menu_still_contains_teacher_workflows():
    result = run_main_command("menu", input_text="2\n5\n5\n")

    assert result.returncode == 0
    output = combined_output(result)
    assert "Roster Management" in output
    assert "ScoreForm\nRoster Management" in output
    assert "1. Create a class roster" in output
    assert "2. View a class roster" in output
    assert "3. Edit class roster" in output
    assert "4. Validate a roster file" in output
    assert output.count("B. Back") == 1
    assert output.count("M. Main Menu") == 1
    assert output.count("Q. Quit") == 3  # initial main, submenu, redrawn main


def test_menu_selection_does_not_strip_quotes():
    result = run_main_command(
        "menu",
        input_text='"5"\n\n5\n',
    )

    assert result.returncode == 0
    output = combined_output(result)
    assert "Invalid selection" in output
    assert "Please choose a listed option or Q." in output
    assert "Goodbye." in output


def test_assignment_submenu_validate_assignment_accepts_quoted_path():
    result = run_main_command(
        "menu",
        input_text='1\n3\n"examples/sample_assignment.json"\n\n8\n5\n',
    )

    assert result.returncode == 0
    output = combined_output(result)
    assert "Assignment file is valid." in output
    assert "Goodbye." in output


def test_roster_submenu_validate_roster_accepts_quoted_path():
    result = run_main_command(
        "menu",
        input_text='2\n4\n"examples/sample_roster_english9_p2.csv"\n\n5\n5\n',
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


def test_direct_cli_setup_assignment_remains_discoverable():
    result = run_main_command("--help")

    assert result.returncode == 0
    assert "scoreform setup-assignment <assignment.json> <roster.csv>" in combined_output(result)


def test_menu_clear_and_pause_helpers_are_used_for_help(monkeypatch):
    calls = []
    responses = iter(["4", "5"])

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
    responses = iter(["1", "5", "1", "2", "1", "8", "5"])

    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))
    monkeypatch.setattr(menu_scoring, "pause_for_user", lambda: None)
    monkeypatch.setattr(menu_scoring, "run_score", lambda args: run_score_calls.append(args) or 0)

    assert scoreform.cli.launch_menu() == 0

    output = capsys.readouterr().out
    assert "Score Scanned Responses" in output
    assert f"Available scans in {scans_dir}:" in output
    assert "1. class_packet_period2.jpg" in output
    assert "2. mixed_scan.pdf" in output
    assert "z_unsupported.txt" not in output
    assert "Selected scan:" in output
    assert "QR-aware routed scoring (recommended)" in output
    assert "Output CSV path (blank for routed QR-aware default):" not in output
    assert run_score_calls == [[str(scans_dir / "mixed_scan.pdf")]]


def test_menu_score_invalid_inbox_selection_returns_to_scoring_input_menu(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    scans_dir = tmp_path / "scans_inbox"
    scans_dir.mkdir()
    (scans_dir / "class_packet.pdf").write_text("synthetic scan", encoding="utf-8")

    pauses = []
    run_score_calls = []
    responses = iter(["1", "5", "1", "99", "2", "custom_scan.pdf", "1", "8", "5"])

    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))
    monkeypatch.setattr(menu_scoring, "pause_for_user", lambda: pauses.append("pause"))
    monkeypatch.setattr(menu_scoring, "run_score", lambda args: run_score_calls.append(args) or 0)

    assert scoreform.cli.launch_menu() == 0

    output = capsys.readouterr().out
    assert "Error: Scan selection out of range: 99" in output
    assert output.count("Score Scanned Responses") >= 2
    assert pauses == ["pause", "pause"]
    assert run_score_calls == [["custom_scan.pdf"]]


def test_menu_score_manual_scoring_with_explicit_output_preserves_quoted_path_normalization(monkeypatch):
    run_score_calls = []
    responses = iter([
        "1",
        "5",
        "2",
        '"Downloads/my scan.pdf"',
        "2",
        '"answer key.json"',
        '"results.csv"',
        "8",
        "5",
    ])

    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))
    monkeypatch.setattr(menu_scoring, "pause_for_user", lambda: None)
    monkeypatch.setattr(menu_scoring, "run_score", lambda args: run_score_calls.append(args) or 0)

    assert scoreform.cli.launch_menu() == 0

    assert run_score_calls == [["Downloads/my scan.pdf", "results.csv", "answer key.json"]]


def test_menu_score_manual_scoring_with_answer_key_only(monkeypatch):
    run_score_calls = []
    responses = iter(["1", "5", "2", "scan.pdf", "2", "answer_key.json", "", "8", "5"])

    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))
    monkeypatch.setattr(menu_scoring, "pause_for_user", lambda: None)
    monkeypatch.setattr(menu_scoring, "run_score", lambda args: run_score_calls.append(args) or 0)

    assert scoreform.cli.launch_menu() == 0

    assert run_score_calls == [["scan.pdf", "answer_key.json"]]


def test_menu_score_manual_scoring_rejects_blank_answer_key(monkeypatch, capsys):
    pauses = []
    run_score_calls = []
    responses = iter(["1", "5", "2", "scan.pdf", "2", "", "3", "8", "5"])

    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))
    monkeypatch.setattr(menu_scoring, "pause_for_user", lambda: pauses.append("pause"))
    monkeypatch.setattr(menu_scoring, "run_score", lambda args: run_score_calls.append(args) or 0)

    assert scoreform.cli.launch_menu() == 0

    output = capsys.readouterr().out
    assert "Answer key JSON path is required for manual scoring." in output
    assert output.count("Scoring mode:") >= 2
    assert pauses == ["pause"]
    assert run_score_calls == []


def test_menu_score_invalid_scoring_mode_returns_to_mode_selection(monkeypatch, capsys):
    pauses = []
    run_score_calls = []
    responses = iter(["1", "5", "2", "scan.pdf", "9", "3", "8", "5"])

    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))
    monkeypatch.setattr(menu_scoring, "pause_for_user", lambda: pauses.append("pause"))
    monkeypatch.setattr(menu_scoring, "run_score", lambda args: run_score_calls.append(args) or 0)

    assert scoreform.cli.launch_menu() == 0

    output = capsys.readouterr().out
    assert "Invalid selection: 9." in output
    assert "Please choose a listed option, B, M, or Q." in output
    assert output.count("Scoring mode:") >= 2
    assert pauses == ["pause"]
    assert run_score_calls == []


def test_menu_decode_qr_runs_from_assignment_management(monkeypatch):
    decode_calls = []
    responses = iter(["1", "7", '"scan with qr.pdf"', "8", "5"])

    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))
    monkeypatch.setattr(assignment_workflows, "pause_for_user", lambda: None)
    monkeypatch.setattr(qr_workflows, "run_decode_qr", lambda args: decode_calls.append(args) or 0)

    assert scoreform.cli.launch_menu() == 0

    assert decode_calls == [["scan with qr.pdf"]]


def test_prompt_select_scan_from_inbox_handles_missing_and_empty_inbox(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    pauses = []
    monkeypatch.setattr(menu_scoring, "pause_for_user", lambda: pauses.append("pause"))

    assert scoreform.cli.prompt_select_scan_from_inbox() is None

    scans_dir = tmp_path / "scans_inbox"
    scans_dir.mkdir()
    (scans_dir / "notes.txt").write_text("not a scan", encoding="utf-8")

    assert scoreform.cli.prompt_select_scan_from_inbox() is None

    output = capsys.readouterr().out
    assert output.count(f"No scans found in {scans_dir}.") == 2
    assert (
        f"Place scanned PDFs or images in {scans_dir}, then try again."
        in output
    )
    assert pauses == ["pause", "pause"]


def test_prompt_select_scan_from_inbox_uses_core_route_by_default(
    tmp_path,
    monkeypatch,
):
    route_calls = []
    discovery_calls = []

    monkeypatch.setattr(
        menu_scoring,
        "scans_inbox_dir",
        lambda root: route_calls.append(root) or Path(root) / "scans_inbox",
    )
    monkeypatch.setattr(
        menu_scoring,
        "discover_scans_in_inbox",
        lambda scans_dir: discovery_calls.append(scans_dir) or [],
    )
    monkeypatch.setattr(menu_scoring, "pause_for_user", lambda: None)

    assert scoreform.cli.prompt_select_scan_from_inbox() is None
    assert route_calls == [tmp_path]
    assert discovery_calls == [str(tmp_path / "scans_inbox")]


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
        scoreform.cli_score,
        "process_file_qr_aware",
        lambda _input_file, workspace_root=None: [],
    )

    assert scoreform.cli.main(["score", "scan.pdf"]) == 1


def test_invalid_score_usage_does_not_resolve_workspace(monkeypatch, capsys):
    monkeypatch.setattr(
        scoreform.cli_score.workspace,
        "get_scoreform_workspace_root",
        lambda: (_ for _ in ()).throw(
            AssertionError("workspace should not be resolved for usage text")
        ),
    )

    assert scoreform.cli.run_score([]) == 1

    output = capsys.readouterr().out
    assert "<PDS workspace root>/local_outputs/results/results.csv" in output


def test_manual_score_defaults_to_workspace_and_preserves_explicit_inputs(
    tmp_path,
    monkeypatch,
):
    calls = {}
    scan_path = r"C:\Somewhere\scan.pdf"
    answer_key_path = r"C:\Somewhere\answer_key.json"

    monkeypatch.setattr(
        scoreform.cli_score,
        "load_answer_key",
        lambda path: calls.setdefault("answer_key", path) or {1: "A"},
    )
    monkeypatch.setattr(
        scoreform.cli_score,
        "process_file",
        lambda path, key: calls.setdefault("input_file", path) or [{"page_num": 1}],
    )
    monkeypatch.setattr(
        scoreform.cli_score,
        "export_to_csv",
        lambda results, path, workspace_root=None: (
            calls.setdefault("output_file", path) or True
        ),
    )

    assert scoreform.cli.run_score([scan_path, answer_key_path]) == 0
    assert calls == {
        "answer_key": answer_key_path,
        "input_file": scan_path,
        "output_file": str(
            tmp_path / "local_outputs" / "results" / "results.csv"
        ),
    }


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
    monkeypatch.setattr(
        scoreform.cli,
        "print_menu_header",
        lambda _title=None: (_ for _ in ()).throw(
            AssertionError("print_menu_header should not be called")
        ),
    )

    assert scoreform.cli.main(["validate-assignment", "examples/sample_assignment.json"]) == 0
