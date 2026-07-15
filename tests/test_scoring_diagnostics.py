from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from scoreform.config import CORNER_SIZE, CORNERS, IMG_HEIGHT, IMG_WIDTH
from scoreform.module_errors import ScoreFormPageScoringError
from scoreform.scoring import score_image


def _image(*, corners: bool) -> np.ndarray:
    image = np.full((IMG_HEIGHT, IMG_WIDTH, 3), 255, np.uint8)
    if corners:
        for x, y in CORNERS:
            cv2.rectangle(
                image,
                (x, y),
                (x + CORNER_SIZE, y + CORNER_SIZE),
                (0, 0, 0),
                -1,
            )
    return image


def test_registration_failure_preserves_created_diagnostic_path(tmp_path):
    debug_dir = tmp_path / "managed" / "debug"
    with pytest.raises(ScoreFormPageScoringError) as caught:
        score_image(
            _image(corners=False),
            {1: "A"},
            page_num=1,
            debug_dir=debug_dir,
            question_count=1,
            diagnostic_stem="scan_source_1_pg_test",
            raise_on_failure=True,
        )
    paths = caught.value.diagnostic_paths
    assert isinstance(paths, tuple)
    assert len(paths) == 1
    path = Path(paths[0])
    assert path.is_file()
    path.resolve().relative_to(debug_dir.resolve())


def test_warped_diagnostic_failure_preserves_prior_evidence(
    tmp_path, monkeypatch
):
    debug_dir = tmp_path / "managed" / "debug"
    original = cv2.imwrite
    calls = 0

    def fail_second(path, image):
        nonlocal calls
        calls += 1
        if calls == 2:
            return False
        return original(path, image)

    monkeypatch.setattr(cv2, "imwrite", fail_second)
    with pytest.raises(ScoreFormPageScoringError, match="warped") as caught:
        score_image(
            _image(corners=True),
            {1: "A"},
            page_num=1,
            debug_dir=debug_dir,
            question_count=1,
            diagnostic_stem="scan_source_1_pg_test",
            raise_on_failure=True,
        )
    paths = caught.value.diagnostic_paths
    assert isinstance(paths, tuple)
    assert len(paths) == 1
    assert Path(paths[0]).is_file()
    Path(paths[0]).resolve().relative_to(debug_dir.resolve())
