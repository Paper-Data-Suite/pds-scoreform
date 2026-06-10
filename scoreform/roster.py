import csv
import os

from scoreform.validation import validate_identifier


def load_roster(roster_path):
    """Loads and validates a roster CSV file."""
    if not os.path.exists(roster_path):
        print(f"Error: Roster file '{roster_path}' not found.")
        return None

    try:
        with open(roster_path, encoding="utf-8", newline="") as roster_file:
            reader = csv.DictReader(roster_file)
            if reader.fieldnames is None:
                print(f"Error: Roster file '{roster_path}' is empty or missing headers.")
                return None

            required_columns = {"class_id", "student_id", "last_name", "first_name", "period"}
            header_columns = {column.strip() for column in reader.fieldnames if column is not None}
            if not required_columns.issubset(header_columns):
                missing = required_columns - header_columns
                print(
                    f"Error: Roster file '{roster_path}' is missing required columns: {', '.join(sorted(missing))}."
                )
                return None

            students = []
            class_id_value = None
            seen_student_ids = set()
            row_number = 1

            for row in reader:
                row_number += 1
                normalized = {
                    k.strip(): (v.strip() if v is not None else "")
                    for k, v in row.items()
                    if k is not None
                }

                class_id = normalized.get("class_id", "")
                student_id = normalized.get("student_id", "")
                last_name = normalized.get("last_name", "")
                first_name = normalized.get("first_name", "")
                period = normalized.get("period", "")

                if not class_id:
                    print(f"Error: Missing class_id on row {row_number}.")
                    return None
                if not student_id:
                    print(f"Error: Missing student_id on row {row_number}.")
                    return None
                if not last_name:
                    print(f"Error: Missing last_name on row {row_number}.")
                    return None
                if not first_name:
                    print(f"Error: Missing first_name on row {row_number}.")
                    return None
                if not period:
                    print(f"Error: Missing period on row {row_number}.")
                    return None

                if not validate_identifier("class_id", class_id, context=f"roster row {row_number}"):
                    return None
                if not validate_identifier("student_id", student_id, context=f"roster row {row_number}"):
                    return None

                if class_id_value is None:
                    class_id_value = class_id
                elif class_id != class_id_value:
                    print(
                        f"Error: Inconsistent class_id on row {row_number}. "
                        f"Expected '{class_id_value}', got '{class_id}'."
                    )
                    return None

                if student_id in seen_student_ids:
                    print(
                        f"Error: Duplicate student_id '{student_id}' found on row {row_number}."
                    )
                    return None

                seen_student_ids.add(student_id)
                students.append(normalized)

    except Exception as e:
        print(f"Error: Could not read roster file '{roster_path}': {e}")
        return None

    if class_id_value is None:
        print(f"Error: Roster file '{roster_path}' contains no student rows.")
        return None

    return {
        "class_id": class_id_value,
        "roster_path": roster_path,
        "students": students,
    }
