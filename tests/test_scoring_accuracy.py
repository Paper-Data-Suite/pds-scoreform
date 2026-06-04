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
from scoreform.scoring import (
    _expected_corner_regions,
    _find_registration_mark_centers,
    non_overwriting_path,
    score_image,
)


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


def test_non_overwriting_path_returns_missing_path_unchanged(tmp_path):
    path = tmp_path / "debug_corners_page_1.png"

    assert non_overwriting_path(path) == str(path)


def test_non_overwriting_path_adds_suffix_for_existing_path(tmp_path):
    path = tmp_path / "debug_corners_page_1.png"
    path.write_text("existing", encoding="utf-8")

    assert non_overwriting_path(path) == str(tmp_path / "debug_corners_page_1_2.png")


def test_non_overwriting_path_skips_existing_suffixes(tmp_path):
    path = tmp_path / "debug_warped_page_1.png"
    path.write_text("existing", encoding="utf-8")
    (tmp_path / "debug_warped_page_1_2.png").write_text("existing", encoding="utf-8")
    (tmp_path / "debug_warped_page_1_3.png").write_text("existing", encoding="utf-8")

    assert non_overwriting_path(path) == str(tmp_path / "debug_warped_page_1_4.png")


def test_non_overwriting_path_preserves_extension_and_directory(tmp_path):
    debug_dir = tmp_path / "classes" / "english9_p2" / "assignments" / "quiz" / "debug"
    debug_dir.mkdir(parents=True)
    path = debug_dir / "debug_warped_page_2.jpeg"
    path.write_text("existing", encoding="utf-8")

    assert non_overwriting_path(path) == str(debug_dir / "debug_warped_page_2_2.jpeg")


def test_score_image_preserves_existing_debug_outputs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    debug_dir = tmp_path / "debug"
    debug_dir.mkdir()
    (debug_dir / "debug_corners_page_1.png").write_text("existing", encoding="utf-8")
    (debug_dir / "debug_warped_page_1.png").write_text("existing", encoding="utf-8")

    question_count = 10
    answer_key = {q_num: "A" for q_num in range(1, question_count + 1)}
    marked_answers = answer_key.copy()
    image = _draw_synthetic_answer_sheet(marked_answers, question_count)

    result = score_image(
        image,
        answer_key,
        page_num=1,
        debug_dir=debug_dir,
        question_count=question_count,
    )

    assert result is not None
    assert (debug_dir / "debug_corners_page_1.png").read_text(encoding="utf-8") == "existing"
    assert (debug_dir / "debug_warped_page_1.png").read_text(encoding="utf-8") == "existing"
    assert (debug_dir / "debug_corners_page_1_2.png").exists()
    assert (debug_dir / "debug_warped_page_1_2.png").exists()


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


def test_score_image_detects_synthetic_15_question_answers(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    question_count = 15
    pattern = ["A", "B", "C", "D"]
    answer_key = {q_num: pattern[(q_num - 1) % len(pattern)] for q_num in range(1, 16)}
    marked_answers = answer_key.copy()

    image = _draw_synthetic_answer_sheet(marked_answers, question_count)
    result = score_image(
        image,
        answer_key,
        page_num=1,
        debug_dir=tmp_path / "debug",
        question_count=question_count,
    )

    assert result is not None
    assert result["total_points"] == 15
    assert result["score"] == 15
    assert len(result["answers"]) == 15

    for answer in result["answers"]:
        assert answer["Answer"] == answer_key[answer["Q"]]
        assert answer["Correct"] is True

    assert result["answers"][14]["Answer"] == "C"
    assert result["answers"][14]["Correct"] is True


def test_filled_q15_answer_box_is_not_selected_as_registration_mark():
    question_count = 15
    marked_answers = {q_num: "A" for q_num in range(1, question_count + 1)}
    image = _draw_synthetic_answer_sheet(marked_answers, question_count)

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    thresh = cv2.threshold(
        blurred,
        0,
        255,
        cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU,
    )[1]

    candidates, corner_centers = _find_registration_mark_centers(
        thresh,
        IMG_WIDTH,
        IMG_HEIGHT,
    )

    expected_centers = {
        (x + CORNER_SIZE // 2, y + CORNER_SIZE // 2)
        for x, y in CORNERS
    }
    q15_a_center = (
        BOX_START_X + BOX_SIZE // 2,
        Q_START_Y + 14 * Q_STEP_Y + BOX_SIZE // 2,
    )

    assert set(corner_centers) == expected_centers
    assert q15_a_center not in candidates
    assert q15_a_center not in corner_centers


def test_imperfect_bottom_left_registration_mark_is_selected():
    question_count = 15
    marked_answers = {q_num: "A" for q_num in range(1, question_count + 1)}
    image = _draw_synthetic_answer_sheet(marked_answers, question_count)

    bottom_left_x, bottom_left_y = CORNERS[2]
    cv2.rectangle(
        image,
        (bottom_left_x - 5, bottom_left_y - 5),
        (bottom_left_x + CORNER_SIZE + 8, bottom_left_y + CORNER_SIZE + 8),
        (255, 255, 255),
        -1,
    )

    imperfect_marker = np.array(
        [
            [bottom_left_x - 8, bottom_left_y + 2],
            [bottom_left_x + CORNER_SIZE + 11, bottom_left_y - 3],
            [bottom_left_x + CORNER_SIZE + 18, bottom_left_y + CORNER_SIZE - 2],
            [bottom_left_x + 7, bottom_left_y + CORNER_SIZE + 13],
            [bottom_left_x - 12, bottom_left_y + 35],
        ],
        dtype=np.int32,
    )
    cv2.fillPoly(image, [imperfect_marker], (0, 0, 0))
    cv2.line(
        image,
        (0, bottom_left_y + CORNER_SIZE + 4),
        (bottom_left_x + 20, bottom_left_y + CORNER_SIZE + 4),
        (0, 0, 0),
        6,
    )

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    thresh = cv2.threshold(
        blurred,
        0,
        255,
        cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU,
    )[1]

    _, corner_centers = _find_registration_mark_centers(
        thresh,
        IMG_WIDTH,
        IMG_HEIGHT,
    )

    expected_bottom_left = (
        bottom_left_x + CORNER_SIZE // 2,
        bottom_left_y + CORNER_SIZE // 2,
    )
    selected_bottom_left = max(corner_centers, key=lambda point: point[1] - point[0])

    assert len(corner_centers) == 4
    assert abs(selected_bottom_left[0] - expected_bottom_left[0]) <= 35
    assert abs(selected_bottom_left[1] - expected_bottom_left[1]) <= 35


def test_15_question_answer_boxes_stay_outside_registration_corner_zones():
    unsafe_regions = [bounds for _, bounds in _expected_corner_regions(IMG_WIDTH, IMG_HEIGHT)]

    for question_index in range(15):
        y = Q_START_Y + question_index * Q_STEP_Y
        for choice_index in range(len(CHOICES)):
            center = (
                BOX_START_X + choice_index * BOX_STEP_X + BOX_SIZE // 2,
                y + BOX_SIZE // 2,
            )
            assert not any(
                x_min <= center[0] <= x_max and y_min <= center[1] <= y_max
                for x_min, y_min, x_max, y_max in unsafe_regions
            )
