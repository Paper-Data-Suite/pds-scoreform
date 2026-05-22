import sys
import os

from scoreform.templates import (
    generate_template,
    student_pdf_filename,
    generate_student_pdf,
    generate_class_packet_pdf,
)
from scoreform.scoring import process_file
from scoreform.assignment import load_answer_key, load_assignment
from scoreform.roster import load_roster
from scoreform.folders import setup_assignment_folder
from scoreform.results import export_to_csv


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python main.py generate")
        print("  python main.py generate <assignment_json> --rosters <roster_csv> [more_rosters...]")
        print("  python main.py setup-assignment <assignment_json> <roster_csv>")
        print("  python main.py score <input_file> [output_csv] [answer_key_json]")
        print("  python main.py validate-assignment <assignment_json>")
        print("  python main.py validate-roster <roster_csv>")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "generate":
        # No arguments: preserve existing behavior (generate template files)
        if len(sys.argv) == 2:
            generate_template()
        else:
            # Expect: python main.py generate <assignment_json> --rosters <roster_csv> [more_rosters...]
            if len(sys.argv) < 3:
                print("Usage: python main.py generate <assignment_json> --rosters <roster_csv> [more_rosters...]")
                sys.exit(1)

            assignment_file = sys.argv[2]

            # require --rosters flag
            if "--rosters" not in sys.argv[3:]:
                print("Error: Missing --rosters.\nUsage: python main.py generate <assignment_json> --rosters <roster_csv> [more_rosters...]")
                sys.exit(1)

            rosters_index = sys.argv.index("--rosters")
            roster_files = sys.argv[rosters_index + 1 :]

            if not roster_files:
                print("Error: --rosters provided but no roster files specified.")
                print("Usage: python main.py generate <assignment_json> --rosters <roster_csv> [more_rosters...]")
                sys.exit(1)

            # Load and validate assignment
            assignment = load_assignment(assignment_file)
            if assignment is None:
                sys.exit(1)

            # Process each roster file
            for roster_path in roster_files:
                roster = load_roster(roster_path)
                if roster is None:
                    print(f"Error: Failed to load/validate roster: {roster_path}")
                    sys.exit(1)

                setup_paths = setup_assignment_folder(roster, assignment, roster_path, assignment_file)
                if setup_paths is None:
                    print(f"Error: Failed to setup assignment folder for roster: {roster_path}")
                    sys.exit(1)

                # Print readable summary for this class
                print("--- Setup Summary ---")
                print(f"Class: {roster.get('class_id')}")
                print(f"  Class dir: {setup_paths['class_dir']}")
                print(f"  Assignment dir: {setup_paths['assignment_dir']}")
                print(f"  Roster copy: {setup_paths['roster_copy']}")
                print(f"  Assignment copy: {setup_paths['assignment_copy']}")
                
                # Generate individual student PDFs inside templates/individual
                individual_dir = setup_paths.get('individual_templates_dir')
                if not individual_dir:
                    print("Error: Individual templates directory is missing in setup paths.")
                    sys.exit(1)

                students = roster.get('students', [])
                generated_count = 0
                for student in students:
                    out_name = student_pdf_filename(student)
                    out_path = os.path.join(individual_dir, out_name)
                    ok = generate_student_pdf(out_path, assignment, student)
                    if not ok:
                        print(f"Error: Failed to generate student PDF for {student.get('student_id')}")
                        sys.exit(1)
                    generated_count += 1

                print(f"Generated {generated_count} individual student PDFs in:")
                print(individual_dir)

                # Generate class packet PDF in templates/ since all succeeded
                try:
                    templates_dir = setup_paths.get('templates_dir')
                    if templates_dir:
                        packet_path = os.path.join(templates_dir, 'class_packet.pdf')
                        ok_packet = generate_class_packet_pdf(packet_path, assignment, roster)
                        if not ok_packet:
                            print(f"Error: Failed to generate class packet PDF: {packet_path}")
                            sys.exit(1)
                        print("Generated class packet PDF:")
                        print(packet_path)
                    else:
                        print("Error: Templates directory is missing in setup paths.")
                        sys.exit(1)
                except Exception as e:
                    print(f"Error while creating class packet: {e}")
                    sys.exit(1)

    elif cmd == "score":
        if len(sys.argv) < 3:
            print("Please provide the path to the scanned PDF or image.")
            print("Example: python main.py score batch_test.pdf results.csv answer_key.json")
            sys.exit(1)

        input_file = sys.argv[2]
        output_file = "results.csv"
        answer_key_file = "answer_key.json"

        if len(sys.argv) == 4:
            if sys.argv[3].lower().endswith(".json"):
                answer_key_file = sys.argv[3]
            else:
                output_file = sys.argv[3]
        elif len(sys.argv) >= 5:
            output_file = sys.argv[3]
            answer_key_file = sys.argv[4]

        key = load_answer_key(answer_key_file)
        if key is None:
            sys.exit(1)

        # Process the file and get the structured data
        results_data = process_file(input_file, key)

        # Export the collected results to CSV
        if results_data:
            export_to_csv(results_data, output_file)

    elif cmd == "validate-assignment":
        if len(sys.argv) != 3:
            print("Usage: python main.py validate-assignment <assignment_json>")
            sys.exit(1)

        assignment_file = sys.argv[2]
        assignment = load_assignment(assignment_file)
        if assignment is None:
            sys.exit(1)

        print("Assignment file is valid.")
        print(assignment)

    elif cmd == "validate-roster":
        if len(sys.argv) != 3:
            print("Usage: python main.py validate-roster <roster_csv>")
            sys.exit(1)

        roster_file = sys.argv[2]
        roster = load_roster(roster_file)
        if roster is None:
            sys.exit(1)

        print("Roster file is valid.")
        print(f"class_id: {roster['class_id']}")
        print(f"students: {len(roster['students'])}")
        if roster["students"]:
            print("First students:")
            for student in roster["students"][:5]:
                print(
                    f"  {student['student_id']}: {student['last_name']}, {student['first_name']}"
                )

    elif cmd == "setup-assignment":
        if len(sys.argv) != 4:
            print("Usage: python main.py setup-assignment <assignment_json> <roster_csv>")
            sys.exit(1)

        assignment_file = sys.argv[2]
        roster_file = sys.argv[3]

        assignment = load_assignment(assignment_file)
        if assignment is None:
            sys.exit(1)

        roster = load_roster(roster_file)
        if roster is None:
            sys.exit(1)

        setup_paths = setup_assignment_folder(roster, assignment, roster_file, assignment_file)
        if setup_paths is None:
            sys.exit(1)

        print("Assignment folder setup complete.")
        print(f"Class dir: {setup_paths['class_dir']}")
        print(f"Assignment dir: {setup_paths['assignment_dir']}")
        print(f"Roster copy: {setup_paths['roster_copy']}")
        print(f"Assignment copy: {setup_paths['assignment_copy']}")

    else:
        print(f"Unknown command: {cmd}")