"""Command-line interface for ScoreForm."""

import os
import sys

from pds_core.scan_routes import scans_inbox_dir  # noqa: F401 - compatibility re-export
from pds_core.school_years import (
    SchoolYearStateError,
    close_school_year,
    load_school_year_state,
    open_school_year,
)

from scoreform import generate_workflows as _generate_workflows
from scoreform import menu_scoring as _menu_scoring
from scoreform import qr_workflows as _qr_workflows
from scoreform import workspace
from scoreform.assignment import load_assignment
from scoreform.assignment_workflows import launch_assignment_menu
from scoreform.cli_help import (
    get_version,  # noqa: F401 - compatibility re-export
    print_help,
    print_menu_help,
    print_version,
)
from scoreform.cli_school_year import (
    _format_school_year_timestamp,
    _print_school_year_open_success,
    current_local_time,
    format_school_year_state,  # noqa: F401 - compatibility re-export
    print_school_year_help,  # noqa: F401 - compatibility re-export
    run_school_year,
)
from scoreform.cli_score import run_score
from scoreform.cli_workspace import (
    print_workspace_help,  # noqa: F401 - compatibility re-export
    run_workspace,
)
from scoreform.folders import setup_assignment_folder
from scoreform.roster import load_roster
from scoreform.roster_workflows import launch_roster_menu
from scoreform.scoring import (
    decode_qr_from_image,  # noqa: F401 - compatibility re-export
)
from scoreform.templates import (
    generate_class_packet_pdf,  # noqa: F401 - compatibility re-export
    generate_student_pdf,  # noqa: F401 - compatibility re-export
    generate_template,  # noqa: F401 - compatibility re-export
)
from scoreform.workflows import (
    discover_class_assignments,  # noqa: F401 - compatibility re-export
    discover_class_rosters,  # noqa: F401 - compatibility re-export
    discover_scans_in_inbox,  # noqa: F401 - compatibility re-export
    normalize_path_input,
    parse_single_selection,  # noqa: F401 - compatibility re-export
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


def prompt_select_scan_from_inbox(scans_dir=None):
    """Compatibility wrapper for interactive scan inbox selection."""
    return _menu_scoring.prompt_select_scan_from_inbox(scans_dir)


def prompt_scoring_input_file():
    """Compatibility wrapper for interactive scan path selection."""
    return _menu_scoring.prompt_scoring_input_file()


def run_menu_qr_aware_routed_scoring(input_file):
    """Compatibility wrapper for QR-aware menu scoring."""
    return _menu_scoring.run_menu_qr_aware_routed_scoring(input_file)


def run_menu_manual_scoring(input_file):
    """Compatibility wrapper for manual menu scoring."""
    return _menu_scoring.run_menu_manual_scoring(input_file)


def prompt_scoring_mode(input_file):
    """Compatibility wrapper for selecting the interactive scoring mode."""
    return _menu_scoring.prompt_scoring_mode(input_file)


def run_generate(args):
    """Compatibility wrapper for direct generate command dispatch."""
    return _generate_workflows.run_generate(args)


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
    """Compatibility wrapper for direct QR decode command dispatch."""
    return _qr_workflows.run_decode_qr(args)


def launch_generate_menu():
    """Teacher-centered generate submenu for interactive menu use."""
    return _generate_workflows.launch_generate_menu()


def launch_school_year_menu():
    """School-year settings submenu for the shared PDS workspace state."""
    try:
        while True:
            clear_screen()
            print_menu_header("School Year Settings")
            print("1. Show school year status")
            print("2. Open school year")
            print("3. Close school year")
            print("4. Back")
            print()

            choice = input("Select an option: ").strip()
            print()

            if choice == "1":
                clear_screen()
                print_menu_header("School Year Status")
                run_school_year(["show"])
                print()
                pause_for_user()

            elif choice == "2":
                clear_screen()
                print_menu_header("Open School Year")
                school_year = input("School year to open (YYYY-YYYY): ").strip()
                if not school_year:
                    print("Cancelled: School year was not opened.")
                    print()
                    pause_for_user()
                    continue

                try:
                    workspace_root = workspace.get_scoreform_workspace_root()
                    existing_state = load_school_year_state(workspace_root)
                    overwrite = False
                    if (
                        existing_state is not None
                        and existing_state.closed_at is None
                        and existing_state.active_school_year != school_year
                    ):
                        print()
                        print(
                            "A different school year is already open: "
                            f"{existing_state.active_school_year}"
                        )
                        print(
                            f"Opening {school_year} will replace the active "
                            "school-year state."
                        )
                        print("This will not delete or archive any data.")
                        print()
                        confirmation = input("Type OVERWRITE to confirm: ").strip()
                        if confirmation != "OVERWRITE":
                            print("Cancelled: School-year overwrite not confirmed.")
                            print()
                            pause_for_user()
                            continue
                        overwrite = True

                    opened_state = open_school_year(
                        workspace_root,
                        school_year,
                        opened_at=current_local_time(),
                        overwrite=overwrite,
                    )
                    _print_school_year_open_success(
                        workspace_root,
                        school_year,
                        existing_state,
                        opened_state,
                        overwrite,
                    )
                except (SchoolYearStateError, workspace.WorkspaceRootError) as exc:
                    print(f"Error: {exc}")
                print()
                pause_for_user()

            elif choice == "3":
                clear_screen()
                print_menu_header("Close School Year")
                try:
                    workspace_root = workspace.get_scoreform_workspace_root()
                    existing_state = load_school_year_state(workspace_root)
                    if existing_state is None or existing_state.closed_at is not None:
                        print("No school year is currently open.")
                        print()
                        pause_for_user()
                        continue

                    print(f"Active school year: {existing_state.active_school_year}")
                    print()
                    print(
                        "Closing the school year will make it inactive for future "
                        "workflows."
                    )
                    print("This will not delete, archive, summarize, or move any data.")
                    print()
                    confirmation = input("Type CLOSE to confirm: ").strip()
                    if confirmation != "CLOSE":
                        print("Cancelled: School-year close not confirmed.")
                        print()
                        pause_for_user()
                        continue

                    closed_state = close_school_year(
                        workspace_root,
                        closed_at=current_local_time(),
                    )
                    print(f"Closed school year: {closed_state.active_school_year}")
                    print(
                        "Closed at: "
                        f"{_format_school_year_timestamp(closed_state.closed_at)}"
                    )
                except (SchoolYearStateError, workspace.WorkspaceRootError) as exc:
                    print(f"Error: {exc}")
                print()
                pause_for_user()

            elif choice == "4":
                return 0

            else:
                print(f"Invalid selection: {choice}. Please enter a number from 1 to 4.")
                print()
                pause_for_user()

    except KeyboardInterrupt:
        print("\nExiting school year settings.")
        return 0


def launch_workspace_menu():
    """Workspace settings submenu for the shared PDS workspace root."""
    try:
        while True:
            clear_screen()
            print_menu_header("Workspace Settings")
            print("1. Show current workspace")
            print("2. Set workspace folder")
            print("3. Validate/create current workspace")
            print("4. School year settings")
            print("5. Reset saved workspace preference")
            print("6. Back")
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
                launch_school_year_menu()

            elif choice == "5":
                clear_screen()
                print_menu_header("Reset Workspace Preference")
                run_workspace(["reset"])
                print()
                pause_for_user()

            elif choice == "6":
                return 0

            else:
                print(f"Invalid selection: {choice}. Please enter a number from 1 to 6.")
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
    elif cmd == "school-year":
        return run_school_year(args)
    else:
        print(f"Unknown command: {cmd}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main(default_to_menu=True))
