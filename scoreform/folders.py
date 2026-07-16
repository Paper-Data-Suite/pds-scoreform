import json
import os

from pds_core.classes import load_class_roster, write_class_roster
from pds_core.rosters import RosterError, create_roster
from pds_core.scan_routes import scans_inbox_dir

from scoreform import workspace
from scoreform.assignment import load_assignment, validate_assignment_data
from scoreform.config import LOCAL_OUTPUTS_DIR
from scoreform.work_paths import (
    initialize_managed_work_layout,
    scoreform_work_paths,
)


def ensure_parent_dir(path):
    """Create the parent directory for a file path when one is present."""
    parent_dir = os.path.dirname(os.fspath(path))
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)


def ensure_local_output_dir(*parts):
    """Ensure and return a path under local_outputs/."""
    path = os.fspath(
        workspace.get_scoreform_workspace_root().joinpath(
            LOCAL_OUTPUTS_DIR,
            *parts,
        )
    )
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
    """Ensure the workspace-level scans_inbox/ directory exists.
    
    Returns the workspace-rooted path on success.
    Creates the directory if it doesn't exist.
    Prints a message when the inbox is first created.
    """
    workspace_root = workspace.get_scoreform_workspace_root()
    inbox_path = os.fspath(scans_inbox_dir(workspace_root))
    if not os.path.exists(inbox_path):
        try:
            os.makedirs(inbox_path, exist_ok=True)
            print(f"Created scan inbox directory: {inbox_path}")
        except Exception as e:
            print(f"Error creating scan inbox directory: {e}")
            return None
    return inbox_path

def _roster_semantic_value(roster):
    return (
        roster.class_id,
        tuple(
            (
                student.student_id,
                student.last_name,
                student.first_name,
                student.period,
                tuple(sorted(student.extra_fields.items())),
            )
            for student in roster.students
        ),
    )


def setup_assignment_folder(
    roster_data,
    assignment_data,
    *,
    workspace_root=None,
):
    """Safely set up one canonical ScoreForm managed-work directory."""

    if not isinstance(roster_data, dict) or not isinstance(assignment_data, dict):
        print("Error: Roster and assignment data must be objects.")
        return None

    class_id = roster_data.get("class_id")
    assignment_id = assignment_data.get("assignment_id")

    try:
        students = roster_data.get("students", [])
        incoming_roster = create_roster(class_id, students)
        normalized_assignment = validate_assignment_data(assignment_data)
        if normalized_assignment is None:
            return None
        if normalized_assignment["assignment_id"] != assignment_id:
            print("Error: assignment_id changed unexpectedly during validation.")
            return None

        root = workspace_root or workspace.get_scoreform_workspace_root()
        paths = scoreform_work_paths(root, class_id, assignment_id)
    except (KeyError, RosterError, TypeError, ValueError) as error:
        print(f"Error: Invalid managed assignment identity or input data: {error}")
        return None

    existing_roster = None
    if paths.roster_path.exists() or paths.roster_path.is_symlink():
        if paths.roster_path.is_symlink() or not paths.roster_path.is_file():
            print(f"Error: Shared class roster path is not a file: {paths.roster_path}")
            return None
        try:
            existing_roster = load_class_roster(root, class_id)
        except RosterError as error:
            print(f"Error: Existing shared class roster is invalid: {error}")
            return None
        if _roster_semantic_value(existing_roster) != _roster_semantic_value(
            incoming_roster
        ):
            print(
                f"Error: The shared roster for class '{class_id}' differs from the "
                "incoming roster. Use the roster-management workflow to review or "
                f"replace it: {paths.roster_path}"
            )
            return None

    existing_assignment = None
    if paths.assignment_path.exists() or paths.assignment_path.is_symlink():
        if paths.assignment_path.is_symlink() or not paths.assignment_path.is_file():
            print(
                "Error: Managed assignment path is not a regular file: "
                f"{paths.assignment_path}"
            )
            return None
        existing_assignment = load_assignment(paths.assignment_path)
        if existing_assignment is None:
            print(
                "Error: Existing managed assignment is invalid and was not "
                f"overwritten: {paths.assignment_path}"
            )
            return None
        if existing_assignment.get("assignment_id") != assignment_id:
            print(
                "Error: Existing managed assignment identifier does not match its "
                f"work directory: {paths.assignment_path}"
            )
            return None
        if existing_assignment != normalized_assignment:
            print(
                f"Error: Assignment '{assignment_id}' already exists with different "
                "contents. Use the assignment-editing workflow or explicitly confirm "
                f"an overwrite there: {paths.assignment_path}"
            )
            return None

    try:
        initialize_managed_work_layout(paths)
        if existing_roster is None:
            write_class_roster(root, incoming_roster, overwrite=False)
        if existing_assignment is None:
            with paths.assignment_path.open("x", encoding="utf-8") as output_file:
                json.dump(
                    normalized_assignment,
                    output_file,
                    indent=2,
                    ensure_ascii=False,
                )
                output_file.write("\n")
    except (OSError, RosterError) as error:
        print(f"Error: Could not set up managed assignment storage: {error}")
        return None

    return {
        "work_ref": paths.work_ref,
        "paths": paths,
        "work_root": os.fspath(paths.work_root),
        "roster_path": os.fspath(paths.roster_path),
        "assignment_path": os.fspath(paths.assignment_path),
        "templates_dir": os.fspath(paths.templates_dir),
        "individual_templates_dir": os.fspath(paths.individual_templates_dir),
        "class_packet_path": os.fspath(paths.class_packet_path),
        "scans_dir": os.fspath(paths.scans_dir),
        "results_path": os.fspath(paths.results_path),
        "debug_dir": os.fspath(paths.debug_dir),
    }
