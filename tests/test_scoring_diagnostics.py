from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from scoreform.config import CORNER_SIZE, CORNERS, IMG_HEIGHT, IMG_WIDTH
from scoreform.diagnostic_artifacts import (
    MAX_DIAGNOSTIC_FILENAME_LENGTH,
    DiagnosticArtifactWarning,
    DiagnosticArtifactWriteResult,
    build_diagnostic_artifact_name,
    write_png_diagnostic_artifact,
)
from scoreform.module_errors import ScoreFormPageScoringError
from scoreform.scoring import score_image

_SOURCE_SHA = "a" * 64
_PAGE_ID = "pg_" + "b" * 32


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


def test_registration_failure_preserves_created_bounded_diagnostic_path(tmp_path):
    debug_dir = tmp_path / "managed" / "debug"
    legacy_stem = "student_source_identity_" + ("x" * 500)
    with pytest.raises(ScoreFormPageScoringError) as caught:
        score_image(
            _image(corners=False),
            {1: "A"},
            page_num=1,
            debug_dir=debug_dir,
            question_count=1,
            diagnostic_stem=legacy_stem,
            diagnostic_source_sha256=_SOURCE_SHA,
            diagnostic_page_id=_PAGE_ID,
            raise_on_failure=True,
        )
    assert caught.value.diagnostic_code == "registration_marks_missing"
    paths = caught.value.diagnostic_paths
    assert isinstance(paths, tuple)
    assert len(paths) == 1
    path = Path(paths[0])
    assert path.is_file()
    path.resolve().relative_to(debug_dir.resolve())
    assert path.name.startswith("sfdiag_corners_")
    assert len(path.name) <= MAX_DIAGNOSTIC_FILENAME_LENGTH
    assert legacy_stem not in path.name
    assert _SOURCE_SHA not in path.name
    assert _PAGE_ID not in path.name


def test_score_image_diagnostics_do_not_use_cv2_imwrite(tmp_path, monkeypatch):
    debug_dir = tmp_path / "managed" / "debug"
    monkeypatch.setattr(
        cv2,
        "imwrite",
        lambda *args, **kwargs: pytest.fail("cv2.imwrite must not be used"),
    )

    result = score_image(
        _image(corners=True),
        {1: "A"},
        page_num=1,
        debug_dir=debug_dir,
        question_count=1,
        diagnostic_source_sha256=_SOURCE_SHA,
        diagnostic_page_id=_PAGE_ID,
        raise_on_failure=True,
    )

    paths = tuple(Path(path) for path in result["diagnostic_paths"])
    assert len(paths) == 2
    assert paths[0].name.startswith("sfdiag_corners_")
    assert paths[1].name.startswith("sfdiag_warped_")
    for path in paths:
        assert path.is_file()
        path.resolve().relative_to(debug_dir.resolve())
        assert len(path.name) <= MAX_DIAGNOSTIC_FILENAME_LENGTH


def test_warped_diagnostic_failure_is_subordinate_to_valid_score(
    tmp_path,
    monkeypatch,
):
    debug_dir = tmp_path / "managed" / "debug"

    def write_with_warped_failure(image, **kwargs):
        if kwargs["kind"] != "warped_page":
            return write_png_diagnostic_artifact(image, **kwargs)
        filename = build_diagnostic_artifact_name(
            kind=kwargs["kind"],
            source_sha256=kwargs["source_sha256"],
            source_page_number=kwargs["source_page_number"],
            page_id=kwargs["page_id"],
        )
        return DiagnosticArtifactWriteResult(
            kind="warped_page",
            intended_filename=filename,
            warning=DiagnosticArtifactWarning(
                kind="warped_page",
                stage="write",
                exception_type="PermissionError",
            ),
        )

    monkeypatch.setattr(
        "scoreform.scoring.write_png_diagnostic_artifact",
        write_with_warped_failure,
    )
    result = score_image(
        _image(corners=True),
        {1: "A"},
        page_num=1,
        debug_dir=debug_dir,
        question_count=1,
        diagnostic_source_sha256=_SOURCE_SHA,
        diagnostic_page_id=_PAGE_ID,
        raise_on_failure=True,
    )

    assert result["score"] == 0
    assert result["total_points"] == 1
    assert result["answers"] == [
        {"Q": 1, "Answer": "BLANK", "Correct": False}
    ]
    paths = result["diagnostic_paths"]
    assert len(paths) == 1
    assert Path(paths[0]).is_file()
    Path(paths[0]).resolve().relative_to(debug_dir.resolve())
    warnings = result["diagnostic_warnings"]
    assert len(warnings) == 1
    assert warnings[0].kind == "warped_page"
    assert warnings[0].stage == "write"
    assert warnings[0].code == "diagnostic_artifact_write_failed"


def test_valid_score_survives_all_diagnostic_persistence_failures(
    tmp_path,
    monkeypatch,
):
    debug_dir = tmp_path / "managed" / "debug"

    def fail_diagnostic(_image, **kwargs):
        filename = build_diagnostic_artifact_name(
            kind=kwargs["kind"],
            source_sha256=kwargs["source_sha256"],
            source_page_number=kwargs["source_page_number"],
            page_id=kwargs["page_id"],
        )
        return DiagnosticArtifactWriteResult(
            kind=kwargs["kind"],
            intended_filename=filename,
            warning=DiagnosticArtifactWarning(
                kind=kwargs["kind"],
                stage="write",
                exception_type="PermissionError",
            ),
        )

    monkeypatch.setattr(
        "scoreform.scoring.write_png_diagnostic_artifact",
        fail_diagnostic,
    )
    result = score_image(
        _image(corners=True),
        {1: "A"},
        page_num=1,
        debug_dir=debug_dir,
        question_count=1,
        diagnostic_source_sha256=_SOURCE_SHA,
        diagnostic_page_id=_PAGE_ID,
        raise_on_failure=True,
    )

    assert result["score"] == 0
    assert result["total_points"] == 1
    assert result["answers"] == [
        {"Q": 1, "Answer": "BLANK", "Correct": False}
    ]
    assert result["diagnostic_paths"] == ()
    assert tuple(warning.kind for warning in result["diagnostic_warnings"]) == (
        "registration_marks",
        "warped_page",
    )


def test_registration_failure_remains_primary_when_diagnostic_write_fails(
    tmp_path,
    monkeypatch,
):
    debug_dir = tmp_path / "managed" / "debug"

    def fail_diagnostic(_image, **kwargs):
        filename = build_diagnostic_artifact_name(
            kind=kwargs["kind"],
            source_sha256=kwargs["source_sha256"],
            source_page_number=kwargs["source_page_number"],
            page_id=kwargs["page_id"],
        )
        return DiagnosticArtifactWriteResult(
            kind=kwargs["kind"],
            intended_filename=filename,
            warning=DiagnosticArtifactWarning(
                kind=kwargs["kind"],
                stage="write",
                exception_type="PermissionError",
            ),
        )

    monkeypatch.setattr(
        "scoreform.scoring.write_png_diagnostic_artifact",
        fail_diagnostic,
    )
    with pytest.raises(ScoreFormPageScoringError) as caught:
        score_image(
            _image(corners=False),
            {1: "A"},
            page_num=1,
            debug_dir=debug_dir,
            question_count=1,
            diagnostic_source_sha256=_SOURCE_SHA,
            diagnostic_page_id=_PAGE_ID,
            raise_on_failure=True,
        )

    assert caught.value.diagnostic_code == "registration_marks_missing"
    assert caught.value.diagnostic_paths == ()
    assert len(caught.value.diagnostic_warnings) == 1
    warning = caught.value.diagnostic_warnings[0]
    assert warning.kind == "registration_marks"
    assert warning.code == "diagnostic_artifact_write_failed"


def test_legacy_diagnostic_stem_is_accepted_but_not_used_as_filename_identity(
    tmp_path,
):
    debug_dir = tmp_path / "managed" / "debug"
    legacy_stem = "class_student_assignment_scan_" + ("z" * 800)

    with pytest.raises(ScoreFormPageScoringError) as caught:
        score_image(
            _image(corners=False),
            {1: "A"},
            page_num=7,
            debug_dir=debug_dir,
            question_count=1,
            diagnostic_stem=legacy_stem,
            raise_on_failure=True,
        )

    assert caught.value.diagnostic_code == "registration_marks_missing"
    path = Path(caught.value.diagnostic_paths[0])
    assert path.name.startswith("sfdiag_corners_")
    assert len(path.name) <= MAX_DIAGNOSTIC_FILENAME_LENGTH
    assert "class_student_assignment_scan" not in path.name
    assert "zzzz" not in path.name
