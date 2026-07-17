from itertools import combinations

import pytest

from scoreform.layouts import get_layout
from scoreform.templates import (
    HEADER_QUESTION_CLEARANCE,
    HEADER_TEXT_CLEARANCE,
    AnswerSheetHeaderPlan,
    PdfRectangle,
    header_text_bounds,
    plan_answer_sheet_header,
    rectangles_overlap,
)

PHYSICAL_TITLE = "ScoreForm v0.9.1 Physical Acceptance"
PAGE_ID = "pg_0123456789abcdef0123456789abcdef"
ROUTE_ID = "rt_fedcba9876543210fedcba9876543210"


def _inside(inner: PdfRectangle, outer: PdfRectangle) -> bool:
    return (
        inner.left >= outer.left
        and inner.bottom >= outer.bottom
        and inner.right <= outer.right
        and inner.top <= outer.top
    )


def _assert_clear(
    first: PdfRectangle,
    second: PdfRectangle,
    clearance: float = HEADER_TEXT_CLEARANCE,
) -> None:
    assert not rectangles_overlap(first, second, clearance=clearance)


def _make_plan(
    layout_id: str,
    question_count: int,
    logical_page: int,
    *,
    title: str = PHYSICAL_TITLE,
    student_name: str = "Synthetic, Student",
    class_id: str = "physical_acceptance",
) -> AnswerSheetHeaderPlan:
    layout = get_layout(layout_id)
    total_pages = (question_count + layout.questions_per_page - 1) // (
        layout.questions_per_page
    )
    question_start = (logical_page - 1) * layout.questions_per_page + 1
    question_end = min(
        logical_page * layout.questions_per_page, question_count
    )
    return plan_answer_sheet_header(
        assignment_title=title,
        student_name=student_name,
        student_id="synthetic1",
        class_id=class_id,
        period="1",
        logical_page=logical_page,
        total_pages=total_pages,
        question_start=question_start,
        question_end=question_end,
        page_id=PAGE_ID,
        route_id=ROUTE_ID,
        layout=layout,
    )


def _assert_header_geometry(plan: AnswerSheetHeaderPlan) -> None:
    title_bounds = tuple(map(header_text_bounds, plan.title_runs))
    metadata_bounds = tuple(map(header_text_bounds, plan.left_metadata_runs))
    context_bounds = tuple(map(header_text_bounds, plan.page_context_runs))
    identifier_bounds = tuple(map(header_text_bounds, plan.identifier_runs))
    all_bounds = title_bounds + metadata_bounds + context_bounds + identifier_bounds

    for bounds in title_bounds:
        assert _inside(bounds, plan.left_column)
        for context in context_bounds:
            _assert_clear(bounds, context)
        _assert_clear(bounds, plan.qr_rectangle)

    for first, second in combinations(metadata_bounds, 2):
        _assert_clear(first, second)
    for first, second in combinations(identifier_bounds, 2):
        _assert_clear(first, second)
    for identifier in identifier_bounds:
        for metadata in metadata_bounds:
            _assert_clear(identifier, metadata)
        for context in context_bounds:
            _assert_clear(identifier, context)
        _assert_clear(identifier, plan.qr_rectangle)

    for bounds in all_bounds:
        assert _inside(bounds, plan.page_bounds)
        _assert_clear(
            bounds,
            plan.first_question_boundary,
            HEADER_QUESTION_CLEARANCE,
        )
        for registration in plan.registration_rectangles:
            _assert_clear(bounds, registration)

    assert tuple(run.text for run in plan.identifier_runs) == (
        f"Sheet ID: {PAGE_ID}",
        f"Route ID: {ROUTE_ID}",
    )
    assert all(run.font_size >= 6.5 for run in plan.identifier_runs)


@pytest.mark.parametrize(
    ("layout_id", "question_count", "output_kind"),
    (
        ("standard_15q_abcd_v1", 15, "individual"),
        ("standard_15q_abcd_v1", 30, "individual"),
        ("standard_15q_abcd_v1", 30, "class_packet"),
        ("compact_25q_abcd_v1", 25, "individual"),
        ("compact_25q_abcd_v1", 50, "individual"),
        ("compact_25q_abcd_v1", 50, "class_packet"),
    ),
)
def test_header_geometry_for_every_output_page(
    layout_id: str, question_count: int, output_kind: str
) -> None:
    layout = get_layout(layout_id)
    total_pages = (question_count + layout.questions_per_page - 1) // (
        layout.questions_per_page
    )
    student_names = ("Synthetic, Student",)
    if output_kind == "class_packet":
        student_names += ("Rivera-Santos, Jordan",)

    for student_name in student_names:
        for logical_page in range(1, total_pages + 1):
            plan = _make_plan(
                layout_id,
                question_count,
                logical_page,
                student_name=student_name,
            )
            _assert_header_geometry(plan)
            assert " ".join(run.text for run in plan.title_runs) == (
                f"Assignment: {PHYSICAL_TITLE}"
            )
            assert "\N{HORIZONTAL ELLIPSIS}" not in "".join(
                run.text for run in plan.title_runs
            )


def test_long_title_wraps_or_reduces_without_leaving_left_column() -> None:
    title = (
        "Long Validated District Benchmark Assignment for Semester Two "
        "Mathematics Review"
    )
    plan = _make_plan("standard_15q_abcd_v1", 30, 2, title=title)

    _assert_header_geometry(plan)
    assert len(plan.title_runs) == 2
    assert all(10.0 <= run.font_size <= 14.0 for run in plan.title_runs)


def test_long_valid_student_and_class_metadata_remain_complete() -> None:
    student_name = "Montgomery-Worthington, Alexandra-Catherine"
    class_id = "advanced_physical_sciences_section_12"
    plan = _make_plan(
        "compact_25q_abcd_v1",
        50,
        2,
        student_name=student_name,
        class_id=class_id,
    )

    _assert_header_geometry(plan)
    assert tuple(run.text for run in plan.left_metadata_runs) == (
        f"Student: {student_name}",
        "ID: synthetic1",
        f"Class: {class_id}",
        "Period: 1",
    )


def test_extreme_title_uses_deterministic_final_line_ellipsis() -> None:
    title = " ".join(["extraordinary"] * 30)

    first = _make_plan("standard_15q_abcd_v1", 15, 1, title=title)
    second = _make_plan("standard_15q_abcd_v1", 15, 1, title=title)

    _assert_header_geometry(first)
    assert first == second
    assert len(first.title_runs) == 2
    assert first.title_runs[-1].text.endswith("\N{HORIZONTAL ELLIPSIS}")
    assert all(run.font_size == 10.0 for run in first.title_runs)
