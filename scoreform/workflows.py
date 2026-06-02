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

import os
import csv
import json
import re

from scoreform.roster import load_roster
from scoreform.assignment import load_assignment
from scoreform.validation import is_safe_identifier, validate_identifier


def normalize_path_input(value):
    """Strip whitespace and one matching pair of surrounding quotes from a path input."""
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


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


def discover_class_rosters(classes_dir="classes"):
    """Return valid class rosters discovered under classes/<class_id>/roster.csv."""
    if not os.path.isdir(classes_dir):
        return []

    discovered = []
    for entry in sorted(os.listdir(classes_dir)):
        class_dir = os.path.join(classes_dir, entry)
        roster_path = os.path.join(class_dir, "roster.csv")
        if not os.path.isdir(class_dir) or not os.path.exists(roster_path):
            continue

        roster = load_roster(roster_path)
        if roster is None:
            print(f"Skipping invalid roster: {roster_path}")
            continue

        class_id = roster.get("class_id")
        if class_id != entry:
            print(
                f"Skipping roster with mismatched class_id: {roster_path} "
                f"(folder '{entry}', roster '{class_id}')"
            )
            continue

        discovered.append({
            "class_id": class_id,
            "roster_path": roster_path,
            "roster": roster,
        })

    return discovered


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

        parent_dir = os.path.dirname(path)
        if parent_dir and not os.path.exists(parent_dir):
            try:
                os.makedirs(parent_dir, exist_ok=True)
                print(f"Created directory: {parent_dir}")
            except Exception as e:
                print(f"Error: Could not create parent directory '{parent_dir}': {e}")
                return False

        with open(path, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['class_id', 'student_id', 'last_name', 'first_name', 'period'])
            writer.writeheader()
            for student in students:
                writer.writerow({
                    'class_id': class_id,
                    'student_id': student['student_id'],
                    'last_name': student['last_name'],
                    'first_name': student['first_name'],
                    'period': period,
                })
        return True
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
    print("--- Create a Class Roster ---")
    print()

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

    output_path = os.path.join("classes", class_id, "roster.csv")

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


def prompt_create_assignment():
    """Interactive prompt to create assignment JSON files for selected classes.

    Returns 0 on success, 1 on cancellation or error.
    """
    print("--- Create an Assignment for Class(es) ---")
    print()

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
        count_input = input("Question count (1-15): ").strip()
        if not count_input.isdigit():
            print("Error: question_count must be an integer from 1 to 15.")
            continue
        count_value = int(count_input)
        if count_value < 1 or count_value > 15:
            print("Error: question_count must be an integer from 1 to 15.")
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

    assignment = {
        "assignment_id": assignment_id,
        "title": title,
        "question_count": question_count,
        "choices": choices,
        "answer_key": answer_key,
        "standards": {str(i): [] for i in range(1, question_count + 1)},
    }

    written_paths = []
    skipped_paths = []
    for class_record in selected_classes:
        class_id = class_record["class_id"]
        output_path = os.path.join(
            "classes",
            class_id,
            "assignments",
            assignment_id,
            "assignment.json",
        )

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
            print("Roster Management")
            print()
            print("1. Create a class roster")
            print("2. Validate an existing roster")
            print("3. Return to main menu")
            print()

            choice = input("Select an option: ").strip()
            print()

            if choice == "1":
                result = prompt_create_roster()
                print()
                if result != 0:
                    continue

            elif choice == "2":
                roster_path = normalize_path_input(input("Roster CSV path: "))
                if not roster_path:
                    print("Roster file path is required.")
                    print()
                    continue

                # Validate using load_roster and print results
                roster = load_roster(roster_path)
                if roster is None:
                    print()
                    continue
                print("Roster file is valid.")
                print(f"class_id: {roster['class_id']}")
                print(f"students: {len(roster['students'])}")
                if roster['students']:
                    print("First students:")
                    for student in roster['students'][:5]:
                        print(f"  {student['student_id']}: {student['last_name']}, {student['first_name']}")
                print()

            elif choice == "3":
                return 0

            else:
                print(f"Invalid selection: {choice}. Please enter a number from 1 to 3.")
                print()

    except KeyboardInterrupt:
        print("\nExiting roster menu.")
        return 0


def launch_assignment_menu():
    """Assignment management submenu."""
    try:
        while True:
            print("Assignment Management")
            print()
            print("1. Create an assignment for class(es)")
            print("2. Validate an existing assignment")
            print("3. Return to main menu")
            print()

            choice = input("Select an option: ").strip()
            print()

            if choice == "1":
                result = prompt_create_assignment()
                print()
                if result != 0:
                    continue

            elif choice == "2":
                assignment_path = normalize_path_input(input("Assignment JSON path: "))
                if not assignment_path:
                    print("Assignment file path is required.")
                    print()
                    continue

                # Validate using load_assignment and print results
                assignment = load_assignment(assignment_path)
                if assignment is None:
                    print()
                    continue
                print("Assignment file is valid.")
                print(assignment)
                print()

            elif choice == "3":
                return 0

            else:
                print(f"Invalid selection: {choice}. Please enter a number from 1 to 3.")
                print()

    except KeyboardInterrupt:
        print("\nExiting assignment menu.")
        return 0
