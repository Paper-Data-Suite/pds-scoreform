"""Build shared standards usage events from ScoreForm assignment metadata."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime

from pds_core.standards import StandardUsageEvent


def build_standard_usage_events_from_assignment_standards(
    *,
    assignment_id: str,
    standards_by_question: Mapping[int, Iterable[str]],
    school_year: str,
    class_id: str,
    used_at: datetime,
    event_id_prefix: str,
    usage_type: str = "assessed",
) -> tuple[StandardUsageEvent, ...]:
    """Build pds-core standards usage events from ScoreForm assignment alignment."""
    standards_to_questions: dict[str, set[int]] = {}

    for question_number, standards in standards_by_question.items():
        _validate_question_number(question_number)
        question_standards = _normalize_question_standards(
            standards,
            question_number=question_number,
        )

        for standard_id in question_standards:
            standards_to_questions.setdefault(standard_id, set()).add(question_number)

    events = []
    for index, standard_id in enumerate(sorted(standards_to_questions), start=1):
        events.append(
            StandardUsageEvent(
                event_id=f"{event_id_prefix}_{index:03d}",
                standard_id=standard_id,
                school_year=school_year,
                class_id=class_id,
                module="pds-scoreform",
                usage_type=usage_type,
                used_at=used_at,
                assignment_id=assignment_id,
                metadata={
                    "question_numbers": sorted(standards_to_questions[standard_id]),
                },
            )
        )

    return tuple(events)


def _validate_question_number(question_number: object) -> None:
    if (
        isinstance(question_number, bool)
        or not isinstance(question_number, int)
        or question_number < 1
    ):
        raise ValueError(
            f"question number must be a positive integer: {question_number!r}"
        )


def _normalize_question_standards(
    standards: object,
    *,
    question_number: int,
) -> set[str]:
    if isinstance(standards, (str, bytes)) or standards is None:
        raise ValueError(
            f"standards for question {question_number} must be an iterable of strings"
        )

    try:
        standards_entries = tuple(standards)  # type: ignore[arg-type]
    except TypeError as error:
        raise ValueError(
            f"standards for question {question_number} must be an iterable of strings"
        ) from error

    normalized = set()
    for standard in standards_entries:
        if not isinstance(standard, str):
            raise ValueError(
                f"standard for question {question_number} must be a string"
            )

        standard_id = standard.strip()
        if not standard_id:
            raise ValueError(
                f"standard for question {question_number} must not be blank"
            )

        normalized.add(standard_id)

    return normalized
