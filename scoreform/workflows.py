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
from scoreform.assignment import load_assignment, validate_assignment_data
from scoreform.config import MAX_QUESTION_COUNT
from scoreform.results_viewer import (
    ResultsViewError,
    format_assignment_results_table,
    load_assignment_results,
    summarize_assignment_results,
)
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


def _assignment_answer_key_for_edit(assignment):
    return {
        str(question_number): assignment["answer_key"][question_number]
        for question_number in range(1, assignment["question_count"] + 1)
    }


def _assignment_standards_for_edit(assignment):
    question_count = assignment["question_count"]
    standards_by_question = initialize_empty_standards_alignment(question_count)
    for question_number, standards in assignment.get("standards", {}).items():
        standards_by_question[str(question_number)] = list(standards)
    return standards_by_question


def _assignment_for_edit(assignment):
    """Return a JSON-shaped copy of a loaded assignment for staged editing."""
    return {
        "assignment_id": assignment["assignment_id"],
        "title": assignment["title"],
        "question_count": assignment["question_count"],
        "choices": list(assignment["choices"]),
        "answer_key": _assignment_answer_key_for_edit(assignment),
        "standards": _assignment_standards_for_edit(assignment),
    }


def format_assignment_for_display(assignment_record):
    """Return a compact terminal summary for an assignment record."""
    assignment = assignment_record["assignment"]
    question_count = assignment["question_count"]
    answer_key = assignment["answer_key"]
    standards = assignment.get("standards", {})
    aligned = [
        question_number
        for question_number in range(1, question_count + 1)
        if standards.get(str(question_number)) or standards.get(question_number)
    ]
    unaligned = [
        question_number
        for question_number in range(1, question_count + 1)
        if not standards.get(str(question_number)) and not standards.get(question_number)
    ]

    answer_summary = ", ".join(
        f"Q{question_number}:{answer_key[question_number]}"
        for question_number in range(1, question_count + 1)
    )
    if len(answer_summary) > 120:
        answer_summary = f"{len(answer_key)} entries; first five: " + ", ".join(
            f"Q{question_number}:{answer_key[question_number]}"
            for question_number in range(1, min(question_count, 5) + 1)
        )

    if aligned:
        standards_summary = (
            f"{len(aligned)} aligned, {len(unaligned)} unaligned"
        )
        if unaligned:
            standards_summary += ": " + ", ".join(
                f"Q{question_number}" for question_number in unaligned[:10]
            )
            if len(unaligned) > 10:
                standards_summary += ", ..."
    else:
        standards_summary = "No standards aligned."

    return "\n".join([
        f"class_id: {assignment_record['class_id']}",
        f"assignment_id: {assignment['assignment_id']}",
        f"title: {assignment['title']}",
        f"question_count: {question_count}",
        f"choices: {', '.join(assignment['choices'])}",
        f"answer_key: {answer_summary}",
        f"standards: {standards_summary}",
        f"assignment path: {assignment_record['assignment_path']}",
    ])


def _print_assignment_answer_key(assignment):
    print("Answer key:")
    for question_number in range(1, assignment["question_count"] + 1):
        print(f"  Q{question_number}: {assignment['answer_key'][str(question_number)]}")


def _print_assignment_standards(assignment):
    print("Standards alignment:")
    for question_number in range(1, assignment["question_count"] + 1):
        standards = assignment["standards"].get(str(question_number), [])
        if standards:
            print(f"  Q{question_number}: {', '.join(standards)}")
        else:
            print(f"  Q{question_number}: (unaligned)")


def _prompt_edit_assignment_title(assignment):
    print(f"Current title: {assignment['title']}")
    new_title = input("New title: ").strip()
    if not new_title:
        print("Error: title is required.")
        return assignment, False
    updated = dict(assignment)
    updated["title"] = new_title
    return updated, new_title != assignment["title"]


def _prompt_edit_assignment_answer_key(assignment):
    updated = dict(assignment)
    updated["answer_key"] = dict(assignment["answer_key"])
    changed = False

    while True:
        _print_assignment_answer_key(updated)
        print()
        selection_text = input("Question to edit: ").strip()
        if not selection_text:
            print("Error: Select one question.")
        elif not selection_text.isdigit():
            print(f"Error: Invalid question selection: {selection_text}")
        else:
            question_number = int(selection_text)
            if question_number < 1 or question_number > assignment["question_count"]:
                print(f"Error: Question selection out of range: {question_number}")
            else:
                question_key = str(question_number)
                current_answer = updated["answer_key"][question_key]
                print(f"Current answer for Q{question_number}: {current_answer}")

                new_answer = input("New answer: ").strip().upper()
                if new_answer not in assignment["choices"]:
                    print(
                        "Error: Answer must be one of "
                        f"{', '.join(assignment['choices'])}."
                    )
                elif current_answer == new_answer:
                    print(f"No change staged for Q{question_number}.")
                else:
                    updated["answer_key"][question_key] = new_answer
                    changed = True
                    print(
                        f"Staged: Q{question_number} changed from "
                        f"{current_answer} to {new_answer}."
                    )

        continue_editing = input("Edit another answer? (y/yes): ").strip().lower()
        if continue_editing not in {"y", "yes"}:
            return updated, changed
        print()


def _load_active_standard_definitions(workspace_root):
    library = load_workspace_standards_library(workspace_root)
    return sorted(
        filter_standard_definitions(library, active=True),
        key=_standards_sort_key,
    )


def _prompt_existing_standard_id(workspace_root):
    try:
        definitions = _load_active_standard_definitions(workspace_root)
    except Exception as e:
        print(f"Error: Could not load shared standards library: {e}")
        return None

    if not definitions:
        print("No shared standards exist yet.")
        return None

    print()
    print("Available shared standards:")
    for index, definition in enumerate(definitions, start=1):
        print(f"{index}. {format_standard_for_selection(definition)}")
    print()

    selection_text = input("Select standard: ").strip()
    try:
        definition = parse_single_selection(
            selection_text,
            definitions,
            "standard",
        )
    except ValueError as e:
        print(f"Error: {e}")
        return None

    if find_standard_definition(
        load_workspace_standards_library(workspace_root),
        definition.standard_id,
    ) is None:
        print(f"Error: Standard ID not found: {definition.standard_id}")
        return None
    return definition.standard_id


def _prompt_assignment_standard_questions(assignment):
    try:
        return parse_question_selection(
            input("Question(s), comma-separated: "),
            assignment["question_count"],
        )
    except ValueError as e:
        print(f"Error: {e}")
        return None


def _prompt_attach_standard_to_assignment(assignment, workspace_root):
    standard_id = _prompt_existing_standard_id(workspace_root)
    if standard_id is None:
        return assignment, False
    question_numbers = _prompt_assignment_standard_questions(assignment)
    if question_numbers is None:
        return assignment, False

    try:
        standards = attach_standard_to_questions(
            assignment["standards"],
            standard_id=standard_id,
            question_numbers=question_numbers,
            question_count=assignment["question_count"],
        )
    except ValueError as e:
        print(f"Error: {e}")
        return assignment, False

    updated = dict(assignment)
    updated["standards"] = standards
    return updated, standards != assignment["standards"]


def _prompt_remove_standard_from_assignment(assignment, workspace_root):
    standard_id = _prompt_existing_standard_id(workspace_root)
    if standard_id is None:
        return assignment, False
    question_numbers = _prompt_assignment_standard_questions(assignment)
    if question_numbers is None:
        return assignment, False

    updated_standards = {
        str(question_number): list(assignment["standards"].get(str(question_number), []))
        for question_number in range(1, assignment["question_count"] + 1)
    }
    changed = False
    for question_number in question_numbers:
        question_key = str(question_number)
        before = list(updated_standards[question_key])
        updated_standards[question_key] = [
            value for value in before if value != standard_id
        ]
        if updated_standards[question_key] != before:
            changed = True

    updated = dict(assignment)
    updated["standards"] = updated_standards
    return updated, changed


def _prompt_clear_assignment_standards(assignment):
    question_numbers = _prompt_assignment_standard_questions(assignment)
    if question_numbers is None:
        return assignment, False

    updated_standards = {
        str(question_number): list(assignment["standards"].get(str(question_number), []))
        for question_number in range(1, assignment["question_count"] + 1)
    }
    changed = False
    for question_number in question_numbers:
        question_key = str(question_number)
        if updated_standards[question_key]:
            updated_standards[question_key] = []
            changed = True

    updated = dict(assignment)
    updated["standards"] = updated_standards
    return updated, changed


def _prompt_edit_assignment_standards(assignment, workspace_root):
    while True:
        print()
        _print_assignment_standards(assignment)
        print()
        print("Standards alignment menu")
        print("1. Attach existing standard")
        print("2. Remove standard")
        print("3. Clear standards for question(s)")
        print("4. Return to assignment edit menu")
        print()

        choice = input("Select an option: ").strip()
        print()

        if choice == "1":
            return _prompt_attach_standard_to_assignment(assignment, workspace_root)
        if choice == "2":
            return _prompt_remove_standard_from_assignment(assignment, workspace_root)
        if choice == "3":
            return _prompt_clear_assignment_standards(assignment)
        if choice == "4":
            return assignment, False

        print("Invalid selection. Please enter 1, 2, 3, or 4.")


def _assignment_record_for_display(class_id, assignment_path, assignment):
    return {
        "class_id": class_id,
        "assignment_id": assignment["assignment_id"],
        "assignment_path": assignment_path,
        "assignment": {
            "assignment_id": assignment["assignment_id"],
            "title": assignment["title"],
            "question_count": assignment["question_count"],
            "choices": list(assignment["choices"]),
            "answer_key": {
                int(question_number): answer
                for question_number, answer in assignment["answer_key"].items()
            },
            "standards": {
                int(question_number): list(standards)
                for question_number, standards in assignment["standards"].items()
            },
        },
    }


def _validate_staged_assignment(assignment):
    required_keys = {
        "assignment_id",
        "title",
        "question_count",
        "choices",
        "answer_key",
        "standards",
    }
    if set(assignment) < required_keys:
        print("Error: staged assignment is missing required fields.")
        return False
    if not assignment["title"].strip():
        print("Error: title is required.")
        return False
    if set(assignment["answer_key"]) != {
        str(question_number)
        for question_number in range(1, assignment["question_count"] + 1)
    }:
        print("Error: answer_key must preserve all existing questions.")
        return False
    if set(assignment["standards"]) != {
        str(question_number)
        for question_number in range(1, assignment["question_count"] + 1)
    }:
        print("Error: standards must preserve all existing questions.")
        return False
    return validate_assignment_data(assignment) is not None


def prompt_edit_assignment():
    """Interactive workflow for staging and saving edits to an assignment."""
    print_menu_header("Edit an Assignment")

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

    class_id = class_record["class_id"]
    available_assignments = discover_class_assignments(class_id)
    if not available_assignments:
        print(f"No assignments found for class '{class_id}'.")
        print("Create an assignment first, then return to this option.")
        return 1

    print()
    print(f"Available assignments for {class_id}:")
    for index, assignment_record in enumerate(available_assignments, start=1):
        title = assignment_record["assignment"].get("title", "")
        print(f"{index}. {assignment_record['assignment_id']} - {title}")
    print()

    try:
        assignment_record = parse_single_selection(
            input("Select assignment: "),
            available_assignments,
            "assignment",
        )
    except ValueError as e:
        print(f"Error: {e}")
        return 1

    assignment_path = assignment_record["assignment_path"]
    loaded_assignment = load_assignment(assignment_path)
    if loaded_assignment is None:
        print(f"Error: Could not load assignment: {assignment_path}")
        return 1

    workspace_root = workspace.get_scoreform_workspace_root()
    staged_assignment = _assignment_for_edit(loaded_assignment)
    original_identity = (
        staged_assignment["assignment_id"],
        staged_assignment["question_count"],
        tuple(staged_assignment["choices"]),
    )
    dirty = False

    print()
    print(format_assignment_for_display(
        _assignment_record_for_display(class_id, assignment_path, staged_assignment)
    ))
    print()
    print("assignment_id, question_count, and choices are not editable here.")
    print("Changes are staged until you choose Save changes.")

    while True:
        print()
        print("Edit menu")
        print("1. Edit title")
        print("2. Edit answer key")
        print("3. Edit standards alignment")
        print("4. View current assignment summary")
        print("5. Save changes")
        print("6. Cancel without saving")
        print()

        choice = input("Select an option: ").strip()
        print()

        if choice == "1":
            updated_assignment, changed = _prompt_edit_assignment_title(
                staged_assignment,
            )
            if changed:
                staged_assignment = updated_assignment
                dirty = True
                print("Staged: title updated.")
            else:
                print("No title change staged.")

        elif choice == "2":
            updated_assignment, changed = _prompt_edit_assignment_answer_key(
                staged_assignment,
            )
            if changed:
                staged_assignment = updated_assignment
                dirty = True
                print("Staged: answer key updated.")
                print("Historical results are not changed or rescored.")
            else:
                print("No answer-key change staged.")

        elif choice == "3":
            updated_assignment, changed = _prompt_edit_assignment_standards(
                staged_assignment,
                workspace_root,
            )
            if changed:
                staged_assignment = updated_assignment
                dirty = True
                print("Staged: standards alignment updated.")
            else:
                print("No standards change staged.")

        elif choice == "4":
            print(format_assignment_for_display(
                _assignment_record_for_display(
                    class_id,
                    assignment_path,
                    staged_assignment,
                )
            ))
            if dirty:
                print()
                print("Unsaved staged changes are shown above.")

        elif choice == "5":
            if not dirty:
                print("No changes to save.")
                return 0
            if original_identity != (
                staged_assignment["assignment_id"],
                staged_assignment["question_count"],
                tuple(staged_assignment["choices"]),
            ):
                print("Error: immutable assignment fields changed unexpectedly.")
                continue
            if not _validate_staged_assignment(staged_assignment):
                print("Error: staged assignment validation failed.")
                continue
            confirmation = input("Type SAVE to write staged changes: ").strip()
            if confirmation != "SAVE":
                print("Cancelled: save not confirmed.")
                continue
            if not write_assignment_json(assignment_path, staged_assignment):
                print("Error: Failed to save assignment JSON.")
                continue
            saved_assignment = load_assignment(assignment_path)
            if saved_assignment is None:
                print("Error: Assignment validation failed after save.")
                continue
            print(f"Saved assignment: {assignment_path}")
            return 0

        elif choice == "6":
            if dirty:
                confirmation = input(
                    "Type DISCARD to discard staged changes: "
                ).strip()
                if confirmation != "DISCARD":
                    print("Cancelled: staged changes were not discarded.")
                    continue
            print("Cancelled: no assignment changes were saved.")
            return 0

        else:
            print(f"Invalid selection: {choice}. Please enter a number from 1 to 6.")


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


def format_roster_for_display(class_record):
    """Compatibility wrapper for roster display formatting."""
    return _roster_workflows_module().format_roster_for_display(class_record)


def prompt_edit_class_roster():
    """Compatibility wrapper for the roster edit workflow."""
    return _roster_workflows_module().prompt_edit_class_roster()


def launch_view_assignment_results_menu():
    """Interactive read-only workflow for viewing assignment-local results."""
    print_menu_header("View Assignment Results")

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

    class_id = class_record["class_id"]
    available_assignments = discover_class_assignments(class_id)
    if not available_assignments:
        print(f"No assignments found for class '{class_id}'.")
        print("Create an assignment first, then return to this option.")
        return 1

    print()
    print(f"Available assignments for {class_id}:")
    for index, assignment_record in enumerate(available_assignments, start=1):
        title = assignment_record["assignment"].get("title", "")
        print(f"{index}. {assignment_record['assignment_id']} - {title}")
    print()

    try:
        assignment_record = parse_single_selection(
            input("Select assignment: "),
            available_assignments,
            "assignment",
        )
    except ValueError as e:
        print(f"Error: {e}")
        return 1

    assignment_id = assignment_record["assignment_id"]
    results_csv_path = Path(assignment_record["assignment_path"]).parent / "results.csv"

    print()
    print(f"Results for: {class_id} / {assignment_id}")
    print(f"Source: {results_csv_path}")
    print()

    try:
        rows = load_assignment_results(results_csv_path)
    except FileNotFoundError:
        print("No results have been recorded for this assignment yet.")
        return 0
    except ResultsViewError as e:
        print(f"Error: Could not read assignment results: {e}")
        return 1

    if not rows:
        print("No results have been recorded for this assignment yet.")
        return 0

    summary_rows = summarize_assignment_results(rows)
    print(format_assignment_results_table(summary_rows))
    return 0


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
    """Compatibility wrapper for the Roster Management menu."""
    return _roster_workflows_module().launch_roster_menu()


def launch_assignment_menu():
    """Assignment management submenu."""
    try:
        while True:
            clear_screen()
            print_menu_header("Assignment Management")
            print("1. Create an assignment")
            print("2. Edit an assignment")
            print("3. Validate an assignment file")
            print("4. Generate answer sheets")
            print("5. Score scanned responses")
            print("6. View assignment results")
            print("7. Decode QR from a file")
            print("8. Return to main menu")
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
                prompt_edit_assignment()
                print()
                pause_for_user()

            elif choice == "3":
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

            elif choice == "4":
                from scoreform.cli import launch_generate_menu

                launch_generate_menu()

            elif choice == "5":
                from scoreform.cli import prompt_scoring_input_file, prompt_scoring_mode

                input_file = prompt_scoring_input_file()
                if input_file:
                    prompt_scoring_mode(input_file)

            elif choice == "6":
                clear_screen()
                launch_view_assignment_results_menu()
                print()
                pause_for_user()

            elif choice == "7":
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

            elif choice == "8":
                return 0

            else:
                print(f"Invalid selection: {choice}. Please enter a number from 1 to 8.")
                print()
                pause_for_user()

    except KeyboardInterrupt:
        print("\nExiting assignment menu.")
        return 0
