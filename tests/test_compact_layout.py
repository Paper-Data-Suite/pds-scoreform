import cv2
import numpy as np
import pytest

from scoreform import templates
from scoreform.layouts import get_layout
from scoreform.migration import ScoreFormMigrationPendingError
from scoreform.scoring import score_image


class RecordingCanvas:
    def __init__(self):
        self.text = []
        self.payloads = []

    def setFont(self, *_args):
        pass

    def setLineWidth(self, *_args):
        pass

    def rect(self, *_args, **_kwargs):
        pass

    def drawImage(self, *_args):
        pass

    def drawString(self, _x, _y, value):
        self.text.append(value)


def _compact_assignment(question_count=50):
    return {
        "assignment_id": "compact_quiz",
        "title": "Compact Quiz",
        "question_count": question_count,
        "choices": ["A", "B", "C", "D"],
        "layout_id": "compact_25q_abcd_v1",
    }


def test_compact_second_page_renders_global_question_labels(monkeypatch):
    canvas = RecordingCanvas()
    student = {"class_id": "class1", "student_id": "1001"}

    with pytest.raises(ScoreFormMigrationPendingError, match=r"#141"):
        templates.draw_student_answer_sheet_page(
            canvas, _compact_assignment(), student, 2
        )


def test_compact_synthetic_page_scores_both_columns(tmp_path):
    layout = get_layout("compact_25q_abcd_v1")
    image = np.full(
        (layout.img_height, layout.img_width, 3), 255, dtype=np.uint8
    )
    for x, y in layout.registration_marks:
        cv2.rectangle(
            image,
            (x, y),
            (x + layout.registration_size, y + layout.registration_size),
            (0, 0, 0),
            -1,
        )

    answer_key = {}
    for index, slot in enumerate(layout.question_slots):
        answer = layout.choices[index % len(layout.choices)]
        answer_key[index + 26] = answer
        for box in slot.boxes:
            cv2.rectangle(
                image,
                (box.x, box.y),
                (box.x + box.size, box.y + box.size),
                (0, 0, 0),
                2,
            )
            if box.choice == answer:
                cv2.rectangle(
                    image,
                    (box.x + 6, box.y + 6),
                    (box.x + box.size - 6, box.y + box.size - 6),
                    (0, 0, 0),
                    -1,
                )

    result = score_image(
        image,
        answer_key,
        page_num=2,
        debug_dir=tmp_path,
        question_count=25,
        question_start=26,
        layout=layout,
    )

    assert result is not None
    assert result["score"] == 25
    assert result["total_points"] == 25
    assert [answer["Q"] for answer in result["answers"]] == list(range(26, 51))
