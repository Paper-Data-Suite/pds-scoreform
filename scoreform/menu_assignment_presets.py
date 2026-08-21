"""Teacher-facing assessment setup preset workflows."""

from __future__ import annotations

from collections.abc import Mapping
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
from scoreform.assignment_bulk_ui import prompt_answer_key_entry
from scoreform.assignment_presets import (
    AssignmentPresetApplicationPlan,
    AssignmentPresetApplicationResult,
    AssignmentPresetError,
    AssignmentPresetFromAssignmentPlan,
    AssignmentPresetSnapshot,
    build_assignment_preset,
    commit_assignment_preset_application,
    commit_assignment_preset_from_assignment,
    commit_assignment_preset_mutation,
    discover_assignment_presets,
    plan_assignment_preset_application,
    plan_create_assignment_preset,
    plan_create_assignment_preset_from_assignment,
    plan_delete_assignment_preset,
    plan_update_assignment_preset,
)
from scoreform.config import MAX_ASSIGNMENT_QUESTION_COUNT as MAX_QUESTION_COUNT
from scoreform.layouts import DEFAULT_LAYOUT_ID, get_layout
from scoreform.menu_navigation import (
    parse_scoreform_navigation,
    print_invalid_navigation,
    print_scoreform_navigation_options,
)
from scoreform.workflows import (
    clear_screen,
    discover_class_assignments,
    discover_class_rosters,
    parse_class_selection,
    parse_single_selection,
    pause_for_user,
    print_menu_header,
)


def _navigation_is_back(value: str) -> bool:
    return parse_scoreform_navigation(value) is NavigationChoice.BACK


def _workspace_relative(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _load_optional_standards_library(
    root: Path,
) -> tuple[StandardsLibrary | None, str | None]:
    try:
        return load_standards_for_selection(root), None
    except (StandardsReadError, StandardsValidationError, OSError) as error:
        return None, str(error)


def _print_preset_configuration(preset: dict[str, object]) -> None:
    question_count = cast(int, preset["question_count"])
    choices = cast(list[str], preset["choices"])
    answer_key = cast(dict[str, str], preset["answer_key"])
    standards = cast(dict[str, list[str]], preset["standards"])

    print(f"preset_id: {preset['preset_id']}")
    print(f"label: {preset['label']}")
    print(f"questions: {question_count}")
    print(f"choices: {', '.join(choices)}")
    print(f"layout: {preset['layout_id']}")
    profile = preset.get("standards_profile_id")
    print(f"standards profile: {profile if profile is not None else '(none)'}")
    print("Answer key:")
    for question_number in range(1, question_count + 1):
        print(f"  Q{question_number}: {answer_key[str(question_number)]}")
    print("Standards alignment:")
    for question_number in range(1, question_count + 1):
        values = standards.get(str(question_number), [])
        label = ", ".join(values) if values else "(unaligned)"
        print(f"  Q{question_number}: {label}")


def _print_preset_choices(
    snapshots: list[AssignmentPresetSnapshot] | tuple[AssignmentPresetSnapshot, ...],
) -> None:
    for index, snapshot in enumerate(snapshots, start=1):
        print(
            f"{index}. {snapshot.preset_id} - "
            f"{snapshot.preset.get('label', '(unlabeled)')}"
        )


def _select_preset(
    root: Path,
    *,
    prompt: str = "Select preset: ",
) -> AssignmentPresetSnapshot | None:
    discovery = discover_assignment_presets(root)
    if discovery.issues:
        print("Some preset entries could not be loaded:")
        for issue in discovery.issues:
            print(f"  {_workspace_relative(root, issue.path)}: {issue.message}")
        print()
    if not discovery.presets:
        print("No valid assessment setup presets found.")
        return None

    _print_preset_choices(discovery.presets)
    print_scoreform_navigation_options()
    print()
    selection = input(prompt).strip()
    if _navigation_is_back(selection):
        return None
    try:
        return parse_single_selection(
            selection,
            list(discovery.presets),
            "preset",
        )
    except ValueError as error:
        print(f"Error: {error}")
        return None


def _print_save_from_assignment_preview(
    root: Path,
    plan: AssignmentPresetFromAssignmentPlan,
) -> None:
    candidate = plan.mutation.candidate
    if candidate is None:
        raise ValueError("Preset save plan has no candidate.")

    clear_screen()
    print_menu_header("Review Assessment Setup Preset")
    print("Source assignment")
    print(f"  class: {plan.source.work.class_id}")
    print(f"  assignment_id: {plan.source.work.work_id}")
    print(f"  title: {plan.source.definition.title}")
    print()
    _print_preset_configuration(candidate)
    print()
    print(f"Preset path: {_workspace_relative(root, plan.mutation.path)}")
    print()
    print("Not saved in the preset")
    print("  source class or assignment identity")
    print("  roster or student information")
    print("  generated sheets, pages, issuances, or routes")
    print("  scans, results, attempts, manifests, or publications")
    print("  debug/export history")
    print()
    print("No preset state has been written yet.")


def prompt_create_preset_from_assignment() -> int:
    """Create one independent preset from one exact canonical assignment."""

    try:
        root = Path(workspace.get_scoreform_workspace_root())
    except workspace.WorkspaceRootError as error:
        print(f"Error: {error}")
        return 1

    classes = discover_class_rosters(workspace_root=root)
    if not classes:
        print("No class rosters found.")
        return 1

    clear_screen()
    print_menu_header("Create Preset from Assignment")
    print("Source class")
    for index, class_record in enumerate(classes, start=1):
        print(f"{index}. {class_record['class_id']}")
    print_scoreform_navigation_options()
    print()
    selection = input("Select source class: ").strip()
    if _navigation_is_back(selection):
        print("Cancelled: no preset was saved.")
        return 0
    try:
        class_record = parse_single_selection(selection, classes, "source class")
    except ValueError as error:
        print(f"Error: {error}")
        return 1
    class_id = cast(str, class_record["class_id"])

    assignments = discover_class_assignments(class_id, workspace_root=root)
    if not assignments:
        print(f"No assignments found for class '{class_id}'.")
        return 1

    clear_screen()
    print_menu_header("Create Preset from Assignment")
    print(f"Source class: {class_id}")
    for index, assignment_record in enumerate(assignments, start=1):
        assignment = cast(dict[str, object], assignment_record["assignment"])
        print(
            f"{index}. {assignment_record['assignment_id']} - "
            f"{assignment.get('title', '')}"
        )
    print_scoreform_navigation_options()
    print()
    selection = input("Select source assignment: ").strip()
    if _navigation_is_back(selection):
        print("Cancelled: no preset was saved.")
        return 0
    try:
        assignment_record = parse_single_selection(
            selection,
            assignments,
            "source assignment",
        )
    except ValueError as error:
        print(f"Error: {error}")
        return 1

    assignment_id = cast(str, assignment_record["assignment_id"])
    preset_id = input("Preset ID (B to cancel): ").strip()
    if _navigation_is_back(preset_id):
        print("Cancelled: no preset was saved.")
        return 0
    label = input(
        "Preset label (blank to use the assignment title): "
    ).strip()
    if _navigation_is_back(label):
        print("Cancelled: no preset was saved.")
        return 0

    standards_library, standards_error = _load_optional_standards_library(root)
    try:
        plan = plan_create_assignment_preset_from_assignment(
            root,
            source_class_id=class_id,
            source_assignment_id=assignment_id,
            preset_id=preset_id,
            label=label or None,
            standards_library=standards_library,
        )
    except AssignmentPresetError as error:
        if standards_error and "standards library" in str(error).lower():
            print(
                "Error: This assignment uses standards, but the current Core "
                f"standards library could not be loaded: {standards_error}"
            )
        else:
            print(f"Error: {error}")
        return 1

    _print_save_from_assignment_preview(root, plan)
    print_scoreform_navigation_options()
    print()
    confirmation = input("Type SAVE to save this preset: ").strip()
    if _navigation_is_back(confirmation) or confirmation != "SAVE":
        print("Cancelled: preset save was not confirmed.")
        print("No preset state was written.")
        return 0

    try:
        snapshot = commit_assignment_preset_from_assignment(
            root,
            plan,
            standards_library=standards_library,
        )
    except AssignmentPresetError as error:
        print(f"Error: {error}")
        return 1

    print(f"Saved preset: {snapshot.preset_id}")
    print(f"Path: {_workspace_relative(root, snapshot.path)}")
    return 0


def _prompt_layout_and_question_count() -> tuple[str, int] | None:
    print("Layout")
    print("1. Standard 15-question A-D")
    print("2. Compact 25-question A-D")
    print_scoreform_navigation_options()
    selection = input("Select layout: ").strip()
    if _navigation_is_back(selection):
        return None
    if selection in {"", "1"}:
        layout_id = DEFAULT_LAYOUT_ID
    elif selection == "2":
        layout_id = "compact_25q_abcd_v1"
    else:
        print("Error: Select layout 1 or 2.")
        return None

    selected_layout = get_layout(layout_id)
    while True:
        count_text = input(
            f"Question count (1-{MAX_QUESTION_COUNT}; "
            f"{selected_layout.questions_per_page} per page; B to cancel): "
        ).strip()
        if _navigation_is_back(count_text):
            return None
        if count_text.isdigit():
            question_count = int(count_text)
            if 1 <= question_count <= MAX_QUESTION_COUNT:
                return layout_id, question_count
        print(
            f"Error: question_count must be an integer from 1 to "
            f"{MAX_QUESTION_COUNT}."
        )


def _prompt_answer_key(
    question_count: int,
    choices: list[str],
) -> dict[str, str] | None:
    answer_key: dict[str, str] = {}
    for question_number in range(1, question_count + 1):
        while True:
            value = input(
                f"Q{question_number} answer "
                f"({'/'.join(choices)}; type BACK to cancel): "
            ).strip()
            if value.lower() == "back":
                return None
            if value.lower() in {"m", "main", "q", "quit"}:
                parse_scoreform_navigation(value)
            answer = value.upper()
            if answer in choices:
                answer_key[str(question_number)] = answer
                break
            print(f"Error: Answer must be one of {', '.join(choices)}.")
    return answer_key


def prompt_create_preset_manually() -> int:
    """Create one preset directly without fabricating class-qualified work."""

    try:
        root = Path(workspace.get_scoreform_workspace_root())
    except workspace.WorkspaceRootError as error:
        print(f"Error: {error}")
        return 1

    clear_screen()
    print_menu_header("Create Preset Manually")
    preset_id = input("Preset ID (B to cancel): ").strip()
    if _navigation_is_back(preset_id):
        print("Cancelled: no preset was saved.")
        return 0
    label = input("Preset label (B to cancel): ").strip()
    if _navigation_is_back(label):
        print("Cancelled: no preset was saved.")
        return 0

    layout_and_count = _prompt_layout_and_question_count()
    if layout_and_count is None:
        print("Cancelled: no preset was saved.")
        return 0
    layout_id, question_count = layout_and_count

    choices = ["A", "B", "C", "D"]
    answer_key_value = prompt_answer_key_entry(
        question_count=question_count,
        choices=choices,
    )
    if answer_key_value is None:
        print("Cancelled: no preset was saved.")
        return 0
    answer_key = answer_key_value.as_assignment_mapping()

    from scoreform.assignment_workflows import prompt_standards_alignment

    standards_profile_id, standards = prompt_standards_alignment(
        root,
        question_count,
    )
    standards_library, standards_error = _load_optional_standards_library(root)

    try:
        preset = build_assignment_preset(
            preset_id=preset_id,
            label=label,
            question_count=question_count,
            choices=choices,
            layout_id=layout_id,
            answer_key=cast(
                Mapping[int | str, str],
                answer_key,
            ),
            standards=cast(
                Mapping[int | str, list[str] | tuple[str, ...]],
                standards,
            ),
            standards_profile_id=standards_profile_id,
            standards_library=standards_library,
        )
        plan = plan_create_assignment_preset(
            root,
            preset,
            standards_library=standards_library,
        )
    except AssignmentPresetError as error:
        if standards_error and "standards library" in str(error).lower():
            print(
                "Error: The current Core standards library could not be loaded: "
                f"{standards_error}"
            )
        else:
            print(f"Error: {error}")
        return 1

    clear_screen()
    print_menu_header("Review Assessment Setup Preset")
    _print_preset_configuration(preset)
    print()
    print(f"Preset path: {_workspace_relative(root, plan.path)}")
    print("No class, roster, student, or operational state will be stored.")
    print()
    confirmation = input("Type SAVE to save this preset: ").strip()
    if _navigation_is_back(confirmation) or confirmation != "SAVE":
        print("Cancelled: preset save was not confirmed.")
        return 0

    try:
        snapshot = commit_assignment_preset_mutation(
            root,
            plan,
            standards_library=standards_library,
        )
    except AssignmentPresetError as error:
        print(f"Error: {error}")
        return 1
    if snapshot is None:
        print("Error: preset save did not produce a persisted preset.")
        return 1

    print(f"Saved preset: {snapshot.preset_id}")
    return 0


def prompt_view_presets() -> int:
    """Show one selected preset's complete reusable configuration."""

    try:
        root = Path(workspace.get_scoreform_workspace_root())
    except workspace.WorkspaceRootError as error:
        print(f"Error: {error}")
        return 1

    clear_screen()
    print_menu_header("View Assessment Setup Presets")
    snapshot = _select_preset(root)
    if snapshot is None:
        return 0
    print()
    _print_preset_configuration(snapshot.preset)
    print()
    print(f"Path: {_workspace_relative(root, snapshot.path)}")
    return 0


def _preset_as_editable_assignment(
    snapshot: AssignmentPresetSnapshot,
) -> dict[str, object]:
    preset = snapshot.preset
    answer_key = cast(dict[str, str], preset["answer_key"])
    standards = cast(dict[str, list[str]], preset["standards"])
    editable: dict[str, object] = {
        "assignment_id": "preset_edit",
        "title": preset["label"],
        "question_count": preset["question_count"],
        "choices": list(cast(list[str], preset["choices"])),
        "layout_id": preset["layout_id"],
        "answer_key": dict(answer_key),
        "standards": {
            question_number: list(values)
            for question_number, values in standards.items()
        },
    }
    if preset.get("standards_profile_id") is not None:
        editable["standards_profile_id"] = preset["standards_profile_id"]
    return editable


def _build_preset_from_editable(
    snapshot: AssignmentPresetSnapshot,
    editable: dict[str, object],
    *,
    standards_library: StandardsLibrary | None,
) -> dict[str, object]:
    answer_key = cast(dict[str, str], editable["answer_key"])
    standards = cast(dict[str, list[str]], editable["standards"])
    return build_assignment_preset(
        preset_id=snapshot.preset_id,
        label=cast(str, editable["title"]),
        question_count=cast(int, editable["question_count"]),
        choices=cast(list[str], editable["choices"]),
        layout_id=cast(str, editable["layout_id"]),
        answer_key=cast(
            Mapping[int | str, str],
            answer_key,
        ),
        standards=cast(
            Mapping[int | str, list[str] | tuple[str, ...]],
            standards,
        ),
        standards_profile_id=cast(str | None, editable.get("standards_profile_id")),
        standards_library=standards_library,
    )


def prompt_edit_preset() -> int:
    """Stage and explicitly update one preset without touching prior assignments."""

    try:
        root = Path(workspace.get_scoreform_workspace_root())
    except workspace.WorkspaceRootError as error:
        print(f"Error: {error}")
        return 1

    clear_screen()
    print_menu_header("Edit Assessment Setup Preset")
    snapshot = _select_preset(root)
    if snapshot is None:
        return 0

    from scoreform import assignment_workflows

    standards_library, _standards_error = _load_optional_standards_library(root)
    staged = _preset_as_editable_assignment(snapshot)
    dirty = False

    while True:
        clear_screen()
        print_menu_header("Edit Assessment Setup Preset")
        print(f"Preset: {snapshot.preset_id}")
        print(f"Staged changes: {'yes' if dirty else 'none'}")
        print()
        print("1. Edit label")
        print("2. Edit answer key")
        print("3. Edit standards alignment")
        print("4. View staged preset")
        print("5. Save changes")
        print_scoreform_navigation_options()
        print()

        choice = input("Select an option: ").strip()
        navigation = parse_scoreform_navigation(choice)
        if navigation is NavigationChoice.BACK:
            if dirty:
                confirmation = input(
                    "Type DISCARD to discard staged preset changes: "
                ).strip()
                if confirmation != "DISCARD":
                    print("Cancelled: staged changes were not discarded.")
                    pause_for_user()
                    continue
            print("Cancelled: no preset changes were saved.")
            return 0

        if choice == "1":
            updated, changed = assignment_workflows._prompt_edit_assignment_title(
                staged
            )
            if changed:
                staged = updated
                dirty = True

        elif choice == "2":
            updated, changed = assignment_workflows._prompt_edit_assignment_answer_key(
                staged
            )
            if changed:
                staged = updated
                dirty = True

        elif choice == "3":
            updated, changed = assignment_workflows._prompt_edit_assignment_standards(
                staged,
                root,
            )
            if changed:
                staged = updated
                dirty = True

        elif choice == "4":
            try:
                preview = _build_preset_from_editable(
                    snapshot,
                    staged,
                    standards_library=standards_library,
                )
            except AssignmentPresetError as error:
                print(f"Error: {error}")
            else:
                _print_preset_configuration(preview)
            pause_for_user()

        elif choice == "5":
            if not dirty:
                print("No changes to save.")
                return 0
            try:
                replacement = _build_preset_from_editable(
                    snapshot,
                    staged,
                    standards_library=standards_library,
                )
                plan = plan_update_assignment_preset(
                    root,
                    snapshot.preset_id,
                    replacement,
                    standards_library=standards_library,
                )
            except AssignmentPresetError as error:
                print(f"Error: {error}")
                pause_for_user()
                continue

            clear_screen()
            print_menu_header("Review Preset Update")
            _print_preset_configuration(replacement)
            print()
            print("Assignments previously created from this preset will not change.")
            confirmation = input("Type UPDATE to save these preset changes: ").strip()
            if confirmation != "UPDATE":
                print("Cancelled: preset update was not confirmed.")
                pause_for_user()
                continue

            try:
                saved = commit_assignment_preset_mutation(
                    root,
                    plan,
                    standards_library=standards_library,
                )
            except AssignmentPresetError as error:
                print(f"Error: {error}")
                return 1
            if saved is None:
                print("Error: preset update did not produce a persisted preset.")
                return 1
            print(f"Updated preset: {saved.preset_id}")
            return 0

        else:
            print(f"Invalid selection: {choice}.")
            print_invalid_navigation()
            pause_for_user()


def prompt_delete_preset() -> int:
    """Delete one exact reviewed preset without touching prior assignments."""

    try:
        root = Path(workspace.get_scoreform_workspace_root())
    except workspace.WorkspaceRootError as error:
        print(f"Error: {error}")
        return 1

    clear_screen()
    print_menu_header("Delete Assessment Setup Preset")
    snapshot = _select_preset(root)
    if snapshot is None:
        return 0

    try:
        plan = plan_delete_assignment_preset(root, snapshot.preset_id)
    except AssignmentPresetError as error:
        print(f"Error: {error}")
        return 1

    clear_screen()
    print_menu_header("Delete Assessment Setup Preset")
    print(f"Preset: {snapshot.preset_id} - {snapshot.preset['label']}")
    print(f"Path: {_workspace_relative(root, plan.path)}")
    print()
    print("Existing assignments created from this preset will not be changed.")
    confirmation = input("Type DELETE to delete this preset: ").strip()
    if _navigation_is_back(confirmation) or confirmation != "DELETE":
        print("Cancelled: preset deletion was not confirmed.")
        return 0

    try:
        commit_assignment_preset_mutation(root, plan)
    except AssignmentPresetError as error:
        print(f"Error: {error}")
        return 1

    print(f"Deleted preset: {snapshot.preset_id}")
    return 0


def _print_application_preview(
    root: Path,
    plan: AssignmentPresetApplicationPlan,
) -> None:
    clear_screen()
    print_menu_header("Review Assignment from Preset")
    print(f"Preset: {plan.preset.preset_id} - {plan.preset.preset['label']}")
    print()
    candidate = plan.candidate
    question_count = cast(int, candidate["question_count"])
    answer_key = cast(dict[int, str], candidate["answer_key"])
    standards = cast(dict[str, list[str]], candidate["standards"])
    print("Fresh assignment")
    print(f"  assignment_id: {candidate['assignment_id']}")
    print(f"  title: {candidate['title']}")
    print(f"  questions: {question_count}")
    print(f"  layout: {candidate['layout_id']}")
    print("  answer key:")
    for question_number in range(1, question_count + 1):
        print(f"    Q{question_number}: {answer_key[question_number]}")
    print("  standards:")
    for question_number in range(1, question_count + 1):
        values = standards.get(str(question_number), [])
        print(
            f"    Q{question_number}: "
            f"{', '.join(values) if values else '(unaligned)'}"
        )
    print()
    print("Targets")
    for index, target in enumerate(plan.targets, start=1):
        print(
            f"  {index}. {target.work.class_id}/{target.work.work_id} "
            f"({target.roster.student_count} students)"
        )
        print(
            f"     {_workspace_relative(root, target.assignment_path)}"
        )
    print()
    print("No target assignment state has been written yet.")


def _print_application_result(
    root: Path,
    result: AssignmentPresetApplicationResult,
) -> None:
    clear_screen()
    print_menu_header("Preset Application Result")
    print("Created")
    if result.created:
        for created in result.created:
            print(
                f"  {created.work.class_id}/{created.work.work_id} -> "
                f"{_workspace_relative(root, created.assignment_path)}"
            )
    else:
        print("  (none)")

    if result.failures:
        print()
        print("Failed")
        for failure in result.failures:
            print(
                f"  {failure.target.work.class_id}/"
                f"{failure.target.work.work_id}: {failure.message}"
            )
    if result.not_attempted:
        print()
        print("Not attempted after runtime failure")
        for target in result.not_attempted:
            print(f"  {target.work.class_id}/{target.work.work_id}")

    print()
    if result.complete:
        print(f"Created {len(result.created)} fresh assignment(s).")
        print("No answer sheets or downstream result/publication state were created.")
        print("Next: generate answer sheets when you are ready.")
    else:
        print(
            "Application stopped after a runtime failure. Earlier successful "
            "targets remain durable."
        )


def prompt_apply_preset() -> int:
    """Guide a teacher through reviewed creation of fresh assignments from a preset."""

    try:
        root = Path(workspace.get_scoreform_workspace_root())
    except workspace.WorkspaceRootError as error:
        print(f"Error: {error}")
        return 1

    clear_screen()
    print_menu_header("Create Assignment from Preset")
    snapshot = _select_preset(root)
    if snapshot is None:
        return 0

    classes = discover_class_rosters(workspace_root=root)
    if not classes:
        print("No class rosters found.")
        return 1
    print()
    print("Target classes")
    for index, class_record in enumerate(classes, start=1):
        print(f"{index}. {class_record['class_id']}")
    print_scoreform_navigation_options()
    selection = input("Select target class(es), comma-separated: ").strip()
    if _navigation_is_back(selection):
        print("Cancelled: no assignment was created.")
        return 0
    try:
        selected_classes = parse_class_selection(selection, classes)
    except ValueError as error:
        print(f"Error: {error}")
        return 1
    target_class_ids = tuple(
        cast(str, class_record["class_id"]) for class_record in selected_classes
    )

    assignment_id = input("New assignment ID (B to cancel): ").strip()
    if _navigation_is_back(assignment_id):
        print("Cancelled: no assignment was created.")
        return 0
    title = input("New assignment title (B to cancel): ").strip()
    if _navigation_is_back(title):
        print("Cancelled: no assignment was created.")
        return 0

    standards_library, standards_error = _load_optional_standards_library(root)
    try:
        plan = plan_assignment_preset_application(
            root,
            preset_id=snapshot.preset_id,
            target_class_ids=target_class_ids,
            target_assignment_id=assignment_id,
            title=title,
            standards_library=standards_library,
        )
    except AssignmentPresetError as error:
        if standards_error and "standards library" in str(error).lower():
            print(
                "Error: The current Core standards library could not be loaded: "
                f"{standards_error}"
            )
        else:
            print(f"Error: {error}")
        return 1

    _print_application_preview(root, plan)
    print()
    print("1. Create as shown")
    print("2. Edit staged title/key/standards")
    print("B. Cancel")
    action = input("Select an option: ").strip()
    if _navigation_is_back(action):
        print("Cancelled: no assignment was created.")
        return 0

    if action == "2":
        from scoreform import assignment_workflows

        staged = assignment_workflows._assignment_for_edit(plan.candidate)
        while True:
            clear_screen()
            print_menu_header("Edit Staged Assignment from Preset")
            print("1. Edit title")
            print("2. Edit answer key")
            print("3. Edit standards alignment")
            print("4. Done editing")
            print_scoreform_navigation_options()
            choice = input("Select an option: ").strip()
            if _navigation_is_back(choice):
                print("Cancelled: no assignment was created.")
                return 0
            if choice == "1":
                staged, _changed = assignment_workflows._prompt_edit_assignment_title(
                    staged
                )
            elif choice == "2":
                staged, _changed = (
                    assignment_workflows._prompt_edit_assignment_answer_key(staged)
                )
            elif choice == "3":
                staged, _changed = (
                    assignment_workflows._prompt_edit_assignment_standards(
                        staged,
                        root,
                    )
                )
            elif choice == "4":
                break
            else:
                print(f"Invalid selection: {choice}.")
                pause_for_user()

        try:
            edited_title = cast(str, staged["title"])
            plan = plan_assignment_preset_application(
                root,
                preset_id=snapshot.preset_id,
                target_class_ids=target_class_ids,
                target_assignment_id=assignment_id,
                title=edited_title,
                standards_library=standards_library,
            )
        except AssignmentPresetError as error:
            print(f"Error: {error}")
            return 1

        candidate = dict(plan.candidate)
        candidate["answer_key"] = {
            int(question_number): answer
            for question_number, answer in cast(
                dict[str, str],
                staged["answer_key"],
            ).items()
        }
        candidate["standards"] = {
            str(question_number): list(values)
            for question_number, values in cast(
                dict[str, list[str]],
                staged["standards"],
            ).items()
        }
        if staged.get("standards_profile_id") is None:
            candidate.pop("standards_profile_id", None)
        else:
            candidate["standards_profile_id"] = staged["standards_profile_id"]

        from scoreform.assignment import validate_assignment_data

        normalized = validate_assignment_data(candidate)
        if normalized is None:
            print("Error: staged assignment validation failed.")
            return 1

        import hashlib
        import json
        from dataclasses import replace

        digest = hashlib.sha256(
            json.dumps(
                normalized,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        plan = replace(
            plan,
            candidate=normalized,
            candidate_sha256=digest,
        )
        _print_application_preview(root, plan)

    elif action != "1":
        print("Cancelled: no assignment was created.")
        return 0

    confirmation = input("Type CREATE to create these assignments: ").strip()
    if _navigation_is_back(confirmation) or confirmation != "CREATE":
        print("Cancelled: assignment creation was not confirmed.")
        return 0

    try:
        result = commit_assignment_preset_application(
            root,
            plan,
            standards_library=standards_library,
        )
    except AssignmentPresetError as error:
        print(f"Error: {error}")
        return 1

    _print_application_result(root, result)
    return 0 if result.complete else 1


def launch_assignment_presets_menu() -> int:
    """Temporary v0.11 preset submenu pending #187's menu reorganization."""

    try:
        while True:
            clear_screen()
            print_menu_header("Assessment Setup Presets")
            print("1. Create preset from an assignment")
            print("2. Create preset manually")
            print("3. View presets")
            print("4. Edit preset")
            print("5. Delete preset")
            print("6. Create assignment from preset")
            print_scoreform_navigation_options()
            print()

            choice = input("Select an option: ").strip()
            navigation = parse_scoreform_navigation(choice)
            if navigation is NavigationChoice.BACK:
                return 0

            if choice == "1":
                prompt_create_preset_from_assignment()
                pause_for_user()
            elif choice == "2":
                prompt_create_preset_manually()
                pause_for_user()
            elif choice == "3":
                prompt_view_presets()
                pause_for_user()
            elif choice == "4":
                prompt_edit_preset()
                pause_for_user()
            elif choice == "5":
                prompt_delete_preset()
                pause_for_user()
            elif choice == "6":
                prompt_apply_preset()
                pause_for_user()
            else:
                print(f"Invalid selection: {choice}.")
                print_invalid_navigation()
                pause_for_user()
    except KeyboardInterrupt:
        print("\nExiting assessment setup presets.")
        return 0
