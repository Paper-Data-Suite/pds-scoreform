"""Prompt-free direct CLI for ScoreForm assessment setup presets."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, cast

from pds_core.standards import (
    StandardsLibrary,
    StandardsReadError,
    StandardsValidationError,
)
from pds_core.standards_selection import load_standards_for_selection

from scoreform import workspace
from scoreform.assignment_presets import (
    AssignmentPresetApplicationPlan,
    AssignmentPresetApplicationResult,
    AssignmentPresetError,
    AssignmentPresetFromAssignmentPlan,
    AssignmentPresetMutationPlan,
    AssignmentPresetSnapshot,
    commit_assignment_preset_application,
    commit_assignment_preset_from_assignment,
    commit_assignment_preset_mutation,
    discover_assignment_presets,
    load_assignment_preset,
    plan_assignment_preset_application,
    plan_create_assignment_preset_from_assignment,
    plan_delete_assignment_preset,
)


def print_assignment_preset_help() -> None:
    """Print the direct preset command contract."""

    print(
        """Usage:
  scoreform preset list
  scoreform preset show --preset-id <preset_id>
  scoreform preset save --preset-id <preset_id> --source-class-id <class_id> --source-assignment-id <assignment_id> [--label <label>] [--apply]
  scoreform preset apply --preset-id <preset_id> --target-assignment-id <assignment_id> --title <title> --target-class-id <class_id> [--target-class-id <class_id> ...] [--apply]
  scoreform preset delete --preset-id <preset_id> [--apply]

Safe defaults:
  list and show are read-only.
  save, apply, and delete are PLAN ONLY unless --apply is supplied.
  There is no overwrite or force mode.

Preset rules:
  Presets are workspace-local ScoreForm configuration, not assignments.
  Presets contain no class, roster, student, result, scan, route, manifest, or publication state.
  Applying a preset creates only fresh class-qualified assignment work.
  --target-class-id may be repeated for preset apply."""
    )


def _workspace_root(
    workspace_root: str | Path | None,
) -> Path:
    if workspace_root is not None:
        return Path(workspace_root)
    return Path(workspace.get_scoreform_workspace_root())


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


def _parse_value_options(
    args: Sequence[str],
    *,
    allowed: dict[str, str],
    repeatable: set[str] | None = None,
    allow_apply: bool = False,
) -> tuple[dict[str, str], dict[str, list[str]], bool]:
    repeatable = repeatable or set()
    values: dict[str, str] = {}
    repeated: dict[str, list[str]] = {flag: [] for flag in repeatable}
    apply = False
    index = 0

    while index < len(args):
        token = args[index]

        if token in {"--force", "--overwrite"}:
            raise ValueError(
                f"{token} is not supported; preset mutations and application "
                "are guarded explicitly."
            )

        if token == "--apply":
            if not allow_apply:
                raise ValueError("--apply is not valid for this preset command.")
            if apply:
                raise ValueError("--apply may be supplied only once.")
            apply = True
            index += 1
            continue

        if token in repeatable:
            if index + 1 >= len(args) or args[index + 1].startswith("--"):
                raise ValueError(f"{token} requires a value.")
            repeated[token].append(args[index + 1])
            index += 2
            continue

        key = allowed.get(token)
        if key is None:
            raise ValueError(f"Unknown preset argument: {token}")
        if key in values:
            raise ValueError(f"{token} may be supplied only once.")
        if index + 1 >= len(args) or args[index + 1].startswith("--"):
            raise ValueError(f"{token} requires a value.")
        values[key] = args[index + 1]
        index += 2

    return values, repeated, apply


def _require(values: dict[str, str], *required: tuple[str, str]) -> None:
    missing = [
        flag
        for key, flag in required
        if key not in values or not values[key].strip()
    ]
    if missing:
        raise ValueError(
            "Missing required argument(s): " + ", ".join(missing)
        )


def _print_preset(snapshot: AssignmentPresetSnapshot) -> None:
    preset = snapshot.preset
    question_count = cast(int, preset["question_count"])
    choices = cast(list[str], preset["choices"])
    answer_key = cast(dict[str, str], preset["answer_key"])
    standards = cast(dict[str, list[str]], preset["standards"])

    print(f"preset_id: {snapshot.preset_id}")
    print(f"label: {preset['label']}")
    print(f"schema_version: {preset['schema_version']}")
    print(f"question_count: {question_count}")
    print(f"choices: {', '.join(choices)}")
    print(f"layout_id: {preset['layout_id']}")
    profile = preset.get("standards_profile_id")
    print(
        "standards_profile_id: "
        f"{profile if profile is not None else '(none)'}"
    )
    print(f"sha256: {snapshot.preset_sha256}")
    print("answer_key:")
    for question_number in range(1, question_count + 1):
        print(f"  Q{question_number}: {answer_key[str(question_number)]}")
    print("standards:")
    for question_number in range(1, question_count + 1):
        values = standards.get(str(question_number), [])
        label = ", ".join(values) if values else "(unaligned)"
        print(f"  Q{question_number}: {label}")


def _run_list(root: Path) -> int:
    discovery = discover_assignment_presets(root)

    print("Assessment setup presets")
    if not discovery.presets:
        print("  (none)")
    for snapshot in discovery.presets:
        print(
            f"  {snapshot.preset_id}: "
            f"{snapshot.preset.get('label', '(unlabeled)')}"
        )

    if discovery.issues:
        print()
        print("Invalid preset entries")
        for issue in discovery.issues:
            print(
                f"  {_workspace_relative(root, issue.path)}: {issue.message}"
            )
        return 1
    return 0


def _run_show(root: Path, args: Sequence[str]) -> int:
    values, _repeated, apply = _parse_value_options(
        args,
        allowed={"--preset-id": "preset_id"},
    )
    if apply:
        raise AssertionError("show parser cannot enable apply")
    _require(values, ("preset_id", "--preset-id"))

    snapshot = load_assignment_preset(root, values["preset_id"])
    _print_preset(snapshot)
    return 0


def _print_save_plan(
    root: Path,
    plan: AssignmentPresetFromAssignmentPlan,
) -> None:
    source = plan.source
    mutation = plan.mutation
    candidate = mutation.candidate
    if candidate is None:
        raise ValueError("Preset save plan has no candidate.")

    print("Assessment setup preset save plan")
    print("Mode: PLAN ONLY")
    print()
    print("Source assignment")
    print(f"  class_id: {source.work.class_id}")
    print(f"  assignment_id: {source.work.work_id}")
    print(f"  title: {source.definition.title}")
    print(f"  assignment_sha256: {source.assignment_sha256}")
    print()
    print("Preset")
    print(f"  preset_id: {candidate['preset_id']}")
    print(f"  label: {candidate['label']}")
    print(
        "  path: "
        f"{_workspace_relative(root, mutation.path)}"
    )
    print("  source assignment/class identity persisted: no")
    print("  student/operational/result history persisted: no")
    print()
    print("No changes were made.")
    print("Re-run the same command with --apply to save this preset.")


def _run_save(
    root: Path,
    args: Sequence[str],
    standards_library: StandardsLibrary | None,
) -> int:
    values, _repeated, apply = _parse_value_options(
        args,
        allowed={
            "--preset-id": "preset_id",
            "--source-class-id": "source_class_id",
            "--source-assignment-id": "source_assignment_id",
            "--label": "label",
        },
        allow_apply=True,
    )
    _require(
        values,
        ("preset_id", "--preset-id"),
        ("source_class_id", "--source-class-id"),
        ("source_assignment_id", "--source-assignment-id"),
    )

    plan = plan_create_assignment_preset_from_assignment(
        root,
        source_class_id=values["source_class_id"],
        source_assignment_id=values["source_assignment_id"],
        preset_id=values["preset_id"],
        label=values.get("label"),
        standards_library=standards_library,
    )

    if not apply:
        _print_save_plan(root, plan)
        return 0

    snapshot = commit_assignment_preset_from_assignment(
        root,
        plan,
        standards_library=standards_library,
    )
    print("Saved assessment setup preset.")
    print(f"preset_id: {snapshot.preset_id}")
    print(f"path: {_workspace_relative(root, snapshot.path)}")
    return 0


def _print_apply_plan(
    root: Path,
    plan: AssignmentPresetApplicationPlan,
) -> None:
    candidate = plan.candidate
    question_count = cast(int, candidate["question_count"])
    choices = cast(list[str], candidate["choices"])
    answer_key = cast(dict[int, str], candidate["answer_key"])
    standards = cast(dict[str, list[str]], candidate["standards"])

    print("Assessment setup preset application plan")
    print("Mode: PLAN ONLY")
    print()
    print("Preset")
    print(f"  preset_id: {plan.preset.preset_id}")
    print(f"  label: {plan.preset.preset['label']}")
    print(f"  preset_sha256: {plan.preset.preset_sha256}")
    print()
    print("Fresh assignment configuration")
    print(f"  assignment_id: {candidate['assignment_id']}")
    print(f"  title: {candidate['title']}")
    print(f"  question_count: {question_count}")
    print(f"  choices: {', '.join(choices)}")
    print(f"  layout_id: {candidate['layout_id']}")
    profile = candidate.get("standards_profile_id")
    print(
        "  standards_profile_id: "
        f"{profile if profile is not None else '(none)'}"
    )
    print("  answer_key:")
    for question_number in range(1, question_count + 1):
        print(f"    Q{question_number}: {answer_key[question_number]}")
    print("  standards:")
    for question_number in range(1, question_count + 1):
        values = standards.get(str(question_number), [])
        label = ", ".join(values) if values else "(unaligned)"
        print(f"    Q{question_number}: {label}")

    print()
    print("Targets")
    for index, target in enumerate(plan.targets, start=1):
        print(f"  {index}. {target.work.class_id}/{target.work.work_id}")
        print(f"     students: {target.roster.student_count}")
        periods = ", ".join(target.roster.periods) or "(none)"
        print(f"     periods: {periods}")
        print(
            "     assignment_path: "
            f"{_workspace_relative(root, target.assignment_path)}"
        )

    print()
    print("No changes were made.")
    print("Re-run the same command with --apply to create these assignments.")


def _print_apply_result(
    root: Path,
    result: AssignmentPresetApplicationResult,
) -> None:
    print("Assessment setup preset application result")
    print()

    print("Created")
    if result.created:
        for created in result.created:
            print(
                f"  {created.work.class_id}/{created.work.work_id}: "
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
            for residue in failure.residue_paths:
                print(
                    "    inspect residue: "
                    f"{_workspace_relative(root, residue)}"
                )

    if result.not_attempted:
        print()
        print("Not attempted after runtime failure")
        for target in result.not_attempted:
            print(f"  {target.work.class_id}/{target.work.work_id}")

    print()
    if result.complete:
        print(
            f"Created {len(result.created)} fresh assignment"
            f"{'' if len(result.created) == 1 else 's'} from preset "
            f"{result.preset.preset_id}."
        )
        print(
            "No generated sheets, routes, scans, results, registrations, "
            "manifests, or publications were created."
        )
    else:
        print(
            "Preset application completed with a runtime failure. Earlier "
            "successful targets remain durable."
        )


def _run_apply(
    root: Path,
    args: Sequence[str],
    standards_library: StandardsLibrary | None,
) -> int:
    values, repeated, apply = _parse_value_options(
        args,
        allowed={
            "--preset-id": "preset_id",
            "--target-assignment-id": "target_assignment_id",
            "--title": "title",
        },
        repeatable={"--target-class-id"},
        allow_apply=True,
    )
    _require(
        values,
        ("preset_id", "--preset-id"),
        ("target_assignment_id", "--target-assignment-id"),
        ("title", "--title"),
    )
    targets = repeated["--target-class-id"]
    if not targets:
        raise ValueError("Missing required argument(s): --target-class-id")

    plan = plan_assignment_preset_application(
        root,
        preset_id=values["preset_id"],
        target_class_ids=targets,
        target_assignment_id=values["target_assignment_id"],
        title=values["title"],
        standards_library=standards_library,
    )

    if not apply:
        _print_apply_plan(root, plan)
        return 0

    result = commit_assignment_preset_application(
        root,
        plan,
        standards_library=standards_library,
    )
    _print_apply_result(root, result)
    return 0 if result.complete else 1


def _print_delete_plan(
    root: Path,
    plan: AssignmentPresetMutationPlan,
) -> None:
    print("Assessment setup preset delete plan")
    print("Mode: PLAN ONLY")
    print(f"preset_id: {plan.preset_id}")
    print(f"path: {_workspace_relative(root, plan.path)}")
    print(f"reviewed_sha256: {plan.current_sha256}")
    print()
    print("Assignments previously created from this preset will not be changed.")
    print("No changes were made.")
    print("Re-run the same command with --apply to delete this preset.")


def _run_delete(root: Path, args: Sequence[str]) -> int:
    values, _repeated, apply = _parse_value_options(
        args,
        allowed={"--preset-id": "preset_id"},
        allow_apply=True,
    )
    _require(values, ("preset_id", "--preset-id"))

    plan = plan_delete_assignment_preset(root, values["preset_id"])
    if not apply:
        _print_delete_plan(root, plan)
        return 0

    commit_assignment_preset_mutation(root, plan)
    print(f"Deleted assessment setup preset: {plan.preset_id}")
    return 0


def run_assignment_preset(
    args: Sequence[str],
    *,
    workspace_root: str | Path | None = None,
) -> int:
    """Run one direct preset command."""

    if not args or args[0] in {"help", "--help", "-h"}:
        print_assignment_preset_help()
        return 0 if args else 1

    command = args[0]
    command_args = args[1:]

    try:
        root = _workspace_root(workspace_root)
    except workspace.WorkspaceRootError as error:
        print(f"Error: {error}")
        return 1

    standards_library, standards_error = _load_optional_standards_library(root)

    try:
        if command == "list":
            if command_args:
                raise ValueError("preset list does not accept arguments.")
            return _run_list(root)
        if command == "show":
            return _run_show(root, command_args)
        if command == "save":
            return _run_save(root, command_args, standards_library)
        if command == "apply":
            return _run_apply(root, command_args, standards_library)
        if command == "delete":
            return _run_delete(root, command_args)
        raise ValueError(f"Unknown preset command: {command}")
    except (AssignmentPresetError, ValueError) as error:
        if (
            standards_error is not None
            and "standards library" in str(error).lower()
        ):
            print(
                "Error: The requested preset operation requires the current Core "
                f"standards library, but it could not be loaded: {standards_error}"
            )
        else:
            print(f"Error: {error}")
        return 1
