from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from scoreform.diagnostic_artifacts import (
    DIAGNOSTIC_ARTIFACT_WRITE_FAILED_CODE,
    MAX_DIAGNOSTIC_COLLISION_ATTEMPTS,
    MAX_DIAGNOSTIC_FILENAME_LENGTH,
    build_diagnostic_artifact_name,
    write_png_diagnostic_artifact,
)

_SOURCE_SHA = "a" * 64
_PAGE_ID = "pg_" + "b" * 96


def _image() -> np.ndarray:
    image = np.full((40, 60, 3), 255, np.uint8)
    cv2.rectangle(image, (5, 5), (25, 25), (0, 0, 0), -1)
    return image


def _name(kind="registration_marks") -> str:
    return build_diagnostic_artifact_name(
        kind=kind,
        source_sha256=_SOURCE_SHA,
        source_page_number=17,
        page_id=_PAGE_ID,
    )


def test_filename_is_deterministic_bounded_and_opaque():
    name = _name()
    assert name == _name()
    assert name.startswith("sfdiag_corners_")
    assert name.endswith(".png")
    assert len(name) <= MAX_DIAGNOSTIC_FILENAME_LENGTH
    assert _SOURCE_SHA not in name
    assert _PAGE_ID not in name
    assert "17" not in name

    other = build_diagnostic_artifact_name(
        kind="registration_marks",
        source_sha256="c" * 64,
        source_page_number=17,
        page_id=_PAGE_ID,
    )
    assert other != name


def test_writer_uses_png_encoding_and_python_create_only_io(tmp_path, monkeypatch):
    monkeypatch.setattr(
        cv2,
        "imwrite",
        lambda *args, **kwargs: pytest.fail("cv2.imwrite must not be used"),
    )
    result = write_png_diagnostic_artifact(
        _image(),
        diagnostic_root=tmp_path / "debug",
        kind="registration_marks",
        source_sha256=_SOURCE_SHA,
        source_page_number=17,
        page_id=_PAGE_ID,
    )

    assert result.warning is None
    assert result.path is not None
    path = Path(result.path)
    assert path.is_file()
    assert path.name == _name()
    assert len(path.name) <= MAX_DIAGNOSTIC_FILENAME_LENGTH
    path.resolve().relative_to((tmp_path / "debug").resolve())
    decoded = cv2.imread(str(path))
    assert decoded is not None
    assert decoded.shape == _image().shape


def test_existing_artifact_is_never_overwritten(tmp_path):
    root = tmp_path / "debug"
    root.mkdir()
    first = root / _name()
    first.write_bytes(b"preserve-me")

    result = write_png_diagnostic_artifact(
        _image(),
        diagnostic_root=root,
        kind="registration_marks",
        source_sha256=_SOURCE_SHA,
        source_page_number=17,
        page_id=_PAGE_ID,
    )

    assert first.read_bytes() == b"preserve-me"
    assert result.path is not None
    assert Path(result.path).name.endswith("_02.png")
    assert len(Path(result.path).name) <= MAX_DIAGNOSTIC_FILENAME_LENGTH


def test_encode_failure_is_structured_and_nonthrowing(tmp_path, monkeypatch):
    monkeypatch.setattr(cv2, "imencode", lambda *args, **kwargs: (False, None))
    result = write_png_diagnostic_artifact(
        _image(),
        diagnostic_root=tmp_path / "debug",
        kind="warped_page",
        source_sha256=_SOURCE_SHA,
        source_page_number=17,
        page_id=_PAGE_ID,
    )

    assert result.path is None
    assert result.warning is not None
    assert result.warning.code == DIAGNOSTIC_ARTIFACT_WRITE_FAILED_CODE
    assert result.warning.stage == "encode"
    assert result.warning.exception_type == "ValueError"
    assert not (tmp_path / "debug").exists()


def test_unavailable_root_is_structured_and_nonthrowing(tmp_path):
    root = tmp_path / "debug"
    root.write_text("not a directory", encoding="utf-8")

    result = write_png_diagnostic_artifact(
        _image(),
        diagnostic_root=root,
        kind="registration_marks",
        source_sha256=_SOURCE_SHA,
        source_page_number=17,
        page_id=_PAGE_ID,
    )

    assert result.path is None
    assert result.warning is not None
    assert result.warning.code == DIAGNOSTIC_ARTIFACT_WRITE_FAILED_CODE
    assert result.warning.stage == "prepare_root"
    assert result.warning.exception_type in {"FileExistsError", "ValueError"}


def test_write_failure_is_structured_and_partial_file_is_removed(
    tmp_path,
    monkeypatch,
):
    original_fsync = __import__("os").fsync

    def fail_fsync(fd):
        raise PermissionError("injected write failure")

    monkeypatch.setattr("scoreform.diagnostic_artifacts.os.fsync", fail_fsync)
    result = write_png_diagnostic_artifact(
        _image(),
        diagnostic_root=tmp_path / "debug",
        kind="registration_marks",
        source_sha256=_SOURCE_SHA,
        source_page_number=17,
        page_id=_PAGE_ID,
    )
    monkeypatch.setattr("scoreform.diagnostic_artifacts.os.fsync", original_fsync)

    assert result.path is None
    assert result.warning is not None
    assert result.warning.stage == "write"
    assert result.warning.exception_type == "PermissionError"
    assert list((tmp_path / "debug").iterdir()) == []


def test_collision_exhaustion_is_bounded_and_non_destructive(tmp_path):
    root = tmp_path / "debug"
    root.mkdir()
    base = _name()
    stem = base.removesuffix(".png")
    expected = []
    for attempt in range(1, MAX_DIAGNOSTIC_COLLISION_ATTEMPTS + 1):
        name = base if attempt == 1 else f"{stem}_{attempt:02d}.png"
        path = root / name
        path.write_bytes(f"existing-{attempt}".encode())
        expected.append((path, path.read_bytes()))

    result = write_png_diagnostic_artifact(
        _image(),
        diagnostic_root=root,
        kind="registration_marks",
        source_sha256=_SOURCE_SHA,
        source_page_number=17,
        page_id=_PAGE_ID,
    )

    assert result.path is None
    assert result.warning is not None
    assert result.warning.stage == "collision"
    assert result.warning.exception_type == "FileExistsError"
    assert len(result.intended_filename) <= MAX_DIAGNOSTIC_FILENAME_LENGTH
    assert [(path, path.read_bytes()) for path, _ in expected] == expected


def test_legacy_identity_heavy_name_can_exceed_260_without_expanding_new_leaf(
    tmp_path,
):
    very_long_page_id = "pg_" + ("identity" * 200)
    legacy_name = (
        f"debug_corners_page_scan_{'s' * 120}_source_123456_"
        f"{very_long_page_id}.png"
    )
    hypothetical_legacy_path = (
        tmp_path
        / "classes"
        / ("class-" + "c" * 80)
        / "modules"
        / "scoreform"
        / "work"
        / ("assignment-" + "a" * 80)
        / "debug"
        / legacy_name
    )
    assert len(str(hypothetical_legacy_path)) > 260

    result = write_png_diagnostic_artifact(
        _image(),
        diagnostic_root=tmp_path / "debug",
        kind="registration_marks",
        source_sha256=_SOURCE_SHA,
        source_page_number=123456,
        page_id=very_long_page_id,
    )

    assert result.path is not None
    name = Path(result.path).name
    assert len(name) <= MAX_DIAGNOSTIC_FILENAME_LENGTH
    assert very_long_page_id not in name
    assert _SOURCE_SHA not in name


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("source_sha256", "A" * 64),
        ("source_sha256", "a" * 63),
        ("source_page_number", True),
        ("source_page_number", 0),
        ("page_id", ""),
    ),
)
def test_identity_contract_rejects_invalid_values(field, value):
    kwargs = {
        "kind": "registration_marks",
        "source_sha256": _SOURCE_SHA,
        "source_page_number": 17,
        "page_id": _PAGE_ID,
    }
    kwargs[field] = value
    with pytest.raises(ValueError):
        build_diagnostic_artifact_name(**kwargs)
