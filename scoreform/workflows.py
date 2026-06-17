"""Interactive workflow helpers split from cli.py.

Contains:
- confirm_overwrite
- write_roster_csv
- write_assignment_json
- prompt_create_assignment
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
)
from pds_core.rosters import (
    create_roster as create_core_roster,
)
from pds_core.rosters import (
    write_roster as write_core_roster,
)
from pds_core.scan_routes import scans_inbox_dir
from pds_core.standards import write_workspace_standards_library

from scoreform import workspace
from scoreform.assignment import load_assignment
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


def _roster_workflows_module():
    from scoreform import roster_workflows

    roster_workflows.clear_screen = clear_screen
    roster_workflows.discover_class_rosters = discover_class_rosters
    roster_workflows.load_class_roster = load_class_roster
    roster_workflows.normalize_path_input = normalize_path_input
    roster_workflows.parse_single_selection = parse_single_selection
    roster_workflows.pause_for_user = pause_for_user
    roster_workflows.print_menu_header = print_menu_header
    roster_workflows.suggest_class_id = suggest_class_id
    roster_workflows.write_class_roster = write_class_roster
    roster_workflows.write_roster_csv = write_roster_csv
    return roster_workflows


def _assignment_workflows_module():
    from scoreform import assignment_workflows

    assignment_workflows.attach_standard_to_questions = attach_standard_to_questions
    assignment_workflows.clear_screen = clear_screen
    assignment_workflows.discover_class_assignments = discover_class_assignments
    assignment_workflows.discover_class_rosters = discover_class_rosters
    assignment_workflows.ensure_core_assignment_folder = (
        ensure_core_assignment_folder
    )
    assignment_workflows.initialize_empty_standards_alignment = (
        initialize_empty_standards_alignment
    )
    assignment_workflows.normalize_path_input = normalize_path_input
    assignment_workflows.parse_class_selection = parse_class_selection
    assignment_workflows.parse_question_selection = parse_question_selection
    assignment_workflows.parse_single_selection = parse_single_selection
    assignment_workflows.pause_for_user = pause_for_user
    assignment_workflows.print_menu_header = print_menu_header
    assignment_workflows.suggest_assignment_id = suggest_assignment_id
    assignment_workflows.write_assignment_json = write_assignment_json
    assignment_workflows.write_workspace_standards_library = (
        write_workspace_standards_library
    )
    return assignment_workflows


def format_assignment_for_display(assignment_record):
    """Compatibility wrapper for assignment display formatting."""
    return _assignment_workflows_module().format_assignment_for_display(
        assignment_record
    )


def prompt_edit_assignment():
    """Compatibility wrapper for the assignment edit workflow."""
    return _assignment_workflows_module().prompt_edit_assignment()


def format_roster_for_display(class_record):
    """Compatibility wrapper for roster display formatting."""
    return _roster_workflows_module().format_roster_for_display(class_record)


def prompt_edit_class_roster():
    """Compatibility wrapper for the roster edit workflow."""
    return _roster_workflows_module().prompt_edit_class_roster()


def launch_view_assignment_results_menu():
    """Compatibility wrapper for the assignment results viewer workflow."""
    return _assignment_workflows_module().launch_view_assignment_results_menu()


def prompt_view_roster():
    """Compatibility wrapper for the roster view workflow."""
    return _roster_workflows_module().prompt_view_roster()


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
    """Compatibility wrapper for roster overwrite confirmation."""
    return _roster_workflows_module().confirm_roster_overwrite(path, class_id)


def prompt_create_roster():
    """Compatibility wrapper for the roster creation workflow."""
    return _roster_workflows_module().prompt_create_roster()


def confirm_assignment_overwrite(path, class_id):
    """Compatibility wrapper for assignment overwrite confirmation."""
    return _assignment_workflows_module().confirm_assignment_overwrite(path, class_id)


def prompt_standards_alignment(workspace_root, question_count):
    """Compatibility wrapper for assignment standards alignment prompts."""
    return _assignment_workflows_module().prompt_standards_alignment(
        workspace_root,
        question_count,
    )


def prompt_create_assignment():
    """Compatibility wrapper for the assignment creation workflow."""
    return _assignment_workflows_module().prompt_create_assignment()


def launch_roster_menu():
    """Compatibility wrapper for the Roster Management menu."""
    return _roster_workflows_module().launch_roster_menu()


def launch_assignment_menu():
    """Compatibility wrapper for the Assignment Management menu."""
    return _assignment_workflows_module().launch_assignment_menu()
