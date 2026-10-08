"""Issue #225 Slice 2: verify physical QR size and header collision guards."""

from dataclasses import replace

import numpy as np
import pytest

from scoreform.layouts import get_layout, supported_layout_ids
from scoreform.qr_print_baseline import measure_qr_print_baseline
from scoreform.scoring import _expected_qr_crop_candidates
from scoreform.templates import (
    HEADER_QUESTION_CLEARANCE,
    HEADER_TEXT_CLEARANCE,
    header_text_bounds,
    plan_answer_sheet_header,
    rectangles_overlap,
)

PAGE_ID = "pg_0123456789abcdef0123456789abcdef"
ROUTE_ID = "rt_fedcba9876543210fedcba9876543210"


def _plan(layout):
    return plan_answer_sheet_header(
        assignment_title="Issue 225 Printing Qualification",
        student_name="Synthetic, Student",
        student_id="synthetic1",
        class_id="english_12_pd4",
        period="4",
        logical_page=1,
        total_pages=1,
        question_start=1,
        question_end=layout.questions_per_page,
        page_id=PAGE_ID,
        route_id=ROUTE_ID,
        layout=layout,
    )


@pytest.mark.parametrize("layout_id", supported_layout_ids())
def test_enlarged_qr_square_and_module_pitch(layout_id):
    layout = get_layout(layout_id)
    profile = measure_qr_print_baseline(
        layout, "PDS2|m=scoreform|c=english_12_pd4|w=locke|r=" + ROUTE_ID
    )
    assert layout.qr_size == 145
    assert layout.qr_y == 185
    assert profile.size_points == pytest.approx(69.6)
    assert 0.95 <= profile.size_inches <= 1.0
    assert profile.border_modules == 4
    assert profile.module_points > 0


@pytest.mark.parametrize("layout_id", supported_layout_ids())
def test_qr_and_header_keep_full_identifiers_and_safe_separation(layout_id):
    layout = get_layout(layout_id)
    plan = _plan(layout)
    qr = plan.qr_rectangle
    assert qr.right - qr.left == pytest.approx(69.6)
    assert qr.top - qr.bottom == pytest.approx(69.6)
    assert qr.left == pytest.approx(950 * layout.pdf_scale)
    assert qr.top == pytest.approx(layout.pdf_height - 185 * layout.pdf_scale)
    # The pre-change title baseline is retained; it no longer tracks QR height.
    assert plan.title_runs[0].baseline_y == pytest.approx(
        layout.pdf_height - 220 * layout.pdf_scale
    )
    assert tuple(item.text for item in plan.identifier_runs) == (
        f"Sheet ID: {PAGE_ID}",
        f"Route ID: {ROUTE_ID}",
    )
    assert all(item.font_size >= 6.5 for item in plan.identifier_runs)
    for registration in plan.registration_rectangles:
        assert not rectangles_overlap(qr, registration, clearance=HEADER_TEXT_CLEARANCE)
    assert not rectangles_overlap(
        qr, plan.first_question_boundary, clearance=HEADER_QUESTION_CLEARANCE
    )
    for item in plan.text_runs:
        assert not rectangles_overlap(
            qr, header_text_bounds(item), clearance=HEADER_TEXT_CLEARANCE
        )
    for item in plan.identifier_runs:
        assert (
            header_text_bounds(item).bottom
            >= plan.first_question_boundary.top + HEADER_QUESTION_CLEARANCE
        )


@pytest.mark.parametrize("layout_id", supported_layout_ids())
def test_enlarged_qr_remains_fully_inside_existing_tight_scan_crop(layout_id):
    layout = get_layout(layout_id)
    image = np.zeros((layout.img_height, layout.img_width), dtype=np.uint8)
    x, y, size = layout.qr_x, layout.qr_y, layout.qr_size
    image[y : y + size, x : x + size] = 255
    crops = dict(_expected_qr_crop_candidates(image))
    assert "tight" in crops
    assert np.count_nonzero(crops["tight"]) == size * size


@pytest.mark.parametrize("layout_id", supported_layout_ids())
def test_qr_symbol_collision_with_question_region_is_rejected(layout_id):
    layout = replace(get_layout(layout_id), qr_y=360)
    with pytest.raises(ValueError, match="QR symbol and questions"):
        _plan(layout)


@pytest.mark.parametrize("layout_id", supported_layout_ids())
def test_qr_symbol_collision_with_registration_mark_is_rejected(layout_id):
    layout = get_layout(layout_id)
    x, y = layout.registration_marks[1]
    overlapping = replace(layout, qr_x=x, qr_y=y)
    with pytest.raises(ValueError, match="QR symbol and registration mark"):
        _plan(overlapping)


@pytest.mark.parametrize("layout_id", supported_layout_ids())
def test_qr_symbol_outside_page_is_rejected(layout_id):
    layout = replace(get_layout(layout_id), qr_x=1200)
    with pytest.raises(ValueError, match="QR symbol falls outside"):
        _plan(layout)
