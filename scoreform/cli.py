"""Command-line interface for ScoreForm."""

import sys
import os
import cv2
import numpy as np

from scoreform.templates import (
    generate_template,
    student_pdf_filename,
    generate_student_pdf,
    generate_class_packet_pdf,
)
from scoreform.scoring import process_file, decode_qr_from_image, process_file_qr_aware
from scoreform.assignment import load_answer_key, load_assignment
from scoreform.roster import load_roster
from scoreform.folders import setup_assignment_folder
from scoreform.results import export_to_csv, export_routed_results


def run_generate(args):
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


def run_score(args):
    if len(args) < 1:
        print("Usage:")
        print("  scoreform score <input_file>")
        print("  scoreform score <input_file> <output_csv>")
        print("  scoreform score <input_file> <output_csv> <answer_key_json>")
        return 1

    input_file = args[0]
    use_qr_aware = False
    output_file = "results.csv"
    answer_key_file = "answer_key.json"
    explicit_output_csv = False

    if len(args) == 1:
        use_qr_aware = True
    elif len(args) == 2:
        arg2 = args[1]
        if arg2.lower().endswith(".json"):
            answer_key_file = arg2
            use_qr_aware = False
        else:
            output_file = arg2
            explicit_output_csv = True
            use_qr_aware = True
    else:
        output_file = args[1]
        answer_key_file = args[2]
        use_qr_aware = False

    if use_qr_aware:
        print("Using QR-aware scoring mode...")
        results_data = process_file_qr_aware(input_file)
    else:
        print("Using legacy/manual scoring mode...")
        key = load_answer_key(answer_key_file)
        if key is None:
            return 1
        results_data = process_file(input_file, key)

    if not results_data:
        print("Error: No pages were scored successfully.")
        return 1

    if use_qr_aware and not explicit_output_csv:
        export_success = export_routed_results(results_data)
    else:
        export_success = export_to_csv(results_data, output_file)

    if not export_success:
        print("Error: Failed to export results.")
        return 1

    return 0


def run_validate_assignment(args):
    if len(args) != 1:
        print("Usage: scoreform validate-assignment <assignment_json>")
        return 1

    assignment_file = args[0]
    assignment = load_assignment(assignment_file)
    if assignment is None:
        return 1

    print("Assignment file is valid.")
    print(assignment)
    return 0


def run_validate_roster(args):
    if len(args) != 1:
        print("Usage: scoreform validate-roster <roster_csv>")
        return 1

    roster_file = args[0]
    roster = load_roster(roster_file)
    if roster is None:
        return 1

    print("Roster file is valid.")
    print(f"class_id: {roster['class_id']}")
    print(f"students: {len(roster['students'])}")
    if roster["students"]:
        print("First students:")
        for student in roster["students"][:5]:
            print(
                f"  {student['student_id']}: {student['last_name']}, {student['first_name']}"
            )
    return 0


def run_setup_assignment(args):
    if len(args) != 2:
        print("Usage: scoreform setup-assignment <assignment_json> <roster_csv>")
        return 1

    assignment_file = args[0]
    roster_file = args[1]

    assignment = load_assignment(assignment_file)
    if assignment is None:
        return 1

    roster = load_roster(roster_file)
    if roster is None:
        return 1

    setup_paths = setup_assignment_folder(roster, assignment, roster_file, assignment_file)
    if setup_paths is None:
        return 1

    print("Assignment folder setup complete.")
    print(f"Class dir: {setup_paths['class_dir']}")
    print(f"Assignment dir: {setup_paths['assignment_dir']}")
    print(f"Roster copy: {setup_paths['roster_copy']}")
    print(f"Assignment copy: {setup_paths['assignment_copy']}")
    return 0


def run_decode_qr(args):
    if len(args) != 1:
        print("Usage: scoreform decode-qr <input_file>")
        return 1

    input_file = args[0]

    if not os.path.exists(input_file):
        print(f"Error: File {input_file} does not exist.")
        return 1

    ext = os.path.splitext(input_file)[1].lower()
    found_any = False
    bad_found = False

    if ext == ".pdf":
        try:
            from pdf2image import convert_from_path
        except ImportError:
            print("Error: The 'pdf2image' module is not installed.\nPlease run: pip install pdf2image")
            return 1

        try:
            pages = convert_from_path(input_file)
        except Exception as e:
            print(f"Error while converting PDF: {e}")
            return 1

        for page_num, page in enumerate(pages, start=1):
            open_cv_image = cv2.cvtColor(np.array(page), cv2.COLOR_RGB2BGR)
            print(f"Page {page_num} QR:")
            parsed = decode_qr_from_image(open_cv_image)
            if parsed:
                found_any = True
                print(f"  class_id: {parsed.get('class_id')}")
                print(f"  assignment_id: {parsed.get('assignment_id')}")
                print(f"  student_id: {parsed.get('student_id')}")
            else:
                bad_found = True
                print(f"  No valid QR decoded on page {page_num}.")

    elif ext in [".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif"]:
        img = cv2.imread(input_file)
        if img is None:
            print(f"Error: Could not read image {input_file}")
            return 1

        parsed = decode_qr_from_image(img)
        if parsed:
            found_any = True
            print(f"Decoded QR:")
            print(f"  class_id: {parsed.get('class_id')}")
            print(f"  assignment_id: {parsed.get('assignment_id')}")
            print(f"  student_id: {parsed.get('student_id')}")
        else:
            print("No valid QR decoded from image.")
            return 1

    else:
        print(f"Error: Unsupported file extension '{ext}'. Please provide a PDF or an image.")
        return 1

    if not found_any:
        print("Error: No QR code could be decoded from any page or image.")
        return 1

    if bad_found:
        print("Error: At least one page contained an unreadable or malformed QR payload.")
        return 1

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
    import csv
    
    try:
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


def confirm_overwrite(path):
    """Prompt for confirmation to overwrite an existing file.
    
    Args:
        path: File path to check.
    
    Returns:
        True if user confirms overwrite or file does not exist, False otherwise.
    """
    if not os.path.exists(path):
        return True
    
    response = input(f"File '{path}' already exists. Overwrite? (y/yes to confirm): ").strip().lower()
    return response in ['y', 'yes']


def write_assignment_json(path, assignment):
    """Write an assignment JSON file to `path`.

    Creates parent directories if needed. Returns True on success.
    """
    import json

    try:
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


def prompt_create_roster():
    """Interactive prompt to create a new roster.
    
    Returns:
        0 on success, 1 on cancellation or error.
    """
    print("--- Create a New Roster ---")
    print()
    
    output_path = input("Output CSV path: ").strip()
    if not output_path:
        print("Cancelled: No output path provided.")
        return 1
    
    if not confirm_overwrite(output_path):
        print("Cancelled: File overwrite not confirmed.")
        return 1
    
    class_id = input("Class ID: ").strip()
    if not class_id:
        print("Error: class_id is required.")
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
            
            # Once we have a student_id, we need last_name.
            # Re-prompt until we get a non-blank last_name.
            while True:
                last_name = input("  last_name: ").strip()
                if last_name:
                    break
                print("  Error: last_name is required.")
            
            # Once we have last_name, we need first_name.
            # Re-prompt until we get a non-blank first_name.
            while True:
                first_name = input("  first_name: ").strip()
                if first_name:
                    break
                print("  Error: first_name is required.")
            
            # Now we have all required fields for this student.
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


def prompt_create_assignment():
    """Interactive prompt to create a new assignment JSON file.

    Returns 0 on success, 1 on cancellation or error.
    """
    import json

    print("--- Create a New Assignment ---")
    print()

    output_path = input("Output JSON path: ").strip()
    if not output_path:
        print("Cancelled: No output path provided.")
        return 1

    if not confirm_overwrite(output_path):
        print("Cancelled: File overwrite not confirmed.")
        return 1

    assignment_id = input("assignment_id: ").strip()
    if not assignment_id:
        print("Error: assignment_id is required.")
        return 1

    title = input("title: ").strip()
    if not title:
        print("Error: title is required.")
        return 1

    print()
    print("Using question_count: 10")
    print("Using choices: A, B, C, D")
    print()

    choices = ["A", "B", "C", "D"]
    answer_key = {}

    for i in range(1, 11):
        while True:
            ans = input(f"Q{i} answer (A/B/C/D): ").strip().upper()
            if ans in choices:
                answer_key[str(i)] = ans
                break
            print("Error: Answer must be one of A, B, C, or D (case-insensitive). Please try again.")

    assignment = {
        "assignment_id": assignment_id,
        "title": title,
        "question_count": 10,
        "choices": choices,
        "answer_key": answer_key,
    }

    print(f"Writing assignment to: {output_path}")
    if not write_assignment_json(output_path, assignment):
        print("Error: Failed to write assignment JSON.")
        return 1

    print("Validating assignment...")
    loaded = load_assignment(output_path)
    if loaded is None:
        print("Error: Assignment validation failed after save.")
        return 1

    print("Success! Assignment created and validated.")
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
            print("1. Create a new roster")
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
                roster_path = input("Roster CSV path: ").strip()
                if not roster_path:
                    print("Roster file path is required.")
                    print()
                    continue
                
                run_validate_roster([roster_path])
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
            print("1. Create a new assignment")
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
                assignment_path = input("Assignment JSON path: ").strip()
                if not assignment_path:
                    print("Assignment file path is required.")
                    print()
                    continue

                run_validate_assignment([assignment_path])
                print()

            elif choice == "3":
                return 0

            else:
                print(f"Invalid selection: {choice}. Please enter a number from 1 to 3.")
                print()

    except KeyboardInterrupt:
        print("\nExiting assignment menu.")
        return 0


def launch_menu():
    print("ScoreForm")
    print()

    try:
        while True:
            print("1. Generate answer sheets")
            print("2. Score scanned responses")
            print("3. Decode QR from a file")
            print("4. Validate an assignment file")
            print("5. Validate a roster file")
            print("6. Set up assignment folders")
            print("7. Roster management")
            print("8. Assignment management")
            print("9. Exit")

            choice = input("Select an option: ").strip()
            print()

            if choice == "1":
                assignment_path = input("Assignment JSON path (blank for generic template): ").strip()
                if not assignment_path:
                    run_generate([])
                    print()
                    continue

                roster_input = input("Roster CSV path(s), comma-separated: ").strip()
                if not roster_input:
                    print("Assignment-based generation requires at least one roster CSV.")
                    print()
                    continue

                roster_files = [p.strip() for p in roster_input.split(",") if p.strip()]
                if not roster_files:
                    print("Assignment-based generation requires at least one roster CSV.")
                    print()
                    continue

                run_generate([assignment_path, "--rosters"] + roster_files)
                print()

            elif choice == "2":
                input_file = input("Input scan/PDF/image path: ").strip()
                if not input_file:
                    print("Input file path is required.")
                    print()
                    continue

                output_csv = input("Output CSV path (blank for routed QR-aware default): ").strip()
                answer_key = input("Answer key JSON path (blank for QR-aware scoring): ").strip()

                args = [input_file]
                if answer_key:
                    if output_csv:
                        args = [input_file, output_csv, answer_key]
                    else:
                        args = [input_file, "results.csv", answer_key]
                elif output_csv:
                    args = [input_file, output_csv]

                run_score(args)
                print()

            elif choice == "3":
                input_file = input("File path: ").strip()
                if not input_file:
                    print("File path is required.")
                    print()
                    continue

                run_decode_qr([input_file])
                print()

            elif choice == "4":
                assignment_path = input("Assignment JSON path: ").strip()
                if not assignment_path:
                    print("Assignment file path is required.")
                    print()
                    continue

                run_validate_assignment([assignment_path])
                print()

            elif choice == "5":
                roster_path = input("Roster CSV path: ").strip()
                if not roster_path:
                    print("Roster file path is required.")
                    print()
                    continue

                run_validate_roster([roster_path])
                print()

            elif choice == "6":
                assignment_path = input("Assignment JSON path: ").strip()
                roster_path = input("Roster CSV path: ").strip()
                if not assignment_path or not roster_path:
                    print("Both assignment JSON path and roster CSV path are required.")
                    print()
                    continue

                run_setup_assignment([assignment_path, roster_path])
                print()

            elif choice == "7":
                launch_roster_menu()
                print()

            elif choice == "8":
                launch_assignment_menu()
                print()

            elif choice == "9":
                print("Goodbye.")
                return 0

            else:
                print(f"Invalid selection: {choice}. Please enter a number from 1 to 9.")
                print()

    except KeyboardInterrupt:
        print("\nExiting menu.")
        return 0


def main(argv=None, default_to_menu=True):
    """Main CLI entry point.

    Args:
        argv: Command-line arguments. If None, sys.argv[1:] is used.
        default_to_menu: If True and no command is provided, launch the menu.
                         If False, print usage.
    """
    if argv is None:
        argv = sys.argv[1:]

    if not argv:
        if default_to_menu:
            return launch_menu()
        print("Usage:")
        print("  scoreform")
        print("  scoreform menu")
        print("  scoreform generate [assignment_json --rosters roster_csv ...]")
        print("  scoreform score <input_file> [output_csv] [answer_key_json]")
        print("  scoreform decode-qr <input_file>")
        print("  scoreform validate-assignment <assignment_json>")
        print("  scoreform validate-roster <roster_csv>")
        print("  scoreform setup-assignment <assignment_json> <roster_csv>")
        return 1

    cmd = argv[0]
    args = argv[1:]

    if cmd == "menu":
        return launch_menu()
    elif cmd == "generate":
        return run_generate(args)
    elif cmd == "score":
        return run_score(args)
    elif cmd == "validate-assignment":
        return run_validate_assignment(args)
    elif cmd == "validate-roster":
        return run_validate_roster(args)
    elif cmd == "setup-assignment":
        return run_setup_assignment(args)
    elif cmd == "decode-qr":
        return run_decode_qr(args)
    else:
        print(f"Unknown command: {cmd}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main(default_to_menu=True))
