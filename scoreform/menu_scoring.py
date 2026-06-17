"""Interactive scan/menu scoring workflows for ScoreForm."""

import os

from pds_core.scan_routes import scans_inbox_dir

from scoreform import workspace
from scoreform.cli_score import run_score
from scoreform.workflows import (
    clear_screen,
    discover_scans_in_inbox,
    normalize_path_input,
    parse_single_selection,
    pause_for_user,
    print_menu_header,
)


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

    output_csv = normalize_path_input(
        input("Output CSV path (blank for default local results): ")
    )

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
