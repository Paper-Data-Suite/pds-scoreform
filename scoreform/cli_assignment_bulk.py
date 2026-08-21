"""Prompt-free direct CLI for bulk answer-key and standards assignment edits."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from pds_core.standards import (
    StandardsLibrary,
    StandardsReadError,
    StandardsValidationError,
)
from pds_core.standards_selection import load_standards_for_selection

from scoreform import workspace
from scoreform.assignment_bulk_entry import (
    BulkAnswerKey,
    BulkParseResult,
    BulkStandardsAlignment,
    format_bulk_diagnostic,
    parse_alignment_csv,
    parse_alignment_json,
    parse_alignment_text,
    parse_answer_key_csv,
    parse_answer_key_json,
    parse_answer_key_text,
)
from scoreform.assignment_bulk_mutation import (
    AssignmentBulkMutationError,
    AssignmentBulkMutationPlan,
    AssignmentBulkSnapshot,
    commit_assignment_bulk_mutation,
    load_assignment_bulk_snapshot,
    plan_assignment_bulk_mutation,
)

_MAX_BULK_FILE_BYTES = 1_048_576
_MAX_INLINE_TEXT_CHARS = 262_144

BulkKeySourceKind = Literal["text", "csv", "json"]
BulkAlignmentSourceKind = Literal["text", "csv", "json"]


@dataclass(frozen=True, slots=True)
class BulkInputSource:
    """One explicit direct-CLI bulk input source."""

    kind: Literal["text", "csv", "json"]
    value: str


@dataclass(frozen=True, slots=True)
class AssignmentBulkCliOptions:
    """Parsed direct CLI options for one guarded assignment mutation."""

    class_id: str
    assignment_id: str
    answer_key: BulkInputSource | None
    alignment: BulkInputSource | None
    standards_profile_id: str | None
    apply: bool


def print_assignment_bulk_help() -> None:
    """Print the direct bulk-edit-assignment command contract."""

    print(
        """Usage:
  scoreform bulk-edit-assignment --class-id <class_id> --assignment-id <assignment_id> [answer-key source] [alignment source] [--standards-profile-id <profile_id>] [--apply]

Answer-key sources (choose at most one):
  --answer-key-text <text>     Complete positional key, for example \"A B C D\".
  --answer-key-csv <path>      Explicit UTF-8 CSV file with header question,answer.
  --answer-key-json <path>     Explicit UTF-8 JSON question-to-answer mapping.

Alignment sources (choose at most one):
  --alignment-text <text>      Complete selector groups, for example \"1-5=id_a;6-10=-\".
  --alignment-csv <path>       Explicit UTF-8 CSV file with header question,standards.
  --alignment-json <path>      Explicit UTF-8 JSON question-to-standard-ID-array mapping.

Safe defaults:
  At least one answer-key or alignment source is required.
  Without --apply, ScoreForm prints the complete normalized plan and writes nothing.
  --apply revalidates the exact reviewed assignment snapshot and current standards,
  then atomically replaces only assignment.json.

Rules:
  Key and alignment imports are full replacements, never partial patches.
  --standards-profile-id is valid only when an alignment source is supplied.
  Without --standards-profile-id, alignment replacement retains the assignment's
  current profile when one exists. A nonempty alignment requires a valid profile.
  CSV/JSON paths are explicit read-only regular files; directories and symlinks are
  rejected, supported suffixes are required, and input size is bounded to 1 MiB.
  There is no --force or --overwrite mode.
  Results, attempts, generated sheets, routes, registrations, manifests, and
  publications are never regenerated, rescored, or otherwise changed."""
    )


def _parse_assignment_bulk_args(args: Sequence[str]) -> AssignmentBulkCliOptions:
    values: dict[str, str] = {}
    key_sources: list[BulkInputSource] = []
    alignment_sources: list[BulkInputSource] = []
    apply = False
    index = 0

    scalar_flags = {
        "--class-id": "class_id",
        "--assignment-id": "assignment_id",
        "--standards-profile-id": "standards_profile_id",
    }
    source_flags: dict[
        str,
        tuple[Literal["key", "alignment"], Literal["text", "csv", "json"]],
    ] = {
        "--answer-key-text": ("key", "text"),
        "--answer-key-csv": ("key", "csv"),
        "--answer-key-json": ("key", "json"),
        "--alignment-text": ("alignment", "text"),
        "--alignment-csv": ("alignment", "csv"),
        "--alignment-json": ("alignment", "json"),
    }

    while index < len(args):
        token = args[index]

        if token in scalar_flags:
            key = scalar_flags[token]
            if key in values:
                raise ValueError(f"{token} may be supplied only once.")
            if index + 1 >= len(args) or args[index + 1].startswith("--"):
                raise ValueError(f"{token} requires a value.")
            values[key] = args[index + 1]
            index += 2
            continue

        if token in source_flags:
            target, kind = source_flags[token]
            if index + 1 >= len(args) or args[index + 1].startswith("--"):
                raise ValueError(f"{token} requires a value.")
            source = BulkInputSource(kind=kind, value=args[index + 1])
            if target == "key":
                key_sources.append(source)
            else:
                alignment_sources.append(source)
            index += 2
            continue

        if token == "--apply":
            if apply:
                raise ValueError("--apply may be supplied only once.")
            apply = True
            index += 1
            continue

        if token in {"--force", "--overwrite"}:
            raise ValueError(
                f"{token} is not supported; bulk assignment edits use guarded replacement only."
            )

        raise ValueError(f"Unknown bulk-edit-assignment argument: {token}")

    missing: list[str] = []
    for key, flag in (
        ("class_id", "--class-id"),
        ("assignment_id", "--assignment-id"),
    ):
        value = values.get(key)
        if value is None or not value.strip():
            missing.append(flag)
    if missing:
        raise ValueError("Missing required argument(s): " + ", ".join(missing))

    if "standards_profile_id" in values and not values["standards_profile_id"].strip():
        raise ValueError("--standards-profile-id must not be blank.")

    if len(key_sources) > 1:
        raise ValueError("Choose at most one answer-key source.")
    if len(alignment_sources) > 1:
        raise ValueError("Choose at most one alignment source.")
    if not key_sources and not alignment_sources:
        raise ValueError("Supply at least one answer-key or alignment source.")
    if "standards_profile_id" in values and not alignment_sources:
        raise ValueError(
            "--standards-profile-id requires an alignment source because profile changes are full alignment replacements."
        )

    return AssignmentBulkCliOptions(
        class_id=values["class_id"],
        assignment_id=values["assignment_id"],
        answer_key=key_sources[0] if key_sources else None,
        alignment=alignment_sources[0] if alignment_sources else None,
        standards_profile_id=values.get("standards_profile_id"),
        apply=apply,
    )


def _load_optional_standards_library(
    root: Path,
) -> tuple[StandardsLibrary | None, str | None]:
    try:
        return load_standards_for_selection(root), None
    except (StandardsReadError, StandardsValidationError, OSError) as error:
        return None, str(error)


def _read_bulk_file(source: BulkInputSource) -> bytes:
    path = Path(source.value).expanduser()
    expected_suffix = f".{source.kind}"
    if path.suffix.lower() != expected_suffix:
        raise ValueError(
            f"Bulk {source.kind.upper()} input must use the {expected_suffix} suffix: {path}"
        )
    if path.is_symlink():
        raise ValueError(f"Bulk input path must not be a symbolic link: {path}")
    try:
        if not path.is_file():
            raise ValueError(f"Bulk input path is not a regular file: {path}")
        size = path.stat().st_size
    except OSError as error:
        raise ValueError(f"Could not inspect bulk input file {path}: {error}") from error
    if size > _MAX_BULK_FILE_BYTES:
        raise ValueError(
            f"Bulk input file exceeds the {_MAX_BULK_FILE_BYTES}-byte limit: {path}"
        )
    try:
        return path.read_bytes()
    except OSError as error:
        raise ValueError(f"Could not read bulk input file {path}: {error}") from error


def _source_data(source: BulkInputSource) -> str | bytes:
    if source.kind == "text":
        if len(source.value) > _MAX_INLINE_TEXT_CHARS:
            raise ValueError(
                f"Inline bulk text exceeds the {_MAX_INLINE_TEXT_CHARS}-character limit."
            )
        return source.value
    return _read_bulk_file(source)


def _print_parse_diagnostics(label: str, result: BulkParseResult[object]) -> None:
    print(f"Error: {label} input is invalid.")
    for diagnostic in result.diagnostics:
        print(f"  - {diagnostic.code}: {format_bulk_diagnostic(diagnostic)}")


def _parse_answer_key_source(
    source: BulkInputSource,
    *,
    snapshot: AssignmentBulkSnapshot,
) -> BulkAnswerKey | None:
    question_count = cast(int, snapshot.assignment["question_count"])
    choices = cast(list[str], snapshot.assignment["choices"])
    data = _source_data(source)

    if source.kind == "text":
        result = parse_answer_key_text(
            cast(str, data),
            question_count=question_count,
            choices=choices,
        )
    elif source.kind == "csv":
        result = parse_answer_key_csv(
            data,
            question_count=question_count,
            choices=choices,
        )
    else:
        result = parse_answer_key_json(
            data,
            question_count=question_count,
            choices=choices,
        )

    if not result.ok:
        _print_parse_diagnostics("Answer key", cast(BulkParseResult[object], result))
        return None
    return result.value


def _parse_alignment_source(
    source: BulkInputSource,
    *,
    snapshot: AssignmentBulkSnapshot,
    requested_profile_id: str | None,
    standards_library: StandardsLibrary | None,
) -> BulkStandardsAlignment | None:
    question_count = cast(int, snapshot.assignment["question_count"])
    current_profile = snapshot.assignment.get("standards_profile_id")
    profile_id = requested_profile_id
    if profile_id is None and isinstance(current_profile, str):
        profile_id = current_profile

    data = _source_data(source)
    if source.kind == "text":
        result = parse_alignment_text(
            cast(str, data),
            question_count=question_count,
            standards_profile_id=profile_id,
            standards_library=standards_library,
        )
    elif source.kind == "csv":
        result = parse_alignment_csv(
            data,
            question_count=question_count,
            standards_profile_id=profile_id,
            standards_library=standards_library,
        )
    else:
        result = parse_alignment_json(
            data,
            question_count=question_count,
            standards_profile_id=profile_id,
            standards_library=standards_library,
        )

    if not result.ok:
        _print_parse_diagnostics("Standards alignment", cast(BulkParseResult[object], result))
        return None
    return result.value


def _workspace_relative(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _answer_mapping(assignment: dict[str, object]) -> dict[int, str]:
    raw = cast(dict[int | str, str], assignment["answer_key"])
    return {int(question): answer for question, answer in raw.items()}


def _standards_mapping(assignment: dict[str, object]) -> dict[int, list[str]]:
    raw = cast(dict[int | str, list[str]], assignment["standards"])
    return {int(question): list(values) for question, values in raw.items()}


def _print_complete_plan(root: Path, plan: AssignmentBulkMutationPlan) -> None:
    snapshot = plan.snapshot
    current = snapshot.assignment
    candidate = plan.candidate_assignment
    question_count = cast(int, candidate["question_count"])
    current_answers = _answer_mapping(current)
    candidate_answers = _answer_mapping(candidate)
    current_standards = _standards_mapping(current)
    candidate_standards = _standards_mapping(candidate)

    print("Assignment bulk-edit plan")
    print("Mode: PLAN ONLY")
    print()
    print("Managed assignment")
    print(f"  class_id: {snapshot.class_id}")
    print(f"  assignment_id: {snapshot.assignment_id}")
    print(f"  assignment_path: {_workspace_relative(root, snapshot.assignment_path)}")
    print(f"  original_sha256: {snapshot.assignment_sha256}")
    print(f"  candidate_sha256: {plan.candidate_sha256}")
    print()
    print("Immutable configuration")
    print(f"  title: {candidate['title']}")
    print(f"  question_count: {candidate['question_count']}")
    print(f"  choices: {', '.join(cast(list[str], candidate['choices']))}")
    print(f"  layout_id: {candidate['layout_id']}")
    print()
    print("Complete normalized answer key")
    for question in range(1, question_count + 1):
        marker = " *" if current_answers[question] != candidate_answers[question] else ""
        print(f"  Q{question}: {candidate_answers[question]}{marker}")
    print()
    profile = candidate.get("standards_profile_id")
    print(
        "Standards profile: "
        f"{profile if isinstance(profile, str) else '(none)'}"
    )
    print("Complete normalized standards alignment")
    for question in range(1, question_count + 1):
        values = candidate_standards[question]
        label = ", ".join(values) if values else "(unaligned)"
        marker = " *" if current_standards[question] != values else ""
        print(f"  Q{question}: {label}{marker}")

    changed_fields = [
        field
        for field in ("answer_key", "standards", "standards_profile_id")
        if current.get(field) != candidate.get(field)
    ]
    print()
    print(
        "Changed assignment fields: "
        + (", ".join(changed_fields) if changed_fields else "(none; normalized candidate matches current definition)")
    )
    print("Unchanged downstream state")
    print("  results/attempt history")
    print("  generated answer sheets, pages, issuances, and routes")
    print("  Academic Work Registration")
    print("  manifests and publications")
    print("  scans, scan-review, debug, and export state")
    print()
    print("No changes were made.")
    print("Re-run the same command with --apply to atomically replace assignment.json.")


def _print_apply_result(root: Path, snapshot: AssignmentBulkSnapshot) -> None:
    assignment = snapshot.assignment
    question_count = cast(int, assignment["question_count"])
    answers = _answer_mapping(assignment)
    standards = _standards_mapping(assignment)

    print("Assignment bulk-edit result")
    print("Mode: APPLIED")
    print(f"class_id: {snapshot.class_id}")
    print(f"assignment_id: {snapshot.assignment_id}")
    print(f"assignment_path: {_workspace_relative(root, snapshot.assignment_path)}")
    print(f"assignment_sha256: {snapshot.assignment_sha256}")
    print()
    print("Complete persisted answer key")
    for question in range(1, question_count + 1):
        print(f"  Q{question}: {answers[question]}")
    profile = assignment.get("standards_profile_id")
    print()
    print(
        "Standards profile: "
        f"{profile if isinstance(profile, str) else '(none)'}"
    )
    print("Complete persisted standards alignment")
    for question in range(1, question_count + 1):
        values = standards[question]
        print(f"  Q{question}: {', '.join(values) if values else '(unaligned)'}")
    print()
    print("Only the canonical assignment definition was replaced.")
    print("Historical results were not rescored and downstream state was not regenerated.")


def run_assignment_bulk(
    args: Sequence[str],
    *,
    workspace_root: str | Path | None = None,
) -> int:
    """Plan or explicitly apply one guarded bulk assignment edit."""

    if not args:
        print_assignment_bulk_help()
        return 1
    if len(args) == 1 and args[0] in {"help", "--help", "-h"}:
        print_assignment_bulk_help()
        return 0

    try:
        options = _parse_assignment_bulk_args(args)
    except ValueError as error:
        print(f"Error: {error}")
        print_assignment_bulk_help()
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
        snapshot = load_assignment_bulk_snapshot(
            root,
            options.class_id,
            options.assignment_id,
            standards_library=standards_library,
        )
    except AssignmentBulkMutationError as error:
        if standards_error is not None and "standards library" in str(error).lower():
            print(
                "Error: The assignment uses standards, but the current Core standards "
                f"library could not be loaded: {standards_error}"
            )
        else:
            print(f"Error: {error}")
        return 1

    try:
        answer_key = (
            _parse_answer_key_source(options.answer_key, snapshot=snapshot)
            if options.answer_key is not None
            else None
        )
        if options.answer_key is not None and answer_key is None:
            return 1

        alignment = (
            _parse_alignment_source(
                options.alignment,
                snapshot=snapshot,
                requested_profile_id=options.standards_profile_id,
                standards_library=standards_library,
            )
            if options.alignment is not None
            else None
        )
        if options.alignment is not None and alignment is None:
            return 1
    except ValueError as error:
        print(f"Error: {error}")
        return 1

    try:
        plan = plan_assignment_bulk_mutation(
            snapshot,
            answer_key=answer_key,
            standards_alignment=alignment,
            standards_library=standards_library,
        )
    except AssignmentBulkMutationError as error:
        print(f"Error: {error}")
        return 1

    if not options.apply:
        _print_complete_plan(root, plan)
        return 0

    try:
        persisted = commit_assignment_bulk_mutation(
            root,
            plan,
            standards_library=standards_library,
        )
    except AssignmentBulkMutationError as error:
        print(f"Error: {error}")
        return 1

    _print_apply_result(root, persisted)
    return 0


__all__ = [
    "AssignmentBulkCliOptions",
    "BulkInputSource",
    "print_assignment_bulk_help",
    "run_assignment_bulk",
]
