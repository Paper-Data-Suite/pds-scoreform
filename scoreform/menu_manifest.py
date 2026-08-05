"""Teacher menu for explicit immutable Academic Result Manifest operations."""

from __future__ import annotations

from scoreform import workspace
from scoreform.academic_result_manifest_generation import (
    ScoreFormManifestGenerationError,
    generate_academic_result_manifest,
    list_academic_result_manifest_revisions,
    load_academic_result_manifest_revision,
    validate_academic_result_manifest_revision,
)
from scoreform.academic_work_registration import (
    ScoreFormAcademicWorkRegistrationError,
    load_current_scoreform_academic_work_registration,
)
from scoreform.menu_navigation import (
    parse_scoreform_navigation,
    print_scoreform_navigation_options,
)
from scoreform.work_paths import scoreform_work_paths
from scoreform.workflows import (
    discover_class_assignments,
    discover_class_rosters,
    parse_single_selection,
    print_menu_header,
)


def _counts(manifest) -> tuple[int, int]:
    return len(manifest.students), sum(len(item.attempts) for item in manifest.students)


def _summary(stored) -> None:
    students, attempts = _counts(stored.manifest)
    print(f"revision: {stored.revision}")
    print(f"generated_at: {stored.manifest.generated_at.isoformat()}")
    print(f"manifest path: {stored.relative_path}")
    print(f"manifest SHA-256: {stored.sha256}")
    print(f"student count: {students}")
    print(f"attempt count: {attempts}")


def _select_assignment():
    classes = discover_class_rosters()
    if not classes:
        print("No valid classes found.")
        return None
    print("Available classes:")
    for index, record in enumerate(classes, start=1):
        print(f"{index}. {record['class_id']}")
    print_scoreform_navigation_options()
    choice = input("Select class: ")
    if parse_scoreform_navigation(choice) is not None:
        return None
    class_record = parse_single_selection(choice, classes, "class")
    class_id = class_record["class_id"]
    assignments = discover_class_assignments(class_id)
    if not assignments:
        print(f"No managed ScoreForm assignments found for class '{class_id}'.")
        return None
    print("Available managed assignments:")
    for index, record in enumerate(assignments, start=1):
        print(f"{index}. {record['assignment_id']} - {record['assignment']['title']}")
    print_scoreform_navigation_options()
    choice = input("Select assignment: ")
    if parse_scoreform_navigation(choice) is not None:
        return None
    return class_id, parse_single_selection(choice, assignments, "assignment")


def launch_academic_result_manifests_menu() -> int:
    """Run privacy-minimized read/generate operations for one managed assignment."""
    print_menu_header("Academic Result Manifests")
    try:
        selected = _select_assignment()
        if selected is None:
            print("Cancelled: no manifest state was created.")
            return 0
        class_id, assignment_record = selected
        assignment_id = assignment_record["assignment_id"]
        title = assignment_record["assignment"]["title"]
        root = workspace.get_scoreform_workspace_root()
        paths = scoreform_work_paths(root, class_id, assignment_id)
        history = list_academic_result_manifest_revisions(root, paths.work_ref)
        print()
        print(f"Class: {class_id}")
        print(f"Assignment: {assignment_id} - {title}")
        print(f"assignment.json available: {'yes' if paths.assignment_path.is_file() else 'no'}")
        print(f"results.csv available: {'yes' if paths.results_path.is_file() else 'no'}")
        print(
            "Allocated revisions: "
            + (", ".join(str(item.revision) for item in history) if history else "none")
        )
        try:
            registration = load_current_scoreform_academic_work_registration(
                root, class_id, assignment_id
            )
            print(
                "Registration status (informational): "
                + (
                    f"registered revision {registration.registration_revision}"
                    if registration is not None
                    else "not registered"
                )
            )
        except ScoreFormAcademicWorkRegistrationError as error:
            print(f"Registration status (informational): unavailable ({error})")
        print()
        print("1. Generate or exact replay")
        print("2. List revisions")
        print("3. Validate a revision")
        print("4. View revision summary")
        print("5. Return")
        action = input("Select an option: ").strip()
        if action == "1":
            if input("Type GENERATE to confirm: ").strip() != "GENERATE":
                print("Cancelled: no manifest revision was generated.")
                return 0
            result = generate_academic_result_manifest(root, class_id, assignment_id)
            students, attempts = _counts(result.manifest)
            print(f"disposition: {result.disposition.value}")
            print(f"reason: {result.reason.value}")
            print(f"revision: {result.revision}")
            print(f"manifest path: {result.relative_path}")
            print(f"manifest SHA-256: {result.sha256}")
            print(f"student count: {students}")
            print(f"attempt count: {attempts}")
            return 0
        if action == "2":
            if not history:
                print("No academic-result manifest revisions are allocated.")
            for stored in history:
                _summary(stored)
            return 0
        if action in {"3", "4"}:
            value = input("Revision: ").strip()
            if not value.isdecimal() or value == "0" or str(int(value)) != value:
                print("Error: revision must be a canonical positive integer.")
                return 1
            revision = int(value)
            stored = (
                validate_academic_result_manifest_revision(root, paths.work_ref, revision)
                if action == "3"
                else load_academic_result_manifest_revision(root, paths.work_ref, revision)
            )
            if action == "3":
                print(f"Valid academic-result manifest revision: {revision}")
            _summary(stored)
            return 0
        print("Cancelled: no manifest state was changed.")
        return 0
    except (ScoreFormManifestGenerationError, ValueError, TypeError) as error:
        print(f"Error: {error}")
        return 1


__all__ = ["launch_academic_result_manifests_menu"]
