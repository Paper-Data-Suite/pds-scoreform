"""Prompt-free direct CLI for safe assignment copying."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence, cast

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


@dataclass(frozen=True, slots=True)
class AssignmentCopyCliOptions:
    """Parsed direct CLI options for one assignment-copy operation."""

    source_class_id: str
    source_assignment_id: str
    target_assignment_id: str
    target_class_ids: tuple[str, ...]
    title: str | None
    apply: bool


def print_assignment_copy_help() -> None:
    """Print the direct copy-assignment command contract."""
    print(
        """Usage:
  scoreform copy-assignment --source-class-id <class_id> --source-assignment-id <assignment_id> --target-assignment-id <assignment_id> --target-class-id <class_id> [--target-class-id <class_id> ...] [--title <title>] [--apply]

Safe defaults:
  Without --apply, ScoreForm validates and prints the complete copy plan and
  writes nothing. --apply revalidates the reviewed plan and creates only fresh
  target work identities.

Rules:
  --target-class-id may be repeated.
  The source assignment ID may be reused in another class.
  Same-class copying requires a different unused target assignment ID.
  Existing target work roots are collisions.
  There is no overwrite or force mode.
  Rosters, sheets, routes, scans, results, manifests, and publications are not copied."""
    )


def _parse_assignment_copy_args(
    args: Sequence[str],
) -> AssignmentCopyCliOptions:
    values: dict[str, str] = {}
    targets: list[str] = []
    apply = False
    index = 0

    value_flags = {
        "--source-class-id": "source_class_id",
        "--source-assignment-id": "source_assignment_id",
        "--target-assignment-id": "target_assignment_id",
        "--title": "title",
    }

    while index < len(args):
        token = args[index]

        if token == "--target-class-id":
            if index + 1 >= len(args) or args[index + 1].startswith("--"):
                raise ValueError("--target-class-id requires a value.")
            targets.append(args[index + 1])
            index += 2
            continue

        if token in value_flags:
            key = value_flags[token]
            if key in values:
                raise ValueError(f"{token} may be supplied only once.")
            if index + 1 >= len(args) or args[index + 1].startswith("--"):
                raise ValueError(f"{token} requires a value.")
            values[key] = args[index + 1]
            index += 2
            continue

        if token == "--apply":
            if apply:
                raise ValueError("--apply may be supplied only once.")
            apply = True
            index += 1
            continue

        if token in {"--overwrite", "--force"}:
            raise ValueError(
                f"{token} is not supported; assignment copying is create-only."
            )

        raise ValueError(f"Unknown copy-assignment argument: {token}")

    missing: list[str] = []
    required = (
        ("source_class_id", "--source-class-id"),
        ("source_assignment_id", "--source-assignment-id"),
        ("target_assignment_id", "--target-assignment-id"),
    )
    for key, flag in required:
        value = values.get(key)
        if value is None or not value.strip():
            missing.append(flag)
    if not targets:
        missing.append("--target-class-id")
    if missing:
        raise ValueError(
            "Missing required argument(s): " + ", ".join(missing)
        )

    return AssignmentCopyCliOptions(
        source_class_id=values["source_class_id"],
        source_assignment_id=values["source_assignment_id"],
        target_assignment_id=values["target_assignment_id"],
        target_class_ids=tuple(targets),
        title=values.get("title"),
        apply=apply,
    )


def _workspace_relative(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _format_periods(periods: tuple[str, ...]) -> str:
    return ", ".join(periods) if periods else "(none)"


def _print_plan(root: Path, plan: AssignmentCopyPlan) -> None:
    source = plan.source
    candidate = plan.candidate
    question_count = cast(int, candidate["question_count"])
    choices = cast(list[str], candidate["choices"])
    answer_key = cast(dict[int, str], candidate["answer_key"])
    standards = cast(dict[str, list[str]], candidate["standards"])

    print("Assignment copy plan")
    print("Mode: PLAN ONLY")
    print()
    print("Source")
    print(f"  class_id: {source.work.class_id}")
    print(f"  assignment_id: {source.work.work_id}")
    print(f"  title: {source.definition.title}")
    print(f"  assignment_sha256: {source.assignment_sha256}")
    print()
    print("Target assignment configuration")
    print(f"  assignment_id: {candidate['assignment_id']}")
    print(f"  title: {candidate['title']}")
    print(f"  question_count: {question_count}")
    print(f"  choices: {', '.join(choices)}")
    print(f"  layout_id: {candidate['layout_id']}")
    profile = candidate.get("standards_profile_id")
    print(f"  standards_profile_id: {profile if profile is not None else '(none)'}")
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
        roster = target.roster
        print(f"  {index}. {target.work.class_id}/{target.work.work_id}")
        print(f"     students: {roster.student_count}")
        print(f"     periods: {_format_periods(roster.periods)}")
        print(
            "     school_year: "
            f"{roster.school_year if roster.school_year is not None else '(not set)'}"
        )
        if roster.metadata_warning is not None:
            print(f"     class metadata warning: {roster.metadata_warning}")
        print(
            "     assignment_path: "
            f"{_workspace_relative(root, target.assignment_path)}"
        )

    print()
    print("Not copied")
    print("  roster/student state")
    print("  generated sheets, issuances, pages, or routes")
    print("  scans or scan-review history")
    print("  results or attempts")
    print("  Academic Work Registration")
    print("  manifests or publications")
    print("  debug/export state")
    print()
    print("No changes were made.")
    print("Re-run the same command with --apply to create these assignments.")


def _print_result(root: Path, result: AssignmentCopyResult) -> None:
    print("Assignment copy result")
    print()

    if result.created:
        print("Created")
        for created in result.created:
            print(
                f"  {created.work.class_id}/{created.work.work_id}: "
                f"{_workspace_relative(root, created.assignment_path)}"
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
        noun = "copy" if len(result.created) == 1 else "copies"
        print(f"Created {len(result.created)} fresh assignment {noun}.")
        print(
            "No sheets, routes, scans, results, manifests, or publications "
            "were created."
        )
    else:
        print(
            "Assignment copying completed with a runtime failure. Earlier "
            "successful targets remain durable."
        )


def _load_optional_standards_library(
    root: Path,
) -> tuple[StandardsLibrary | None, str | None]:
    try:
        return load_standards_for_selection(root), None
    except (StandardsReadError, StandardsValidationError, OSError) as error:
        return None, str(error)


def run_assignment_copy(
    args: Sequence[str],
    *,
    workspace_root: str | Path | None = None,
) -> int:
    """Plan or explicitly apply one safe assignment-copy operation."""
    if not args:
        print_assignment_copy_help()
        return 1
    if len(args) == 1 and args[0] in {"help", "--help", "-h"}:
        print_assignment_copy_help()
        return 0

    try:
        options = _parse_assignment_copy_args(args)
    except ValueError as error:
        print(f"Error: {error}")
        print_assignment_copy_help()
        return 1

    try:
        root = (
            Path(workspace_root)
            if workspace_root is not None
            else Path(workspace.get_scoreform_workspace_root())
        )
    except workspace.WorkspaceRootError as error:
        print(f"Error: {error}")
        return 1

    standards_library, standards_error = _load_optional_standards_library(root)

    try:
        source = load_assignment_copy_source(
            root,
            options.source_class_id,
            options.source_assignment_id,
            standards_library=standards_library,
        )
        plan = plan_assignment_copy(
            root,
            source,
            target_class_ids=options.target_class_ids,
            target_assignment_id=options.target_assignment_id,
            title=options.title,
        )
    except AssignmentCopyError as error:
        if (
            standards_error is not None
            and "standards library is required" in str(error)
        ):
            print(
                "Error: The source assignment uses standards, but the current "
                f"Core standards library could not be loaded: {standards_error}"
            )
        else:
            print(f"Error: {error}")
        return 1

    if not options.apply:
        _print_plan(root, plan)
        return 0

    try:
        result = commit_assignment_copy(
            root,
            plan,
            standards_library=standards_library,
        )
    except AssignmentCopyError as error:
        print(f"Error: {error}")
        return 1

    _print_result(root, result)
    return 0 if result.complete else 1
