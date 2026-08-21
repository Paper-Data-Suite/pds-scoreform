"""Prompt-free multi-class managed answer-sheet generation CLI."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from scoreform import workspace
from scoreform.multi_class_generation import (
    GenerationTargetRef,
    MultiClassGenerationPlanNotReadyError,
    MultiClassGenerationStalePlanError,
    MultiClassGenerationValidationError,
    execute_multi_class_generation,
    plan_multi_class_generation,
)
from scoreform.multi_class_generation_ui import (
    format_multi_class_generation_plan,
    format_multi_class_generation_result,
)
from scoreform.validation import is_safe_identifier

USAGE = (
    "Usage: scoreform generate-batch --target <class_id>/<assignment_id> "
    "[--target <class_id>/<assignment_id> ...] [--apply]"
)


def print_generate_batch_help() -> None:
    """Print the deterministic direct-command contract."""
    print(USAGE)
    print()
    print("Plan or execute managed answer-sheet generation for explicit targets.")
    print()
    print("Options:")
    print("  --target <class_id>/<assignment_id>  Add one exact target; repeatable.")
    print("  --apply                             Execute after the complete plan is ready.")
    print("  --help                              Show this help.")
    print()
    print("Without --apply, generation is plan-only and writes nothing.")
    print("Targets execute in the order supplied. Exact duplicate targets are rejected.")
    print("There is no force, overwrite, implicit discovery, or identity-reuse mode.")


def parse_generation_target_spec(value: str) -> GenerationTargetRef:
    """Parse one exact ``class_id/assignment_id`` CLI target specification."""
    if not isinstance(value, str):
        raise MultiClassGenerationValidationError(
            "Generation target must be a string in class_id/assignment_id form."
        )
    if value != value.strip() or value.count("/") != 1:
        raise MultiClassGenerationValidationError(
            "Generation target must use exact class_id/assignment_id form."
        )
    class_id, assignment_id = value.split("/", 1)
    if not class_id or not assignment_id:
        raise MultiClassGenerationValidationError(
            "Generation target requires non-empty class_id and assignment_id values."
        )
    if not is_safe_identifier(class_id):
        raise MultiClassGenerationValidationError(
            f"Generation target class_id is unsafe: {class_id!r}."
        )
    if not is_safe_identifier(assignment_id):
        raise MultiClassGenerationValidationError(
            f"Generation target assignment_id is unsafe: {assignment_id!r}."
        )
    return GenerationTargetRef(class_id, assignment_id)


def _parse_generate_batch_args(
    args: Sequence[str],
) -> tuple[tuple[GenerationTargetRef, ...], bool]:
    targets: list[GenerationTargetRef] = []
    apply = False
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--target":
            if index + 1 >= len(args) or args[index + 1].startswith("--"):
                raise MultiClassGenerationValidationError(
                    "--target requires a class_id/assignment_id value."
                )
            targets.append(parse_generation_target_spec(args[index + 1]))
            index += 2
            continue
        if arg == "--apply":
            if apply:
                raise MultiClassGenerationValidationError(
                    "--apply may be specified only once."
                )
            apply = True
            index += 1
            continue
        raise MultiClassGenerationValidationError(f"Unknown option: {arg}")

    if not targets:
        raise MultiClassGenerationValidationError(
            "At least one --target class_id/assignment_id is required."
        )
    return tuple(targets), apply


def _print_stale_plan_error(error: MultiClassGenerationStalePlanError) -> None:
    print("Error: The reviewed generation plan became stale before generation started.")
    for diagnostic in error.freshness.diagnostics:
        print(
            f"- {diagnostic.target.class_id}/{diagnostic.target.assignment_id}: "
            f"{diagnostic.message}"
        )
    print("Build and review a fresh plan before generating.")


def run_generate_batch(
    args: Sequence[str],
    *,
    workspace_root: str | Path | None = None,
) -> int:
    """Plan by default, or explicitly execute, one ordered target batch."""
    values = tuple(args)
    if values in {("--help",), ("-h",), ("help",)}:
        print_generate_batch_help()
        return 0

    try:
        targets, apply = _parse_generate_batch_args(values)
    except MultiClassGenerationValidationError as error:
        print(f"Error: {error}")
        print(USAGE)
        return 1

    try:
        root = Path(
            workspace_root
            if workspace_root is not None
            else workspace.get_scoreform_workspace_root()
        )
        plan = plan_multi_class_generation(root, targets)
    except (MultiClassGenerationValidationError, workspace.WorkspaceRootError) as error:
        print(f"Error: {error}")
        print("No changes were made.")
        return 1

    print(f"Mode: {'APPLY' if apply else 'PLAN ONLY'}")
    print()
    print(format_multi_class_generation_plan(plan))

    if not plan.ready:
        print()
        print("Error: Generation cannot start while any selected target is blocked.")
        print("No changes were made.")
        return 1

    if not apply:
        print()
        print("No changes were made.")
        return 0

    try:
        result = execute_multi_class_generation(plan)
    except MultiClassGenerationStalePlanError as error:
        print()
        _print_stale_plan_error(error)
        print("No changes were made.")
        return 1
    except MultiClassGenerationPlanNotReadyError as error:
        print()
        print(f"Error: {error}")
        print("No changes were made.")
        return 1

    print()
    print(format_multi_class_generation_result(result, workspace_root=root))
    return 0 if result.success else 1
