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
from pds_core.routes import (
    class_metadata_path as core_class_metadata_path,
)
from pds_core.routes import (
    class_roster_path as core_class_roster_path,
)
from pds_core.school_years import (
    SchoolYearStateError,
    SchoolYearValidationError,
    get_active_school_year,
    validate_school_year,
)

from scoreform import generate_workflows, workspace
from scoreform.menu_navigation import (
    parse_scoreform_navigation,
    print_invalid_navigation,
    print_scoreform_navigation_options,
)
from scoreform.migration import ScoreFormMigrationPendingError
from scoreform.roster import _core_roster_to_legacy_dict, load_roster
from scoreform.validation import is_safe_identifier, validate_identifier
from scoreform.workflows import (
    clear_screen,
    discover_class_assignments,
    discover_class_rosters,
    normalize_path_input,
    parse_single_selection,
    pause_for_user,
    print_menu_header,
    suggest_class_id,
    write_roster_with_class_metadata,
)


def _offer_sheet_regeneration_after_save(class_id):
    """Offer an explicit next step only when the saved class has assignments."""
    assignments = discover_class_assignments(class_id)
    if not assignments:
        print("No assignments found for this class yet.")
        return 0
        return 0
    print()
    print("Generated answer sheets for this class may be out of date.")
    print()
    print("1. Update sheets now")
    print("2. Not now")
    choice = input("Select an option: ").strip()
    if choice != "1":
        print("Answer sheets were not changed.")
        return 0
    try:
        return generate_workflows.launch_regenerate_sheets_menu(
            preselected_class_id=class_id
        )
    except ScoreFormMigrationPendingError:
        print(
            "Answer-sheet regeneration is temporarily unavailable pending "
            "page-record and route-registration work (#140 and #141)."
        )
        return 0


def format_roster_for_display(class_record):
    """Return readable terminal text for a discovered class roster."""
    roster = class_record["roster"]
    students = roster.get("students", [])
    metadata_error = class_record.get("metadata_error")
    school_year = class_record.get("school_year")
    if metadata_error:
        school_year_text = "metadata error"
    elif school_year:
        school_year_text = school_year
    else:
        school_year_text = "not set"
    fieldnames = ["student_id", "last_name", "first_name", "period"]

    for student in students:
        for field in student:
            if field != "class_id" and field not in fieldnames:
                fieldnames.append(field)

    widths = {
        field: max(
            [len(field)]
            + [len(str(student.get(field, ""))) for student in students]
        )
        for field in fieldnames
    }

    lines = [
        f"Class: {class_record['class_id']}",
        f"School year: {school_year_text}",
        f"Roster: {class_record['roster_path']}",
        f"Class metadata: {class_record.get('metadata_path', 'not set')}",
    ]
    if metadata_error:
        lines.append(f"Metadata error: {metadata_error}")
    lines.extend([
        f"Students: {len(students)}",
        "",
    ])

    if not students:
        lines.append("(No student rows)")
        return "\n".join(lines)

    lines.append(" ".join(field.ljust(widths[field]) for field in fieldnames))
    for student in students:
        lines.append(
            " ".join(str(student.get(field, "")).ljust(widths[field]) for field in fieldnames)
        )

    return "\n".join(lines)


def _class_record_from_core_roster(roster, roster_path, base_record=None):
    record = {
        "class_id": roster.class_id,
        "roster_path": os.fspath(roster_path),
        "roster": _core_roster_to_legacy_dict(roster),
    }
    if base_record:
        for key in ("metadata_path", "school_year", "metadata_error"):
            if key in base_record:
                record[key] = base_record[key]
    return record


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
    if parse_scoreform_navigation(selection) is not None:
        return None
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
    print_scoreform_navigation_options()
    print()
    student = _prompt_student_selection(
        roster,
        "Select student by number or student_id: ",
    )
    if student is None:
        return roster

    clear_screen()
    print_menu_header("Edit Student")
    print(f"Class: {roster.class_id}")
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
    print_scoreform_navigation_options()
    print()
    student = _prompt_student_selection(
        roster,
        "Select student by number or student_id: ",
    )
    if student is None:
        return roster

    clear_screen()
    print_menu_header("Remove Student from Active Roster")
    print(f"Class: {roster.class_id}")
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
    print_scoreform_navigation_options()
    print()

    try:
        selection = input("Select class: ")
        if parse_scoreform_navigation(selection) is not None:
            return 0
        class_record = parse_single_selection(
            selection,
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
    print(
        format_roster_for_display(
            _class_record_from_core_roster(staged_roster, saved_path, class_record)
        )
    )

    while True:
        clear_screen()
        print_menu_header("Edit Class Roster")
        print(f"Class: {class_id}")
        print(f"Staged changes: {'yes' if dirty else 'none'}")
        print()
        print("1. Add student")
        print("2. Edit student")
        print("3. Remove student from active roster")
        print("4. View current roster")
        print("5. Save changes")
        print_scoreform_navigation_options()
        print()

        choice = input("Select an option: ").strip()
        print()

        if parse_scoreform_navigation(choice) is not None:
            choice = "6"

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
            print(
                format_roster_for_display(
                    _class_record_from_core_roster(
                        staged_roster,
                        saved_path,
                        class_record,
                    )
                )
            )
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
            return _offer_sheet_regeneration_after_save(class_id)

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
            print(f"Invalid selection: {choice}.")
            print_invalid_navigation()


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
    print_scoreform_navigation_options()
    print()

    try:
        selection = input("Select class: ")
        if parse_scoreform_navigation(selection) is not None:
            return 0
        class_record = parse_single_selection(
            selection,
            available_classes,
            "class",
        )
    except ValueError as e:
        print(f"Error: {e}")
        return 1

    clear_screen()
    print_menu_header("View a Class Roster")
    print(f"Class: {class_record['class_id']}")
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


def confirm_class_files_overwrite(roster_path, metadata_path, class_id):
    """Prompt once before replacing existing canonical class files."""
    existing = []
    if os.path.exists(roster_path):
        existing.append(("Roster", roster_path))
    if os.path.exists(metadata_path):
        existing.append(("Class metadata", metadata_path))

    if not existing:
        return True

    print(f"Existing class files were found for class '{class_id}':")
    print()
    for label, path in existing:
        print(f"{label}:")
        print(path)
        print()

    response = input(
        "Type OVERWRITE to replace the roster and class metadata: "
    ).strip()
    return response == "OVERWRITE"


def prompt_school_year_for_roster(workspace_root):
    """Prompt for a pds-core validated school year for a new class roster."""
    try:
        active_school_year = get_active_school_year(workspace_root)
    except SchoolYearStateError as e:
        print(f"Error: Could not read active school-year state: {e}")
        return None

    if active_school_year:
        print(f"Active school year: {active_school_year}")
        response = input("Use this school year for the class roster? [Y/n]: ").strip()
        if response.lower() not in {"n", "no"}:
            return active_school_year
    else:
        print("No active school year is open for this workspace.")

    school_year = input("School year for this roster (YYYY-YYYY): ").strip()
    try:
        return validate_school_year(school_year)
    except SchoolYearValidationError as e:
        print(f"Error: Invalid school year: {e}")
        return None


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
    metadata_path = os.fspath(core_class_metadata_path(workspace_root, class_id))

    if not confirm_class_files_overwrite(output_path, metadata_path, class_id):
        print("Cancelled: class file overwrite not confirmed.")
        return 1

    school_year = prompt_school_year_for_roster(workspace_root)
    if school_year is None:
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
    result = write_roster_with_class_metadata(
        workspace_root=workspace_root,
        class_id=class_id,
        period=period,
        students=students,
        school_year=school_year,
        overwrite=True,
    )
    if result is None:
        print("Error: Failed to write roster and class metadata.")
        return 1
    print(f"Class metadata: {result['metadata_path']}")

    print("Validating roster...")
    roster = load_roster(output_path)
    if roster is None:
        print("Error: Roster validation failed after save.")
        return 1

    print(f"Success! Roster created with {len(roster['students'])} students.")
    return _offer_sheet_regeneration_after_save(class_id)


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
            print("U. Update generated answer sheets")
            print_scoreform_navigation_options()
            print()

            choice = input("Select an option: ").strip()
            print()

            if parse_scoreform_navigation(choice) is not None or choice == "5":
                return 0

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

            elif choice.lower() == "u":
                clear_screen()
                generate_workflows.launch_regenerate_sheets_menu()
                print()
                pause_for_user()

            else:
                print(f"Invalid selection: {choice}.")
                print_invalid_navigation()
                print()
                pause_for_user()

    except KeyboardInterrupt:
        print("\nExiting roster menu.")
        return 0
