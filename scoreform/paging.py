"""Page math for the fixed 15-question physical answer-sheet layout."""

from scoreform.config import MAX_ASSIGNMENT_QUESTION_COUNT, QUESTIONS_PER_PAGE


def page_count_for_question_count(question_count: int) -> int:
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
    return (question_count + QUESTIONS_PER_PAGE - 1) // QUESTIONS_PER_PAGE


def question_range_for_page(page_number: int, question_count: int) -> tuple[int, int]:
    page_count = page_count_for_question_count(question_count)
    if (
        isinstance(page_number, bool)
        or not isinstance(page_number, int)
        or page_number < 1
        or page_number > page_count
    ):
        raise ValueError(f"page_number must be an integer between 1 and {page_count}.")
    start = (page_number - 1) * QUESTIONS_PER_PAGE + 1
    return start, min(start + QUESTIONS_PER_PAGE - 1, question_count)


def question_count_for_page(page_number: int, question_count: int) -> int:
    start, end = question_range_for_page(page_number, question_count)
    return end - start + 1
