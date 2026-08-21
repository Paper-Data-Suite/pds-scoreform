"""Teacher-facing multi-class generation planning over exact application services."""

from __future__ import annotations

import os
from pathlib import Path

from scoreform import workspace
from scoreform.menu_navigation import (
    parse_scoreform_navigation,
    print_invalid_navigation,
    print_scoreform_navigation_options,
)
from scoreform.multi_class_generation import (
    GenerationTargetOutcome,
    GenerationTargetPlan,
    GenerationTargetRef,
    MultiClassGenerationPlan,
    MultiClassGenerationPlanNotReadyError,
    MultiClassGenerationResult,
    MultiClassGenerationStalePlanError,
    execute_multi_class_generation,
    plan_multi_class_generation,
)
from scoreform.workflows import (
    clear_screen,
    discover_class_assignments,
    discover_class_rosters,
    parse_single_selection,
    pause_for_user,
    print_menu_header,
)


def _display_path(root: Path, path: Path | None) -> str:
    if path is None:
        return "Unavailable"
    try:
        return os.fspath(path.relative_to(root))
    except ValueError:
        return os.fspath(path)


def _value(value: object | None) -> str:
    return "Unavailable" if value is None else str(value)


def _target_preview_lines(
    plan: MultiClassGenerationPlan,
    target: GenerationTargetPlan,
    *,
    index: int,
) -> tuple[str, ...]:
    status = "READY" if target.ready else "BLOCKED"
    paths = target.work_paths
    packet = paths.class_packet_path if paths is not None else None
    individuals = paths.individual_templates_dir if paths is not None else None
    lines = [
        f"Target {index} — {status}",
        f"Class: {target.target.class_id}",
        f"Assignment: {target.target.assignment_id}",
        f"Title: {_value(target.title)}",
        f"Layout: {_value(target.layout_id)}",
        f"Questions: {_value(target.question_count)}",
        f"Students: {_value(target.student_count)}",
        f"Pages per student: {_value(target.pages_per_student)}",
        f"Individual PDFs: {_value(target.individual_pdf_count)}",
        f"Individual physical pages: {_value(target.individual_physical_page_count)}",
        f"Class-packet PDFs: {_value(target.class_packet_pdf_count)}",
        f"Class-packet physical pages: {_value(target.class_packet_physical_page_count)}",
        f"Total PDF artifacts: {_value(target.total_pdf_artifact_count)}",
        f"Total physical-page copies: {_value(target.total_physical_page_count)}",
        f"Expected PDS2 routes: {_value(target.expected_route_count)}",
        f"Generation state: {_value(target.generation_state)}",
        f"Class packet: {_display_path(plan.workspace_root, packet)}",
        f"Individual folder: {_display_path(plan.workspace_root, individuals)}",
    ]
    if target.diagnostics:
        lines.append("Blocking diagnostics:")
        lines.extend(
            f"- [{diagnostic.code}] {diagnostic.message}"
            for diagnostic in target.diagnostics
        )
    return tuple(lines)


def format_multi_class_generation_plan(plan: MultiClassGenerationPlan) -> str:
    """Return the complete privacy-minimal teacher preview for one batch plan."""
    sections = [
        "Multi-Class Generation Plan",
        f"Targets selected: {len(plan.targets)}",
        f"Ready targets: {len(plan.ready_targets)}",
        f"Blocked targets: {len(plan.blocked_targets)}",
    ]
    for index, target in enumerate(plan.targets, start=1):
        sections.extend(("", *_target_preview_lines(plan, target, index=index)))
    if plan.blocked_targets:
        sections.extend(
            (
                "",
                "Generation cannot start while any selected target is blocked.",
                "Remove the blocked target or fix its current managed state, then review again.",
            )
        )
    else:
        sections.extend(
            (
                "",
                "Planning is read-only. No artifact, issuance, page, or route identity has been allocated.",
            )
        )
    return "\n".join(sections)


def _outcome_label(outcome: GenerationTargetOutcome) -> str:
    return {
        "clean_success": "CLEAN SUCCESS",
        "partial": "PARTIAL — DURABLE OUTPUT EXISTS",
        "failed": "FAILED",
        "not_attempted": "NOT ATTEMPTED",
    }.get(outcome.status, outcome.status.upper())


def _result_path(root: Path | None, value: str) -> str:
    if root is None:
        return value
    try:
        return os.fspath(Path(value).relative_to(root))
    except ValueError:
        return value


def _outcome_lines(
    outcome: GenerationTargetOutcome,
    *,
    index: int,
    workspace_root: Path | None,
) -> tuple[str, ...]:
    lines = [
        f"Target {index} — {_outcome_label(outcome)}",
        f"Class: {outcome.target.class_id}",
        f"Assignment: {outcome.target.assignment_id}",
    ]
    if outcome.class_packet_path:
        lines.append(
            f"Class packet: {_result_path(workspace_root, outcome.class_packet_path)}"
        )
    if outcome.individual_templates_dir:
        lines.append(
            "Individual folder: "
            + _result_path(workspace_root, outcome.individual_templates_dir)
        )
    if outcome.generation_result is not None:
        generation = outcome.generation_result
        lines.extend(
            (
                f"Installed artifacts: {generation.installed_artifact_count}",
                f"Clean-success artifacts: {generation.clean_success_count}",
                f"Partial artifacts: {generation.partial_artifact_count}",
                f"Failed-before-install artifacts: {generation.failed_before_install_count}",
                f"Verified installed routes: {generation.installed_route_count}",
            )
        )
    if outcome.failure_stage:
        lines.append(f"Failure stage: {outcome.failure_stage}")
    if outcome.error:
        lines.append(f"Error: {outcome.error}")
    lines.extend(f"Warning: {warning}" for warning in outcome.warnings)
    return tuple(lines)


def format_multi_class_generation_result(
    result: MultiClassGenerationResult,
    *,
    workspace_root: str | Path | None = None,
) -> str:
    """Return one consolidated truthful outcome summary for every selected target."""
    root = Path(workspace_root) if workspace_root is not None else None
    sections = [
        "Multi-Class Generation Results",
        f"Targets selected: {len(result.outcomes)}",
        f"Clean successes: {result.clean_success_count}",
        f"Partial successes: {result.partial_success_count}",
        f"Failed: {result.failed_count}",
        f"Not attempted: {result.not_attempted_count}",
        f"Installed artifacts: {result.installed_artifact_count}",
        f"Verified installed routes: {result.verified_route_count}",
    ]
    for index, outcome in enumerate(result.outcomes, start=1):
        sections.extend(
            (
                "",
                *_outcome_lines(
                    outcome,
                    index=index,
                    workspace_root=root,
                ),
            )
        )
    return "\n".join(sections)


def _prompt_target(root: Path) -> GenerationTargetRef | None:
    classes = discover_class_rosters(workspace_root=root)
    if not classes:
        print("No class rosters found. Create a class roster first.")
        pause_for_user()
        return None

    clear_screen()
    print_menu_header("Add Generation Target")
    print("Select class:")
    for index, record in enumerate(classes, start=1):
        print(f"{index}. {record['class_id']}")
    print_scoreform_navigation_options()
    try:
        selection = input("Select class: ")
        if parse_scoreform_navigation(selection) is not None:
            return None
        class_record = parse_single_selection(selection, classes, "class")
    except ValueError as error:
        print(f"Error: {error}")
        pause_for_user()
        return None

    class_id = str(class_record["class_id"])
    assignments = discover_class_assignments(class_id, workspace_root=root)
    if not assignments:
        print(f"No assignments found for class '{class_id}'.")
        pause_for_user()
        return None

    clear_screen()
    print_menu_header("Add Generation Target")
    print(f"Class: {class_id}")
    print()
    print("Select assignment:")
    for index, record in enumerate(assignments, start=1):
        assignment = record.get("assignment")
        title = assignment.get("title") if isinstance(assignment, dict) else None
        suffix = f" — {title}" if isinstance(title, str) and title else ""
        print(f"{index}. {record['assignment_id']}{suffix}")
    print_scoreform_navigation_options()
    try:
        selection = input("Select assignment: ")
        if parse_scoreform_navigation(selection) is not None:
            return None
        assignment_record = parse_single_selection(
            selection, assignments, "assignment"
        )
    except ValueError as error:
        print(f"Error: {error}")
        pause_for_user()
        return None

    return GenerationTargetRef(class_id, str(assignment_record["assignment_id"]))


def _remove_target(selected: list[GenerationTargetRef]) -> None:
    if not selected:
        print("No generation targets are selected.")
        pause_for_user()
        return
    clear_screen()
    print_menu_header("Remove Generation Target")
    for index, target in enumerate(selected, start=1):
        print(f"{index}. {target.class_id} / {target.assignment_id}")
    print_scoreform_navigation_options()
    try:
        selection = input("Select target to remove: ")
        if parse_scoreform_navigation(selection) is not None:
            return
        record = parse_single_selection(
            selection,
            [
                {"target": target, "label": f"{target.class_id}/{target.assignment_id}"}
                for target in selected
            ],
            "target",
        )
    except ValueError as error:
        print(f"Error: {error}")
        pause_for_user()
        return
    selected.remove(record["target"])


def _print_selected_targets(selected: list[GenerationTargetRef]) -> None:
    if not selected:
        print("Selected targets: none")
        return
    print("Selected targets:")
    for index, target in enumerate(selected, start=1):
        print(f"{index}. {target.class_id} / {target.assignment_id}")


def launch_multi_class_generation_menu(workspace_root: str | Path | None = None) -> int:
    """Build, preview, confirm, and execute one in-memory multi-target plan."""
    root = Path(workspace_root or workspace.get_scoreform_workspace_root())
    selected: list[GenerationTargetRef] = []

    while True:
        clear_screen()
        print_menu_header("Plan Multi-Class Answer-Sheet Generation")
        _print_selected_targets(selected)
        print()
        print("1. Add target")
        print("2. Remove target")
        print("3. Review plan and generate")
        print("4. Cancel")
        print_scoreform_navigation_options()
        print()

        choice = input("Select an option: ").strip()
        navigation = parse_scoreform_navigation(choice)
        if navigation is not None:
            return 0

        if choice == "1":
            target = _prompt_target(root)
            if target is None:
                continue
            if target in selected:
                print(
                    "That exact class/assignment target is already selected: "
                    f"{target.class_id} / {target.assignment_id}"
                )
                pause_for_user()
                continue
            selected.append(target)
            continue

        if choice == "2":
            _remove_target(selected)
            continue

        if choice == "4":
            print("Cancelled: answer-sheet generation was not started.")
            return 0

        if choice != "3":
            print(f"Invalid selection: {choice}.")
            print_invalid_navigation()
            pause_for_user()
            continue

        if not selected:
            print("Select at least one class/assignment target before reviewing a plan.")
            pause_for_user()
            continue

        plan = plan_multi_class_generation(root, tuple(selected))
        clear_screen()
        print_menu_header("Review Multi-Class Generation Plan")
        print(format_multi_class_generation_plan(plan))
        print()
        if not plan.ready:
            pause_for_user()
            continue

        confirmation = input("Type GENERATE to generate every ready target: ").strip()
        if confirmation != "GENERATE":
            print("Cancelled: answer-sheet generation was not started.")
            return 0

        try:
            result = execute_multi_class_generation(plan)
        except MultiClassGenerationStalePlanError as error:
            print("Generation was not started because the reviewed plan became stale.")
            for diagnostic in error.freshness.diagnostics:
                print(
                    f"- {diagnostic.target.class_id} / "
                    f"{diagnostic.target.assignment_id}: {diagnostic.message}"
                )
            print("Build and review a fresh plan before generating.")
            return 1
        except MultiClassGenerationPlanNotReadyError:
            print("Generation was not started because the reviewed plan is blocked.")
            return 1

        clear_screen()
        print_menu_header("Multi-Class Answer-Sheet Generation Complete")
        print(format_multi_class_generation_result(result, workspace_root=root))
        return 0 if result.success else 1
