"""Task-oriented Assignment Management navigation for ScoreForm teachers."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from pds_core.menu_navigation import NavigationChoice

from scoreform import workflows
from scoreform.assignment_context import AssignmentContextSession
from scoreform.menu_assignment_context import (
    format_active_context_lines,
    launch_assignment_context_menu,
)
from scoreform.menu_navigation import (
    parse_scoreform_navigation,
    print_invalid_navigation,
    print_scoreform_navigation_options,
)
from scoreform.workflows import normalize_path_input, print_menu_header

UiCallback = Callable[[], None]


def _menu_choice(
    title: str,
    options: Sequence[str],
    *,
    clear_screen_fn: UiCallback,
    intro: Sequence[str] = (),
    extra_options: Sequence[str] = (),
) -> str:
    """Render one controlled task menu and return the raw teacher selection."""
    clear_screen_fn()
    print_menu_header(title)
    for line in intro:
        print(line)
    if intro:
        print()
    for option in options:
        print(option)
    for option in extra_options:
        print(option)
    print_scoreform_navigation_options()
    print()
    return input("Select an option: ").strip()


def _invalid(choice: str, *, pause_for_user_fn: UiCallback) -> None:
    print(f"Invalid selection: {choice}.")
    print_invalid_navigation()
    print()
    pause_for_user_fn()


def _run_create_assignment(
    *,
    clear_screen_fn: UiCallback,
    pause_for_user_fn: UiCallback,
    context_session: AssignmentContextSession | None = None,
) -> None:
    from scoreform.assignment_workflows import prompt_create_assignment

    clear_screen_fn()
    prompt_create_assignment(context_session=context_session)
    print()
    pause_for_user_fn()


def _run_copy_assignment(
    *,
    clear_screen_fn: UiCallback,
    pause_for_user_fn: UiCallback,
    context_session: AssignmentContextSession | None = None,
) -> None:
    from scoreform.menu_assignment_copy import prompt_copy_assignment

    clear_screen_fn()
    prompt_copy_assignment(context_session=context_session)
    print()
    pause_for_user_fn()


def _run_edit_assignment(
    *,
    clear_screen_fn: UiCallback,
    pause_for_user_fn: UiCallback,
    context_session: AssignmentContextSession | None = None,
) -> None:
    from scoreform.assignment_workflows import prompt_edit_assignment

    clear_screen_fn()
    prompt_edit_assignment(context_session=context_session)
    print()
    pause_for_user_fn()


def _run_assignment_presets(
    *,
    clear_screen_fn: UiCallback,
    pause_for_user_fn: UiCallback,
    context_session: AssignmentContextSession | None = None,
) -> None:
    del clear_screen_fn, pause_for_user_fn
    from scoreform.menu_assignment_presets import launch_assignment_presets_menu

    launch_assignment_presets_menu(context_session=context_session)


def _run_print_answer_sheets(
    *,
    clear_screen_fn: UiCallback,
    pause_for_user_fn: UiCallback,
    context_session: AssignmentContextSession | None = None,
) -> None:
    del clear_screen_fn, pause_for_user_fn
    from scoreform.generate_workflows import launch_generate_menu

    launch_generate_menu(context_session=context_session)


def _run_score_scans(
    *,
    clear_screen_fn: UiCallback,
    pause_for_user_fn: UiCallback,
    context_session: AssignmentContextSession | None = None,
) -> None:
    del clear_screen_fn, pause_for_user_fn
    from scoreform import menu_scoring

    session = (
        AssignmentContextSession() if context_session is None else context_session
    )
    input_file = menu_scoring.prompt_scoring_input_file()
    if input_file:
        menu_scoring.prompt_scoring_mode(
            input_file,
            context_session=session,
        )


def _run_scan_review(
    *, clear_screen_fn: UiCallback, pause_for_user_fn: UiCallback
) -> None:
    del clear_screen_fn, pause_for_user_fn
    from scoreform.menu_scan_review import launch_scan_review_menu

    launch_scan_review_menu()


def _run_review_results(
    *,
    clear_screen_fn: UiCallback,
    pause_for_user_fn: UiCallback,
    context_session: AssignmentContextSession | None = None,
) -> None:
    from scoreform.assignment_workflows import launch_view_assignment_results_menu

    clear_screen_fn()
    launch_view_assignment_results_menu(context_session=context_session)
    print()
    pause_for_user_fn()


def _run_plain_paper_results(
    *,
    clear_screen_fn: UiCallback,
    pause_for_user_fn: UiCallback,
    context_session: AssignmentContextSession | None = None,
) -> None:
    del clear_screen_fn, pause_for_user_fn
    from scoreform.menu_manual_entry import launch_manual_entry_menu

    launch_manual_entry_menu(context_session=context_session)


def _run_share_results_with_meridian(
    *,
    clear_screen_fn: UiCallback,
    pause_for_user_fn: UiCallback,
    context_session: AssignmentContextSession | None = None,
) -> None:
    from scoreform.menu_share_results import launch_share_results_with_meridian

    launch_share_results_with_meridian(
        clear_screen_fn=clear_screen_fn,
        context_session=context_session,
    )
    print()
    pause_for_user_fn()



def _run_academic_work_registration(
    *,
    clear_screen_fn: UiCallback,
    pause_for_user_fn: UiCallback,
    context_session: AssignmentContextSession | None = None,
) -> None:
    del clear_screen_fn, pause_for_user_fn
    from scoreform.menu_academic_work import launch_academic_work_registration_menu

    launch_academic_work_registration_menu(context_session=context_session)


def _run_academic_result_manifests(
    *,
    clear_screen_fn: UiCallback,
    pause_for_user_fn: UiCallback,
    context_session: AssignmentContextSession | None = None,
) -> None:
    del clear_screen_fn, pause_for_user_fn
    from scoreform.menu_manifest import launch_academic_result_manifests_menu

    launch_academic_result_manifests_menu(context_session=context_session)


def _run_academic_result_publications(
    *,
    clear_screen_fn: UiCallback,
    pause_for_user_fn: UiCallback,
    context_session: AssignmentContextSession | None = None,
) -> None:
    del clear_screen_fn, pause_for_user_fn
    from scoreform.menu_publication import launch_academic_result_publications_menu

    launch_academic_result_publications_menu(context_session=context_session)


def _run_validate_assignment_file(
    *, clear_screen_fn: UiCallback, pause_for_user_fn: UiCallback
) -> None:
    from scoreform.assignment import load_assignment

    clear_screen_fn()
    print_menu_header("Validate an Assignment File")
    assignment_path = normalize_path_input(input("Assignment JSON path: "))
    if not assignment_path:
        print("Assignment file path is required.")
        print()
        pause_for_user_fn()
        return

    assignment = load_assignment(assignment_path)
    if assignment is not None:
        print("Assignment file is valid.")
        print(assignment)
    print()
    pause_for_user_fn()


def _run_decode_qr_file(
    *, clear_screen_fn: UiCallback, pause_for_user_fn: UiCallback
) -> None:
    from scoreform.qr_workflows import run_decode_qr

    clear_screen_fn()
    print_menu_header("Decode QR from a File")
    input_file = normalize_path_input(input("File path: "))
    if not input_file:
        print("File path is required.")
        print()
        pause_for_user_fn()
        return

    run_decode_qr([input_file])
    print()
    pause_for_user_fn()


def launch_assessment_definition_menu(
    *,
    clear_screen_fn: UiCallback | None = None,
    pause_for_user_fn: UiCallback | None = None,
    context_session: AssignmentContextSession | None = None,
) -> int:
    """Group assignment definition/reuse tasks without owning their semantics."""
    clear = workflows.clear_screen if clear_screen_fn is None else clear_screen_fn
    pause = workflows.pause_for_user if pause_for_user_fn is None else pause_for_user_fn

    while True:
        choice = _menu_choice(
            "Create / Copy / Edit Assessments",
            (
                "1. Create an assignment",
                "2. Copy an assignment",
                "3. Edit an assignment",
                "4. Assessment setup presets",
            ),
            clear_screen_fn=clear,
        )
        navigation = parse_scoreform_navigation(choice)
        if navigation is NavigationChoice.BACK:
            return 0

        if choice == "1":
            _run_create_assignment(
                clear_screen_fn=clear,
                pause_for_user_fn=pause,
                context_session=context_session,
            )
        elif choice == "2":
            _run_copy_assignment(
                clear_screen_fn=clear,
                pause_for_user_fn=pause,
                context_session=context_session,
            )
        elif choice == "3":
            _run_edit_assignment(
                clear_screen_fn=clear,
                pause_for_user_fn=pause,
                context_session=context_session,
            )
        elif choice == "4":
            _run_assignment_presets(
                clear_screen_fn=clear,
                pause_for_user_fn=pause,
                context_session=context_session,
            )
        else:
            _invalid(choice, pause_for_user_fn=pause)


def launch_process_scans_menu(
    *,
    clear_screen_fn: UiCallback | None = None,
    pause_for_user_fn: UiCallback | None = None,
    context_session: AssignmentContextSession | None = None,
) -> int:
    """Group scan processing while preserving one shared assignment context."""
    clear = workflows.clear_screen if clear_screen_fn is None else clear_screen_fn
    pause = workflows.pause_for_user if pause_for_user_fn is None else pause_for_user_fn

    while True:
        choice = _menu_choice(
            "Process Scans",
            (
                "1. Score scanned responses",
                "2. Resolve scan review items",
            ),
            clear_screen_fn=clear,
        )
        navigation = parse_scoreform_navigation(choice)
        if navigation is NavigationChoice.BACK:
            return 0

        if choice == "1":
            _run_score_scans(
                clear_screen_fn=clear,
                pause_for_user_fn=pause,
                context_session=context_session,
            )
        elif choice == "2":
            _run_scan_review(clear_screen_fn=clear, pause_for_user_fn=pause)
        else:
            _invalid(choice, pause_for_user_fn=pause)


def launch_share_results_menu(
    *,
    clear_screen_fn: UiCallback | None = None,
    pause_for_user_fn: UiCallback | None = None,
    context_session: AssignmentContextSession | None = None,
) -> int:
    """Offer the common guided share journey plus exact advanced workflows."""
    clear = workflows.clear_screen if clear_screen_fn is None else clear_screen_fn
    pause = workflows.pause_for_user if pause_for_user_fn is None else pause_for_user_fn

    while True:
        choice = _menu_choice(
            "Share Results",
            (
                "1. Share Results with Meridian",
                "2. Academic Work Registration",
                "3. Academic Result Manifests",
                "4. Academic Result Publications",
            ),
            clear_screen_fn=clear,
            intro=(
                "The guided action publishes ScoreForm evidence through Core so "
                "Meridian can consume it.",
                "Advanced exact registration, manifest, and publication operations "
                "remain available below.",
            ),
        )
        navigation = parse_scoreform_navigation(choice)
        if navigation is NavigationChoice.BACK:
            return 0

        if choice == "1":
            _run_share_results_with_meridian(
                clear_screen_fn=clear,
                pause_for_user_fn=pause,
                context_session=context_session,
            )
        elif choice == "2":
            _run_academic_work_registration(
                clear_screen_fn=clear,
                pause_for_user_fn=pause,
                context_session=context_session,
            )
        elif choice == "3":
            _run_academic_result_manifests(
                clear_screen_fn=clear,
                pause_for_user_fn=pause,
                context_session=context_session,
            )
        elif choice == "4":
            _run_academic_result_publications(
                clear_screen_fn=clear,
                pause_for_user_fn=pause,
                context_session=context_session,
            )
        else:
            _invalid(choice, pause_for_user_fn=pause)


def launch_advanced_tools_menu(
    *,
    clear_screen_fn: UiCallback | None = None,
    pause_for_user_fn: UiCallback | None = None,
) -> int:
    """Keep low-frequency validation and QR diagnostics reachable but bounded."""
    clear = workflows.clear_screen if clear_screen_fn is None else clear_screen_fn
    pause = workflows.pause_for_user if pause_for_user_fn is None else pause_for_user_fn

    while True:
        choice = _menu_choice(
            "Advanced Tools",
            (
                "1. Validate an assignment file",
                "2. Decode QR from a file",
            ),
            clear_screen_fn=clear,
        )
        navigation = parse_scoreform_navigation(choice)
        if navigation is NavigationChoice.BACK:
            return 0

        if choice == "1":
            _run_validate_assignment_file(
                clear_screen_fn=clear, pause_for_user_fn=pause
            )
        elif choice == "2":
            _run_decode_qr_file(clear_screen_fn=clear, pause_for_user_fn=pause)
        else:
            _invalid(choice, pause_for_user_fn=pause)


def launch_assignment_menu(
    *,
    clear_screen_fn: UiCallback | None = None,
    pause_for_user_fn: UiCallback | None = None,
    context_session: AssignmentContextSession | None = None,
) -> int:
    """Launch Assignment Management around bounded, recognizable teacher tasks."""
    clear = workflows.clear_screen if clear_screen_fn is None else clear_screen_fn
    pause = workflows.pause_for_user if pause_for_user_fn is None else pause_for_user_fn
    session = (
        AssignmentContextSession() if context_session is None else context_session
    )

    try:
        while True:
            choice = _menu_choice(
                "Assignment Management",
                (
                    "1. Create / Copy / Edit Assessments",
                    "2. Print Answer Sheets",
                    "3. Process Scans",
                    "4. Review Results",
                    "5. Enter Plain-Paper Results",
                    "6. Share Results",
                    "7. Advanced Tools",
                ),
                clear_screen_fn=clear,
                intro=format_active_context_lines(session),
                extra_options=("C. Assignment Context",),
            )
            navigation = parse_scoreform_navigation(choice)
            if navigation is NavigationChoice.BACK:
                return 0
            if choice.lower() == "c":
                launch_assignment_context_menu(
                    session,
                    clear_screen_fn=clear,
                    pause_for_user_fn=pause,
                )
                continue

            if choice == "1":
                launch_assessment_definition_menu(
                    clear_screen_fn=clear,
                    pause_for_user_fn=pause,
                    context_session=session,
                )
            elif choice == "2":
                _run_print_answer_sheets(
                    clear_screen_fn=clear,
                    pause_for_user_fn=pause,
                    context_session=session,
                )
            elif choice == "3":
                launch_process_scans_menu(
                    clear_screen_fn=clear,
                    pause_for_user_fn=pause,
                    context_session=session,
                )
            elif choice == "4":
                _run_review_results(
                    clear_screen_fn=clear,
                    pause_for_user_fn=pause,
                    context_session=session,
                )
            elif choice == "5":
                _run_plain_paper_results(
                    clear_screen_fn=clear,
                    pause_for_user_fn=pause,
                    context_session=session,
                )
            elif choice == "6":
                launch_share_results_menu(
                    clear_screen_fn=clear,
                    pause_for_user_fn=pause,
                    context_session=session,
                )
            elif choice == "7":
                launch_advanced_tools_menu(
                    clear_screen_fn=clear, pause_for_user_fn=pause
                )
            else:
                _invalid(choice, pause_for_user_fn=pause)
    except KeyboardInterrupt:
        print("\nExiting assignment menu.")
        return 0
