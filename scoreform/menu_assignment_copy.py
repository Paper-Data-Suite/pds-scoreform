"""Teacher-facing workflow for safe assignment copying."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from pds_core.menu_navigation import NavigationChoice
from pds_core.standards import (
    StandardsLibrary,
    StandardsReadError,
    StandardsValidationError,
)
from pds_core.standards_selection import load_standards_for_selection

from scoreform import workspace
from scoreform.assignment_copying import (
    AssignmentCopyError,
    AssignmentCopyPlan,
    AssignmentCopyResult,
    commit_assignment_copy,
    load_assignment_copy_source,
    plan_assignment_copy,
)
from scoreform.menu_navigation import (
    parse_scoreform_navigation,
    print_scoreform_navigation_options,
)
from scoreform.workflows import (
    clear_screen,
    discover_class_assignments,
    discover_class_rosters,
    parse_class_selection,
    parse_single_selection,
    print_menu_header,
)


def _class_periods(class_record: dict[str, object]) -> tuple[str, ...]:
    roster = cast(dict[str, object], class_record["roster"])
    students = cast(list[dict[str, object]], roster.get("students", []))
    return tuple(
        sorted(
            {
                period
                for student in students
                if isinstance((period := student.get("period")), str) and period
            }
        )
    )


def _class_student_count(class_record: dict[str, object]) -> int:
    roster = cast(dict[str, object], class_record["roster"])
    students = roster.get("students", [])
    return len(students) if isinstance(students, list) else 0


def _format_periods(periods: tuple[str, ...]) -> str:
    return ", ".join(periods) if periods else "(none)"


def _print_class_choices(
    classes: list[dict[str, object]],
    *,
    include_metadata: bool = False,
) -> None:
    for index, class_record in enumerate(classes, start=1):
        class_id = cast(str, class_record["class_id"])
        parts = [
            f"{_class_student_count(class_record)} students",
            f"period(s): {_format_periods(_class_periods(class_record))}",
        ]
        if include_metadata:
            school_year = class_record.get("school_year")
            if isinstance(school_year, str):
                parts.append(f"school year: {school_year}")
        print(f"{index}. {class_id} ({'; '.join(parts)})")


def _load_optional_standards_library(
    root: Path,
) -> tuple[StandardsLibrary | None, str | None]:
    try:
        return load_standards_for_selection(root), None
    except (StandardsReadError, StandardsValidationError, OSError) as error:
        return None, str(error)


def _workspace_relative(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _print_copy_preview(root: Path, plan: AssignmentCopyPlan) -> None:
    source = plan.source
    candidate = plan.candidate
    question_count = cast(int, candidate["question_count"])
    choices = cast(list[str], candidate["choices"])
    answer_key = cast(dict[int, str], candidate["answer_key"])
    standards = cast(dict[str, list[str]], candidate["standards"])

    clear_screen()
    print_menu_header("Review Assignment Copy")
    print("Source")
    print(f"  class: {source.work.class_id}")
    print(f"  assignment_id: {source.work.work_id}")
    print(f"  title: {source.definition.title}")
    print()
    print("New assignment configuration")
    print(f"  assignment_id: {candidate['assignment_id']}")
    print(f"  title: {candidate['title']}")
    print(f"  questions: {question_count}")
    print(f"  choices: {', '.join(choices)}")
    print(f"  layout: {candidate['layout_id']}")
    profile = candidate.get("standards_profile_id")
    print(f"  standards profile: {profile if profile is not None else '(none)'}")
    print()
    print("Answer key")
    for question_number in range(1, question_count + 1):
        print(f"  Q{question_number}: {answer_key[question_number]}")
    print()
    print("Standards alignment")
    for question_number in range(1, question_count + 1):
        values = standards.get(str(question_number), [])
        label = ", ".join(values) if values else "(unaligned)"
        print(f"  Q{question_number}: {label}")

    print()
    print("Targets")
    for index, target in enumerate(plan.targets, start=1):
        roster = target.roster
        print(f"  {index}. {target.work.class_id}/{target.work.work_id}")
        print(f"     students: {roster.student_count}")
        print(f"     periods: {_format_periods(roster.periods)}")
        print(
            "     school year: "
            f"{roster.school_year if roster.school_year is not None else '(not set)'}"
        )
        if roster.metadata_warning is not None:
            print(f"     class metadata warning: {roster.metadata_warning}")
        print(
            "     assignment path: "
            f"{_workspace_relative(root, target.assignment_path)}"
        )

    print()
    print("Not copied")
    print("  students or roster state")
    print("  generated sheets, issuances, pages, or routes")
    print("  scans or scan-review history")
    print("  results or attempts")
    print("  Academic Work Registration")
    print("  manifests or publications")
    print("  debug/export history")
    print()
    print(
        f"Ready to create {len(plan.targets)} fresh assignment "
        f"{'copy' if len(plan.targets) == 1 else 'copies'}."
    )
    print("No target state has been written yet.")


def _print_copy_result(root: Path, result: AssignmentCopyResult) -> None:
    clear_screen()
    print_menu_header("Assignment Copy Result")

    if result.created:
        print("Created")
        for created in result.created:
            print(
                f"  {created.work.class_id}/{created.work.work_id}"
                f" -> {_workspace_relative(root, created.assignment_path)}"
            )
    else:
        print("Created")
        print("  (none)")

    if result.failures:
        print()
        print("Failed")
        for failure in result.failures:
            print(
                f"  {failure.target.work.class_id}/"
                f"{failure.target.work.work_id}: {failure.message}"
            )
            for residue in failure.residue_paths:
                print(
                    "    Inspect residue: "
                    f"{_workspace_relative(root, residue)}"
                )

    if result.not_attempted:
        print()
        print("Not attempted after runtime failure")
        for target in result.not_attempted:
            print(f"  {target.work.class_id}/{target.work.work_id}")

    print()
    if result.complete:
        noun = "copy" if len(result.created) == 1 else "copies"
        print(f"Created {len(result.created)} fresh assignment {noun}.")
        print(
            "No sheets, routes, scans, results, manifests, or publications "
            "were created."
        )
        print("Next: generate answer sheets when you are ready.")
    else:
        print(
            "Copying stopped after an unexpected runtime failure. Earlier "
            "successful targets remain durable."
        )


def _navigation_is_back(value: str) -> bool:
    return parse_scoreform_navigation(value) is NavigationChoice.BACK


def prompt_copy_assignment() -> int:
    """Guide a teacher through one reviewed, create-only assignment copy."""
    try:
        root = Path(workspace.get_scoreform_workspace_root())
    except workspace.WorkspaceRootError as error:
        print(f"Error: {error}")
        return 1

    clear_screen()
    print_menu_header("Copy an Assignment")

    available_classes = discover_class_rosters(workspace_root=root)
    if not available_classes:
        print("No class rosters found.")
        print("Create a class roster first, then return to this option.")
        return 1

    print("Source class")
    _print_class_choices(available_classes)
    print_scoreform_navigation_options()
    print()
    source_class_selection = input("Select source class: ").strip()
    if _navigation_is_back(source_class_selection):
        print("Cancelled: no assignment was copied.")
        return 0
    try:
        source_class = parse_single_selection(
            source_class_selection,
            available_classes,
            "source class",
        )
    except ValueError as error:
        print(f"Error: {error}")
        return 1

    source_class_id = cast(str, source_class["class_id"])
    source_assignments = discover_class_assignments(
        source_class_id,
        workspace_root=root,
    )
    if not source_assignments:
        print(f"No assignments found for class '{source_class_id}'.")
        return 1

    clear_screen()
    print_menu_header("Copy an Assignment")
    print(f"Source class: {source_class_id}")
    print()
    print("Source assignment")
    for index, assignment_record in enumerate(source_assignments, start=1):
        assignment = cast(dict[str, object], assignment_record["assignment"])
        print(
            f"{index}. {assignment_record['assignment_id']} - "
            f"{assignment.get('title', '')}"
        )
    print_scoreform_navigation_options()
    print()

    source_assignment_selection = input("Select source assignment: ").strip()
    if _navigation_is_back(source_assignment_selection):
        print("Cancelled: no assignment was copied.")
        return 0
    try:
        source_assignment_record = parse_single_selection(
            source_assignment_selection,
            source_assignments,
            "source assignment",
        )
    except ValueError as error:
        print(f"Error: {error}")
        return 1

    source_assignment_id = cast(str, source_assignment_record["assignment_id"])
    standards_library, standards_error = _load_optional_standards_library(root)
    try:
        source = load_assignment_copy_source(
            root,
            source_class_id,
            source_assignment_id,
            standards_library=standards_library,
        )
    except AssignmentCopyError as error:
        if (
            standards_error is not None
            and "standards library is required" in str(error)
        ):
            print(
                "Error: This assignment uses standards, but the current PDS Core "
                f"standards library could not be loaded: {standards_error}"
            )
        else:
            print(f"Error: {error}")
        return 1

    clear_screen()
    print_menu_header("Copy an Assignment")
    print(
        f"Source: {source.work.class_id}/{source.work.work_id}"
        f" - {source.definition.title}"
    )
    print()
    print("Target classes")
    _print_class_choices(available_classes, include_metadata=True)
    print_scoreform_navigation_options()
    print()
    target_selection = input("Select target class(es), comma-separated: ").strip()
    if _navigation_is_back(target_selection):
        print("Cancelled: no assignment was copied.")
        return 0
    try:
        selected_targets = parse_class_selection(
            target_selection,
            available_classes,
        )
    except ValueError as error:
        print(f"Error: {error}")
        return 1

    target_class_ids = tuple(
        cast(str, record["class_id"]) for record in selected_targets
    )

    clear_screen()
    print_menu_header("Copy an Assignment")
    print(
        f"Source: {source.work.class_id}/{source.work.work_id}"
        f" - {source.definition.title}"
    )
    print(f"Targets: {', '.join(target_class_ids)}")
    print()
    print(f"Default target assignment_id: {source.work.work_id}")
    target_assignment_id_input = input(
        "Press Enter to keep it, or enter a different assignment_id: "
    ).strip()
    if _navigation_is_back(target_assignment_id_input):
        print("Cancelled: no assignment was copied.")
        return 0
    target_assignment_id = target_assignment_id_input or source.work.work_id

    print()
    print(f"Default title: {source.definition.title}")
    title_input = input(
        "Press Enter to keep it, or enter a different title: "
    ).strip()
    if _navigation_is_back(title_input):
        print("Cancelled: no assignment was copied.")
        return 0
    target_title = title_input or source.definition.title

    try:
        plan = plan_assignment_copy(
            root,
            source,
            target_class_ids=target_class_ids,
            target_assignment_id=target_assignment_id,
            title=target_title,
        )
    except AssignmentCopyError as error:
        print(f"Error: {error}")
        print("No target state was written.")
        return 1

    _print_copy_preview(root, plan)
    print_scoreform_navigation_options()
    print()
    confirmation = input("Type COPY to create these assignments: ").strip()
    if _navigation_is_back(confirmation):
        print("Cancelled: no assignment was copied.")
        return 0
    if confirmation != "COPY":
        print("Cancelled: copy was not confirmed.")
        print("No target state was written.")
        return 0

    try:
        result = commit_assignment_copy(
            root,
            plan,
            standards_library=standards_library,
        )
    except AssignmentCopyError as error:
        print(f"Error: {error}")
        print("No new copy was confirmed as created.")
        return 1

    _print_copy_result(root, result)
    return 0 if result.complete else 1
