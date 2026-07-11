"""Teacher-facing workspace menu for ScoreForm scan filing settings."""

from pds_core.menu_navigation import NavigationChoice

from scoreform.menu_navigation import (
    parse_scoreform_navigation,
    print_invalid_navigation,
    print_scoreform_navigation_options,
)
from scoreform.scan_filing_settings import (
    ScoreFormSettingsError,
    inspect_scan_filing_settings,
    reset_scan_filing_mode,
    set_scan_filing_mode,
)
from scoreform.workflows import clear_screen, pause_for_user, print_menu_header


def _show_result(message):
    clear_screen()
    print_menu_header("ScoreForm Scan Filing Mode")
    print(message)
    print()
    pause_for_user()


def _set_mode(mode):
    try:
        settings = set_scan_filing_mode(mode)
    except ScoreFormSettingsError as error:
        _show_result(f"Could not update ScoreForm settings safely: {error}")
        return
    _show_result(f"Scan filing mode set to: {settings.effective_mode}")


def _confirm_move_mode():
    clear_screen()
    print_menu_header("Confirm Move Mode")
    print("Move mode only removes the original when it is a direct child of scans_inbox.")
    print("Custom paths, Downloads, OneDrive, and nested folders are preserved.")
    print()
    return input("Type MOVE to confirm: ").strip() == "MOVE"


def launch_scan_filing_menu():
    """Inspect and change the workspace's ScoreForm scan filing mode."""
    while True:
        clear_screen()
        settings = inspect_scan_filing_settings()
        print_menu_header("ScoreForm Scan Filing Mode")
        print(f"Current mode: {settings.effective_mode}")
        if settings.warning:
            print("Warning: saved settings are invalid; using copy.")
        print()
        print("1. copy - file a scored-copy and preserve the original")
        print("2. move - file a scored-copy, then remove a safe scans_inbox original")
        print("3. off  - do not file automatic scored-copies")
        print("4. reset to default")
        print_scoreform_navigation_options()
        print()

        choice = input("Select an option: ").strip()
        navigation = parse_scoreform_navigation(choice)
        if navigation is NavigationChoice.BACK or choice == "5":
            return 0

        if choice == "1":
            _set_mode("copy")
        elif choice == "2":
            if _confirm_move_mode():
                _set_mode("move")
            else:
                _show_result("Move mode was not enabled. The previous mode is unchanged.")
        elif choice == "3":
            _set_mode("off")
        elif choice == "4":
            try:
                reset_scan_filing_mode()
            except ScoreFormSettingsError as error:
                _show_result(f"Could not update ScoreForm settings safely: {error}")
            else:
                _show_result("Scan filing mode reset. Effective mode: copy")
        else:
            print()
            print(f"Invalid selection: {choice}.")
            print_invalid_navigation()
            print()
            pause_for_user()
