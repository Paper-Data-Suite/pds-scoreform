"""Interactive plain-paper result entry workflow."""

from scoreform import workspace
from scoreform.assignment import load_assignment
from scoreform.manual_entry import (
    build_manual_result,
    format_manual_entry_review,
    is_manual_entry_cancel,
    normalize_manual_response,
)
from scoreform.menu_navigation import (
    parse_scoreform_navigation,
    print_scoreform_navigation_options,
)
from scoreform.results import export_routed_results
from scoreform.roster import load_roster
from scoreform.workflows import (
    clear_screen,
    discover_class_assignments,
    discover_class_rosters,
    parse_single_selection,
    print_menu_header,
)


def _select_record(prompt, records, kind):
    while True:
        selection = input(prompt)
        if parse_scoreform_navigation(selection) is not None:
            return None
        try:
            return parse_single_selection(selection, records, kind)
        except ValueError as error:
            print(f"Error: {error}")


def _student_label(student, duplicate_names):
    name = f"{student['last_name']}, {student['first_name']}"
    if name in duplicate_names:
        return f"{name} ({student['student_id']})"
    return name


def _prompt_responses(assignment):
    responses = {}
    for question_number in range(1, assignment["question_count"] + 1):
        while True:
            raw_value = input(
                f"Q{question_number} Response "
                "[A/B/C/D, blank, ambiguous, q=cancel]: "
            )
            if is_manual_entry_cancel(raw_value):
                return None
            response = normalize_manual_response(raw_value, assignment["choices"])
            if response is not None:
                responses[question_number] = response
                break
            print("Invalid response. Enter A, B, C, D, blank, ambiguous, or q to cancel.")
    return responses


def launch_manual_entry_menu():
    """Select a class and assignment, then enter one or more student results."""
    clear_screen()
    print_menu_header("Enter Plain-Paper Results")
    classes = discover_class_rosters()
    if not classes:
        print("No class rosters found.")
        print("Create a class roster first, then return to this option.")
        return 1

    print("Select Class:")
    for index, record in enumerate(classes, start=1):
        student_count = len(record["roster"].get("students", []))
        print(f"{index}. {record['class_id']} ({student_count} students)")
    print_scoreform_navigation_options()
    class_record = _select_record("Select class: ", classes, "class")
    if class_record is None:
        return 0

    class_id = class_record["class_id"]
    assignments = discover_class_assignments(class_id)
    if not assignments:
        print(f"No assignments found for class '{class_id}'.")
        print("Create an assignment first, then return to this option.")
        return 1

    clear_screen()
    print_menu_header("Enter Plain-Paper Results")
    print(f"Class: {class_id}\n")
    print("Select Assignment:")
    for index, record in enumerate(assignments, start=1):
        print(f"{index}. {record['assignment_id']} - {record['assignment']['title']}")
    print_scoreform_navigation_options()
    assignment_record = _select_record(
        "Select assignment: ", assignments, "assignment"
    )
    if assignment_record is None:
        return 0

    assignment = load_assignment(assignment_record["assignment_path"])
    if assignment is None:
        print("Error: Assignment file failed validation. No result was written.")
        return 1
    if set(assignment["choices"]) != {"A", "B", "C", "D"}:
        print("Error: Plain-paper entry supports A-D assignments only.")
        return 1

    roster = load_roster(class_record["roster_path"])
    if roster is None:
        print("Error: Could not load the selected class roster.")
        return 1
    students = roster["students"]
    if not students:
        print("The selected class roster has no students.")
        return 1

    names = [f"{s['last_name']}, {s['first_name']}" for s in students]
    duplicate_names = {name for name in names if names.count(name) > 1}
    while True:
        clear_screen()
        print_menu_header("Enter Plain-Paper Results")
        print(f"Class: {class_id}")
        print(f"Assignment: {assignment['assignment_id']} - {assignment['title']}\n")
        print("Select Student:")
        for index, student in enumerate(students, start=1):
            print(f"{index}. {_student_label(student, duplicate_names)}")
        print_scoreform_navigation_options()
        student = _select_record("Select student: ", students, "student")
        if student is None:
            return 0

        clear_screen()
        student_name = f"{student['last_name']}, {student['first_name']}"
        print_menu_header("Enter Plain-Paper Results")
        print(student_name)
        print(f"Assignment: {assignment['title']}")
        print(f"Questions: {assignment['question_count']}")
        print("Choices: A, B, C, D\n")
        responses = _prompt_responses(assignment)
        if responses is None:
            print("Cancelled: result was not written.")
            continue

        result = build_manual_result(
            class_id=class_id,
            assignment=assignment,
            student=student,
            responses=responses,
        )
        print()
        print(format_manual_entry_review(student, assignment, result))
        confirmation = input("\nWrite this result? (y/yes): ").strip().lower()
        if confirmation not in {"y", "yes"}:
            print("Cancelled: result was not written.")
            continue

        if export_routed_results(
            [result], workspace_root=workspace.get_scoreform_workspace_root()
        ):
            print(f"Result written for {student_name}.")
        else:
            print("Error: No manual result was written successfully.")
