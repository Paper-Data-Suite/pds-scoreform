import os
import shutil

def setup_assignment_folder(roster_data, assignment_data, roster_path, assignment_path):
    """Create class/assignment folder structure and copy roster/assignment files.

    Returns a dictionary of created paths on success, or None on failure.
    """
    try:
        class_id = roster_data.get("class_id")
        assignment_id = assignment_data.get("assignment_id")

        if not class_id or not assignment_id:
            print("Error: roster_data or assignment_data missing required identifiers.")
            return None

        class_dir = os.path.join("classes", class_id)
        assignments_dir = os.path.join(class_dir, "assignments")
        assignment_dir = os.path.join(assignments_dir, assignment_id)
        templates_dir = os.path.join(assignment_dir, "templates")
        individual_templates_dir = os.path.join(templates_dir, "individual")
        scans_dir = os.path.join(assignment_dir, "scans")
        debug_dir = os.path.join(assignment_dir, "debug")

        # Create directories
        os.makedirs(individual_templates_dir, exist_ok=True)
        os.makedirs(scans_dir, exist_ok=True)
        os.makedirs(debug_dir, exist_ok=True)

        # Copy roster and assignment files
        roster_copy = os.path.join(class_dir, "roster.csv")
        assignment_copy = os.path.join(assignment_dir, "assignment.json")

        # Ensure parent dirs exist for copies
        os.makedirs(class_dir, exist_ok=True)
        os.makedirs(assignment_dir, exist_ok=True)

        shutil.copy2(roster_path, roster_copy)
        shutil.copy2(assignment_path, assignment_copy)

        return {
            "class_dir": class_dir,
            "assignment_dir": assignment_dir,
            "templates_dir": templates_dir,
            "individual_templates_dir": individual_templates_dir,
            "scans_dir": scans_dir,
            "debug_dir": debug_dir,
            "roster_copy": roster_copy,
            "assignment_copy": assignment_copy,
        }

    except Exception as e:
        print(f"Error setting up assignment folder: {e}")
        return None
