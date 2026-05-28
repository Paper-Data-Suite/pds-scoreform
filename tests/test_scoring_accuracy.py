import cv2
import numpy as np

from scoreform.config import (
    BOX_SIZE,
    BOX_START_X,
    BOX_STEP_X,
    CORNER_SIZE,
    CORNERS,
    IMG_HEIGHT,
    IMG_WIDTH,
    Q_START_Y,
    Q_STEP_Y,
)
from scoreform.scoring import score_image


CHOICES = ["A", "B", "C", "D"]


def _draw_synthetic_answer_sheet(marked_answers, question_count):
    """Build a clean synthetic sheet using the production template geometry."""
    img = np.ones((IMG_HEIGHT, IMG_WIDTH, 3), dtype=np.uint8) * 255

    for x, y in CORNERS:
        cv2.rectangle(
            img,
            (x, y),
            (x + CORNER_SIZE, y + CORNER_SIZE),
            (0, 0, 0),
            -1,
        )

    for question_index in range(question_count):
        y = Q_START_Y + question_index * Q_STEP_Y

        for choice_index, letter in enumerate(CHOICES):
            x = BOX_START_X + choice_index * BOX_STEP_X
            cv2.rectangle(
                img,
                (x, y),
                (x + BOX_SIZE, y + BOX_SIZE),
                (0, 0, 0),
                2,
            )

            if marked_answers[question_index + 1] == letter:
                cv2.rectangle(
                    img,
                    (x + 6, y + 6),
                    (x + BOX_SIZE - 6, y + BOX_SIZE - 6),
                    (0, 0, 0),
                    -1,
                )

    return img


def test_score_image_detects_synthetic_marked_answers(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    question_count = 10
    answer_key = {
        1: "A",
        2: "B",
        3: "C",
        4: "D",
        5: "A",
        6: "B",
        7: "C",
        8: "D",
        9: "A",
        10: "B",
    }
    marked_answers = {
        1: "A",
        2: "B",
        3: "D",
        4: "D",
        5: "C",
        6: "B",
        7: "C",
        8: "A",
        9: "A",
        10: "D",
    }

    image = _draw_synthetic_answer_sheet(marked_answers, question_count)
    result = score_image(
        image,
        answer_key,
        page_num=1,
        debug_dir=tmp_path / "debug",
        question_count=question_count,
    )

    assert result is not None
    assert result["total_points"] == 10
    assert result["score"] == 6
    assert len(result["answers"]) == 10

    for answer in result["answers"]:
        q_num = answer["Q"]
        expected_answer = marked_answers[q_num]

        assert answer["Answer"] == expected_answer
        assert answer["Correct"] == (expected_answer == answer_key[q_num])
