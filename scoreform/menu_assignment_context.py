"""Teacher-facing selection and management for ScoreForm assignment context."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from pds_core.menu_navigation import NavigationChoice

from scoreform import workflows, workspace
from scoreform.assignment_context import (
    AssignmentContextSession,
    assignment_context_ref_from_record,
    resolve_active_assignment_context,
    resolve_recent_assignment_contexts,
)
from scoreform.menu_navigation import (
    parse_scoreform_navigation,
    print_invalid_navigation,
    print_scoreform_navigation_options,
)
from scoreform.workflows import parse_single_selection, print_menu_header

UiCallback = Callable[[], None]


def _title_for_record(record: dict[str, Any]) -> str:
    assignment = record.get("assignment")
    if isinstance(assignment, dict):
        title = assignment.get("title")
        if isinstance(title, str):
            return title
    return ""


def format_active_context_lines(
    session: AssignmentContextSession,
) -> tuple[str, ...]:
    """Return a compact privacy-safe banner for Assignment Management."""
    if session.active is None:
        return ("Active assignment: none",)

    outcome = resolve_active_assignment_context(session)
    if outcome is None or not outcome.is_valid or outcome.record is None:
        reason = (
            outcome.stale_reason
            if outcome is not None and outcome.stale_reason
            else "The previous assignment context is no longer available."
        )
        return ("Active assignment: none", f"Context notice: {reason}")

    record = outcome.record
    title = _title_for_record(record)
    suffix = f" — {title}" if title else ""
    return (
        f"Active assignment: {outcome.ref.class_id} / "
        f"{outcome.ref.assignment_id}{suffix}",
    )


def _select_class(
    *,
    workspace_root: str | Path,
    clear_screen_fn: UiCallback,
    notice: str | None = None,
) -> dict[str, Any] | None:
    classes = workflows.discover_class_rosters(workspace_root=workspace_root)
    if not classes:
        clear_screen_fn()
        print_menu_header("Select Assignment Context")
        print("No class rosters found.")
        return None

    clear_screen_fn()
    print_menu_header("Select Assignment Context")
    if notice:
        print(notice)
        print()
    print("Available classes:")
    for index, record in enumerate(classes, start=1):
        print(f"{index}. {record['class_id']}")
    print_scoreform_navigation_options()
    print()

    selection = input("Select class: ").strip()
    navigation = parse_scoreform_navigation(selection)
    if navigation is NavigationChoice.BACK:
        return None
    try:
        return parse_single_selection(selection, classes, "class")
    except ValueError as exc:
        print(f"Error: {exc}")
        return None


def select_canonical_assignment(
    session: AssignmentContextSession,
    *,
    clear_screen_fn: UiCallback | None = None,
) -> dict[str, Any] | None:
    """Select one canonical assignment and activate its exact identity."""
    clear = workflows.clear_screen if clear_screen_fn is None else clear_screen_fn
    root = workspace.get_scoreform_workspace_root()
    workspace_changed = session.bind_workspace(root)
    notice = (
        "Assignment context was cleared because the workspace changed."
        if workspace_changed
        else None
    )

    class_record = _select_class(
        workspace_root=root,
        clear_screen_fn=clear,
        notice=notice,
    )
    if class_record is None:
        return None
    class_id = str(class_record["class_id"])

    assignments = workflows.discover_class_assignments(
        class_id,
        workspace_root=root,
    )
    if not assignments:
        print(f"No assignments found for class '{class_id}'.")
        return None

    clear()
    print_menu_header("Select Assignment Context")
    print(f"Class: {class_id}")
    print()
    print("Available assignments:")
    for index, record in enumerate(assignments, start=1):
        title = _title_for_record(record)
        suffix = f" - {title}" if title else ""
        print(f"{index}. {record['assignment_id']}{suffix}")
    print_scoreform_navigation_options()
    print()

    selection = input("Select assignment: ").strip()
    navigation = parse_scoreform_navigation(selection)
    if navigation is NavigationChoice.BACK:
        return None
    try:
        record = parse_single_selection(selection, assignments, "assignment")
    except ValueError as exc:
        print(f"Error: {exc}")
        return None

    ref = assignment_context_ref_from_record(record)
    session.activate(ref, workspace_root=root)
    return record


def select_assignment_for_workflow(
    session: AssignmentContextSession,
    *,
    clear_screen_fn: UiCallback | None = None,
    offer_switch: bool = False,
    workflow_title: str = "Continue with Assignment",
) -> dict[str, Any] | None:
    """Reuse valid active context or fall back to canonical assignment selection."""
    clear = workflows.clear_screen if clear_screen_fn is None else clear_screen_fn
    if session.active is not None:
        outcome = resolve_active_assignment_context(session)
        if outcome is not None and outcome.is_valid and outcome.record is not None:
            title = _title_for_record(outcome.record)
            suffix = f" — {title}" if title else ""
            if not offer_switch:
                print(
                    f"Using active assignment: {outcome.ref.class_id} / "
                    f"{outcome.ref.assignment_id}{suffix}"
                )
                print()
                return outcome.record

            while True:
                clear()
                print_menu_header(workflow_title)
                print(
                    f"Active assignment: {outcome.ref.class_id} / "
                    f"{outcome.ref.assignment_id}{suffix}"
                )
                print()
                print("1. Continue with active assignment")
                print("2. Select another assignment")
                print_scoreform_navigation_options()
                print()
                choice = input("Select an option: ").strip()
                navigation = parse_scoreform_navigation(choice)
                if navigation is NavigationChoice.BACK:
                    return None
                if choice == "1":
                    return outcome.record
                if choice == "2":
                    return select_canonical_assignment(
                        session,
                        clear_screen_fn=clear,
                    )
                print(f"Invalid selection: {choice}.")
                print_invalid_navigation()
                print()

        if outcome is not None and outcome.stale_reason:
            print(f"Previous assignment context is unavailable: {outcome.stale_reason}")
            print("Select the assignment again from current workspace records.")
            print()

    return select_canonical_assignment(session, clear_screen_fn=clear)


def _choose_recent_assignment(
    session: AssignmentContextSession,
    *,
    clear_screen_fn: UiCallback,
) -> bool:
    outcomes = resolve_recent_assignment_contexts(session)
    if not outcomes:
        print("No valid recent assignments are available.")
        return False

    clear_screen_fn()
    print_menu_header("Recent Assignments")
    for index, outcome in enumerate(outcomes, start=1):
        assert outcome.record is not None
        title = _title_for_record(outcome.record)
        suffix = f" — {title}" if title else ""
        print(
            f"{index}. {outcome.ref.class_id} / "
            f"{outcome.ref.assignment_id}{suffix}"
        )
    print_scoreform_navigation_options()
    print()

    selection = input("Select recent assignment: ").strip()
    navigation = parse_scoreform_navigation(selection)
    if navigation is NavigationChoice.BACK:
        return False
    try:
        outcome = parse_single_selection(selection, outcomes, "recent assignment")
    except ValueError as exc:
        print(f"Error: {exc}")
        return False

    root = workspace.get_scoreform_workspace_root()
    session.activate(outcome.ref, workspace_root=root)
    return True


def launch_assignment_context_menu(
    session: AssignmentContextSession,
    *,
    clear_screen_fn: UiCallback | None = None,
    pause_for_user_fn: UiCallback | None = None,
) -> int:
    """View, switch, or clear identity-only assignment context."""
    clear = workflows.clear_screen if clear_screen_fn is None else clear_screen_fn
    pause = workflows.pause_for_user if pause_for_user_fn is None else pause_for_user_fn

    while True:
        clear()
        print_menu_header("Assignment Context")
        for line in format_active_context_lines(session):
            print(line)
        print()
        print("1. Select another assignment")
        print("2. Use a recent assignment")
        print("3. Clear active assignment")
        print("4. Clear recent history")
        print_scoreform_navigation_options()
        print()

        choice = input("Select an option: ").strip()
        navigation = parse_scoreform_navigation(choice)
        if navigation is NavigationChoice.BACK:
            return 0

        if choice == "1":
            select_canonical_assignment(session, clear_screen_fn=clear)
        elif choice == "2":
            if not _choose_recent_assignment(session, clear_screen_fn=clear):
                print()
                pause()
        elif choice == "3":
            session.clear_active()
            print("Active assignment context cleared.")
            print()
            pause()
        elif choice == "4":
            session.clear_recent()
            print("Recent assignment history cleared for this session.")
            print()
            pause()
        else:
            print(f"Invalid selection: {choice}.")
            print_invalid_navigation()
            print()
            pause()
