"""Continuous teacher workflow from retained scan processing to useful next actions."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from pds_core.menu_navigation import NavigationChoice

from scoreform import workspace
from scoreform.assignment_context import AssignmentContextSession
from scoreform.cli_score import execute_routed_scoring_operation
from scoreform.guided_scan_context import (
    open_guided_result_target,
    select_guided_result_target,
)
from scoreform.guided_scan_results import (
    GuidedScanSummary,
    build_guided_scan_summary,
    format_guided_scan_summary,
    safe_scan_source_filename,
)
from scoreform.menu_navigation import (
    parse_scoreform_navigation,
    print_invalid_navigation,
    print_scoreform_navigation_options,
)
from scoreform.menu_scan_review import launch_scan_review_menu
from scoreform.workflows import clear_screen, pause_for_user, print_menu_header

UiCallback = Callable[[], None]


def _next_actions(summary: GuidedScanSummary) -> tuple[tuple[str, str], ...]:
    actions: list[tuple[str, str]] = []
    if summary.targets:
        actions.append(("results", "Review recorded assignment results"))
    if summary.source_scan_id is not None and summary.review_items_persisted:
        actions.append(("review", "Review unresolved items from this scan"))
    actions.append(("return", "Return to Process Scans"))
    return tuple(actions)


def _print_durable_state_notice(summary: GuidedScanSummary) -> None:
    if not summary.retention_succeeded:
        return
    print()
    print(
        "Processing has already created durable state where reported above. "
        "Returning does not delete retained evidence, results, or review records."
    )


def launch_guided_scan_to_results(
    input_file: str | Path,
    *,
    context_session: AssignmentContextSession,
    clear_screen_fn: UiCallback | None = None,
    pause_for_user_fn: UiCallback | None = None,
) -> int:
    """Process one retained PDS2 scan once, then guide review/results continuity."""

    if not isinstance(context_session, AssignmentContextSession):
        raise TypeError("context_session must be an AssignmentContextSession.")

    clear = clear_screen if clear_screen_fn is None else clear_screen_fn
    pause = pause_for_user if pause_for_user_fn is None else pause_for_user_fn
    root = workspace.get_scoreform_workspace_root()

    clear()
    print_menu_header("Process a Retained PDS2 Scan")
    print(f"Selected scan: {safe_scan_source_filename(input_file)}")
    print()
    print("Core will retain the source before dispatch.")
    print(
        "Complete ScoreForm attempts will use the existing assembly, export, "
        "idempotency, and review contracts."
    )
    print()

    operation = execute_routed_scoring_operation(
        input_file,
        workspace_root=root,
    )
    summary = build_guided_scan_summary(operation, input_file)

    while True:
        clear()
        print_menu_header("Scan Processing Summary")
        print(format_guided_scan_summary(summary))
        _print_durable_state_notice(summary)
        print()

        actions = _next_actions(summary)
        for index, (_action, label) in enumerate(actions, start=1):
            print(f"{index}. {label}")
        print_scoreform_navigation_options()
        print()

        selection = input("Select an option: ").strip()
        navigation = parse_scoreform_navigation(selection)
        if navigation is NavigationChoice.BACK:
            return operation.exit_code

        if not selection.isdigit() or not 1 <= int(selection) <= len(actions):
            print(f"Invalid selection: {selection}.")
            print_invalid_navigation()
            print()
            pause()
            continue

        action = actions[int(selection) - 1][0]
        if action == "return":
            return operation.exit_code

        if action == "results":
            target = select_guided_result_target(
                summary.targets,
                clear_screen_fn=clear,
            )
            if target is None:
                continue
            clear()
            status = open_guided_result_target(
                context_session,
                target,
                workspace_root=root,
            )
            print()
            pause()
            if status != 0:
                continue

        elif action == "review":
            assert summary.source_scan_id is not None
            launch_scan_review_menu(source_scan_id=summary.source_scan_id)
