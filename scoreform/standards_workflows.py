"""Assignment-local standards workflow helpers."""


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


def attach_standard_to_questions(
    standards_by_question,
    *,
    standard_id,
    question_numbers,
    question_count,
):
    """Return assignment-local standards alignment with standard_id attached."""
    updated = initialize_empty_standards_alignment(question_count)
    for question_key, standards in standards_by_question.items():
        q_num = int(question_key)
        if q_num < 1 or q_num > question_count:
            raise ValueError(f"Question number out of range: {q_num}")
        updated[str(q_num)] = [
            standard.strip()
            for standard in standards
            if isinstance(standard, str) and standard.strip()
        ]

    normalized_standard_id = standard_id.strip()
    if not normalized_standard_id:
        raise ValueError("standard_id is required.")

    for question_number in question_numbers:
        if question_number < 1 or question_number > question_count:
            raise ValueError(f"Question number out of range: {question_number}")
        standards = updated[str(question_number)]
        if normalized_standard_id not in standards:
            standards.append(normalized_standard_id)

    return updated


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
