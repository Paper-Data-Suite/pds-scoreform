from __future__ import annotations

import builtins
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path

import cv2
import numpy as np
import pytest
from pdf2image.exceptions import PDFInfoNotInstalledError, PDFSyntaxError
from pds_core.scan_retention import RetainedSourceScan, retain_source_scan
from PIL import Image

from scoreform.module_errors import ScoreFormRetainedPageError
from scoreform.retained_page import load_retained_source_page


def _retained(
    tmp_path: Path,
    suffix: str = ".png",
    *,
    timestamp: datetime | None = None,
    intake_date: date | None = None,
) -> RetainedSourceScan:
    timestamp = timestamp or datetime(2026, 1, 2, tzinfo=timezone.utc)
    intake_date = intake_date or date(2026, 1, 2)
    relative = f"scans/source/{intake_date.isoformat()}/retained{suffix}"
    path = tmp_path / Path(relative)
    path.parent.mkdir(parents=True)
    if suffix == ".png":
        assert cv2.imwrite(str(path), np.full((20, 30, 3), 255, np.uint8))
    else:
        path.write_bytes(b"not an active scan")
    return RetainedSourceScan(
        source_scan_id="scan_retained",
        source_filename=f"original{suffix}",
        source_sha256="a" * 64,
        retained_source_path=path,
        retained_source_relative_path=relative,
        intake_timestamp=timestamp,
        intake_date=intake_date,
    )


def test_load_retained_png_page(tmp_path):
    page = load_retained_source_page(
        _retained(tmp_path), 1, workspace_root=tmp_path
    )
    assert page.image.shape == (20, 30, 3)
    assert (page.width, page.height) == (30, 20)
    assert page.source_page_number == 1


def test_image_source_rejects_later_page(tmp_path):
    with pytest.raises(ScoreFormRetainedPageError, match="only source page one"):
        load_retained_source_page(
            _retained(tmp_path), 2, workspace_root=tmp_path
        )


def test_bmp_is_not_an_active_retained_source(tmp_path):
    with pytest.raises(ScoreFormRetainedPageError, match="supported"):
        load_retained_source_page(
            _retained(tmp_path, ".bmp"), 1, workspace_root=tmp_path
        )


def test_explicit_intake_date_may_differ_from_timestamp_date(tmp_path):
    source = tmp_path / "incoming.png"
    assert cv2.imwrite(str(source), np.full((20, 30, 3), 255, np.uint8))
    retained = retain_source_scan(
        tmp_path,
        source,
        intake_timestamp=datetime(2026, 1, 2, 23, 30, tzinfo=timezone.utc),
        intake_date=date(2026, 1, 1),
    )
    assert load_retained_source_page(
        retained, 1, workspace_root=tmp_path
    ).source_scan_id == retained.source_scan_id


def test_date_bucket_must_match_intake_date(tmp_path):
    retained = _retained(tmp_path)
    mismatched = replace(retained, intake_date=date(2026, 1, 1))
    with pytest.raises(ScoreFormRetainedPageError, match="date bucket"):
        load_retained_source_page(mismatched, 1, workspace_root=tmp_path)


def test_naive_intake_timestamp_is_rejected(tmp_path):
    retained = replace(
        _retained(tmp_path), intake_timestamp=datetime(2026, 1, 2, 12, 0)
    )
    with pytest.raises(ScoreFormRetainedPageError, match="timezone-aware"):
        load_retained_source_page(retained, 1, workspace_root=tmp_path)


def test_datetime_is_not_an_intake_date(tmp_path):
    retained = replace(
        _retained(tmp_path),
        intake_date=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    with pytest.raises(ScoreFormRetainedPageError, match="not a datetime"):
        load_retained_source_page(retained, 1, workspace_root=tmp_path)


def test_nested_retained_path_is_not_canonical(tmp_path):
    retained = _retained(tmp_path)
    relative = "scans/source/2026-01-02/nested/retained.png"
    nested = tmp_path / Path(relative)
    nested.parent.mkdir(parents=True)
    nested.write_bytes(retained.retained_source_path.read_bytes())
    forged = replace(
        retained,
        retained_source_path=nested,
        retained_source_relative_path=relative,
    )
    with pytest.raises(ScoreFormRetainedPageError, match="scans/source"):
        load_retained_source_page(forged, 1, workspace_root=tmp_path)


@pytest.mark.parametrize(
    "source_filename",
    (
        "../incoming.png",
        "folder/incoming.png",
        "folder\\incoming.png",
        "C:\\incoming.png",
        "incoming.bmp",
        "incoming.png\n",
    ),
)
def test_source_filename_must_be_supported_filename_only(
    tmp_path, source_filename
):
    retained = replace(_retained(tmp_path), source_filename=source_filename)
    with pytest.raises(ScoreFormRetainedPageError, match="source_filename"):
        load_retained_source_page(retained, 1, workspace_root=tmp_path)


def test_source_filename_extension_must_match_retained_extension(tmp_path):
    retained = replace(_retained(tmp_path), source_filename="incoming.jpg")
    with pytest.raises(ScoreFormRetainedPageError, match="must agree exactly"):
        load_retained_source_page(retained, 1, workspace_root=tmp_path)


def test_pdf_converts_only_requested_page(tmp_path, monkeypatch):
    retained = _retained(tmp_path, ".pdf")
    calls = []

    def convert(path, **kwargs):
        calls.append((path, kwargs))
        return [Image.fromarray(np.full((4, 5, 3), 255, np.uint8), "RGB")]

    monkeypatch.setattr("pdf2image.convert_from_path", convert)
    page = load_retained_source_page(
        retained, 2, workspace_root=tmp_path
    )
    assert page.image.shape == (4, 5, 3)
    assert calls == [
        (
            retained.retained_source_path,
            {"first_page": 2, "last_page": 2},
        )
    ]


def test_pdf_out_of_range_requires_exactly_one_page(tmp_path, monkeypatch):
    retained = _retained(tmp_path, ".pdf")
    monkeypatch.setattr("pdf2image.convert_from_path", lambda *args, **kwargs: [])
    with pytest.raises(ScoreFormRetainedPageError, match="outside"):
        load_retained_source_page(retained, 9, workspace_root=tmp_path)


def test_pdf_rejects_multiple_converted_pages(tmp_path, monkeypatch):
    retained = _retained(tmp_path, ".pdf")
    page = Image.fromarray(np.full((4, 5, 3), 255, np.uint8), "RGB")
    monkeypatch.setattr(
        "pdf2image.convert_from_path", lambda *args, **kwargs: [page, page]
    )
    with pytest.raises(ScoreFormRetainedPageError, match="exactly one"):
        load_retained_source_page(retained, 2, workspace_root=tmp_path)


def test_missing_pdf2image_is_distinguishable(tmp_path, monkeypatch):
    retained = _retained(tmp_path, ".pdf")
    original_import = builtins.__import__

    def fail_pdf2image(name, *args, **kwargs):
        if name == "pdf2image":
            raise ImportError("missing")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fail_pdf2image)
    with pytest.raises(ScoreFormRetainedPageError, match="pdf2image package"):
        load_retained_source_page(retained, 1, workspace_root=tmp_path)


def test_missing_poppler_is_distinguishable(tmp_path, monkeypatch):
    retained = _retained(tmp_path, ".pdf")

    def missing(*args, **kwargs):
        raise PDFInfoNotInstalledError("missing")

    monkeypatch.setattr("pdf2image.convert_from_path", missing)
    with pytest.raises(ScoreFormRetainedPageError, match="Poppler"):
        load_retained_source_page(retained, 1, workspace_root=tmp_path)


def test_malformed_pdf_is_distinguishable(tmp_path, monkeypatch):
    retained = _retained(tmp_path, ".pdf")

    def malformed(*args, **kwargs):
        raise PDFSyntaxError("bad PDF")

    monkeypatch.setattr("pdf2image.convert_from_path", malformed)
    with pytest.raises(ScoreFormRetainedPageError, match="malformed"):
        load_retained_source_page(retained, 1, workspace_root=tmp_path)


def test_invalid_pdf_image_conversion_is_distinguishable(tmp_path, monkeypatch):
    retained = _retained(tmp_path, ".pdf")

    class InvalidPage:
        def convert(self, mode):
            raise ValueError("invalid image")

    monkeypatch.setattr(
        "pdf2image.convert_from_path", lambda *args, **kwargs: [InvalidPage()]
    )
    with pytest.raises(ScoreFormRetainedPageError, match="not valid image"):
        load_retained_source_page(retained, 1, workspace_root=tmp_path)
