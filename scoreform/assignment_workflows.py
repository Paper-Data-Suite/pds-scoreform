"""Interactive assignment workflow helpers."""

import os

from pds_core.menu_navigation import NavigationChoice
from pds_core.standards import StandardsReadError, StandardsValidationError
from pds_core.standards_selection import (
    list_profiles_for_selection,
    list_standards_for_profile_selection,
    load_standards_for_selection,
    resolve_profile_standard_selection,
)

from scoreform import (
    generate_workflows,
    menu_manual_entry,
    menu_scan_review,
    menu_scoring,
    qr_workflows,
    workspace,
)
from scoreform.assignment import load_assignment, validate_assignment_data
from scoreform.assignment_bulk_mutation import (
    AssignmentBulkMutationError,
    commit_assignment_bulk_mutation,
    load_assignment_bulk_snapshot,
    plan_assignment_staged_replacement,
)
from scoreform.assignment_bulk_ui import (
    assignment_uses_standards,
    print_complete_assignment_preview,
    prompt_answer_key_entry,
    prompt_standards_bulk_entry,
)
from scoreform.config import MAX_ASSIGNMENT_QUESTION_COUNT as MAX_QUESTION_COUNT
from scoreform.layouts import DEFAULT_LAYOUT_ID, get_layout
from scoreform.menu_navigation import (
    parse_scoreform_navigation,
    print_invalid_navigation,
    print_scoreform_navigation_options,
)
from scoreform.results_viewer import (
    ResultsViewError,
    format_assignment_results_table,
    load_assignment_results,
    summarize_assignment_results,
)
from scoreform.standards_workflows import (
    attach_standards_to_questions,
    initialize_empty_standards_alignment,
    parse_question_selection,
    parse_standard_selection,
)
from scoreform.validation import is_safe_identifier, validate_identifier
from scoreform.work_paths import (
    initialize_managed_work_layout,
    scoreform_work_paths,
)
from scoreform.workflows import (
    clear_screen,
    discover_class_assignments,
    discover_class_rosters,
    normalize_path_input,
    parse_class_selection,
    parse_single_selection,
    pause_for_user,
    print_menu_header,
    suggest_assignment_id,
    write_assignment_json,
)


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
    editable = {
        "assignment_id": assignment["assignment_id"],
        "title": assignment["title"],
        "question_count": assignment["question_count"],
        "choices": list(assignment["choices"]),
        "layout_id": assignment["layout_id"],
        "answer_key": _assignment_answer_key_for_edit(assignment),
        "standards": _assignment_standards_for_edit(assignment),
    }
    if "standards_profile_id" in assignment:
        editable["standards_profile_id"] = assignment["standards_profile_id"]
    return editable


def format_assignment_for_display(assignment_record):
    """Return a compact terminal summary for an assignment record."""
    assignment = assignment_record["assignment"]
    question_count = assignment["question_count"]
    answer_key = assignment["answer_key"]
    standards = assignment.get("standards", {})
    layout = get_layout(assignment.get("layout_id"))
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
        f"layout: {layout.display_name}",
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


def _prompt_edit_assignment_answer_key_fine_grained(assignment):
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

                new_answer_text = input(
                    "New answer (type BACK to cancel answer-key editing): "
                ).strip()
                if new_answer_text.lower() == "back":
                    return updated, changed
                new_answer = new_answer_text.upper()
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


def _prompt_assignment_standard_questions(assignment):
    try:
        return parse_question_selection(
            input("Question(s), comma-separated: "),
            assignment["question_count"],
        )
    except ValueError as e:
        print(f"Error: {e}")
        return None


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


def _load_selection_library(workspace_root):
    try:
        return load_standards_for_selection(workspace_root)
    except (StandardsReadError, StandardsValidationError, OSError) as error:
        print(f"Error: Could not load the PDS Core standards library: {error}")
        print("Repair or create standards in PDS Core, then return to ScoreForm.")
        return None


def _load_optional_selection_library(workspace_root):
    """Load current Core standards when available without noisy optional errors."""
    try:
        return load_standards_for_selection(workspace_root)
    except (StandardsReadError, StandardsValidationError, OSError):
        return None


def _prompt_profile(library):
    profiles = list_profiles_for_selection(library)
    if not profiles:
        print("No PDS Core standards profiles found.")
        print("Create or import standards profiles in PDS Core, then return to ScoreForm.")
        return None
    clear_screen()
    print_menu_header("Select Standards Profile")
    print("Available PDS Core standards profiles:")
    for index, profile in enumerate(profiles, start=1):
        print(f"{index}. {profile.label}")
    print_scoreform_navigation_options()
    selection = input("Select profile: ").strip()
    if parse_scoreform_navigation(selection) is not None:
        return None
    try:
        return parse_single_selection(selection, profiles, "standards profile")
    except ValueError as error:
        print(f"Error: {error}")
        return None


def _profile_standards(library, profile_id):
    try:
        standards = list_standards_for_profile_selection(library, profile_id)
    except StandardsValidationError as error:
        print(f"Error: Could not resolve PDS Core standards profile: {error}")
        return None
    if not standards:
        print(f"No active standards found in profile {profile_id}.")
        return None
    return standards


def _run_alignment_loop(assignment, library, available_standards):
    updated = dict(assignment)
    updated["standards"] = _assignment_standards_for_edit(assignment)
    last_action = None
    while True:
        clear_screen()
        print_menu_header("Standards Alignment")
        print(f"Profile: {updated['standards_profile_id']}")
        print(f"Questions: {updated['question_count']}")
        attached = sum(len(values) for values in updated["standards"].values())
        aligned_questions = sum(bool(values) for values in updated["standards"].values())
        standard_word = "standard" if attached == 1 else "standards"
        question_word = "question" if aligned_questions == 1 else "questions"
        print(
            f"Current alignment: {attached} {standard_word} attached across "
            f"{aligned_questions} {question_word}"
        )
        if last_action:
            print(f"Last action: {last_action}")
        print()
        print("1. Add standard(s) to question(s)")
        print("2. View current alignment")
        print("3. View available standards")
        print("4. Clear standards from question(s)")
        print("5. Done")
        print_scoreform_navigation_options()
        choice = input("Select an option: ").strip()
        navigation = parse_scoreform_navigation(choice)
        if choice == "5":
            return updated, False
        if navigation is NavigationChoice.BACK:
            return updated, True
        if choice == "1":
            clear_screen()
            print_menu_header("Add Standards to Questions")
            print(f"Profile: {updated['standards_profile_id']}")
            print()
            print("Available standards:")
            for index, standard in enumerate(available_standards, start=1):
                print(f"{index}. {standard.label}")
            print_scoreform_navigation_options()
            print()
            try:
                standard_selection = input(
                    "Select standard(s) by number, comma-separated: "
                )
                if parse_scoreform_navigation(standard_selection) is NavigationChoice.BACK:
                    continue
                standard_ids = parse_standard_selection(
                    standard_selection,
                    available_standards,
                )
                question_selection = input("Attach to question(s), comma-separated: ")
                if parse_scoreform_navigation(question_selection) is NavigationChoice.BACK:
                    continue
                question_numbers = parse_question_selection(
                    question_selection,
                    updated["question_count"],
                )
                resolve_profile_standard_selection(
                    library,
                    profile_id=updated["standards_profile_id"],
                    selected_standard_ids=standard_ids,
                )
                updated["standards"] = attach_standards_to_questions(
                    updated["standards"],
                    standard_ids=standard_ids,
                    question_numbers=question_numbers,
                    question_count=updated["question_count"],
                )
                standards_text = ", ".join(standard_ids)
                questions_text = ", ".join(f"Q{number}" for number in question_numbers)
                last_action = f"Attached {standards_text} to {questions_text}."
            except (ValueError, StandardsValidationError) as error:
                last_action = f"Error: {error}"
        elif choice == "2":
            clear_screen()
            print_menu_header("Current Standards Alignment")
            print(f"Profile: {updated['standards_profile_id']}")
            print()
            _print_assignment_standards(updated)
            pause_for_user()
        elif choice == "3":
            clear_screen()
            print_menu_header("Available Standards")
            print(f"Profile: {updated['standards_profile_id']}")
            print()
            for index, standard in enumerate(available_standards, start=1):
                print(f"{index}. {standard.label}")
            pause_for_user()
        elif choice == "4":
            clear_screen()
            print_menu_header("Clear Standards from Questions")
            print(f"Profile: {updated['standards_profile_id']}")
            print()
            before = updated
            updated, changed = _prompt_clear_assignment_standards(updated)
            if changed:
                cleared = [
                    f"Q{number}"
                    for number in range(1, updated["question_count"] + 1)
                    if before["standards"].get(str(number))
                    and not updated["standards"].get(str(number))
                ]
                last_action = f"Cleared standards from {', '.join(cleared)}."
            else:
                last_action = "No standards were cleared."
        else:
            print("Invalid selection.")
            print_invalid_navigation()


def _prompt_edit_assignment_standards_fine_grained(assignment, workspace_root):
    original = assignment
    library = _load_selection_library(workspace_root)
    if library is None:
        return assignment, False
    updated = dict(assignment)
    profile_id = updated.get("standards_profile_id")
    if not profile_id:
        profile = _prompt_profile(library)
        if profile is None:
            return assignment, False
        existing_ids = tuple(
            standard_id
            for values in updated["standards"].values()
            for standard_id in values
        )
        try:
            resolve_profile_standard_selection(
                library,
                profile_id=profile.profile_id,
                selected_standard_ids=existing_ids,
            )
        except StandardsValidationError as error:
            print(f"Error: Existing standards do not belong to that profile: {error}")
            return assignment, False
        updated["standards_profile_id"] = profile.profile_id
    available_standards = _profile_standards(library, updated["standards_profile_id"])
    if available_standards is None:
        return assignment, False
    updated, _ = _run_alignment_loop(updated, library, available_standards)
    return updated, updated != original

def _prompt_edit_assignment_answer_key(assignment):
    """Choose bulk or fine-grained answer-key editing for one staged assignment."""
    while True:
        clear_screen()
        print_menu_header("Edit Answer Key")
        print("1. Paste complete key")
        print("2. Import answer-key CSV")
        print("3. Import answer-key JSON")
        print("4. Edit one question at a time")
        print_scoreform_navigation_options()
        choice = input("Select an option: ").strip()
        if parse_scoreform_navigation(choice) is not None:
            return assignment, False
        if choice == "4":
            return _prompt_edit_assignment_answer_key_fine_grained(assignment)
        methods = {"1": "text", "2": "csv", "3": "json"}
        method = methods.get(choice)
        if method is None:
            print(f"Invalid selection: {choice}.")
            print_invalid_navigation()
            continue

        value = prompt_answer_key_entry(
            question_count=assignment["question_count"],
            choices=assignment["choices"],
            forced_method=method,
        )
        if value is None:
            return assignment, False
        updated = dict(assignment)
        updated["answer_key"] = value.as_assignment_mapping()
        return updated, updated["answer_key"] != assignment["answer_key"]


def _prompt_edit_assignment_standards(assignment, workspace_root):
    """Choose complete bulk replacement or the existing fine-grained editor."""
    while True:
        clear_screen()
        print_menu_header("Edit Standards Alignment")
        print("1. Paste complete alignment")
        print("2. Import alignment CSV")
        print("3. Import alignment JSON")
        print("4. Fine-grained standards editor")
        print_scoreform_navigation_options()
        choice = input("Select an option: ").strip()
        if parse_scoreform_navigation(choice) is not None:
            return assignment, False
        if choice == "4":
            return _prompt_edit_assignment_standards_fine_grained(
                assignment,
                workspace_root,
            )
        methods = {"1": "text", "2": "csv", "3": "json"}
        method = methods.get(choice)
        if method is None:
            print(f"Invalid selection: {choice}.")
            print_invalid_navigation()
            continue

        library = _load_selection_library(workspace_root)
        if library is None:
            return assignment, False
        alignment = prompt_standards_bulk_entry(
            question_count=assignment["question_count"],
            standards_library=library,
            current_profile_id=assignment.get("standards_profile_id"),
            forced_method=method,
        )
        if alignment is None:
            return assignment, False

        updated = dict(assignment)
        updated["standards"] = alignment.as_assignment_mapping()
        if alignment.standards_profile_id is None:
            updated.pop("standards_profile_id", None)
        else:
            updated["standards_profile_id"] = alignment.standards_profile_id
        return updated, updated != assignment


def _print_assignment_change_summary(original, candidate):
    print("Staged differences:")
    if original.get("title") != candidate.get("title"):
        print("  title: changed")

    question_count = candidate["question_count"]
    original_answers = original["answer_key"]
    candidate_answers = candidate["answer_key"]
    answer_changes = [
        question_number
        for question_number in range(1, question_count + 1)
        if original_answers.get(question_number, original_answers.get(str(question_number)))
        != candidate_answers.get(question_number, candidate_answers.get(str(question_number)))
    ]
    if answer_changes:
        print(
            "  answer key: changed "
            + ", ".join(f"Q{question_number}" for question_number in answer_changes)
        )

    original_standards = original.get("standards", {})
    candidate_standards = candidate.get("standards", {})
    standards_changes = [
        question_number
        for question_number in range(1, question_count + 1)
        if original_standards.get(
            question_number,
            original_standards.get(str(question_number), []),
        )
        != candidate_standards.get(
            question_number,
            candidate_standards.get(str(question_number), []),
        )
    ]
    if standards_changes:
        print(
            "  standards: changed "
            + ", ".join(f"Q{question_number}" for question_number in standards_changes)
        )
    if original.get("standards_profile_id") != candidate.get("standards_profile_id"):
        print("  standards profile: changed")

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
            "layout_id": assignment["layout_id"],
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
        "layout_id",
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


def prompt_copy_assignment():
    """Compatibility wrapper for the teacher-facing assignment copy workflow."""
    from scoreform.menu_assignment_copy import prompt_copy_assignment as copy_assignment

    return copy_assignment()


def prompt_edit_assignment():
    """Interactive staged assignment editing with guarded atomic replacement."""
    print_menu_header("Edit an Assignment")

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

    class_id = class_record["class_id"]
    available_assignments = discover_class_assignments(class_id)
    if not available_assignments:
        print(f"No assignments found for class '{class_id}'.")
        print("Create an assignment first, then return to this option.")
        return 1

    clear_screen()
    print_menu_header("Edit an Assignment")
    print(f"Class: {class_id}")
    print()
    print("Available assignments:")
    for index, assignment_record in enumerate(available_assignments, start=1):
        title = assignment_record["assignment"].get("title", "")
        print(f"{index}. {assignment_record['assignment_id']} - {title}")
    print_scoreform_navigation_options()
    print()

    try:
        selection = input("Select assignment: ")
        if parse_scoreform_navigation(selection) is not None:
            return 0
        assignment_record = parse_single_selection(
            selection,
            available_assignments,
            "assignment",
        )
    except ValueError as e:
        print(f"Error: {e}")
        return 1

    workspace_root = workspace.get_scoreform_workspace_root()
    assignment_id = assignment_record["assignment_id"]
    standards_library = _load_optional_selection_library(workspace_root)
    try:
        snapshot = load_assignment_bulk_snapshot(
            workspace_root,
            class_id,
            assignment_id,
            standards_library=standards_library,
        )
    except AssignmentBulkMutationError as error:
        print(f"Error: Could not load exact canonical assignment snapshot: {error}")
        return 1

    assignment_path = snapshot.assignment_path
    loaded_assignment = snapshot.assignment
    staged_assignment = _assignment_for_edit(loaded_assignment)
    original_identity = (
        staged_assignment["assignment_id"],
        staged_assignment["question_count"],
        tuple(staged_assignment["choices"]),
        staged_assignment["layout_id"],
    )
    dirty = False

    print()
    print(format_assignment_for_display(
        _assignment_record_for_display(class_id, assignment_path, staged_assignment)
    ))
    print()
    print("assignment_id, question_count, choices, and layout are not editable here.")
    print("Changes are staged until you choose Save changes.")
    print("Historical results are never automatically rescored by this editor.")

    while True:
        clear_screen()
        print_menu_header("Edit Assignment")
        print(f"Class: {class_id}")
        print(f"Assignment: {staged_assignment['assignment_id']}")
        print(f"Staged changes: {'yes' if dirty else 'none'}")
        print()
        print("1. Edit title")
        print("2. Edit answer key")
        print("3. Edit standards alignment")
        print("4. View current assignment summary")
        print("5. Save changes")
        print_scoreform_navigation_options()
        print()

        choice = input("Select an option: ").strip()
        print()

        if parse_scoreform_navigation(choice) is not None:
            choice = "6"

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
            print_complete_assignment_preview(
                staged_assignment,
                class_ids=(class_id,),
            )
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
                staged_assignment["layout_id"],
            ):
                print("Error: immutable assignment fields changed unexpectedly.")
                continue
            if not _validate_staged_assignment(staged_assignment):
                print("Error: staged assignment validation failed.")
                continue

            if assignment_uses_standards(staged_assignment):
                plan_library = _load_selection_library(workspace_root)
                if plan_library is None:
                    continue
            else:
                plan_library = None
            try:
                plan = plan_assignment_staged_replacement(
                    snapshot,
                    staged_assignment,
                    standards_library=plan_library,
                )
            except AssignmentBulkMutationError as error:
                print(f"Error: Could not build guarded assignment plan: {error}")
                continue

            clear_screen()
            print_menu_header("Review Assignment Changes Before Save")
            _print_assignment_change_summary(
                loaded_assignment,
                plan.candidate_assignment,
            )
            print()
            print_complete_assignment_preview(
                plan.candidate_assignment,
                class_ids=(class_id,),
            )
            print()
            print(f"Canonical assignment path: {plan.snapshot.assignment_path}")
            print(f"Reviewed source SHA-256: {plan.snapshot.assignment_sha256}")
            print("No generated sheets, routes, results, registrations, manifests, or publications are changed by this save.")
            print()
            confirmation = input(
                "Type SAVE to atomically replace this assignment, or BACK to cancel: "
            ).strip()
            if confirmation != "SAVE":
                print("Cancelled: save not confirmed.")
                continue

            if assignment_uses_standards(plan.candidate_assignment):
                commit_library = _load_selection_library(workspace_root)
                if commit_library is None:
                    print("Cancelled: current Core standards could not be revalidated.")
                    continue
            else:
                commit_library = None
            try:
                persisted = commit_assignment_bulk_mutation(
                    workspace_root,
                    plan,
                    standards_library=commit_library,
                )
            except AssignmentBulkMutationError as error:
                print(f"Error: Assignment was not replaced: {error}")
                continue

            saved_assignment = persisted.assignment
            print(f"Saved assignment: {persisted.assignment_path}")
            if saved_assignment["title"] != loaded_assignment["title"]:
                try:
                    from scoreform.academic_work_registration import (
                        ScoreFormAcademicWorkRegistrationError,
                        load_current_scoreform_academic_work_registration,
                    )

                    registration = load_current_scoreform_academic_work_registration(
                        workspace_root,
                        class_id,
                        saved_assignment["assignment_id"],
                    )
                    if registration is not None and registration.title != saved_assignment["title"]:
                        print(
                            "Notice: The Academic Work Registration title snapshot is now stale."
                        )
                        print(
                            "Use Assignment Management > Academic Work Registration "
                            "to update it explicitly."
                        )
                except ScoreFormAcademicWorkRegistrationError as error:
                    print(f"Notice: Registration status could not be inspected: {error}")
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
            print(f"Invalid selection: {choice}.")
            print_invalid_navigation()

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

    class_id = class_record["class_id"]
    available_assignments = discover_class_assignments(class_id)
    if not available_assignments:
        print(f"No assignments found for class '{class_id}'.")
        print("Create an assignment first, then return to this option.")
        return 1

    clear_screen()
    print_menu_header("View Assignment Results")
    print(f"Class: {class_id}")
    print()
    print("Available assignments:")
    for index, assignment_record in enumerate(available_assignments, start=1):
        title = assignment_record["assignment"].get("title", "")
        print(f"{index}. {assignment_record['assignment_id']} - {title}")
    print_scoreform_navigation_options()
    print()

    try:
        selection = input("Select assignment: ")
        if parse_scoreform_navigation(selection) is not None:
            return 0
        assignment_record = parse_single_selection(
            selection,
            available_assignments,
            "assignment",
        )
    except ValueError as e:
        print(f"Error: {e}")
        return 1

    assignment_id = assignment_record["assignment_id"]
    results_csv_path = assignment_record["results_path"]

    clear_screen()
    print_menu_header("View Assignment Results")
    print(f"Class: {class_id}")
    print(f"Assignment: {assignment_id}")
    print()
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


def confirm_assignment_overwrite(path, class_id):
    """Prompt for confirmation to overwrite an existing class assignment."""
    if not os.path.exists(path):
        return True

    print(f"Assignment already exists for class '{class_id}':")
    print(path)
    print()
    response = input("Overwrite? (y/yes to confirm): ").strip().lower()
    return response in ['y', 'yes']


def _prompt_standards_alignment_choice(workspace_root, question_count):
    """Return complete creation alignment, or None when the teacher cancels."""
    while True:
        clear_screen()
        print_menu_header("Standards Alignment")
        print("1. Skip standards for now")
        print("2. Select a PDS Core profile and align questions interactively")
        print("3. Paste complete alignment")
        print("4. Import alignment CSV")
        print("5. Import alignment JSON")
        print_scoreform_navigation_options()
        print()

        choice = input("Select an option: ").strip()
        if parse_scoreform_navigation(choice) is not None:
            return None
        if choice == "1":
            return None, initialize_empty_standards_alignment(question_count)
        if choice == "2":
            library = _load_selection_library(workspace_root)
            if library is None:
                continue
            profile = _prompt_profile(library)
            if profile is None:
                continue
            available_standards = _profile_standards(library, profile.profile_id)
            if available_standards is None:
                continue
            draft = {
                "question_count": question_count,
                "standards_profile_id": profile.profile_id,
                "standards": initialize_empty_standards_alignment(question_count),
            }
            aligned, backed = _run_alignment_loop(draft, library, available_standards)
            if backed:
                continue
            return profile.profile_id, aligned["standards"]
        if choice in {"3", "4", "5"}:
            library = _load_selection_library(workspace_root)
            if library is None:
                continue
            methods = {"3": "text", "4": "csv", "5": "json"}
            alignment = prompt_standards_bulk_entry(
                question_count=question_count,
                standards_library=library,
                forced_method=methods[choice],
            )
            if alignment is None:
                continue
            return (
                alignment.standards_profile_id,
                alignment.as_assignment_mapping(),
            )

        print("Invalid selection.")
        print_invalid_navigation()


def prompt_standards_alignment(workspace_root, question_count):
    """Compatibility wrapper preserving the historical two-value return shape."""
    result = _prompt_standards_alignment_choice(workspace_root, question_count)
    if result is None:
        return None, initialize_empty_standards_alignment(question_count)
    return result

def prompt_create_assignment():
    """Interactive prompt to create assignment JSON files for selected classes.

    Returns 0 on success or teacher cancellation, 1 on an operational error.
    No assignment work is created before the final explicit SAVE confirmation.
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
    print_scoreform_navigation_options()
    print()

    selection_text = input("Select class(es), comma-separated: ").strip()
    if parse_scoreform_navigation(selection_text) is not None:
        print("Cancelled: no assignment state was written.")
        return 0
    try:
        selected_classes = parse_class_selection(selection_text, available_classes)
    except ValueError as e:
        print(f"Error: {e}")
        return 1

    clear_screen()
    print_menu_header("Assignment Identity")
    print(f"Classes: {', '.join(record['class_id'] for record in selected_classes)}")
    print()
    title = input("Assignment title (type BACK to cancel): ").strip()
    if title.lower() == "back":
        print("Cancelled: no assignment state was written.")
        return 0
    if not title:
        print("Error: title is required.")
        return 1

    suggested_assignment_id = suggest_assignment_id(title)
    assignment_id = ""
    if is_safe_identifier(suggested_assignment_id):
        print(f"Suggested assignment_id: {suggested_assignment_id}")
        assignment_id = input(
            "Press Enter to accept, type a different assignment_id, "
            "or BACK to cancel: "
        ).strip()
        if assignment_id.lower() == "back":
            print("Cancelled: no assignment state was written.")
            return 0
        if not assignment_id:
            assignment_id = suggested_assignment_id
    else:
        print("Could not create a safe assignment_id suggestion from that title.")
        assignment_id = input(
            "Enter a valid assignment_id (or BACK to cancel): "
        ).strip()
        if assignment_id.lower() == "back":
            print("Cancelled: no assignment state was written.")
            return 0

    if not assignment_id:
        print("Error: assignment_id is required.")
        return 1
    if not validate_identifier("assignment_id", assignment_id, context="assignment"):
        return 1

    clear_screen()
    print_menu_header("Assignment Questions")
    print(f"Assignment: {assignment_id}")
    print()

    choices = ["A", "B", "C", "D"]
    layout_id = DEFAULT_LAYOUT_ID
    print("Layout:")
    print("1. Standard 15-question A-D")
    print("2. Compact 25-question A-D")
    print_scoreform_navigation_options()
    while True:
        layout_selection = input("Select layout: ").strip()
        if parse_scoreform_navigation(layout_selection) is not None:
            print("Cancelled: no assignment state was written.")
            return 0
        if layout_selection in {"", "1"}:
            break
        if layout_selection == "2":
            layout_id = "compact_25q_abcd_v1"
            break
        print("Error: Select layout 1 or 2.")
    print()

    selected_layout = get_layout(layout_id)
    question_count = None
    while question_count is None:
        count_prompt = (
            f"Question count (1-{MAX_QUESTION_COUNT}; "
            f"{selected_layout.questions_per_page} per page; B to cancel): "
        )
        count_input = input(count_prompt).strip()
        if parse_scoreform_navigation(count_input) is not None:
            print("Cancelled: no assignment state was written.")
            return 0
        if not count_input.isdigit():
            print(f"Error: question_count must be an integer from 1 to {MAX_QUESTION_COUNT}.")
            continue
        count_value = int(count_input)
        if count_value < 1 or count_value > MAX_QUESTION_COUNT:
            print(f"Error: question_count must be an integer from 1 to {MAX_QUESTION_COUNT}.")
            continue
        question_count = count_value

    clear_screen()
    print_menu_header("Answer Key")
    print(f"Assignment: {assignment_id}")
    print(f"Using question_count: {question_count}")
    print("Using choices: A, B, C, D")
    print()
    answer_key_value = prompt_answer_key_entry(
        question_count=question_count,
        choices=choices,
    )
    if answer_key_value is None:
        print("Cancelled: no assignment state was written.")
        return 0

    workspace_root = workspace.get_scoreform_workspace_root()
    standards_choice = _prompt_standards_alignment_choice(
        workspace_root,
        question_count,
    )
    if standards_choice is None:
        print("Cancelled: no assignment state was written.")
        return 0
    standards_profile_id, standards_by_question = standards_choice

    assignment = {
        "assignment_id": assignment_id,
        "title": title,
        "question_count": question_count,
        "choices": choices,
        "layout_id": layout_id,
        "answer_key": answer_key_value.as_assignment_mapping(),
        "standards": standards_by_question,
    }
    if standards_profile_id is not None:
        assignment["standards_profile_id"] = standards_profile_id
    normalized_assignment = validate_assignment_data(assignment)
    if normalized_assignment is None:
        print("Error: Assignment validation failed before saving.")
        return 1

    clear_screen()
    print_menu_header("Review Assignment Before Save")
    print_complete_assignment_preview(
        normalized_assignment,
        class_ids=tuple(record["class_id"] for record in selected_classes),
    )
    print()
    print("No assignment state has been written yet.")
    print("Generated sheets, routes, results, registrations, manifests, and publications are not changed here.")
    print_scoreform_navigation_options()
    print()
    confirmation = input(
        "Type SAVE to create/update the selected assignment file(s), or BACK to cancel: "
    ).strip()
    if confirmation != "SAVE":
        print("Cancelled: final SAVE was not confirmed.")
        print("No assignment state was written.")
        return 0

    clear_screen()
    print_menu_header("Save Assignment")
    print(f"Assignment: {assignment_id}")
    print(f"Classes: {', '.join(record['class_id'] for record in selected_classes)}")
    print()
    written_paths = []
    skipped_paths = []
    for class_record in selected_classes:
        class_id = class_record["class_id"]
        try:
            paths = scoreform_work_paths(workspace_root, class_id, assignment_id)
        except (TypeError, ValueError) as error:
            print(f"Error: Invalid managed-work identity for class '{class_id}': {error}")
            skipped_paths.append(f"{class_id}/{assignment_id}")
            continue
        output_path = os.fspath(paths.assignment_path)

        existing_snapshot = None
        if paths.assignment_path.is_symlink():
            print(f"Error: Existing assignment path is a symbolic link: {output_path}")
            skipped_paths.append(output_path)
            continue
        if paths.assignment_path.exists():
            existing_library = _load_optional_selection_library(workspace_root)
            try:
                existing_snapshot = load_assignment_bulk_snapshot(
                    workspace_root,
                    class_id,
                    assignment_id,
                    standards_library=existing_library,
                )
            except AssignmentBulkMutationError as error:
                print(f"Error: Existing assignment is not safely editable: {error}")
                skipped_paths.append(output_path)
                continue
            existing_assignment = existing_snapshot.assignment
            immutable_fields = ("assignment_id", "question_count", "choices", "layout_id")
            if any(
                existing_assignment.get(field) != normalized_assignment.get(field)
                for field in immutable_fields
            ):
                print(
                    "Error: Existing assignment has different immutable identity "
                    f"fields and was not overwritten: {output_path}"
                )
                skipped_paths.append(output_path)
                continue

        if not confirm_assignment_overwrite(output_path, class_id):
            print(f"Skipped: {output_path}")
            skipped_paths.append(output_path)
            continue

        if existing_snapshot is not None:
            if assignment_uses_standards(normalized_assignment) or assignment_uses_standards(
                existing_snapshot.assignment
            ):
                replacement_library = _load_selection_library(workspace_root)
                if replacement_library is None:
                    skipped_paths.append(output_path)
                    continue
            else:
                replacement_library = None
            try:
                replacement_plan = plan_assignment_staged_replacement(
                    existing_snapshot,
                    normalized_assignment,
                    standards_library=replacement_library,
                )
                persisted = commit_assignment_bulk_mutation(
                    workspace_root,
                    replacement_plan,
                    standards_library=replacement_library,
                )
            except AssignmentBulkMutationError as error:
                print(f"Error: Existing assignment was not replaced safely: {error}")
                skipped_paths.append(output_path)
                continue
            print(f"Atomically replaced assignment: {persisted.assignment_path}")
            written_paths.append(output_path)
            continue

        try:
            initialize_managed_work_layout(paths)
        except OSError as error:
            print(
                f"Error: Could not initialize assignment storage for class "
                f"'{class_id}': {error}"
            )
            skipped_paths.append(output_path)
            continue

        print(f"Writing assignment to: {output_path}")
        if not write_assignment_json(output_path, normalized_assignment):
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
            print("8. Enter Plain-Paper Results")
            print("9. Resolve scan review items")
            print("10. Academic Work Registration")
            print("11. Academic Result Manifests")
            print("12. Academic Result Publications")
            print("13. Copy an assignment")
            print("14. Assessment setup presets")
            print_scoreform_navigation_options()
            print()

            choice = input("Select an option: ").strip()
            print()

            if parse_scoreform_navigation(choice) is not None:
                return 0

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
                generate_workflows.launch_generate_menu()

            elif choice == "5":
                input_file = menu_scoring.prompt_scoring_input_file()
                if input_file:
                    menu_scoring.prompt_scoring_mode(input_file)

            elif choice == "6":
                clear_screen()
                launch_view_assignment_results_menu()
                print()
                pause_for_user()

            elif choice == "7":
                clear_screen()
                print_menu_header("Decode QR from a File")
                input_file = normalize_path_input(input("File path: "))
                if not input_file:
                    print("File path is required.")
                    print()
                    pause_for_user()
                    continue

                qr_workflows.run_decode_qr([input_file])
                print()
                pause_for_user()

            elif choice == "8":
                menu_manual_entry.launch_manual_entry_menu()

            elif choice == "9":
                menu_scan_review.launch_scan_review_menu()

            elif choice == "10":
                from scoreform.menu_academic_work import (
                    launch_academic_work_registration_menu,
                )

                launch_academic_work_registration_menu()

            elif choice == "11":
                from scoreform.menu_manifest import (
                    launch_academic_result_manifests_menu,
                )

                launch_academic_result_manifests_menu()

            elif choice == "12":
                from scoreform.menu_publication import (
                    launch_academic_result_publications_menu,
                )

                launch_academic_result_publications_menu()

            elif choice == "13":
                clear_screen()
                prompt_copy_assignment()
                print()
                pause_for_user()

            elif choice == "14":
                from scoreform.menu_assignment_presets import (
                    launch_assignment_presets_menu,
                )

                launch_assignment_presets_menu()

            else:
                print(f"Invalid selection: {choice}.")
                print_invalid_navigation()
                print()
                pause_for_user()

    except KeyboardInterrupt:
        print("\nExiting assignment menu.")
        return 0
