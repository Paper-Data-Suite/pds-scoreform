"""Assignment-local standards workflow helpers."""

from collections.abc import Sequence

from pds_core.standards_selection import StandardSelectionItem


def initialize_empty_standards_alignment(question_count):
    """Return empty assignment-local standards alignment for each question."""
    return {str(i): [] for i in range(1, question_count + 1)}


def parse_question_selection(selection_text, question_count):
    """Parse comma-separated question numbers for standards alignment."""
    if not selection_text or not selection_text.strip():
        raise ValueError("Select at least one question.")

    selected = []
    seen = set()
    for raw_part in selection_text.split(","):
        part = raw_part.strip()
        if not part:
            raise ValueError("Question selections cannot be empty.")
        if not part.isdigit():
            raise ValueError(f"Invalid question selection: {part}")

        question_number = int(part)
        if question_number < 1 or question_number > question_count:
            raise ValueError(
                f"Question selection out of range: {question_number}"
            )
        if question_number in seen:
            continue

        seen.add(question_number)
        selected.append(question_number)

    if not selected:
        raise ValueError("Select at least one question.")

    return tuple(selected)


def parse_standard_selection(
    selection_text: str,
    available_standards: Sequence[StandardSelectionItem],
) -> tuple[str, ...]:
    """Resolve comma-separated display numbers to durable standard IDs."""
    if not selection_text or not selection_text.strip():
        raise ValueError("Select at least one standard.")

    selected: list[str] = []
    seen: set[int] = set()
    for raw_part in selection_text.split(","):
        part = raw_part.strip()
        if not part:
            raise ValueError("Standard selections cannot be empty.")
        if not part.isdigit():
            raise ValueError(f"Invalid standard selection: {part}")
        selection_number = int(part)
        if selection_number < 1 or selection_number > len(available_standards):
            raise ValueError(f"Standard selection out of range: {selection_number}")
        if selection_number in seen:
            raise ValueError(f"Duplicate standard selection: {selection_number}")
        seen.add(selection_number)
        selected.append(available_standards[selection_number - 1].standard_id)
    return tuple(selected)


def attach_standards_to_questions(
    standards_by_question,
    *,
    standard_ids,
    question_numbers,
    question_count,
):
    """Attach each selected standard to each selected question."""
    updated = initialize_empty_standards_alignment(question_count)
    for question_key, standards in standards_by_question.items():
        try:
            q_num = int(question_key)
        except (TypeError, ValueError) as error:
            raise ValueError(f"Invalid question number: {question_key!r}") from error
        if q_num < 1 or q_num > question_count:
            raise ValueError(f"Question number out of range: {q_num}")
        normalized: list[str] = []
        for standard in standards:
            if isinstance(standard, str) and standard.strip():
                standard_id = standard.strip()
                if standard_id not in normalized:
                    normalized.append(standard_id)
        updated[str(q_num)] = normalized

    normalized_ids: list[str] = []
    for standard_id in standard_ids:
        if not isinstance(standard_id, str) or not standard_id.strip():
            raise ValueError("standard_ids must contain non-empty strings.")
        value = standard_id.strip()
        if value not in normalized_ids:
            normalized_ids.append(value)
    if not normalized_ids:
        raise ValueError("Select at least one standard.")

    for question_number in question_numbers:
        if question_number < 1 or question_number > question_count:
            raise ValueError(f"Question number out of range: {question_number}")
        for standard_id in normalized_ids:
            if standard_id not in updated[str(question_number)]:
                updated[str(question_number)].append(standard_id)
    return updated


def attach_standard_to_questions(
    standards_by_question,
    *,
    standard_id,
    question_numbers,
    question_count,
):
    """Return assignment-local standards alignment with standard_id attached."""
    return attach_standards_to_questions(
        standards_by_question,
        standard_ids=(standard_id,),
        question_numbers=question_numbers,
        question_count=question_count,
    )


def standards_sort_key(definition):
    return (
        definition.source.lower(),
        definition.code.lower(),
        definition.standard_id.lower(),
    )


def format_standard_for_selection(definition):
    """Return compact teacher-readable text for a shared standard."""
    pieces = [
        definition.standard_id,
        definition.code,
        definition.short_name,
    ]
    if definition.subject:
        pieces.append(definition.subject)
    if definition.domain:
        pieces.append(definition.domain)
    return " | ".join(pieces)
