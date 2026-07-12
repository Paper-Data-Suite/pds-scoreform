"""Generate answer-sheet command and menu workflows."""

import os
from dataclasses import dataclass
from pathlib import Path

from scoreform import workspace
from scoreform.assignment import load_assignment
from scoreform.folders import setup_assignment_folder
from scoreform.layouts import get_layout
from scoreform.menu_navigation import (
    parse_scoreform_navigation,
    print_invalid_navigation,
    print_scoreform_navigation_options,
)
from scoreform.paging import page_count_for_question_count
from scoreform.roster import load_roster
from scoreform.templates import (
    generate_class_packet_pdf,
    generate_student_pdf,
    generate_template,
    student_pdf_filename,
)
from scoreform.validation import is_safe_identifier
from scoreform.workflows import (
    clear_screen,
    discover_class_assignments,
    discover_class_rosters,
    parse_single_selection,
    pause_for_user,
    print_menu_header,
)


@dataclass(frozen=True)
class RegenerateSheetsResult:
    """Summary of regenerated print artifacts for one managed assignment."""

    class_id: str
    assignment_id: str
    student_count: int
    individual_count: int
    class_packet_path: str
    templates_dir: str
    pages_per_student: int = 1
    stale_extra_count: int = 0
    stale_extra_examples: tuple[str, ...] = ()


def regenerate_answer_sheets_for_assignment(class_id, assignment_id, workspace_root=None):
    """Regenerate one assignment from its current managed roster and assignment."""
    if not is_safe_identifier(class_id):
        raise ValueError(f"Unsafe class_id: {class_id!r}")
    if not is_safe_identifier(assignment_id):
        raise ValueError(f"Unsafe assignment_id: {assignment_id!r}")

    root = Path(workspace_root or workspace.get_scoreform_workspace_root())
    class_dir = root / "classes" / class_id
    roster_path = class_dir / "roster.csv"
    assignment_dir = class_dir / "assignments" / assignment_id
    assignment_path = assignment_dir / "assignment.json"
    if not roster_path.is_file():
        raise FileNotFoundError(f"Managed roster not found for class '{class_id}': {roster_path}")
    if not assignment_path.is_file():
        raise FileNotFoundError(
            f"Managed assignment '{assignment_id}' not found for class '{class_id}': {assignment_path}"
        )

    roster = load_roster(roster_path)
    if roster is None:
        raise ValueError(f"Managed roster is invalid for class '{class_id}'.")
    assignment = load_assignment(assignment_path)
    if assignment is None:
        raise ValueError(f"Managed assignment '{assignment_id}' is invalid.")
    if roster.get("class_id") != class_id:
        raise ValueError(
            f"Managed roster class_id '{roster.get('class_id')}' does not match '{class_id}'."
        )
    if assignment.get("assignment_id") != assignment_id:
        raise ValueError(
            "Managed assignment identifier does not match its assignment folder."
        )

    templates_dir = assignment_dir / "templates"
    individual_dir = templates_dir / "individual"
    individual_dir.mkdir(parents=True, exist_ok=True)
    expected_names = {student_pdf_filename(student) for student in roster["students"]}
    existing_names = {
        path.name for path in individual_dir.iterdir()
        if path.is_file() and path.suffix.lower() == ".pdf"
    }

    for student in roster["students"]:
        output_path = individual_dir / student_pdf_filename(student)
        if not generate_student_pdf(os.fspath(output_path), assignment, student):
            raise RuntimeError(
                f"Failed to generate student PDF for {student.get('student_id')} "
                f"in assignment '{assignment_id}'."
            )

    packet_path = templates_dir / "class_packet.pdf"
    templates_dir.mkdir(parents=True, exist_ok=True)
    if not generate_class_packet_pdf(os.fspath(packet_path), assignment, roster):
        raise RuntimeError(f"Failed to generate class packet for assignment '{assignment_id}'.")

    stale = sorted(existing_names - expected_names, key=str.lower)
    return RegenerateSheetsResult(
        class_id=class_id,
        assignment_id=assignment_id,
        student_count=len(roster["students"]),
        individual_count=len(roster["students"]),
        class_packet_path=os.fspath(packet_path),
        templates_dir=os.fspath(templates_dir),
        pages_per_student=page_count_for_question_count(
            assignment["question_count"], get_layout(assignment["layout_id"])
        ),
        stale_extra_count=len(stale),
        stale_extra_examples=tuple(stale[:3]),
    )


def regenerate_answer_sheets_for_class(class_id, workspace_root=None):
    """Regenerate every managed assignment for a class, failing fast."""
    if not is_safe_identifier(class_id):
        raise ValueError(f"Unsafe class_id: {class_id!r}")
    root = Path(workspace_root or workspace.get_scoreform_workspace_root())
    assignments_dir = root / "classes" / class_id / "assignments"
    if not (root / "classes" / class_id / "roster.csv").is_file():
        raise FileNotFoundError(f"Managed roster not found for class '{class_id}'.")
    assignment_ids = sorted(
        path.parent.name for path in assignments_dir.glob("*/assignment.json")
        if is_safe_identifier(path.parent.name)
    ) if assignments_dir.is_dir() else []
    if not assignment_ids:
        raise FileNotFoundError(f"No managed assignments found for class '{class_id}'.")
    return tuple(
        regenerate_answer_sheets_for_assignment(class_id, assignment_id, root)
        for assignment_id in assignment_ids
    )


def _print_stale_note(result, *, include_examples=False):
    if not result.stale_extra_count:
        return
    print()
    print(
        f"Note: {result.stale_extra_count} older individual PDFs were not changed. "
        "Review the individual templates folder before printing individual sheets."
    )
    if include_examples and result.stale_extra_examples:
        print("Examples: " + ", ".join(result.stale_extra_examples))


def run_regenerate_sheets(args):
    """Run the non-interactive managed answer-sheet regeneration command."""
    usage = (
        "Usage: scoreform regenerate-sheets --class-id <class_id> "
        "(--assignment-id <assignment_id> | --all-assignments)"
    )
    if not args or args in (["help"], ["--help"], ["-h"]):
        print(usage)
        print("Regenerate print artifacts from the current managed roster and assignment files.")
        return 0
    class_id = None
    assignment_id = None
    all_assignments = False
    index = 0
    while index < len(args):
        arg = args[index]
        if arg in {"--class-id", "--assignment-id"}:
            if index + 1 >= len(args) or args[index + 1].startswith("--"):
                print(f"Error: {arg} requires a value.\n{usage}")
                return 1
            if arg == "--class-id":
                if class_id is not None:
                    print(f"Error: {arg} may be specified only once.\n{usage}")
                    return 1
                class_id = args[index + 1]
            else:
                if assignment_id is not None:
                    print(f"Error: {arg} may be specified only once.\n{usage}")
                    return 1
                assignment_id = args[index + 1]
            index += 2
            continue
        if arg == "--all-assignments":
            if all_assignments:
                print(f"Error: {arg} may be specified only once.\n{usage}")
                return 1
            all_assignments = True
            index += 1
            continue
        print(f"Error: Unknown option: {arg}\n{usage}")
        return 1

    if not class_id:
        print(f"Error: --class-id is required.\n{usage}")
        return 1
    if not is_safe_identifier(class_id):
        print(f"Error: class_id is unsafe: '{class_id}'.")
        return 1
    if (assignment_id is None) == (not all_assignments):
        print(f"Error: Choose exactly one of --assignment-id or --all-assignments.\n{usage}")
        return 1
    if assignment_id is not None and not is_safe_identifier(assignment_id):
        print(f"Error: assignment_id is unsafe: '{assignment_id}'.")
        return 1

    try:
        if assignment_id is not None:
            result = regenerate_answer_sheets_for_assignment(class_id, assignment_id)
            print("Regenerated answer sheets.\n")
            print(f"Class: {class_id}")
            print(f"Assignment: {assignment_id}")
            print(f"Students: {result.student_count}")
            print(f"Pages per student: {result.pages_per_student}")
            print(f"Individual sheets: {result.individual_count}")
            print(f"Class packet: {result.class_packet_path}")
            _print_stale_note(result, include_examples=True)
        else:
            results = regenerate_answer_sheets_for_class(class_id)
            print("Regenerated answer sheets.\n")
            print(f"Class: {class_id}")
            print(f"Assignments updated: {len(results)}")
            print(f"Students in current roster: {results[0].student_count}")
            stale_count = sum(result.stale_extra_count for result in results)
            if stale_count:
                print()
                print(f"Note: {stale_count} older individual PDFs were not changed.")
                print("Review the individual templates folders before printing individual sheets.")
    except (FileNotFoundError, ValueError, RuntimeError) as error:
        print(f"Error: {error}")
        return 1
    return 0


def launch_regenerate_sheets_menu(preselected_class_id=None):
    """Run the compact teacher-facing managed regeneration workflow."""
    clear_screen()
    print_menu_header("Update Generated Answer Sheets")
    if preselected_class_id is None:
        classes = discover_class_rosters()
        if not classes:
            print("No class rosters found.")
            return 1
        print("Select class:")
        for index, record in enumerate(classes, start=1):
            print(f"{index}. {record['class_id']}")
        print_scoreform_navigation_options()
        try:
            selection = input("Select class: ")
            if parse_scoreform_navigation(selection) is not None:
                return 0
            class_id = parse_single_selection(selection, classes, "class")["class_id"]
        except ValueError as error:
            print(f"Error: {error}")
            return 1
    else:
        class_id = preselected_class_id

    assignments = discover_class_assignments(class_id)
    if not assignments:
        print(f"No assignments found for class '{class_id}' yet.")
        return 0
    roster_path = Path(workspace.get_scoreform_workspace_root()) / "classes" / class_id / "roster.csv"
    roster = load_roster(roster_path)
    if roster is None:
        return 1

    clear_screen()
    print_menu_header("Update Generated Answer Sheets")
    print(f"Class: {class_id}")
    print()
    print("1. Update sheets for one assignment")
    print("2. Update sheets for all assignments")
    print("3. Not now")
    mode = input("Select an option: ").strip()
    if mode == "3" or parse_scoreform_navigation(mode) is not None:
        print("Answer sheets were not changed.")
        return 0
    if mode not in {"1", "2"}:
        print(f"Invalid selection: {mode}.")
        return 1

    if mode == "1":
        clear_screen()
        print_menu_header("Update Generated Answer Sheets")
        print(f"Class: {class_id}\n")
        print("Select assignment:")
        for index, record in enumerate(assignments, start=1):
            print(f"{index}. {record['assignment_id']}")
        print_scoreform_navigation_options()
        try:
            selection = input("Select assignment: ")
            if parse_scoreform_navigation(selection) is not None:
                return 0
            assignment_id = parse_single_selection(
                selection, assignments, "assignment"
            )["assignment_id"]
        except ValueError as error:
            print(f"Error: {error}")
            return 1
        clear_screen()
        print_menu_header("Regenerate Answer Sheets?")
        print(f"Class: {class_id}")
        print(f"Assignment: {assignment_id}")
        print(f"Students: {len(roster['students'])}\n")
        if input("Type REGENERATE to continue: ").strip() != "REGENERATE":
            print("Cancelled: regeneration not confirmed.")
            return 0
        try:
            result = regenerate_answer_sheets_for_assignment(class_id, assignment_id)
        except (FileNotFoundError, ValueError, RuntimeError) as error:
            print(f"Error: {error}")
            return 1
        clear_screen()
        print_menu_header("Answer Sheets Updated")
        print(f"Class: {class_id}")
        print(f"Assignment: {assignment_id}")
        print(f"Students: {result.student_count}")
        print(f"Pages per student: {result.pages_per_student}")
        print(f"Class packet: {result.class_packet_path}")
        if result.stale_extra_count:
            print("\nNote: Older individual PDFs remain in the templates folder.")
            print("Review that folder before printing individual sheets.")
        return 0

    clear_screen()
    print_menu_header("Regenerate Answer Sheets for All Assignments?")
    print(f"Class: {class_id}")
    print(f"Assignments: {len(assignments)}")
    print(f"Students: {len(roster['students'])}\n")
    if input("Type REGENERATE to continue: ").strip() != "REGENERATE":
        print("Cancelled: regeneration not confirmed.")
        return 0
    try:
        results = regenerate_answer_sheets_for_class(class_id)
    except (FileNotFoundError, ValueError, RuntimeError) as error:
        print(f"Error: {error}")
        return 1
    clear_screen()
    print_menu_header("Answer Sheets Updated")
    print(f"Class: {class_id}")
    print(f"Assignments updated: {len(results)}")
    print(f"Students: {results[0].student_count}")
    if any(result.stale_extra_count for result in results):
        print("\nNote: Older individual PDFs remain in the templates folders.")
        print("Review those folders before printing individual sheets.")
    return 0


def run_generate(args):
    """Generate blank templates or assignment-specific answer sheets."""
    if not args:
        generate_template()
        return 0

    assignment_file = args[0]
    if "--rosters" not in args[1:]:
        print("Error: Missing --rosters.\nUsage: scoreform generate <assignment_json> --rosters <roster_csv> [more_rosters...]")
        return 1

    rosters_index = args.index("--rosters")
    roster_files = args[rosters_index + 1 :]

    if not roster_files:
        print("Error: --rosters provided but no roster files specified.")
        print("Usage: scoreform generate <assignment_json> --rosters <roster_csv> [more_rosters...]")
        return 1

    assignment = load_assignment(assignment_file)
    if assignment is None:
        return 1

    for roster_path in roster_files:
        roster = load_roster(roster_path)
        if roster is None:
            print(f"Error: Failed to load/validate roster: {roster_path}")
            return 1

        setup_paths = setup_assignment_folder(roster, assignment, roster_path, assignment_file)
        if setup_paths is None:
            print(f"Error: Failed to setup assignment folder for roster: {roster_path}")
            return 1

        print("--- Setup Summary ---")
        print(f"Class: {roster.get('class_id')}")
        print(f"  Class dir: {setup_paths['class_dir']}")
        print(f"  Assignment dir: {setup_paths['assignment_dir']}")
        print(f"  Roster copy: {setup_paths['roster_copy']}")
        print(f"  Assignment copy: {setup_paths['assignment_copy']}")

        individual_dir = setup_paths.get('individual_templates_dir')
        if not individual_dir:
            print("Error: Individual templates directory is missing in setup paths.")
            return 1

        students = roster.get('students', [])
        generated_count = 0
        for student in students:
            out_name = student_pdf_filename(student)
            out_path = os.path.join(individual_dir, out_name)
            ok = generate_student_pdf(out_path, assignment, student)
            if not ok:
                print(f"Error: Failed to generate student PDF for {student.get('student_id')}")
                return 1
            generated_count += 1

        print(f"Generated {generated_count} individual student PDFs in:")
        print(
            "Pages per student: "
            f"{page_count_for_question_count(assignment['question_count'], get_layout(assignment['layout_id']))}"
        )
        print(individual_dir)

        templates_dir = setup_paths.get('templates_dir')
        if not templates_dir:
            print("Error: Templates directory is missing in setup paths.")
            return 1

        packet_path = os.path.join(templates_dir, 'class_packet.pdf')
        ok_packet = generate_class_packet_pdf(packet_path, assignment, roster)
        if not ok_packet:
            print(f"Error: Failed to generate class packet PDF: {packet_path}")
            return 1
        print("Generated class packet PDF:")
        print(packet_path)

    return 0


def launch_generate_menu():
    """Teacher-centered generate submenu for interactive menu use."""
    try:
        while True:
            clear_screen()
            print_menu_header("Generate Answer Sheets")
            print("1. Generate answer sheets for an existing class assignment")
            print("2. Generate a generic blank template")
            print_scoreform_navigation_options()
            print()

            choice = input("Select an option: ").strip()
            print()

            navigation = parse_scoreform_navigation(choice)
            if navigation is not None or choice == "3":
                return 0

            if choice == "1":
                clear_screen()
                print_menu_header("Generate Answer Sheets")
                available_classes = discover_class_rosters()
                if not available_classes:
                    print("No class rosters found. Create a class roster first from the Roster Management menu.")
                    pause_for_user()
                    return 1

                print("Available classes:")
                for index, class_record in enumerate(available_classes, start=1):
                    print(f"{index}. {class_record['class_id']}")
                print_scoreform_navigation_options()
                print()

                try:
                    selection = input("Select class: ")
                    if parse_scoreform_navigation(selection) is not None:
                        continue
                    class_record = parse_single_selection(
                        selection,
                        available_classes,
                        "class",
                    )
                except ValueError as e:
                    print(f"Error: {e}")
                    pause_for_user()
                    return 1

                class_id = class_record["class_id"]
                available_assignments = discover_class_assignments(class_id)
                if not available_assignments:
                    print(f"No assignments found for class '{class_id}'. Create an assignment first from the Assignment Management menu.")
                    pause_for_user()
                    return 1

                clear_screen()
                print_menu_header("Generate Answer Sheets")
                print(f"Class: {class_id}")
                print()
                print("Available assignments:")
                for index, assignment_record in enumerate(available_assignments, start=1):
                    print(f"{index}. {assignment_record['assignment_id']}")
                print_scoreform_navigation_options()
                print()

                try:
                    selection = input("Select assignment: ")
                    if parse_scoreform_navigation(selection) is not None:
                        continue
                    assignment_record = parse_single_selection(
                        selection,
                        available_assignments,
                        "assignment",
                    )
                except ValueError as e:
                    print(f"Error: {e}")
                    pause_for_user()
                    return 1

                assignment_id = assignment_record["assignment_id"]
                clear_screen()
                print_menu_header("Generate Answer Sheets")
                print("Generate answer sheets for:")
                print(f"Class: {class_id}")
                print(f"Assignment: {assignment_id}")
                print()

                response = input("Generate answer sheets now? (Y/n): ").strip().lower()
                if response in ("n", "no"):
                    print("Cancelled: Answer sheet generation not confirmed.")
                    pause_for_user()
                    return 1

                result = run_generate([
                    assignment_record["assignment_path"],
                    "--rosters",
                    class_record["roster_path"],
                ])
                pause_for_user()
                return result

            elif choice == "2":
                clear_screen()
                print_menu_header("Generate a Generic Blank Template")
                result = run_generate([])
                pause_for_user()
                return result

            else:
                print(f"Invalid selection: {choice}.")
                print_invalid_navigation()
                print()
                pause_for_user()

    except KeyboardInterrupt:
        print("\nExiting generate menu.")
        return 0
