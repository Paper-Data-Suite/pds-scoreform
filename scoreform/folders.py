import json
import os

from pds_core.scan_routes import scans_inbox_dir

from scoreform import workspace
from scoreform.config import LOCAL_OUTPUTS_DIR
from scoreform.migration import migration_pending


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

def setup_assignment_folder(roster_data, assignment_data, roster_path, assignment_path):
    """Create class/assignment folder structure and copy roster/assignment files.

    Also ensures the project-level scan inbox directory exists.
    
    If the target assignment folder already exists and contains an assignment.json,
    compares it with the incoming assignment file. If they differ, refuses to proceed
    to prevent accidental data loss or assignment-ID collisions.

    Returns a dictionary of created paths on success, or None on failure.
    """
    migration_pending("Assignment-folder setup", "#139")
