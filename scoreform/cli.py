"""Command-line interface for ScoreForm."""

import os
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import cv2
import numpy as np
from pds_core.scan_routes import scans_inbox_dir

from scoreform import workspace
from scoreform.assignment import load_answer_key, load_assignment
from scoreform.config import LOCAL_RESULTS_CSV
from scoreform.folders import setup_assignment_folder
from scoreform.results import export_routed_results, export_to_csv
from scoreform.roster import load_roster
from scoreform.scoring import (
    decode_qr_from_image,
    get_qr_batch_summary,
    print_qr_batch_summary,
    process_file,
    process_file_qr_aware,
    save_qr_batch_summary,
    update_qr_batch_result_write_status,
)
from scoreform.templates import (
    generate_class_packet_pdf,
    generate_student_pdf,
    generate_template,
    student_pdf_filename,
)
from scoreform.workflows import (
    discover_class_assignments,
    discover_class_rosters,
    discover_scans_in_inbox,
    launch_assignment_menu,
    launch_roster_menu,
    normalize_path_input,
    parse_single_selection,
    print_menu_header,
)


def clear_screen():
    """Clear the terminal for interactive menu screens."""
    if sys.stdin.isatty() and sys.stdout.isatty():
        os.system("cls" if os.name == "nt" else "clear")


def pause_for_user():
    """Pause after important interactive menu output."""
    try:
        input("Press Enter to continue...")
    except KeyboardInterrupt:
        print()


def get_version():
    """Return the local source version, with installed package metadata fallback."""
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    try:
        in_project_section = False
        for line in pyproject_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped == "[project]":
                in_project_section = True
                continue
            if in_project_section and stripped.startswith("["):
                break
            if in_project_section and stripped.startswith("version"):
                key, separator, value = stripped.partition("=")
                value = value.strip()
                if key.strip() == "version" and separator and len(value) >= 2:
                    if value[0] == value[-1] and value[0] in ("'", '"'):
                        return value[1:-1]
    except OSError:
        pass

    try:
        return version("scoreform")
    except PackageNotFoundError:
        return "unknown"


def print_version():
    print(f"ScoreForm {get_version()}")


def print_help():
    print(
        """ScoreForm
A local-first classroom OMR tool for generating printable answer sheets and scoring scanned responses.

Usage:
  scoreform
  scoreform menu
  scoreform generate
  scoreform generate <assignment.json> --rosters <roster.csv> [more rosters...]
  scoreform score <scan.pdf>
  scoreform score <scan.pdf> <output.csv>
  scoreform score <scan.pdf> <answer_key.json>
  scoreform score <scan.pdf> <output.csv> <answer_key.json>
  scoreform decode-qr <file.pdf-or-image>
  scoreform validate-assignment <assignment.json>
  scoreform validate-roster <roster.csv>
  scoreform setup-assignment <assignment.json> <roster.csv>
  scoreform workspace show
  scoreform workspace set <path>
  scoreform workspace validate
  scoreform workspace reset
  scoreform help
  scoreform --help
  scoreform version
  scoreform --version

Commands:
  menu                  Launch the terminal menu.
  generate              Generate a generic template or assignment-based answer sheets.
  score                 Score scanned responses.
  decode-qr             Decode QR metadata from a PDF or image.
  validate-assignment   Validate an assignment JSON file.
  validate-roster       Validate a roster CSV file.
  setup-assignment      Create class and assignment folders.
  workspace             View or configure the shared PDS workspace root.
  help                  Show this help text.
  version               Show the installed ScoreForm version.

Scoring modes:
  scoreform score scanned_file.pdf
      QR-aware scoring. Uses QR metadata to locate the assignment and routes results to
      classes/<class_id>/assignments/<assignment_id>/results.csv.

  scoreform score scanned_file.pdf output.csv
      QR-aware scoring with an explicit output CSV instead of routed results.

  scoreform score scanned_file.pdf answer_key.json
      Legacy/manual scoring with an explicit answer key and default local results path.

  scoreform score scanned_file.pdf output.csv answer_key.json
      Legacy/manual scoring with an explicit answer key and explicit output CSV.

Examples:
  scoreform
  scoreform generate examples\\sample_assignment.json --rosters examples\\sample_roster_english9_p2.csv
  scoreform score scans_inbox\\class_packet.pdf
  scoreform decode-qr classes\\english9_p2\\assignments\\rj_act1_quiz\\templates\\class_packet.pdf
  scoreform validate-assignment examples\\sample_assignment.json
  scoreform validate-roster examples\\sample_roster_english9_p2.csv
  scoreform workspace show
  scoreform workspace set "C:\\Users\\teacher\\Paper Data Suite"
  scoreform workspace validate
  scoreform workspace reset

Notes:
  Running scoreform with no arguments launches the terminal menu.
  python main.py remains supported for backward compatibility."""
    )


def print_menu_help():
    print_menu_header("Help")
    print("ScoreForm generates printable answer sheets and scores scanned responses.")
    print()
    print("Typical workflow:")
    print("  1. Create or validate a roster CSV.")
    print("  2. Create or validate an assignment JSON file.")
    print("  3. Generate answer sheets.")
    print("  4. Scan completed sheets.")
    print("  5. Score scanned responses.")
    print("  6. Inspect routed results.")
    print()
    print("QR-aware routed scoring writes to:")
    print("  classes/<class_id>/assignments/<assignment_id>/results.csv")
    print()
    print("Routed results are an audit log, not a finalized gradebook export.")
    print("Manually verify scores before using them for grades.")
    print()


def print_workspace_help():
    """Print help for the workspace command group."""
    print(
        """Usage:
  scoreform workspace show
  scoreform workspace set <path>
  scoreform workspace validate
  scoreform workspace reset

Commands:
  show       Show the resolved workspace root and configuration paths.
  set        Validate/create and save a workspace root.
  validate   Validate/create the currently resolved workspace root.
  reset      Clear the saved preference without deleting workspace files.

Setting a new workspace does not move existing ScoreForm files."""
    )


def run_workspace(args):
    """Run shared Paper Data Suite workspace commands."""
    if not args or args[0] in ("help", "--help", "-h"):
        print_workspace_help()
        return 0

    command = args[0]
    command_args = args[1:]

    try:
        if command == "show":
            if command_args:
                print("Usage: scoreform workspace show")
                return 1

            print("Current PDS workspace root:")
            print(workspace.resolve_workspace_root())
            print()
            print("Config file:")
            print(workspace.get_workspace_config_path())
            print()
            print("Default workspace root:")
            print(workspace.get_default_workspace_root())
            return 0

        if command == "set":
            if len(command_args) != 1:
                print("Usage: scoreform workspace set <path>")
                return 1

            saved_root = workspace.set_scoreform_workspace_root(command_args[0])
            print("Saved PDS workspace root:")
            print(saved_root)
            print()
            print("This does not move existing ScoreForm files.")
            return 0

        if command == "validate":
            if command_args:
                print("Usage: scoreform workspace validate")
                return 1

            validated_root = workspace.validate_scoreform_workspace_root()
            print("Workspace is valid:")
            print(validated_root)
            return 0

        if command == "reset":
            if command_args:
                print("Usage: scoreform workspace reset")
                return 1

            cleared, resolved_root = workspace.reset_scoreform_workspace_root()
            if cleared:
                print("Cleared saved PDS workspace root preference.")
            else:
                print("No saved PDS workspace root preference was set.")
            print()
            print("No workspace files were deleted.")
            print()
            print("Current resolved workspace root:")
            print(resolved_root)
            return 0
    except workspace.WorkspaceRootError as exc:
        print(f"Error: {exc}")
        return 1

    print(f"Unknown workspace command: {command}")
    print_workspace_help()
    return 1


def run_generate(args):
    if not args:
        generate_template()
        return 0

    assignment_file = args[0]
    if "--rosters" not in args[1:]:
        print("Error: Missing --rosters.\nUsage: scoreform generate <assignment_json> --rosters <roster_csv> [more_rosters...]")
        return 1

    rosters_index = args.index("--rosters")
    roster_files = args[rosters_index + 1 :]

    if not roster_files:
        print("Error: --rosters provided but no roster files specified.")
        print("Usage: scoreform generate <assignment_json> --rosters <roster_csv> [more_rosters...]")
        return 1

    assignment = load_assignment(assignment_file)
    if assignment is None:
        return 1

    for roster_path in roster_files:
        roster = load_roster(roster_path)
        if roster is None:
            print(f"Error: Failed to load/validate roster: {roster_path}")
            return 1

        setup_paths = setup_assignment_folder(roster, assignment, roster_path, assignment_file)
        if setup_paths is None:
            print(f"Error: Failed to setup assignment folder for roster: {roster_path}")
            return 1

        print("--- Setup Summary ---")
        print(f"Class: {roster.get('class_id')}")
        print(f"  Class dir: {setup_paths['class_dir']}")
        print(f"  Assignment dir: {setup_paths['assignment_dir']}")
        print(f"  Roster copy: {setup_paths['roster_copy']}")
        print(f"  Assignment copy: {setup_paths['assignment_copy']}")

        individual_dir = setup_paths.get('individual_templates_dir')
        if not individual_dir:
            print("Error: Individual templates directory is missing in setup paths.")
            return 1

        students = roster.get('students', [])
        generated_count = 0
        for student in students:
            out_name = student_pdf_filename(student)
            out_path = os.path.join(individual_dir, out_name)
            ok = generate_student_pdf(out_path, assignment, student)
            if not ok:
                print(f"Error: Failed to generate student PDF for {student.get('student_id')}")
                return 1
            generated_count += 1

        print(f"Generated {generated_count} individual student PDFs in:")
        print(individual_dir)

        templates_dir = setup_paths.get('templates_dir')
        if not templates_dir:
            print("Error: Templates directory is missing in setup paths.")
            return 1

        packet_path = os.path.join(templates_dir, 'class_packet.pdf')
        ok_packet = generate_class_packet_pdf(packet_path, assignment, roster)
        if not ok_packet:
            print(f"Error: Failed to generate class packet PDF: {packet_path}")
            return 1
        print("Generated class packet PDF:")
        print(packet_path)

    return 0


def run_score(args):
    if len(args) < 1:
        print("Usage:")
        print("  scoreform score <input_file>")
        print("      QR-aware scoring with routed results.")
        print("  scoreform score <input_file> <output_csv>")
        print("      QR-aware scoring with explicit output CSV.")
        print("  scoreform score <input_file> <answer_key_json>")
        print("      Legacy/manual scoring with default output:")
        print("      <PDS workspace root>/local_outputs/results/results.csv")
        print("  scoreform score <input_file> <output_csv> <answer_key_json>")
        print("      Legacy/manual scoring with explicit output CSV.")
        return 1

    default_results_csv = os.fspath(
        workspace.get_scoreform_workspace_root() / LOCAL_RESULTS_CSV
    )
    input_file = args[0]
    use_qr_aware = False
    output_file = default_results_csv
    answer_key_file = "answer_key.json"
    explicit_output_csv = False

    if len(args) == 1:
        use_qr_aware = True
    elif len(args) == 2:
        arg2 = args[1]
        if arg2.lower().endswith(".json"):
            answer_key_file = arg2
            use_qr_aware = False
        else:
            output_file = arg2
            explicit_output_csv = True
            use_qr_aware = True
    else:
        output_file = args[1]
        answer_key_file = args[2]
        use_qr_aware = False

    if use_qr_aware:
        print("Using QR-aware scoring mode...")
        results_data = process_file_qr_aware(input_file)
    else:
        print("Using legacy/manual scoring mode...")
        key = load_answer_key(answer_key_file)
        if key is None:
            return 1
        results_data = process_file(input_file, key)

    if not results_data:
        if use_qr_aware:
            summary = get_qr_batch_summary(results_data)
            print_qr_batch_summary(summary)
            save_qr_batch_summary(summary, input_file)
        print("Error: No pages were scored successfully.")
        return 1

    if use_qr_aware and not explicit_output_csv:
        export_success = export_routed_results(results_data)
    else:
        export_success = export_to_csv(results_data, output_file)

    if not export_success:
        if use_qr_aware:
            update_qr_batch_result_write_status(
                results_data,
                export_success,
                output_file if explicit_output_csv else None,
            )
            summary = get_qr_batch_summary(results_data)
            print_qr_batch_summary(summary)
            save_qr_batch_summary(summary, input_file)
        print("Error: Failed to export results.")
        return 1

    if use_qr_aware:
        update_qr_batch_result_write_status(
            results_data,
            export_success,
            output_file if explicit_output_csv else None,
        )
        summary = get_qr_batch_summary(results_data)
        print_qr_batch_summary(summary)
        save_qr_batch_summary(summary, input_file)

    return 0


def run_validate_assignment(args):
    if len(args) != 1:
        print("Usage: scoreform validate-assignment <assignment_json>")
        return 1

    assignment_file = args[0]
    assignment = load_assignment(assignment_file)
    if assignment is None:
        return 1

    print("Assignment file is valid.")
    print(assignment)
    return 0


def run_validate_roster(args):
    if len(args) != 1:
        print("Usage: scoreform validate-roster <roster_csv>")
        return 1

    roster_file = args[0]
    roster = load_roster(roster_file)
    if roster is None:
        return 1

    print("Roster file is valid.")
    print(f"class_id: {roster['class_id']}")
    print(f"students: {len(roster['students'])}")
    if roster["students"]:
        print("First students:")
        for student in roster["students"][:5]:
            print(
                f"  {student['student_id']}: {student['last_name']}, {student['first_name']}"
            )
    return 0


def run_setup_assignment(args):
    if len(args) != 2:
        print("Usage: scoreform setup-assignment <assignment_json> <roster_csv>")
        return 1

    assignment_file = args[0]
    roster_file = args[1]

    assignment = load_assignment(assignment_file)
    if assignment is None:
        return 1

    roster = load_roster(roster_file)
    if roster is None:
        return 1

    setup_paths = setup_assignment_folder(roster, assignment, roster_file, assignment_file)
    if setup_paths is None:
        return 1

    print("Assignment folder setup complete.")
    print(f"Class dir: {setup_paths['class_dir']}")
    print(f"Assignment dir: {setup_paths['assignment_dir']}")
    print(f"Roster copy: {setup_paths['roster_copy']}")
    print(f"Assignment copy: {setup_paths['assignment_copy']}")
    return 0


def run_decode_qr(args):
    if len(args) != 1:
        print("Usage: scoreform decode-qr <input_file>")
        return 1

    input_file = args[0]

    if not os.path.exists(input_file):
        print(f"Error: File {input_file} does not exist.")
        return 1

    ext = os.path.splitext(input_file)[1].lower()
    found_any = False
    bad_found = False

    if ext == ".pdf":
        try:
            from pdf2image import convert_from_path
        except ImportError:
            print("Error: The 'pdf2image' module is not installed.\nPlease run: pip install pdf2image")
            return 1

        try:
            pages = convert_from_path(input_file)
        except Exception as e:
            print(f"Error while converting PDF: {e}")
            return 1

        for page_num, page in enumerate(pages, start=1):
            open_cv_image = cv2.cvtColor(np.array(page), cv2.COLOR_RGB2BGR)
            print(f"Page {page_num} QR:")
            parsed = decode_qr_from_image(open_cv_image)
            if parsed:
                found_any = True
                print(f"  class_id: {parsed.get('class_id')}")
                print(f"  assignment_id: {parsed.get('assignment_id')}")
                print(f"  student_id: {parsed.get('student_id')}")
            else:
                bad_found = True
                print(f"  No valid QR decoded on page {page_num}.")

    elif ext in [".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif"]:
        img = cv2.imread(input_file)
        if img is None:
            print(f"Error: Could not read image {input_file}")
            return 1

        parsed = decode_qr_from_image(img)
        if parsed:
            found_any = True
            print("Decoded QR:")
            print(f"  class_id: {parsed.get('class_id')}")
            print(f"  assignment_id: {parsed.get('assignment_id')}")
            print(f"  student_id: {parsed.get('student_id')}")
        else:
            print("No valid QR decoded from image.")
            return 1

    else:
        print(f"Error: Unsupported file extension '{ext}'. Please provide a PDF or an image.")
        return 1

    if not found_any:
        print("Error: No QR code could be decoded from any page or image.")
        return 1

    if bad_found:
        print("Error: At least one page contained an unreadable or malformed QR payload.")
        return 1

    return 0


def launch_generate_menu():
    """Teacher-centered generate submenu for interactive menu use."""
    try:
        while True:
            clear_screen()
            print_menu_header("Generate Answer Sheets")
            print("1. Generate answer sheets for an existing class assignment")
            print("2. Generate a generic blank template")
            print("3. Return to Assignment Management")
            print()

            choice = input("Select an option: ").strip()
            print()

            if choice == "1":
                clear_screen()
                print_menu_header("Generate Answer Sheets")
                available_classes = discover_class_rosters()
                if not available_classes:
                    print("No class rosters found. Create a class roster first from the Roster Management menu.")
                    pause_for_user()
                    return 1

                print("Available classes:")
                for index, class_record in enumerate(available_classes, start=1):
                    print(f"{index}. {class_record['class_id']}")
                print()

                try:
                    class_record = parse_single_selection(
                        input("Select class: "),
                        available_classes,
                        "class",
                    )
                except ValueError as e:
                    print(f"Error: {e}")
                    pause_for_user()
                    return 1

                class_id = class_record["class_id"]
                available_assignments = discover_class_assignments(class_id)
                if not available_assignments:
                    print(f"No assignments found for class '{class_id}'. Create an assignment first from the Assignment Management menu.")
                    pause_for_user()
                    return 1

                print()
                print(f"Available assignments for {class_id}:")
                for index, assignment_record in enumerate(available_assignments, start=1):
                    print(f"{index}. {assignment_record['assignment_id']}")
                print()

                try:
                    assignment_record = parse_single_selection(
                        input("Select assignment: "),
                        available_assignments,
                        "assignment",
                    )
                except ValueError as e:
                    print(f"Error: {e}")
                    pause_for_user()
                    return 1

                assignment_id = assignment_record["assignment_id"]
                print()
                print("Generate answer sheets for:")
                print(f"Class: {class_id}")
                print(f"Assignment: {assignment_id}")
                print()

                response = input("Generate answer sheets now? (Y/n): ").strip().lower()
                if response in ("n", "no"):
                    print("Cancelled: Answer sheet generation not confirmed.")
                    pause_for_user()
                    return 1

                result = run_generate([
                    assignment_record["assignment_path"],
                    "--rosters",
                    class_record["roster_path"],
                ])
                pause_for_user()
                return result

            elif choice == "2":
                clear_screen()
                print_menu_header("Generate a Generic Blank Template")
                result = run_generate([])
                pause_for_user()
                return result

            elif choice == "3":
                return 0

            else:
                print(f"Invalid selection: {choice}. Please enter a number from 1 to 3.")
                print()
                pause_for_user()

    except KeyboardInterrupt:
        print("\nExiting generate menu.")
        return 0


def prompt_select_scan_from_inbox(scans_dir=None):
    """Prompt for one supported scan file from scans_dir."""
    if scans_dir is None:
        workspace_root = workspace.get_scoreform_workspace_root()
        scans_dir = os.fspath(scans_inbox_dir(workspace_root))

    clear_screen()
    print_menu_header("Select a Scan")
    scans = discover_scans_in_inbox(scans_dir)
    if not scans:
        print(f"No scans found in {scans_dir}.")
        print(f"Place scanned PDFs or images in {scans_dir}, then try again.")
        print()
        pause_for_user()
        return None

    print(f"Available scans in {scans_dir}:")
    print()
    for index, scan_path in enumerate(scans, start=1):
        print(f"{index}. {os.path.basename(scan_path)}")
    print()

    try:
        return parse_single_selection(input("Select scan: "), scans, "scan")
    except ValueError as e:
        print()
        print(f"Error: {e}")
        print()
        pause_for_user()
        return None


def prompt_scoring_input_file():
    """Prompt for the input scan path used by interactive menu scoring."""
    while True:
        clear_screen()
        print_menu_header("Score Scanned Responses")
        print("1. Choose a file from scans_inbox")
        print("2. Enter a custom path")
        print("3. Return to Assignment Management")
        print()

        choice = input("Select an option: ").strip()
        print()

        if choice == "1":
            selected_scan = prompt_select_scan_from_inbox()
            if selected_scan:
                print()
                print("Selected scan:")
                print(selected_scan)
                print()
                return selected_scan

        elif choice == "2":
            clear_screen()
            print_menu_header("Score Scanned Responses")
            input_file = normalize_path_input(input("Input scan/PDF/image path: "))
            if not input_file:
                print("Input file path is required.")
                print()
                pause_for_user()
                continue
            return input_file

        elif choice == "3":
            return None

        else:
            print(f"Invalid selection: {choice}. Please enter a number from 1 to 3.")
            print()
            pause_for_user()


def run_menu_qr_aware_routed_scoring(input_file):
    """Run the menu's recommended QR-aware routed scoring workflow."""
    clear_screen()
    print_menu_header("QR-Aware Routed Scoring")
    print("Using QR-aware routed scoring.")
    print("Results will be routed using QR metadata.")
    print()
    run_score([input_file])
    print()
    pause_for_user()


def run_menu_manual_scoring(input_file):
    """Run manual menu scoring with a required answer key."""
    clear_screen()
    print_menu_header("Manual Scoring with Answer Key")
    print("Selected scan:")
    print(input_file)
    print()

    answer_key = normalize_path_input(input("Answer key JSON path: "))
    if not answer_key:
        print()
        print("Answer key JSON path is required for manual scoring.")
        print()
        pause_for_user()
        return False

    output_csv = normalize_path_input(input("Output CSV path (blank for default local results): "))

    if output_csv:
        args = [input_file, output_csv, answer_key]
    else:
        args = [input_file, answer_key]

    run_score(args)
    print()
    pause_for_user()
    return True


def prompt_scoring_mode(input_file):
    """Prompt for QR-aware routed or manual scoring after a scan is selected."""
    while True:
        clear_screen()
        print_menu_header("Select Scoring Mode")
        print("Selected scan:")
        print(input_file)
        print()
        print("Scoring mode:")
        print()
        print("1. QR-aware routed scoring (recommended)")
        print("2. Manual scoring with answer key")
        print("3. Return to Assignment Management")
        print()

        choice = input("Select an option: ").strip()
        print()

        if choice == "1":
            run_menu_qr_aware_routed_scoring(input_file)
            return

        if choice == "2":
            if run_menu_manual_scoring(input_file):
                return
            continue

        if choice == "3":
            return

        print(f"Invalid selection: {choice}. Please enter a number from 1 to 3.")
        print()
        pause_for_user()


def launch_workspace_menu():
    """Workspace settings submenu for the shared PDS workspace root."""
    try:
        while True:
            clear_screen()
            print_menu_header("Workspace Settings")
            print("1. Show current workspace")
            print("2. Set workspace folder")
            print("3. Validate/create current workspace")
            print("4. Reset saved workspace preference")
            print("5. Back")
            print()

            choice = input("Select an option: ").strip()
            print()

            if choice == "1":
                clear_screen()
                print_menu_header("Current Workspace")
                run_workspace(["show"])
                print()
                pause_for_user()

            elif choice == "2":
                clear_screen()
                print_menu_header("Set Workspace Folder")
                workspace_path = normalize_path_input(
                    input("Workspace folder path (blank to cancel): ")
                )
                if not workspace_path:
                    print("Cancelled: Workspace folder was not changed.")
                else:
                    run_workspace(["set", workspace_path])
                print()
                pause_for_user()

            elif choice == "3":
                clear_screen()
                print_menu_header("Validate Current Workspace")
                run_workspace(["validate"])
                print()
                pause_for_user()

            elif choice == "4":
                clear_screen()
                print_menu_header("Reset Workspace Preference")
                run_workspace(["reset"])
                print()
                pause_for_user()

            elif choice == "5":
                return 0

            else:
                print(f"Invalid selection: {choice}. Please enter a number from 1 to 5.")
                print()
                pause_for_user()

    except KeyboardInterrupt:
        print("\nExiting workspace settings.")
        return 0


def launch_menu():
    try:
        while True:
            clear_screen()
            print_menu_header("Main Menu")
            print("1. Assignment Management")
            print("2. Roster Management")
            print("3. Workspace Settings")
            print("4. Help")
            print("5. Exit")

            choice = input("Select an option: ").strip()
            print()

            if choice == "1":
                launch_assignment_menu()

            elif choice == "2":
                launch_roster_menu()

            elif choice == "3":
                launch_workspace_menu()

            elif choice == "4":
                clear_screen()
                print_menu_help()
                pause_for_user()

            elif choice == "5":
                print("Goodbye.")
                return 0

            else:
                print(f"Invalid selection: {choice}. Please enter a number from 1 to 5.")
                print()
                pause_for_user()

    except KeyboardInterrupt:
        print("\nExiting menu.")
        return 0


def main(argv=None, default_to_menu=True):
    """Main CLI entry point.

    Args:
        argv: Command-line arguments. If None, sys.argv[1:] is used.
        default_to_menu: If True and no command is provided, launch the menu.
                         If False, print usage.
    """
    if argv is None:
        argv = sys.argv[1:]

    if not argv:
        if default_to_menu:
            return launch_menu()
        print_help()
        return 1

    cmd = argv[0]
    args = argv[1:]

    if cmd in ("--help", "-h", "help"):
        print_help()
        return 0
    elif cmd in ("--version", "version"):
        print_version()
        return 0
    elif cmd == "menu":
        return launch_menu()
    elif cmd == "generate":
        return run_generate(args)
    elif cmd == "score":
        return run_score(args)
    elif cmd == "validate-assignment":
        return run_validate_assignment(args)
    elif cmd == "validate-roster":
        return run_validate_roster(args)
    elif cmd == "setup-assignment":
        return run_setup_assignment(args)
    elif cmd == "decode-qr":
        return run_decode_qr(args)
    elif cmd == "workspace":
        return run_workspace(args)
    else:
        print(f"Unknown command: {cmd}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main(default_to_menu=True))
