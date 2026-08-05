"""Teacher-menu workflow for explicit Academic Work Registration."""

from __future__ import annotations

from scoreform import workspace
from scoreform.academic_work_registration import (
    SUPPORTED_ACADEMIC_INTENTS,
    SUPPORTED_ACADEMIC_WORK_LIFECYCLES,
    ScoreFormAcademicWorkRegistrationError,
    build_scoreform_academic_work_registration_request,
    load_current_scoreform_academic_work_registration,
    load_managed_assignment_registration_context,
    register_scoreform_academic_work,
    update_scoreform_academic_work_registration,
)
from scoreform.menu_navigation import (
    parse_scoreform_navigation,
    print_scoreform_navigation_options,
)
from scoreform.workflows import (
    discover_class_assignments,
    discover_class_rosters,
    parse_single_selection,
    print_menu_header,
)


def _select(label: str, values: tuple[str, ...]) -> str | None:
    print(f"Select {label}:")
    for index, value in enumerate(values, start=1):
        print(f"{index}. {value}")
    print_scoreform_navigation_options()
    choice = input(f"{label.replace('_', ' ').title()}: ").strip()
    if parse_scoreform_navigation(choice) is not None:
        return None
    if not choice.isdecimal() or not 1 <= int(choice) <= len(values):
        print(f"Error: Select a listed {label}.")
        return None
    return values[int(choice) - 1]


def _display_current(current, assignment_title: str) -> None:
    if current is None:
        print("Registration status: not registered")
        return
    print("Registration status: registered")
    print(f"Registration revision: {current.registration_revision}")
    print(f"Registration title: {current.title}")
    print(f"Academic intent: {current.academic_intent}")
    print(f"Lifecycle: {current.lifecycle}")
    if current.title != assignment_title:
        print("WARNING: registration title snapshot differs from assignment title.")


def _display_request(request) -> None:
    print("Proposed Academic Work Registration request:")
    print(f"  module_id: {request.work.module_id}")
    print(f"  class_id: {request.work.class_id}")
    print(f"  assignment_id: {request.work.work_id}")
    print(f"  producer contract version: {request.producer_contract_version}")
    print(f"  title: {request.title}")
    print(f"  work kind: {request.work_kind}")
    print(f"  academic intent: {request.academic_intent}")
    print(f"  lifecycle: {request.lifecycle}")
    source = request.source_records[0]
    print(
        "  source record: "
        f"{source.module_id}/{source.record_kind}/{source.record_id} "
        "(contract_version=null)"
    )


def launch_academic_work_registration_menu() -> int:
    """Run one explicit, confirmed registration action for a managed assignment."""
    print_menu_header("Academic Work Registration")
    classes = discover_class_rosters()
    if not classes:
        print("No valid classes found.")
        return 1
    print("Available classes:")
    for index, record in enumerate(classes, start=1):
        print(f"{index}. {record['class_id']}")
    print_scoreform_navigation_options()
    try:
        choice = input("Select class: ")
        if parse_scoreform_navigation(choice) is not None:
            print("Cancelled: no registration state was written.")
            return 0
        class_record = parse_single_selection(choice, classes, "class")
    except ValueError as error:
        print(f"Error: {error}")
        return 1

    class_id = class_record["class_id"]
    assignments = discover_class_assignments(class_id)
    if not assignments:
        print(f"No managed ScoreForm assignments found for class '{class_id}'.")
        return 1
    print("Available managed assignments:")
    for index, record in enumerate(assignments, start=1):
        print(f"{index}. {record['assignment_id']} - {record['assignment']['title']}")
    print_scoreform_navigation_options()
    try:
        choice = input("Select assignment: ")
        if parse_scoreform_navigation(choice) is not None:
            print("Cancelled: no registration state was written.")
            return 0
        assignment_record = parse_single_selection(choice, assignments, "assignment")
    except ValueError as error:
        print(f"Error: {error}")
        return 1

    assignment_id = assignment_record["assignment_id"]
    assignment_title = assignment_record["assignment"]["title"]
    workspace_root = workspace.get_scoreform_workspace_root()
    try:
        current = load_current_scoreform_academic_work_registration(
            workspace_root, class_id, assignment_id
        )
        print()
        print(f"Class: {class_id}")
        print(f"Assignment: {assignment_id}")
        print(f"Current assignment title: {assignment_title}")
        _display_current(current, assignment_title)
        print()
        if current is None:
            print("1. Register unregistered assignment")
            print("2. View current registration")
        else:
            print("1. Update current registration")
            print("2. View current registration")
        print("3. Cancel or return")
        action = input("Select an option: ").strip()
        if action == "2":
            _display_current(current, assignment_title)
            return 0
        if action != "1":
            print("Cancelled: no registration state was written.")
            return 0

        intent = _select("academic_intent", SUPPORTED_ACADEMIC_INTENTS)
        if intent is None:
            print("Cancelled: no registration state was written.")
            return 0
        lifecycle = _select("lifecycle", SUPPORTED_ACADEMIC_WORK_LIFECYCLES)
        if lifecycle is None:
            print("Cancelled: no registration state was written.")
            return 0
        context = load_managed_assignment_registration_context(
            workspace_root, class_id, assignment_id
        )
        request = build_scoreform_academic_work_registration_request(
            context, academic_intent=intent, lifecycle=lifecycle
        )
        _display_request(request)
        if current is None:
            if input("Type REGISTER to confirm: ").strip() != "REGISTER":
                print("Cancelled: registration was not written.")
                return 0
            result = register_scoreform_academic_work(
                workspace_root,
                class_id,
                assignment_id,
                academic_intent=intent,
                lifecycle=lifecycle,
            )
        else:
            expected_revision = current.registration_revision
            print(f"Expected current revision: {expected_revision}")
            if input("Type UPDATE to confirm: ").strip() != "UPDATE":
                print("Cancelled: registration was not updated.")
                return 0
            result = update_scoreform_academic_work_registration(
                workspace_root,
                class_id,
                assignment_id,
                academic_intent=intent,
                lifecycle=lifecycle,
                expected_current_revision=expected_revision,
            )
        print(f"disposition: {result.disposition}")
        print(f"registration revision: {result.registration.registration_revision}")
        print(f"title: {result.registration.title}")
        print(f"academic intent: {result.registration.academic_intent}")
        print(f"lifecycle: {result.registration.lifecycle}")
        return 0
    except ScoreFormAcademicWorkRegistrationError as error:
        print(f"Error: {error}")
        state = getattr(error, "state", None)
        if state is not None:
            print("Durable Core state may exist; inspect the registry before retrying.")
            if state.registration is not None:
                print(f"registration revision: {state.registration.registration_revision}")
            if state.canonical_path is not None:
                print(f"canonical path: {state.canonical_path}")
        return 1

