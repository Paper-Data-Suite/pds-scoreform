import os
import shutil
import json

from pds_core.routes import (
    assignment_dir as core_assignment_dir,
    class_dir as core_class_dir,
    class_roster_path as core_class_roster_path,
)
from pds_core.scan_routes import scans_inbox_dir

from scoreform.config import LOCAL_OUTPUTS_DIR
from scoreform.validation import validate_identifier


def ensure_parent_dir(path):
    """Create the parent directory for a file path when one is present."""
    parent_dir = os.path.dirname(os.fspath(path))
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)


def ensure_local_output_dir(*parts):
    """Ensure and return a path under local_outputs/."""
    path = os.path.join(LOCAL_OUTPUTS_DIR, *parts)
    os.makedirs(path, exist_ok=True)
    return path


def load_json_for_comparison(path):
    """Load a JSON file for semantic comparison.
    
    Returns the parsed JSON object, or None if the file cannot be read.
    """
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading JSON from {path}: {e}")
        return None


def assignments_match(existing_assignment_path, incoming_assignment_path):
    """Compare two assignment JSON files for semantic equivalence.
    
    Loads both files and compares the parsed objects, ignoring formatting
    and key order differences.
    
    Returns True if they are semantically equivalent, False if they differ
    or if either file cannot be read.
    """
    existing = load_json_for_comparison(existing_assignment_path)
    if existing is None:
        return False
    
    incoming = load_json_for_comparison(incoming_assignment_path)
    if incoming is None:
        return False
    
    return existing == incoming


def ensure_scan_inbox():
    """Ensure the project-level scans_inbox/ directory exists.
    
    Returns the path string "scans_inbox" on success.
    Creates the directory if it doesn't exist.
    Prints a message when the inbox is first created.
    """
    inbox_path = os.fspath(scans_inbox_dir("."))
    if not os.path.exists(inbox_path):
        try:
            os.makedirs(inbox_path, exist_ok=True)
            print(f"Created scan inbox directory: {inbox_path}")
        except Exception as e:
            print(f"Error creating scan inbox directory: {e}")
            return None
    return inbox_path

def setup_assignment_folder(roster_data, assignment_data, roster_path, assignment_path):
    """Create class/assignment folder structure and copy roster/assignment files.

    Also ensures the project-level scan inbox directory exists.
    
    If the target assignment folder already exists and contains an assignment.json,
    compares it with the incoming assignment file. If they differ, refuses to proceed
    to prevent accidental data loss or assignment-ID collisions.

    Returns a dictionary of created paths on success, or None on failure.
    """
    try:
        class_id = roster_data.get("class_id")
        assignment_id = assignment_data.get("assignment_id")

        if not class_id or not assignment_id:
            print("Error: roster_data or assignment_data missing required identifiers.")
            return None
        if not validate_identifier("class_id", class_id, context="folder setup"):
            return None
        if not validate_identifier("assignment_id", assignment_id, context="folder setup"):
            return None

        # Ensure scan inbox exists only after path-bearing identifiers are safe.
        scan_inbox = ensure_scan_inbox()
        if scan_inbox is None:
            return None

        class_dir = os.fspath(core_class_dir(".", class_id))
        assignment_dir = os.fspath(core_assignment_dir(".", class_id, assignment_id))
        templates_dir = os.path.join(assignment_dir, "templates")
        individual_templates_dir = os.path.join(templates_dir, "individual")
        scans_dir = os.path.join(assignment_dir, "scans")
        debug_dir = os.path.join(assignment_dir, "debug")

        # Compute paths for copies before creating directories
        roster_copy = os.fspath(core_class_roster_path(".", class_id))
        assignment_copy = os.path.join(assignment_dir, "assignment.json")

        # Check for existing assignment.json and collision protection
        if os.path.exists(assignment_copy):
            if not assignments_match(assignment_copy, assignment_path):
                print(f"Error: Assignment folder already exists for class '{class_id}' and assignment '{assignment_id}', but the existing assignment.json differs from the incoming assignment file.")
                print("Refusing to overwrite to prevent assignment/results mismatch.")
                print("Use a different assignment_id or remove/archive the existing assignment folder.")
                return None
            # If they match, continue normally

        # Create directories
        os.makedirs(individual_templates_dir, exist_ok=True)
        os.makedirs(scans_dir, exist_ok=True)
        os.makedirs(debug_dir, exist_ok=True)

        # Ensure parent dirs exist for copies
        os.makedirs(class_dir, exist_ok=True)
        os.makedirs(assignment_dir, exist_ok=True)

        if os.path.abspath(roster_path) != os.path.abspath(roster_copy):
            shutil.copy2(roster_path, roster_copy)
        if os.path.abspath(assignment_path) != os.path.abspath(assignment_copy):
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
            "scan_inbox": scan_inbox,
        }

    except Exception as e:
        print(f"Error setting up assignment folder: {e}")
        return None
