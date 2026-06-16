"""Interactive workflow helpers split from cli.py.

Contains:
- confirm_overwrite
- write_roster_csv
- write_assignment_json
- prompt_create_roster
- prompt_create_assignment
- launch_roster_menu
- launch_assignment_menu

These are designed to be imported by `scoreform.cli` without circular imports.
"""

import json
import os
import re
import sys
from pathlib import Path

from pds_core.assignments import (
    ensure_assignment_folder as ensure_core_assignment_folder,
)
from pds_core.assignments import (
    list_assignment_folders as list_core_assignment_folders,
)
from pds_core.classes import (
    list_class_folders as list_core_class_folders,
)
from pds_core.classes import (
    load_class_roster,
    write_class_roster,
)
from pds_core.rosters import (
    RosterError,
    RosterValidationError,
    StudentRecord,
    add_student_record,
    remove_student_record,
    replace_student_record,
)
from pds_core.rosters import (
    create_roster as create_core_roster,
)
from pds_core.rosters import (
    write_roster as write_core_roster,
)
from pds_core.routes import class_roster_path as core_class_roster_path
from pds_core.scan_routes import scans_inbox_dir
from pds_core.standards import (
    StandardDefinition,
    StandardsValidationError,
    filter_standard_definitions,
    find_standard_definition,
    load_workspace_standards_library,
    upsert_standard_definition,
    validate_standard_definition,
    write_workspace_standards_library,
)

from scoreform import workspace
from scoreform.assignment import load_assignment
from scoreform.config import MAX_QUESTION_COUNT
from scoreform.roster import _core_roster_to_legacy_dict, load_roster
from scoreform.validation import is_safe_identifier, validate_identifier

SUPPORTED_SCAN_EXTENSIONS = (".pdf", ".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif")
GREEN_ANSI = "\033[32m"
RESET_ANSI = "\033[0m"


def _stdout_supports_color():
    """Return True when stdout is an interactive terminal with likely ANSI support."""
    try:
        if not sys.stdout.isatty():
            return False
    except (AttributeError, OSError):
        return False

    if os.environ.get("NO_COLOR") is not None or os.environ.get("TERM") == "dumb":
        return False

    if os.name != "nt":
        return True

    return any(
        os.environ.get(name)
        for name in ("ANSICON", "WT_SESSION", "TERM_PROGRAM")
    ) or os.environ.get("TERM", "").startswith("xterm")


def print_menu_header(title=None):
    """Print the ScoreForm menu identity and an optional workflow title."""
    application_name = "ScoreForm"
    if _stdout_supports_color():
        application_name = f"{GREEN_ANSI}{application_name}{RESET_ANSI}"

    print(application_name)
    if title:
        print(title)
    print()


def clear_screen():
    """Clear the terminal for interactive menu screens."""
    if sys.stdin.isatty() and sys.stdout.isatty():
        os.system("cls" if os.name == "nt" else "clear")


def pause_for_user():
    """Pause after important interactive menu output."""
    try:
        input("Press Enter to continue...")
    except KeyboardInterrupt:
        print()


def normalize_path_input(value):
    """Strip whitespace and one matching pair of surrounding quotes from a path input."""
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def is_supported_scan_file(path):
    """Return True when path has a supported scan file extension."""
    filename = os.path.basename(os.fspath(path))
    if not filename or filename.startswith("."):
        return False
    return os.path.splitext(filename)[1].lower() in SUPPORTED_SCAN_EXTENSIONS


def discover_scans_in_inbox(scans_dir=None):
    """Return supported scan files directly inside scans_dir in deterministic order."""
    if scans_dir is None:
        workspace_root = workspace.get_scoreform_workspace_root()
        scans_dir = os.fspath(scans_inbox_dir(workspace_root))

    if not os.path.isdir(scans_dir):
        return []

    scans = []
    for entry in sorted(os.listdir(scans_dir), key=lambda value: value.lower()):
        path = os.path.join(scans_dir, entry)
        if os.path.isfile(path) and is_supported_scan_file(path):
            scans.append(path)
    return scans


def suggest_class_id(class_name):
    """Derive a safe class_id suggestion from a human-readable class name."""
    value = class_name.strip().lower()
    value = re.sub(r"[\s/\\]+", "_", value)
    value = re.sub(r"[^a-z0-9_-]+", "", value)
    value = re.sub(r"_+", "_", value)
    return value.strip("_")


def suggest_assignment_id(title):
    """Derive a safe assignment_id suggestion from a human-readable title."""
    value = title.strip().lower()
    value = re.sub(r"[\s/\\:]+", "_", value)
    value = re.sub(r"[^a-z0-9_-]+", "", value)
    value = re.sub(r"_+", "_", value)
    return value.strip("_")


def discover_class_rosters(classes_dir=None):
    """Return valid class rosters discovered under classes/<class_id>/roster.csv."""
    if classes_dir is None:
        workspace_root = workspace.get_scoreform_workspace_root()
    else:
        classes_path = Path(classes_dir)
        if classes_path.name == "classes":
            workspace_root = classes_path.parent
        else:
            return _discover_class_rosters_in_legacy_directory(classes_path)

    discovered = []
    for class_folder in list_core_class_folders(
        workspace_root,
        require_roster=True,
        load_rosters=True,
    ):
        if class_folder.roster is None:
            continue

        roster_path = os.fspath(class_folder.roster_path)
        discovered.append({
            "class_id": class_folder.class_id,
            "roster_path": roster_path,
            "roster": _core_roster_to_legacy_dict(class_folder.roster),
        })

    return discovered


def _discover_class_rosters_in_legacy_directory(classes_dir):
    """Preserve explicit discovery for non-canonical class directories."""
    if not classes_dir.is_dir():
        return []

    discovered = []
    for class_dir in sorted(classes_dir.iterdir(), key=lambda entry: entry.name):
        roster_path = class_dir / "roster.csv"
        if not class_dir.is_dir() or not roster_path.exists():
            continue

        roster = load_roster(roster_path)
        if roster is None:
            print(f"Skipping invalid roster: {roster_path}")
            continue

        class_id = roster.get("class_id")
        if class_id != class_dir.name:
            print(
                f"Skipping roster with mismatched class_id: {roster_path} "
                f"(folder '{class_dir.name}', roster '{class_id}')"
            )
            continue

        discovered.append({
            "class_id": class_id,
            "roster_path": os.fspath(roster_path),
            "roster": roster,
        })

    return discovered


def discover_class_assignments(class_id, classes_dir=None):
    """Return valid assignments discovered under classes/<class_id>/assignments/*."""
    if not is_safe_identifier(class_id):
        return []

    if classes_dir is None:
        workspace_root = workspace.get_scoreform_workspace_root()
    else:
        classes_path = Path(classes_dir)
        if classes_path.name == "classes":
            workspace_root = classes_path.parent
        else:
            return _discover_class_assignments_in_legacy_directory(
                class_id,
                classes_path,
            )

    assignment_folders = list_core_assignment_folders(workspace_root, class_id)
    return _load_discovered_assignments(assignment_folders)


def _load_discovered_assignments(assignment_folders):
    """Load ScoreForm assignment records from routed assignment folders."""
    discovered = []
    for folder in assignment_folders:
        assignment_path = folder.assignment_dir / "assignment.json"
        if not assignment_path.exists():
            continue

        assignment = load_assignment(assignment_path)
        if assignment is None:
            print(f"Skipping invalid assignment: {assignment_path}")
            continue

        assignment_id = assignment.get("assignment_id")
        if assignment_id != folder.assignment_id:
            print(
                f"Skipping assignment with mismatched assignment_id: {assignment_path} "
                f"(folder '{folder.assignment_id}', assignment '{assignment_id}')"
            )
            continue

        discovered.append({
            "assignment_id": assignment_id,
            "assignment_path": os.fspath(assignment_path),
            "assignment": assignment,
        })

    return discovered


def _discover_class_assignments_in_legacy_directory(class_id, classes_dir):
    """Preserve explicit discovery for non-canonical class directories."""
    assignments_dir = classes_dir / class_id / "assignments"
    if not assignments_dir.is_dir():
        return []

    assignment_folders = []
    for assignment_dir in sorted(
        assignments_dir.iterdir(),
        key=lambda entry: entry.name,
    ):
        if not assignment_dir.is_dir():
            continue

        assignment_folders.append(
            _LegacyAssignmentFolder(
                assignment_id=assignment_dir.name,
                assignment_dir=assignment_dir,
            )
        )

    return _load_discovered_assignments(assignment_folders)


class _LegacyAssignmentFolder:
    """Minimal folder record for non-canonical explicit classes directories."""

    def __init__(self, assignment_id, assignment_dir):
        self.assignment_id = assignment_id
        self.assignment_dir = assignment_dir


def parse_single_selection(selection_text, available_items, item_label):
    """Parse a one-based numeric selection into one item from available_items."""
    if not selection_text or not selection_text.strip():
        raise ValueError(f"Select one {item_label}.")

    selection = selection_text.strip()
    if not selection.isdigit():
        raise ValueError(f"Invalid {item_label} selection: {selection}")

    index = int(selection)
    if index < 1 or index > len(available_items):
        raise ValueError(f"{item_label.capitalize()} selection out of range: {index}")

    return available_items[index - 1]


def parse_class_selection(selection_text, available_classes):
    """Parse comma-separated one-based class selections into class records."""
    if not selection_text or not selection_text.strip():
        raise ValueError("Select at least one class.")

    selected = []
    selected_indexes = set()
    for raw_part in selection_text.split(","):
        part = raw_part.strip()
        if not part:
            raise ValueError("Class selections cannot be empty.")
        if not part.isdigit():
            raise ValueError(f"Invalid class selection: {part}")

        index = int(part)
        if index < 1 or index > len(available_classes):
            raise ValueError(f"Class selection out of range: {index}")

        zero_based = index - 1
        if zero_based in selected_indexes:
            continue

        selected_indexes.add(zero_based)
        selected.append(available_classes[zero_based])

    if not selected:
        raise ValueError("Select at least one class.")

    return selected


def initialize_empty_standards_alignment(question_count):
    """Return empty assignment-local standards alignment for each question."""
    return {str(i): [] for i in range(1, question_count + 1)}


def parse_question_selection(selection_text, question_count):
    """Parse comma-separated question numbers for standards alignment."""
    if not selection_text or not selection_text.strip():
        raise ValueError("Select at least one question.")

    selected = []
    seen = set()
    for raw_part in selection_text.split(","):
        part = raw_part.strip()
        if not part:
            raise ValueError("Question selections cannot be empty.")
        if not part.isdigit():
            raise ValueError(f"Invalid question selection: {part}")

        question_number = int(part)
        if question_number < 1 or question_number > question_count:
            raise ValueError(
                f"Question selection out of range: {question_number}"
            )
        if question_number in seen:
            continue

        seen.add(question_number)
        selected.append(question_number)

    if not selected:
        raise ValueError("Select at least one question.")

    return tuple(selected)


def attach_standard_to_questions(
    standards_by_question,
    *,
    standard_id,
    question_numbers,
    question_count,
):
    """Return assignment-local standards alignment with standard_id attached."""
    updated = initialize_empty_standards_alignment(question_count)
    for question_key, standards in standards_by_question.items():
        q_num = int(question_key)
        if q_num < 1 or q_num > question_count:
            raise ValueError(f"Question number out of range: {q_num}")
        updated[str(q_num)] = [
            standard.strip()
            for standard in standards
            if isinstance(standard, str) and standard.strip()
        ]

    normalized_standard_id = standard_id.strip()
    if not normalized_standard_id:
        raise ValueError("standard_id is required.")

    for question_number in question_numbers:
        if question_number < 1 or question_number > question_count:
            raise ValueError(f"Question number out of range: {question_number}")
        standards = updated[str(question_number)]
        if normalized_standard_id not in standards:
            standards.append(normalized_standard_id)

    return updated


def format_standard_for_selection(definition):
    """Return compact teacher-readable text for a shared standard."""
    pieces = [
        definition.standard_id,
        definition.code,
        definition.short_name,
    ]
    if definition.subject:
        pieces.append(definition.subject)
    if definition.domain:
        pieces.append(definition.domain)
    return " | ".join(pieces)


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


def write_roster_csv(path, class_id, period, students):
    """Write a roster CSV file.

    Args:
        path: Output CSV file path.
        class_id: Class ID for all students.
        period: Period for all students.
        students: List of dicts with student_id, last_name, first_name.

    Returns:
        True if successful, False otherwise.
    """
    try:
        if not validate_identifier("class_id", class_id, context="roster"):
            return False
        for student in students:
            if not validate_identifier("student_id", student.get("student_id"), context="roster"):
                return False

        rows = [
            {
                "student_id": student["student_id"],
                "last_name": student["last_name"],
                "first_name": student["first_name"],
                "period": period,
            }
            for student in students
        ]
        roster = create_core_roster(class_id, rows)

        parent_dir = os.path.dirname(path)
        if parent_dir and not os.path.exists(parent_dir):
            try:
                os.makedirs(parent_dir, exist_ok=True)
                print(f"Created directory: {parent_dir}")
            except Exception as e:
                print(f"Error: Could not create parent directory '{parent_dir}': {e}")
                return False

        write_core_roster(path, roster, overwrite=True)
        return True
    except RosterError as e:
        print(f"Error: Could not write roster CSV '{path}': {e}")
        return False
    except Exception as e:
        print(f"Error: Could not write roster CSV '{path}': {e}")
        return False


def write_assignment_json(path, assignment):
    """Write an assignment JSON file to `path`. Creates parent directories if needed."""
    try:
        if not validate_identifier("assignment_id", assignment.get("assignment_id"), context="assignment"):
            return False

        parent_dir = os.path.dirname(path)
        if parent_dir and not os.path.exists(parent_dir):
            try:
                os.makedirs(parent_dir, exist_ok=True)
                print(f"Created directory: {parent_dir}")
            except Exception as e:
                print(f"Error: Could not create parent directory '{parent_dir}': {e}")
                return False

        with open(path, 'w', encoding='utf-8') as f:
            json.dump(assignment, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"Error: Could not write assignment JSON '{path}': {e}")
        return False


def confirm_overwrite(path):
    """Prompt for confirmation to overwrite an existing file.

    Returns True if user confirms overwrite or file does not exist, False otherwise.
    """
    if not os.path.exists(path):
        return True

    response = input(f"File '{path}' already exists. Overwrite? (y/yes to confirm): ").strip().lower()
    return response in ['y', 'yes']


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


def confirm_assignment_overwrite(path, class_id):
    """Prompt for confirmation to overwrite an existing class assignment."""
    if not os.path.exists(path):
        return True

    print(f"Assignment already exists for class '{class_id}':")
    print(path)
    print()
    response = input("Overwrite? (y/yes to confirm): ").strip().lower()
    return response in ['y', 'yes']


def _standards_sort_key(definition):
    return (
        definition.source.lower(),
        definition.code.lower(),
        definition.standard_id.lower(),
    )


def _parse_optional_list_input(value):
    if not value.strip():
        return ()
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _prompt_required_text(prompt):
    while True:
        value = input(prompt).strip()
        if value:
            return value
        print("Error: this field is required.")


def _prompt_questions_for_standard(standards_by_question, standard_id, question_count):
    while True:
        selection_text = input("Attach to question(s), comma-separated: ").strip()
        try:
            question_numbers = parse_question_selection(
                selection_text,
                question_count,
            )
            return attach_standard_to_questions(
                standards_by_question,
                standard_id=standard_id,
                question_numbers=question_numbers,
                question_count=question_count,
            )
        except ValueError as e:
            print(f"Error: {e}")


def _prompt_attach_existing_standards(workspace_root, question_count):
    try:
        library = load_workspace_standards_library(workspace_root)
    except Exception as e:
        print(f"Error: Could not load shared standards library: {e}")
        return None

    definitions = sorted(
        filter_standard_definitions(library, active=True),
        key=_standards_sort_key,
    )
    if not definitions:
        print("No shared standards exist yet.")
        print("Return to the standards alignment menu to skip or add a new standard.")
        return None

    standards_by_question = initialize_empty_standards_alignment(question_count)

    while True:
        print()
        print("Available shared standards:")
        for index, definition in enumerate(definitions, start=1):
            print(f"{index}. {format_standard_for_selection(definition)}")
        print()
        selection_text = input("Select standard to attach, or press Enter when done: ").strip()
        if not selection_text:
            return standards_by_question

        try:
            definition = parse_single_selection(
                selection_text,
                definitions,
                "standard",
            )
        except ValueError as e:
            print(f"Error: {e}")
            continue

        standards_by_question = _prompt_questions_for_standard(
            standards_by_question,
            definition.standard_id,
            question_count,
        )


def _prompt_new_standard_definition():
    print()
    print("New shared standard")
    standard_id = _prompt_required_text("standard_id: ")
    code = _prompt_required_text("code: ")
    source = _prompt_required_text("source: ")
    short_name = _prompt_required_text("short_name: ")
    description = _prompt_required_text("description: ")

    subject = input("subject (optional): ").strip() or None
    course = input("course (optional): ").strip() or None
    grade_band = input("grade_band (optional): ").strip() or None
    domain = input("domain (optional): ").strip() or None
    category_path = _parse_optional_list_input(
        input("category_path, comma-separated (optional): ")
    )
    tags = _parse_optional_list_input(input("tags, comma-separated (optional): "))
    available_modules = _parse_optional_list_input(
        input("available_modules, comma-separated [pds-scoreform]: ")
    )
    if not available_modules:
        available_modules = ("pds-scoreform",)
    elif "pds-scoreform" not in available_modules:
        available_modules = available_modules + ("pds-scoreform",)

    definition = StandardDefinition(
        standard_id=standard_id,
        code=code,
        source=source,
        short_name=short_name,
        description=description,
        subject=subject,
        course=course,
        grade_band=grade_band,
        domain=domain,
        category_path=category_path,
        tags=tags,
        active=True,
        available_modules=available_modules,
    )
    return validate_standard_definition(definition)


def _prompt_create_and_attach_new_standard(workspace_root, question_count):
    try:
        definition = _prompt_new_standard_definition()
        library = load_workspace_standards_library(workspace_root)
        updated_library = upsert_standard_definition(library, definition)
        write_workspace_standards_library(
            workspace_root,
            updated_library,
            overwrite=True,
        )
    except StandardsValidationError as e:
        print(f"Error: Invalid standard definition: {e}")
        return None
    except Exception as e:
        print(f"Error: Could not save shared standards library: {e}")
        return None

    try:
        saved_library = load_workspace_standards_library(workspace_root)
        saved_definition = find_standard_definition(
            saved_library,
            definition.standard_id,
        )
    except Exception as e:
        print(f"Error: Could not verify saved standard: {e}")
        return None

    if saved_definition is None:
        print("Error: New standard was not found after saving.")
        return None

    standards_by_question = initialize_empty_standards_alignment(question_count)
    return _prompt_questions_for_standard(
        standards_by_question,
        definition.standard_id,
        question_count,
    )


def prompt_standards_alignment(workspace_root, question_count):
    """Prompt for assignment-local standards alignment during assignment creation."""
    while True:
        print()
        print("Standards alignment")
        print("1. Skip standards for now")
        print("2. Attach existing shared standards")
        print("3. Enter a new shared standard, then attach it")
        print()

        choice = input("Select an option: ").strip()
        if choice == "1":
            return initialize_empty_standards_alignment(question_count)
        if choice == "2":
            standards_by_question = _prompt_attach_existing_standards(
                workspace_root,
                question_count,
            )
            if standards_by_question is not None:
                return standards_by_question
            continue
        if choice == "3":
            standards_by_question = _prompt_create_and_attach_new_standard(
                workspace_root,
                question_count,
            )
            if standards_by_question is not None:
                return standards_by_question
            continue

        print("Invalid selection. Please enter 1, 2, or 3.")


def prompt_create_assignment():
    """Interactive prompt to create assignment JSON files for selected classes.

    Returns 0 on success, 1 on cancellation or error.
    """
    print_menu_header("Create an Assignment for Class(es)")

    available_classes = discover_class_rosters()
    if not available_classes:
        print("No class rosters found. Create a class roster first from the Roster Management menu.")
        return 1

    print("Available classes:")
    for index, class_record in enumerate(available_classes, start=1):
        student_count = len(class_record["roster"].get("students", []))
        print(f"{index}. {class_record['class_id']} ({student_count} students)")
    print()

    selection_text = input("Select class(es), comma-separated: ").strip()
    try:
        selected_classes = parse_class_selection(selection_text, available_classes)
    except ValueError as e:
        print(f"Error: {e}")
        return 1

    print()
    title = input("Assignment title: ").strip()
    if not title:
        print("Error: title is required.")
        return 1

    suggested_assignment_id = suggest_assignment_id(title)
    assignment_id = ""
    if is_safe_identifier(suggested_assignment_id):
        print(f"Suggested assignment_id: {suggested_assignment_id}")
        assignment_id = input("Press Enter to accept, or type a different assignment_id: ").strip()
        if not assignment_id:
            assignment_id = suggested_assignment_id
    else:
        print("Could not create a safe assignment_id suggestion from that title.")
        assignment_id = input("Enter a valid assignment_id: ").strip()

    if not assignment_id:
        print("Error: assignment_id is required.")
        return 1
    if not validate_identifier("assignment_id", assignment_id, context="assignment"):
        return 1

    print()

    choices = ["A", "B", "C", "D"]
    question_count = None
    while question_count is None:
        count_input = input(f"Question count (1-{MAX_QUESTION_COUNT}): ").strip()
        if not count_input.isdigit():
            print(f"Error: question_count must be an integer from 1 to {MAX_QUESTION_COUNT}.")
            continue
        count_value = int(count_input)
        if count_value < 1 or count_value > MAX_QUESTION_COUNT:
            print(f"Error: question_count must be an integer from 1 to {MAX_QUESTION_COUNT}.")
            continue
        question_count = count_value

    print()
    print(f"Using question_count: {question_count}")
    print("Using choices: A, B, C, D")
    print()

    answer_key = {}

    for i in range(1, question_count + 1):
        while True:
            ans = input(f"Q{i} answer (A/B/C/D): ").strip().upper()
            if ans in choices:
                answer_key[str(i)] = ans
                break
            print("Error: Answer must be one of A, B, C, or D (case-insensitive). Please try again.")

    workspace_root = workspace.get_scoreform_workspace_root()
    standards_by_question = prompt_standards_alignment(
        workspace_root,
        question_count,
    )

    assignment = {
        "assignment_id": assignment_id,
        "title": title,
        "question_count": question_count,
        "choices": choices,
        "answer_key": answer_key,
        "standards": standards_by_question,
    }

    written_paths = []
    skipped_paths = []
    for class_record in selected_classes:
        class_id = class_record["class_id"]
        folder = ensure_core_assignment_folder(
            workspace_root,
            class_id,
            assignment_id,
        )
        output_path = os.fspath(folder.assignment_dir / "assignment.json")

        if not confirm_assignment_overwrite(output_path, class_id):
            print(f"Skipped: {output_path}")
            skipped_paths.append(output_path)
            continue

        print(f"Writing assignment to: {output_path}")
        if not write_assignment_json(output_path, assignment):
            print(f"Error: Failed to write assignment JSON for class '{class_id}'.")
            skipped_paths.append(output_path)
            continue

        print("Validating assignment...")
        loaded = load_assignment(output_path)
        if loaded is None:
            print(f"Error: Assignment validation failed after save for class '{class_id}'.")
            skipped_paths.append(output_path)
            continue

        written_paths.append(output_path)

    if not written_paths:
        print("Error: No assignment files were created.")
        return 1

    print()
    print(f"Success! Assignment created and validated for {len(written_paths)} class(es).")
    if skipped_paths:
        print(f"Skipped {len(skipped_paths)} class(es) without overwriting existing files.")
    print("Created assignment file(s):")
    for path in written_paths:
        print(f"  {path}")

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

                # Validate using load_roster and print results
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


def launch_assignment_menu():
    """Assignment management submenu."""
    try:
        while True:
            clear_screen()
            print_menu_header("Assignment Management")
            print("1. Create an assignment")
            print("2. Validate an assignment file")
            print("3. Generate answer sheets")
            print("4. Score scanned responses")
            print("5. Decode QR from a file")
            print("6. Return to main menu")
            print()

            choice = input("Select an option: ").strip()
            print()

            if choice == "1":
                clear_screen()
                prompt_create_assignment()
                print()
                pause_for_user()

            elif choice == "2":
                clear_screen()
                print_menu_header("Validate an Assignment File")
                assignment_path = normalize_path_input(input("Assignment JSON path: "))
                if not assignment_path:
                    print("Assignment file path is required.")
                    print()
                    pause_for_user()
                    continue

                # Validate using load_assignment and print results
                assignment = load_assignment(assignment_path)
                if assignment is None:
                    print()
                    pause_for_user()
                    continue
                print("Assignment file is valid.")
                print(assignment)
                print()
                pause_for_user()

            elif choice == "3":
                from scoreform.cli import launch_generate_menu

                launch_generate_menu()

            elif choice == "4":
                from scoreform.cli import prompt_scoring_input_file, prompt_scoring_mode

                input_file = prompt_scoring_input_file()
                if input_file:
                    prompt_scoring_mode(input_file)

            elif choice == "5":
                from scoreform.cli import run_decode_qr

                clear_screen()
                print_menu_header("Decode QR from a File")
                input_file = normalize_path_input(input("File path: "))
                if not input_file:
                    print("File path is required.")
                    print()
                    pause_for_user()
                    continue

                run_decode_qr([input_file])
                print()
                pause_for_user()

            elif choice == "6":
                return 0

            else:
                print(f"Invalid selection: {choice}. Please enter a number from 1 to 6.")
                print()
                pause_for_user()

    except KeyboardInterrupt:
        print("\nExiting assignment menu.")
        return 0
