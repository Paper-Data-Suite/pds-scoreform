import numpy as np
import pytest

from scoreform.config import (
    CORNERS,
    DST_PTS,
    IMG_HEIGHT,
    IMG_WIDTH,
    PDF_HEIGHT,
    PDF_WIDTH,
)
from scoreform.layouts import (
    DEFAULT_LAYOUT_ID,
    get_layout,
    is_supported_layout_id,
    require_layout,
    supported_layout_ids,
)
from scoreform.paging import page_count_for_question_count, question_range_for_page


def test_standard_layout_registry_and_geometry():
    layout = get_layout()
    assert DEFAULT_LAYOUT_ID == "standard_15q_abcd_v1"
    assert supported_layout_ids() == (DEFAULT_LAYOUT_ID,)
    assert is_supported_layout_id(DEFAULT_LAYOUT_ID)
    assert not is_supported_layout_id(None)
    assert layout.layout_id == DEFAULT_LAYOUT_ID
    assert layout.display_name == "Standard 15-question A-D"
    assert layout.questions_per_page == 15
    assert layout.choices == ("A", "B", "C", "D")
    assert (layout.img_width, layout.img_height) == (IMG_WIDTH, IMG_HEIGHT)
    assert (layout.pdf_width, layout.pdf_height) == (PDF_WIDTH, PDF_HEIGHT)
    assert layout.registration_marks == tuple(CORNERS)
    assert np.array_equal(layout.dst_points, DST_PTS)
    assert len(layout.registration_marks) == 4
    assert len(layout.question_slots) == 15
    assert all(tuple(box.choice for box in slot.boxes) == layout.choices for slot in layout.question_slots)


@pytest.mark.parametrize("layout_id", ["compact_25q_abcd_v1", "", 1, None])
def test_require_layout_rejects_invalid_ids(layout_id):
    with pytest.raises(ValueError):
        require_layout(layout_id)


def test_page_math_accepts_layout_object():
    layout = get_layout(DEFAULT_LAYOUT_ID)
    assert page_count_for_question_count(16, layout) == 2
    assert question_range_for_page(2, 16, layout) == (16, 16)
