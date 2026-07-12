"""Static registry for versioned answer-sheet layouts."""

from dataclasses import dataclass

import numpy as np

from scoreform.config import (
    BOX_SIZE,
    BOX_START_X,
    BOX_STEP_X,
    CORNER_SIZE,
    CORNERS,
    DST_PTS,
    IMG_HEIGHT,
    IMG_WIDTH,
    PDF_HEIGHT,
    PDF_WIDTH,
    Q_START_Y,
    Q_STEP_Y,
    QUESTIONS_PER_PAGE,
)

DEFAULT_LAYOUT_ID = "standard_15q_abcd_v1"


@dataclass(frozen=True)
class ChoiceBox:
    choice: str
    x: int
    y: int
    size: int


@dataclass(frozen=True)
class QuestionSlot:
    row_index: int
    label_x: int
    label_y: int
    y: int
    boxes: tuple[ChoiceBox, ...]


@dataclass(frozen=True)
class AnswerSheetLayout:
    layout_id: str
    display_name: str
    choices: tuple[str, ...]
    questions_per_page: int
    img_width: int
    img_height: int
    pdf_width: int
    pdf_height: int
    registration_marks: tuple[tuple[int, int], ...]
    registration_size: int
    dst_points: np.ndarray
    qr_x: int
    qr_y: int
    qr_size: int
    question_slots: tuple[QuestionSlot, ...]
    page_context_x: int
    page_context_y: int
    choice_label_offset: int = 15
    question_font_size: int = 12
    choice_font_size: int = 12
    mark_inset: int = 5
    strong_mark_fill_ratio: float = 0.30
    possible_secondary_fill_ratio: float = 0.15
    possible_secondary_relative_ratio: float = 0.20

    @property
    def pdf_scale(self) -> float:
        return self.pdf_width / self.img_width


def _standard_question_slots() -> tuple[QuestionSlot, ...]:
    choices = ("A", "B", "C", "D")
    return tuple(
        QuestionSlot(
            row_index=row_index,
            label_x=150,
            label_y=y + 25,
            y=y,
            boxes=tuple(
                ChoiceBox(choice, BOX_START_X + index * BOX_STEP_X, y, BOX_SIZE)
                for index, choice in enumerate(choices)
            ),
        )
        for row_index in range(QUESTIONS_PER_PAGE)
        for y in (Q_START_Y + row_index * Q_STEP_Y,)
    )


STANDARD_15Q_ABCD_V1 = AnswerSheetLayout(
    layout_id=DEFAULT_LAYOUT_ID,
    display_name="Standard 15-question A-D",
    choices=("A", "B", "C", "D"),
    questions_per_page=QUESTIONS_PER_PAGE,
    img_width=IMG_WIDTH,
    img_height=IMG_HEIGHT,
    pdf_width=PDF_WIDTH,
    pdf_height=PDF_HEIGHT,
    registration_marks=tuple(CORNERS),
    registration_size=CORNER_SIZE,
    dst_points=DST_PTS.copy(),
    qr_x=950,
    qr_y=220,
    qr_size=100,
    question_slots=_standard_question_slots(),
    page_context_x=760,
    page_context_y=260,
)


def _compact_question_slots() -> tuple[QuestionSlot, ...]:
    choices = ("A", "B", "C", "D")
    slots = []
    for row_index in range(25):
        column = 0 if row_index < 13 else 1
        column_row = row_index if column == 0 else row_index - 13
        y = 400 + column_row * 80
        label_x = 150 + column * 540
        box_start_x = 215 + column * 540
        slots.append(
            QuestionSlot(
                row_index=row_index,
                label_x=label_x,
                label_y=y + 25,
                y=y,
                boxes=tuple(
                    ChoiceBox(choice, box_start_x + index * 75, y, 30)
                    for index, choice in enumerate(choices)
                ),
            )
        )
    return tuple(slots)


COMPACT_25Q_ABCD_V1 = AnswerSheetLayout(
    layout_id="compact_25q_abcd_v1",
    display_name="Compact 25-question A-D",
    choices=("A", "B", "C", "D"),
    questions_per_page=25,
    img_width=IMG_WIDTH,
    img_height=IMG_HEIGHT,
    pdf_width=PDF_WIDTH,
    pdf_height=PDF_HEIGHT,
    registration_marks=tuple(CORNERS),
    registration_size=CORNER_SIZE,
    dst_points=DST_PTS.copy(),
    qr_x=950,
    qr_y=220,
    qr_size=100,
    question_slots=_compact_question_slots(),
    page_context_x=760,
    page_context_y=260,
    choice_label_offset=8,
    question_font_size=10,
    choice_font_size=9,
)


_LAYOUTS = {
    DEFAULT_LAYOUT_ID: STANDARD_15Q_ABCD_V1,
    COMPACT_25Q_ABCD_V1.layout_id: COMPACT_25Q_ABCD_V1,
}


def supported_layout_ids() -> tuple[str, ...]:
    return tuple(_LAYOUTS)


def is_supported_layout_id(layout_id: object) -> bool:
    return isinstance(layout_id, str) and layout_id in _LAYOUTS


def require_layout(layout_id: object) -> AnswerSheetLayout:
    if not isinstance(layout_id, str) or not layout_id.strip():
        raise ValueError("layout_id must be a non-empty string.")
    try:
        return _LAYOUTS[layout_id]
    except KeyError as error:
        raise ValueError(f"Unsupported layout_id '{layout_id}'.") from error


def get_layout(layout_id: str | None = None) -> AnswerSheetLayout:
    return require_layout(DEFAULT_LAYOUT_ID if layout_id is None else layout_id)
