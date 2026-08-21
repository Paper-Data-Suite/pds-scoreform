"""Teacher-facing bulk answer-key and standards-alignment entry helpers.

This module owns terminal input/preview behavior only. Parsing and normalization stay
in :mod:`scoreform.assignment_bulk_entry`; durable assignment mutation stays in
:mod:`scoreform.assignment_bulk_mutation`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal, cast

from pds_core.standards import StandardsLibrary
from pds_core.standards_selection import list_profiles_for_selection

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
from scoreform.menu_navigation import (
    parse_scoreform_navigation,
    print_invalid_navigation,
    print_scoreform_navigation_options,
)

MAX_BULK_INPUT_BYTES = 256 * 1024
AnswerEntryMethod = Literal["text", "csv", "json", "per-question"]
AlignmentEntryMethod = Literal["text", "csv", "json"]


def _is_back_text(value: str) -> bool:
    """Treat only the explicit word BACK as navigation in free-form content."""

    return value.strip().lower() == "back"


def _print_diagnostics(result: BulkParseResult[object]) -> None:
    print("Bulk input was not staged:")
    for diagnostic in result.diagnostics:
        print(f"  - {format_bulk_diagnostic(diagnostic)}")


def _read_explicit_bulk_file(raw_path: str, *, suffix: str) -> bytes | None:
    """Read one explicitly selected regular file with a strict bounded size."""

    if _is_back_text(raw_path):
        return None
    if not raw_path.strip():
        print("Error: A file path is required.")
        return b""

    normalized_path = raw_path.strip()
    if (
        len(normalized_path) >= 2
        and normalized_path[0] == normalized_path[-1]
        and normalized_path[0] in {"\"", "'"}
    ):
        normalized_path = normalized_path[1:-1].strip()
    path = Path(normalized_path).expanduser()
    if path.suffix.lower() != suffix:
        print(f"Error: Expected a {suffix} file: {path}")
        return b""
    try:
        if path.is_symlink():
            print(f"Error: Bulk input file must not be a symbolic link: {path}")
            return b""
        if not path.is_file():
            print(f"Error: Bulk input path is not a regular file: {path}")
            return b""
        size = path.stat().st_size
        if size == 0:
            print(f"Error: Bulk input file is empty: {path}")
            return b""
        if size > MAX_BULK_INPUT_BYTES:
            print(
                "Error: Bulk input file is too large "
                f"({size} bytes; maximum {MAX_BULK_INPUT_BYTES})."
            )
            return b""
        return path.read_bytes()
    except OSError as error:
        print(f"Error: Could not read bulk input file: {error}")
        return b""


def print_complete_answer_key_preview(answer_key: BulkAnswerKey) -> None:
    """Print every normalized answer; never truncate a pre-stage review."""

    print("Complete normalized answer key:")
    for question_number, answer in enumerate(answer_key.answers, start=1):
        print(f"  Q{question_number}: {answer}")


def print_complete_standards_preview(
    alignment: BulkStandardsAlignment,
) -> None:
    """Print profile identity and every normalized question alignment."""

    profile = alignment.standards_profile_id or "(none)"
    print(f"Standards profile: {profile}")
    print("Complete normalized standards alignment:")
    for question_number, standard_ids in enumerate(
        alignment.by_question,
        start=1,
    ):
        label = ", ".join(standard_ids) if standard_ids else "(unaligned)"
        print(f"  Q{question_number}: {label}")


def _confirm_use(prompt: str) -> bool:
    while True:
        confirmation = input(prompt).strip()
        if confirmation == "USE":
            return True
        if _is_back_text(confirmation):
            return False
        print("Type USE to stage this complete value, or BACK to cancel.")


def _per_question_answer_key(
    question_count: int,
    choices: Sequence[str],
) -> BulkAnswerKey | None:
    normalized_choices = tuple(choice.upper() for choice in choices)
    answers: list[str] = []
    for question_number in range(1, question_count + 1):
        while True:
            value = input(
                f"Q{question_number} answer "
                f"({'/'.join(normalized_choices)}; type BACK to cancel): "
            ).strip()
            if _is_back_text(value):
                return None
            answer = value.upper()
            if answer in normalized_choices:
                answers.append(answer)
                break
            print(f"Error: Answer must be one of {', '.join(normalized_choices)}.")
    return BulkAnswerKey(tuple(answers))


def _answer_method_from_menu() -> AnswerEntryMethod | None:
    while True:
        print("Answer-key entry method:")
        print("1. Paste complete key")
        print("2. Import answer-key CSV")
        print("3. Import answer-key JSON")
        print("4. Enter one question at a time")
        print_scoreform_navigation_options()
        selection = input("Select answer-key method: ").strip()
        if parse_scoreform_navigation(selection) is not None:
            return None
        methods: dict[str, AnswerEntryMethod] = {
            "1": "text",
            "2": "csv",
            "3": "json",
            "4": "per-question",
        }
        method = methods.get(selection)
        if method is not None:
            return method
        print(f"Invalid selection: {selection}.")
        print_invalid_navigation()
        print()


def prompt_answer_key_entry(
    *,
    question_count: int,
    choices: Sequence[str],
    forced_method: AnswerEntryMethod | None = None,
) -> BulkAnswerKey | None:
    """Collect, fully preview, and explicitly stage one complete answer key."""

    method = forced_method
    while True:
        if method is None:
            method = _answer_method_from_menu()
            if method is None:
                return None

        if method == "per-question":
            value = _per_question_answer_key(question_count, choices)
            if value is None:
                return None
            result: BulkParseResult[BulkAnswerKey] = BulkParseResult(value)
        elif method == "text":
            print(
                "Paste all answers in question order, separated by spaces or commas."
            )
            raw = input("Complete answer key (type BACK to cancel): ")
            if _is_back_text(raw):
                return None
            result = parse_answer_key_text(
                raw,
                question_count=question_count,
                choices=choices,
            )
        elif method == "csv":
            raw_path = input("Answer-key CSV path (type BACK to cancel): ").strip()
            data = _read_explicit_bulk_file(raw_path, suffix=".csv")
            if data is None:
                return None
            if not data:
                if forced_method is not None:
                    continue
                method = None
                continue
            result = parse_answer_key_csv(
                data,
                question_count=question_count,
                choices=choices,
            )
        else:
            raw_path = input("Answer-key JSON path (type BACK to cancel): ").strip()
            data = _read_explicit_bulk_file(raw_path, suffix=".json")
            if data is None:
                return None
            if not data:
                if forced_method is not None:
                    continue
                method = None
                continue
            result = parse_answer_key_json(
                data,
                question_count=question_count,
                choices=choices,
            )

        if not result.ok:
            _print_diagnostics(cast(BulkParseResult[object], result))
            print()
            if forced_method is None:
                method = None
            continue

        assert result.value is not None
        print()
        print_complete_answer_key_preview(result.value)
        print()
        if _confirm_use(
            "Type USE to stage this complete answer key, or BACK to cancel: "
        ):
            return result.value
        return None


def _choose_profile(
    library: StandardsLibrary,
    *,
    current_profile_id: str | None,
) -> str | None | Literal[False]:
    """Return profile id, None for explicit no-profile, or False for cancellation."""

    while True:
        print("Standards profile for this complete replacement:")
        if current_profile_id:
            print(f"1. Keep current profile: {current_profile_id}")
            print("2. Choose a different PDS Core profile")
            print("3. No profile (all questions must be unaligned)")
        else:
            print("1. Choose a PDS Core profile")
            print("2. No profile (all questions must be unaligned)")
        print_scoreform_navigation_options()
        selection = input("Select standards profile option: ").strip()
        if parse_scoreform_navigation(selection) is not None:
            return False

        if current_profile_id:
            if selection == "1":
                return current_profile_id
            if selection == "3":
                return None
            choose_new = selection == "2"
        else:
            if selection == "2":
                return None
            choose_new = selection == "1"

        if not choose_new:
            print("Invalid selection.")
            print_invalid_navigation()
            print()
            continue

        profiles = list_profiles_for_selection(library)
        if not profiles:
            print("No PDS Core standards profiles are available.")
            return False
        print("Available PDS Core standards profiles:")
        for index, profile in enumerate(profiles, start=1):
            print(f"{index}. {profile.label}")
        print_scoreform_navigation_options()
        profile_selection = input("Select profile: ").strip()
        if parse_scoreform_navigation(profile_selection) is not None:
            return False
        if not profile_selection.isdigit():
            print("Error: Select one profile by number.")
            continue
        index = int(profile_selection)
        if index < 1 or index > len(profiles):
            print("Error: Standards profile selection is out of range.")
            continue
        return profiles[index - 1].profile_id


def _alignment_method_from_menu() -> AlignmentEntryMethod | None:
    while True:
        print("Standards-alignment entry method:")
        print("1. Paste complete alignment")
        print("2. Import alignment CSV")
        print("3. Import alignment JSON")
        print_scoreform_navigation_options()
        selection = input("Select alignment method: ").strip()
        if parse_scoreform_navigation(selection) is not None:
            return None
        methods: dict[str, AlignmentEntryMethod] = {
            "1": "text",
            "2": "csv",
            "3": "json",
        }
        method = methods.get(selection)
        if method is not None:
            return method
        print(f"Invalid selection: {selection}.")
        print_invalid_navigation()
        print()


def prompt_standards_bulk_entry(
    *,
    question_count: int,
    standards_library: StandardsLibrary,
    current_profile_id: str | None = None,
    forced_method: AlignmentEntryMethod | None = None,
) -> BulkStandardsAlignment | None:
    """Collect, fully preview, and explicitly stage one complete alignment."""

    profile_id = _choose_profile(
        standards_library,
        current_profile_id=current_profile_id,
    )
    if profile_id is False:
        return None

    method = forced_method
    while True:
        if method is None:
            method = _alignment_method_from_menu()
            if method is None:
                return None

        if method == "text":
            print("Use groups such as '1-5 = standard_id; 6-10 = -'.")
            raw = input("Complete alignment (type BACK to cancel): ")
            if _is_back_text(raw):
                return None
            result = parse_alignment_text(
                raw,
                question_count=question_count,
                standards_profile_id=cast(str | None, profile_id),
                standards_library=standards_library,
            )
        elif method == "csv":
            raw_path = input("Alignment CSV path (type BACK to cancel): ").strip()
            data = _read_explicit_bulk_file(raw_path, suffix=".csv")
            if data is None:
                return None
            if not data:
                if forced_method is None:
                    method = None
                continue
            result = parse_alignment_csv(
                data,
                question_count=question_count,
                standards_profile_id=cast(str | None, profile_id),
                standards_library=standards_library,
            )
        else:
            raw_path = input("Alignment JSON path (type BACK to cancel): ").strip()
            data = _read_explicit_bulk_file(raw_path, suffix=".json")
            if data is None:
                return None
            if not data:
                if forced_method is None:
                    method = None
                continue
            result = parse_alignment_json(
                data,
                question_count=question_count,
                standards_profile_id=cast(str | None, profile_id),
                standards_library=standards_library,
            )

        if not result.ok:
            _print_diagnostics(cast(BulkParseResult[object], result))
            print()
            if forced_method is None:
                method = None
            continue

        assert result.value is not None
        print()
        print_complete_standards_preview(result.value)
        print()
        if _confirm_use(
            "Type USE to stage this complete standards alignment, or BACK to cancel: "
        ):
            return result.value
        return None


def print_complete_assignment_preview(
    assignment: Mapping[str, object],
    *,
    class_ids: Sequence[str] = (),
) -> None:
    """Print a complete assignment-definition preview before durable SAVE."""

    question_count = assignment.get("question_count")
    choices = assignment.get("choices")
    answer_key = assignment.get("answer_key")
    standards = assignment.get("standards")
    if (
        not isinstance(question_count, int)
        or isinstance(question_count, bool)
        or not isinstance(choices, list)
        or not isinstance(answer_key, Mapping)
        or not isinstance(standards, Mapping)
    ):
        raise ValueError("Assignment preview requires normalized assignment data.")

    print(f"assignment_id: {assignment.get('assignment_id')}")
    print(f"title: {assignment.get('title')}")
    if class_ids:
        print(f"classes: {', '.join(class_ids)}")
    print(f"layout: {assignment.get('layout_id')}")
    print(f"question_count: {question_count}")
    print(f"choices: {', '.join(cast(list[str], choices))}")
    profile = assignment.get("standards_profile_id")
    print(f"standards profile: {profile if profile is not None else '(none)'}")
    print("Complete answer key:")
    for question_number in range(1, question_count + 1):
        answer = answer_key.get(str(question_number), answer_key.get(question_number))
        print(f"  Q{question_number}: {answer}")
    print("Complete standards alignment:")
    for question_number in range(1, question_count + 1):
        values = standards.get(str(question_number), standards.get(question_number, []))
        if not isinstance(values, (list, tuple)):
            raise ValueError("Assignment standards preview is not normalized.")
        label = ", ".join(cast(Sequence[str], values)) if values else "(unaligned)"
        print(f"  Q{question_number}: {label}")


def assignment_uses_standards(assignment: Mapping[str, object]) -> bool:
    """Return whether current Core standards data is required for validation."""

    if assignment.get("standards_profile_id") is not None:
        return True
    standards = assignment.get("standards")
    return isinstance(standards, Mapping) and any(bool(values) for values in standards.values())


__all__ = [
    "MAX_BULK_INPUT_BYTES",
    "assignment_uses_standards",
    "print_complete_answer_key_preview",
    "print_complete_assignment_preview",
    "print_complete_standards_preview",
    "prompt_answer_key_entry",
    "prompt_standards_bulk_entry",
]
