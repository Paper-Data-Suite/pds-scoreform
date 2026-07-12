import pytest

from scoreform.paging import (
    page_count_for_question_count,
    question_count_for_page,
    question_range_for_page,
)


@pytest.mark.parametrize(
    ("questions", "pages"),
    [(1, 1), (15, 1), (16, 2), (30, 2), (31, 3), (75, 5)],
)
def test_page_count_boundaries(questions, pages):
    assert page_count_for_question_count(questions) == pages


@pytest.mark.parametrize("page", [0, 3])
def test_question_range_rejects_invalid_page(page):
    with pytest.raises(ValueError):
        question_range_for_page(page, 16)


def test_partial_final_page_math():
    assert question_range_for_page(1, 16) == (1, 15)
    assert question_range_for_page(2, 16) == (16, 16)
    assert question_range_for_page(3, 32) == (31, 32)
    assert question_count_for_page(3, 32) == 2
