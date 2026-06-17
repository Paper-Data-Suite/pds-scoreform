"""Interactive roster workflow helpers."""

import os

from pds_core.classes import load_class_roster, write_class_roster
from pds_core.rosters import (
    RosterError,
    RosterValidationError,
    StudentRecord,
    add_student_record,
    remove_student_record,
    replace_student_record,
)
from pds_core.routes import class_roster_path as core_class_roster_path

from scoreform import workspace
from scoreform.roster import _core_roster_to_legacy_dict, load_roster
from scoreform.validation import is_safe_identifier, validate_identifier
from scoreform.workflows import (
    clear_screen,
    discover_class_rosters,
    normalize_path_input,
    parse_single_selection,
    pause_for_user,
    print_menu_header,
    suggest_class_id,
    write_roster_csv,
)


def format_roster_for_display(class_record):
    """Return readable terminal text for a discovered class roster."""
    roster = class_record["roster"]
    students = roster.get("students", [])
    fieldnames = ["student_id", "last_name", "first_name", "period"]

    for student in students:
        for field in student:
            if field != "class_id" and field not in fieldnames:
                fieldnames.append(field)

    widths = {
        field: max(
            len(field),
            *(len(str(student.get(field, ""))) for student in students),
        )
        for field in fieldnames
    }

    lines = [
        f"Class: {class_record['class_id']}",
        f"Roster: {class_record['roster_path']}",
        f"Students: {len(students)}",
        "",
    ]

    if not students:
        lines.append("(No student rows)")
        return "\n".join(lines)

    lines.append(" ".join(field.ljust(widths[field]) for field in fieldnames))
    for student in students:
        lines.append(
            " ".join(str(student.get(field, "")).ljust(widths[field]) for field in fieldnames)
        )

    return "\n".join(lines)


def _class_record_from_core_roster(roster, roster_path):
    return {
        "class_id": roster.class_id,
        "roster_path": os.fspath(roster_path),
        "roster": _core_roster_to_legacy_dict(roster),
    }


def _optional_roster_columns(roster):
    return tuple(
        column
        for column in roster.columns
        if column not in ("class_id", "student_id", "last_name", "first_name", "period")
    )


def _print_roster_validation_error(error):
    print(f"Error: {error}")
    if isinstance(error, RosterValidationError):
        for issue in error.issues:
            location = []
            if issue.row_number is not None:
                location.append(f"row {issue.row_number}")
            if issue.column:
                location.append(issue.column)
            prefix = f"  {' / '.join(location)}: " if location else "  "
            print(f"{prefix}{issue.message}")


def _prompt_nonblank_roster_value(field_name):
    while True:
        value = input(f"  {field_name}: ").strip()
        if value:
            return value
        print(f"  Error: {field_name} is required.")


def _prompt_student_selection(roster, prompt):
    selection = input(prompt).strip()
    if not selection:
        raise ValueError("Select one student.")

    if selection.isdigit():
        index = int(selection)
        if 1 <= index <= len(roster.students):
            return roster.students[index - 1]

    for student in roster.students:
        if student.student_id == selection:
            return student

    raise ValueError(f"Student not found: {selection}")


def _student_record_from_values(roster, student_id, values):
    extra_fields = {
        column: values.get(column, "")
        for column in _optional_roster_columns(roster)
    }
    return StudentRecord(
        class_id=roster.class_id,
        student_id=student_id,
        last_name=values["last_name"],
        first_name=values["first_name"],
        period=values["period"],
        extra_fields=extra_fields,
    )


def _print_student_choices(roster):
    for index, student in enumerate(roster.students, start=1):
        print(
            f"{index}. {student.student_id} - "
            f"{student.last_name}, {student.first_name} (period {student.period})"
        )


def _prompt_add_student_to_roster(roster):
    print()
    print("Add student")
    student_id = _prompt_nonblank_roster_value("student_id")
    last_name = _prompt_nonblank_roster_value("last_name")
    first_name = _prompt_nonblank_roster_value("first_name")
    period = _prompt_nonblank_roster_value("period")

    values = {
        "last_name": last_name,
        "first_name": first_name,
        "period": period,
    }
    for column in _optional_roster_columns(roster):
        values[column] = input(f"  {column} (optional): ").strip()

    return add_student_record(
        roster,
        _student_record_from_values(roster, student_id, values),
    )


def _prompt_edit_student_in_roster(roster):
    print()
    print("Edit student")
    _print_student_choices(roster)
    print()
    student = _prompt_student_selection(
        roster,
        "Select student by number or student_id: ",
    )

    print()
    print(f"student_id: {student.student_id}")
    print("Press Enter to keep the current value.")

    values = {
        "last_name": input(f"  last_name [{student.last_name}]: ").strip()
        or student.last_name,
        "first_name": input(f"  first_name [{student.first_name}]: ").strip()
        or student.first_name,
        "period": input(f"  period [{student.period}]: ").strip()
        or student.period,
    }
    for column in _optional_roster_columns(roster):
        current = student.extra_fields.get(column, "")
        values[column] = input(f"  {column} [{current}]: ").strip() or current

    return replace_student_record(
        roster,
        _student_record_from_values(roster, student.student_id, values),
    )


def _prompt_remove_student_from_roster(roster):
    print()
    print("Remove student from active roster")
    _print_student_choices(roster)
    print()
    student = _prompt_student_selection(
        roster,
        "Select student by number or student_id: ",
    )

    print()
    print(
        f"Selected: {student.student_id} - "
        f"{student.last_name}, {student.first_name} (period {student.period})"
    )
    print("Generated materials, scans, and historical results will not be deleted.")
    confirmation = input("Type REMOVE to remove from active roster: ").strip()
    if confirmation != "REMOVE":
        print("Cancelled: removal not confirmed.")
        return roster

    return remove_student_record(roster, student.student_id)


def prompt_edit_class_roster():
    """Interactive workflow for staging and saving edits to a class roster."""
    print_menu_header("Edit Class Roster")

    available_classes = discover_class_rosters()
    if not available_classes:
        print("No class rosters found.")
        print("Create a class roster first, then return to this option.")
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
        return 1

    workspace_root = workspace.get_scoreform_workspace_root()
    class_id = class_record["class_id"]
    try:
        staged_roster = load_class_roster(workspace_root, class_id)
    except RosterError as e:
        print(f"Error: Could not load class roster '{class_id}': {e}")
        return 1

    dirty = False
    saved_path = class_record["roster_path"]
    print()
    print(format_roster_for_display(_class_record_from_core_roster(staged_roster, saved_path)))

    while True:
        print()
        print("Edit menu")
        print("1. Add student")
        print("2. Edit student")
        print("3. Remove student from active roster")
        print("4. View current roster")
        print("5. Save changes")
        print("6. Cancel without saving")
        print()

        choice = input("Select an option: ").strip()
        print()

        if choice == "1":
            try:
                staged_roster = _prompt_add_student_to_roster(staged_roster)
            except (RosterError, ValueError) as e:
                _print_roster_validation_error(e)
                continue
            dirty = True
            print("Staged: student added.")

        elif choice == "2":
            try:
                staged_roster = _prompt_edit_student_in_roster(staged_roster)
            except (RosterError, ValueError) as e:
                _print_roster_validation_error(e)
                continue
            dirty = True
            print("Staged: student updated.")

        elif choice == "3":
            try:
                updated_roster = _prompt_remove_student_from_roster(staged_roster)
            except (RosterError, ValueError) as e:
                _print_roster_validation_error(e)
                continue
            if updated_roster is not staged_roster:
                staged_roster = updated_roster
                dirty = True
                print("Staged: student removed from active roster.")

        elif choice == "4":
            print(format_roster_for_display(_class_record_from_core_roster(staged_roster, saved_path)))
            if dirty:
                print()
                print("Unsaved staged changes are shown above.")

        elif choice == "5":
            if not dirty:
                print("No changes to save.")
                return 0
            confirmation = input("Type SAVE to write staged changes: ").strip()
            if confirmation != "SAVE":
                print("Cancelled: save not confirmed.")
                continue
            try:
                saved_path = os.fspath(
                    write_class_roster(
                        workspace_root,
                        staged_roster,
                        overwrite=True,
                    )
                )
            except RosterError as e:
                print(f"Error: Could not save roster: {e}")
                continue
            print(f"Saved roster: {saved_path}")
            return 0

        elif choice == "6":
            if dirty:
                confirmation = input(
                    "Type DISCARD to discard staged changes: "
                ).strip()
                if confirmation != "DISCARD":
                    print("Cancelled: staged changes were not discarded.")
                    continue
            print("Cancelled: no roster changes were saved.")
            return 0

        else:
            print(f"Invalid selection: {choice}. Please enter a number from 1 to 6.")


def prompt_view_roster():
    """Interactive read-only workflow for viewing an existing class roster."""
    print_menu_header("View a Class Roster")

    available_classes = discover_class_rosters()
    if not available_classes:
        print("No class rosters found.")
        print("Create a class roster first, then return to this option.")
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
        return 1

    print()
    print(format_roster_for_display(class_record))
    return 0


def confirm_roster_overwrite(path, class_id):
    """Prompt for confirmation to overwrite an existing class roster."""
    if not os.path.exists(path):
        return True

    print(f"Roster already exists for class '{class_id}':")
    print(path)
    print()
    response = input("Overwrite? (y/yes to confirm): ").strip().lower()
    return response in ['y', 'yes']


def prompt_create_roster():
    """Interactive prompt to create a new roster.

    Returns 0 on success, 1 on cancellation or error.
    """
    print_menu_header("Create a Class Roster")

    class_name = input("Class name: ").strip()
    if not class_name:
        print("Error: class name is required.")
        return 1

    suggested_class_id = suggest_class_id(class_name)
    class_id = ""
    if is_safe_identifier(suggested_class_id):
        print(f"Suggested class_id: {suggested_class_id}")
        class_id = input("Press Enter to accept, or type a different class_id: ").strip()
        if not class_id:
            class_id = suggested_class_id
    else:
        print("Could not create a safe class_id suggestion from that class name.")
        class_id = input("Enter a valid class_id: ").strip()

    if not class_id:
        print("Error: class_id is required.")
        return 1
    if not validate_identifier("class_id", class_id, context="roster"):
        return 1

    workspace_root = workspace.get_scoreform_workspace_root()
    output_path = os.fspath(core_class_roster_path(workspace_root, class_id))

    if not confirm_roster_overwrite(output_path, class_id):
        print("Cancelled: Roster overwrite not confirmed.")
        return 1

    period = input("Period: ").strip()
    if not period:
        print("Error: period is required.")
        return 1

    students = []
    print()
    print("Enter students one at a time. Press Ctrl+C to exit, or enter empty data to stop adding students.")
    print()

    try:
        while True:
            print(f"Student #{len(students) + 1}:")
            student_id = input("  student_id: ").strip()
            if not student_id:
                if len(students) == 0:
                    print("Error: At least one student is required.")
                    return 1
                break
            if not validate_identifier("student_id", student_id, context="roster"):
                return 1

            while True:
                last_name = input("  last_name: ").strip()
                if last_name:
                    break
                print("  Error: last_name is required.")

            while True:
                first_name = input("  first_name: ").strip()
                if first_name:
                    break
                print("  Error: first_name is required.")

            students.append({
                'student_id': student_id,
                'last_name': last_name,
                'first_name': first_name,
            })
            print(f"  Added: {student_id} - {last_name}, {first_name}")
            print()

            add_another = input("Add another student? (y/n): ").strip().lower()
            if add_another not in ['y', 'yes']:
                break
            print()

    except KeyboardInterrupt:
        print("\nCancelled: User interrupted.")
        return 1

    print()
    print(f"Writing {len(students)} students to: {output_path}")
    if not write_roster_csv(output_path, class_id, period, students):
        print("Error: Failed to write roster CSV.")
        return 1

    print("Validating roster...")
    roster = load_roster(output_path)
    if roster is None:
        print("Error: Roster validation failed after save.")
        return 1

    print(f"Success! Roster created with {len(roster['students'])} students.")
    return 0


def launch_roster_menu():
    """Roster management submenu.

    Returns:
        0 on return to main menu, 1 on error.
    """
    try:
        while True:
            clear_screen()
            print_menu_header("Roster Management")
            print("1. Create a class roster")
            print("2. View a class roster")
            print("3. Edit class roster")
            print("4. Validate a roster file")
            print("5. Return to main menu")
            print()

            choice = input("Select an option: ").strip()
            print()

            if choice == "1":
                clear_screen()
                prompt_create_roster()
                print()
                pause_for_user()

            elif choice == "2":
                clear_screen()
                prompt_view_roster()
                print()
                pause_for_user()

            elif choice == "3":
                clear_screen()
                prompt_edit_class_roster()
                print()
                pause_for_user()

            elif choice == "4":
                clear_screen()
                print_menu_header("Validate a Roster File")
                roster_path = normalize_path_input(input("Roster CSV path: "))
                if not roster_path:
                    print("Roster file path is required.")
                    print()
                    pause_for_user()
                    continue

                roster = load_roster(roster_path)
                if roster is None:
                    print()
                    pause_for_user()
                    continue
                print("Roster file is valid.")
                print(f"class_id: {roster['class_id']}")
                print(f"students: {len(roster['students'])}")
                if roster['students']:
                    print("First students:")
                    for student in roster['students'][:5]:
                        print(f"  {student['student_id']}: {student['last_name']}, {student['first_name']}")
                print()
                pause_for_user()

            elif choice == "5":
                return 0

            else:
                print(f"Invalid selection: {choice}. Please enter a number from 1 to 5.")
                print()
                pause_for_user()

    except KeyboardInterrupt:
        print("\nExiting roster menu.")
        return 0
