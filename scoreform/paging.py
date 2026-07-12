"""Layout-aware answer-sheet page math."""

from scoreform.config import MAX_ASSIGNMENT_QUESTION_COUNT
from scoreform.layouts import AnswerSheetLayout, get_layout


def page_count_for_question_count(
    question_count: int, layout: AnswerSheetLayout | None = None
) -> int:
    if (
        isinstance(question_count, bool)
        or not isinstance(question_count, int)
        or question_count < 1
        or question_count > MAX_ASSIGNMENT_QUESTION_COUNT
    ):
        raise ValueError(
            "question_count must be an integer between 1 and "
            f"{MAX_ASSIGNMENT_QUESTION_COUNT}."
        )
    capacity = get_layout() if layout is None else layout
    return (question_count + capacity.questions_per_page - 1) // capacity.questions_per_page


def question_range_for_page(
    page_number: int,
    question_count: int,
    layout: AnswerSheetLayout | None = None,
) -> tuple[int, int]:
    resolved = get_layout() if layout is None else layout
    page_count = page_count_for_question_count(question_count, resolved)
    if (
        isinstance(page_number, bool)
        or not isinstance(page_number, int)
        or page_number < 1
        or page_number > page_count
    ):
        raise ValueError(f"page_number must be an integer between 1 and {page_count}.")
    start = (page_number - 1) * resolved.questions_per_page + 1
    return start, min(start + resolved.questions_per_page - 1, question_count)


def question_count_for_page(
    page_number: int,
    question_count: int,
    layout: AnswerSheetLayout | None = None,
) -> int:
    start, end = question_range_for_page(page_number, question_count, layout)
    return end - start + 1
