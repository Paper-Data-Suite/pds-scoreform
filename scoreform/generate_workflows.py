"""Generate answer-sheet command and menu workflows."""

import os

from scoreform.assignment import load_assignment
from scoreform.folders import setup_assignment_folder
from scoreform.menu_navigation import (
    parse_scoreform_navigation,
    print_invalid_navigation,
    print_scoreform_navigation_options,
)
from scoreform.roster import load_roster
from scoreform.templates import (
    generate_class_packet_pdf,
    generate_student_pdf,
    generate_template,
    student_pdf_filename,
)
from scoreform.workflows import (
    clear_screen,
    discover_class_assignments,
    discover_class_rosters,
    parse_single_selection,
    pause_for_user,
    print_menu_header,
)


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
