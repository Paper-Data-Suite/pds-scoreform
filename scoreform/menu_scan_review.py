"""Teacher-facing ScoreForm scan review menu."""

from __future__ import annotations

from scoreform import workspace
from scoreform.menu_navigation import (
    parse_scoreform_navigation,
    print_scoreform_navigation_options,
)
from scoreform.migration import migration_pending
from scoreform.scan_review_resolution import (
    RESOLUTION_ACTIONS,
    ScanReviewError,
    discover_scan_review_items,
    resolve_scan_review_item,
)
from scoreform.workflows import clear_screen, pause_for_user, print_menu_header

ACTION_LABELS = {
    "manual_entry": "Enter answers manually",
    "manual_marks": "Record manual marks",
    "rescan_needed": "Mark rescan needed",
    "cannot_route": "Cannot safely route",
    "mixed_assignment": "Mixed assignment source",
    "evidence_filed": "Evidence already filed",
    "dismissed_duplicate": "Dismiss duplicate",
    "other": "Other resolution",
    "defer": "Defer for later",
}


def _shown(value) -> str:
    return str(value) if value not in (None, "") else "—"


def _prompt_identity(item):
    print("Paper identity")
    print("Enter only identity verified from the paper or retained evidence.")
    print()
    class_id = input(f"Class [{_shown(item.class_id)}]: ").strip() or item.class_id
    assignment_id = (
        input(f"Assignment [{_shown(item.assignment_id)}]: ").strip()
        or item.assignment_id
    )
    student_id = (
        input(f"Student [{_shown(item.student_id)}]: ").strip() or item.student_id
    )
    return class_id, assignment_id, student_id


def _prompt_manual_answers(root, item, identity):
    # Validation and assignment loading happen in the service; read just enough here
    # to collect a complete set before any result or resolution is written.
    assignment = migration_pending("Manual scan-review entry", "#145")
    if assignment is None:
        raise ScanReviewError("The selected assignment could not be loaded.")
    clear_screen()
    print_menu_header("Manual Entry")
    print(f"Questions: {assignment['question_count']}")
    print("Enter A, B, C, or D for each question.")
    print()
    answers = {}
    for question in range(1, assignment["question_count"] + 1):
        while True:
            answer = input(f"Question {question}: ").strip().upper()
            if answer in {"A", "B", "C", "D"}:
                answers[question] = answer
                break
            print("Enter A, B, C, or D.")
    clear_screen()
    print_menu_header("Confirm Manual Entry")
    print("Answers:")
    print("  " + "  ".join(f"{q}:{a}" for q, a in answers.items()))
    print()
    if input("Type WRITE to save the result: ").strip() != "WRITE":
        return None
    return answers


def _perform_action(root, item, action):
    clear_screen()
    print_menu_header(ACTION_LABELS[action])
    identity = (item.class_id, item.assignment_id, item.student_id)
    if action in {"manual_entry", "manual_marks", "rescan_needed"}:
        identity = _prompt_identity(item)
    evidence_path = None
    if action == "evidence_filed":
        evidence_path = input("Workspace-relative evidence path: ").strip()
    elif action in {"manual_entry", "manual_marks", "rescan_needed"}:
        evidence_path = input(
            "Alternate workspace-relative evidence path (blank uses retained source): "
        ).strip() or None
    message = None
    if action == "other":
        message = input("Resolution note: ").strip()
    elif action in {"manual_entry", "manual_marks"}:
        message = input("Teacher note (blank uses default): ").strip() or None
    answers = None
    if action == "manual_entry":
        answers = _prompt_manual_answers(root, item, identity)
        if answers is None:
            return None
    return resolve_scan_review_item(
        root,
        item.failure_id,
        action,
        message=message,
        evidence_path=evidence_path,
        class_id=identity[0],
        assignment_id=identity[1],
        student_id=identity[2],
        answers=answers,
    )


def launch_scan_review_menu() -> int:
    """List active items, show one detail view, and resolve or defer it."""
    root = workspace.get_scoreform_workspace_root()
    while True:
        clear_screen()
        print_menu_header("Resolve Scan Review Items")
        discovery = discover_scan_review_items(root)
        if not discovery.items:
            print("No unresolved or deferred ScoreForm scan review items.")
            print()
            pause_for_user()
            return 0
        for index, item in enumerate(discovery.items, start=1):
            page = f", page {item.source_page_number}" if item.source_page_number else ""
            print(
                f"{index}. {item.status}: {item.failure_category} — "
                f"{item.source_filename}{page}"
            )
        if discovery.warning_count:
            print(f"Warning: {discovery.warning_count} malformed record(s) ignored.")
        print_scoreform_navigation_options()
        print()
        choice = input("Select an item: ").strip()
        if parse_scoreform_navigation(choice) is not None:
            return 0
        if not choice.isdigit() or not 1 <= int(choice) <= len(discovery.items):
            print("Select a listed review item.")
            pause_for_user()
            continue
        item = discovery.items[int(choice) - 1]
        clear_screen()
        print_menu_header("Scan Review Details")
        print(f"Category: {item.failure_category}")
        print(f"Reason: {item.failure_message}")
        print(f"Source: {item.source_filename}")
        print(f"Page: {_shown(item.source_page_number)}")
        print(f"Class: {_shown(item.class_id)}")
        print(f"Assignment: {_shown(item.assignment_id)}")
        print(f"Student: {_shown(item.student_id)}")
        print(f"Retained source: {_shown(item.retained_source_path)}")
        print()
        for index, action in enumerate(RESOLUTION_ACTIONS, start=1):
            print(f"{index}. {ACTION_LABELS[action]}")
        print_scoreform_navigation_options()
        print()
        action_choice = input("Select an action: ").strip()
        if parse_scoreform_navigation(action_choice) is not None:
            continue
        if not action_choice.isdigit() or not 1 <= int(action_choice) <= len(
            RESOLUTION_ACTIONS
        ):
            print("Select a listed action.")
            pause_for_user()
            continue
        action = RESOLUTION_ACTIONS[int(action_choice) - 1]
        try:
            result = _perform_action(root, item, action)
        except (ScanReviewError, OSError) as error:
            clear_screen()
            print_menu_header("Scan Review Not Updated")
            print(f"Error: {error}")
            print()
            pause_for_user()
            continue
        if result is None:
            clear_screen()
            print_menu_header("Manual Entry Cancelled")
            print("No result or resolution record was written.")
        else:
            clear_screen()
            print_menu_header("Scan Review Updated")
            print(f"Status: {result.resolution_status}")
            print(f"Resolution record: {result.resolution_metadata_relative_path}")
            if result.evidence_path:
                print(f"Evidence: {result.evidence_path}")
            if result.result_written:
                print("Manual-entry result written to assignment results.")
        print()
        pause_for_user()
