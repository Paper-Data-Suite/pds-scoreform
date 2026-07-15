"""Strict, reusable extraction of one page from a Core retained source."""

from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path, PurePosixPath, PureWindowsPath

import cv2
import numpy as np
from pds_core.identifiers import IdentifierValidationError, validate_identifier
from pds_core.scan_retention import RetainedSourceScan
from pds_core.scan_routes import ScanRouteError, retained_source_scan_path

from scoreform.module_errors import ScoreFormRetainedPageError

SUPPORTED_RETAINED_SOURCE_EXTENSIONS = frozenset(
    {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}
)
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class RetainedPageImage:
    """One normalized OpenCV page plus its immutable Core provenance."""

    image: np.ndarray
    source_scan_id: str
    source_page_number: int
    retained_source_relative_path: str
    source_sha256: str
    width: int
    height: int


def _page_number(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ScoreFormRetainedPageError(
            "source_page_number must be an integer greater than or equal to one."
        )
    return value


def validate_retained_source(
    retained_source: RetainedSourceScan,
    *,
    workspace_root: Path,
) -> Path:
    """Validate Core provenance and return the exact retained regular file."""
    if not isinstance(retained_source, RetainedSourceScan):
        raise ScoreFormRetainedPageError(
            "retained_source must be a RetainedSourceScan."
        )
    if not isinstance(workspace_root, Path):
        raise ScoreFormRetainedPageError("workspace_root must be a Path.")
    try:
        validate_identifier(retained_source.source_scan_id, "source_scan_id")
    except (IdentifierValidationError, TypeError, ValueError) as error:
        raise ScoreFormRetainedPageError("source_scan_id is unsafe.") from error
    source_filename = retained_source.source_filename
    if (
        not isinstance(source_filename, str)
        or not source_filename
        or source_filename != source_filename.strip()
        or source_filename in {".", ".."}
        or "/" in source_filename
        or "\\" in source_filename
        or PureWindowsPath(source_filename).is_absolute()
        or PureWindowsPath(source_filename).drive
        or PurePosixPath(source_filename).is_absolute()
        or any(
            unicodedata.category(character) in {"Cc", "Zl", "Zp"}
            for character in source_filename
        )
    ):
        raise ScoreFormRetainedPageError(
            "source_filename must be a trimmed, control-free filename only."
        )
    source_suffix = Path(source_filename).suffix.lower()
    if source_suffix not in SUPPORTED_RETAINED_SOURCE_EXTENSIONS:
        raise ScoreFormRetainedPageError(
            "source_filename must use a supported active-scan extension."
        )
    if not isinstance(
        retained_source.source_sha256, str
    ) or not _SHA256_PATTERN.fullmatch(retained_source.source_sha256):
        raise ScoreFormRetainedPageError(
            "source_sha256 must be 64 lowercase hexadecimal characters."
        )
    timestamp = retained_source.intake_timestamp
    if not isinstance(timestamp, datetime) or timestamp.tzinfo is None or (
        timestamp.utcoffset() is None
    ):
        raise ScoreFormRetainedPageError("intake_timestamp must be timezone-aware.")
    intake_date = retained_source.intake_date
    if isinstance(intake_date, datetime) or not isinstance(intake_date, date):
        raise ScoreFormRetainedPageError(
            "intake_date must be a date, not a datetime."
        )

    relative_text = retained_source.retained_source_relative_path
    if not isinstance(relative_text, str) or not relative_text:
        raise ScoreFormRetainedPageError(
            "retained_source_relative_path must be nonempty."
        )
    windows = PureWindowsPath(relative_text)
    posix = PurePosixPath(relative_text)
    normalized_parts = tuple(relative_text.split("/"))
    if (
        "\\" in relative_text
        or windows.is_absolute()
        or posix.is_absolute()
        or windows.drive
        or windows.root
        or any(part in {"", ".", ".."} for part in normalized_parts)
    ):
        raise ScoreFormRetainedPageError(
            "retained_source_relative_path must be a safe relative path."
        )
    if normalized_parts[:2] != ("scans", "source") or len(normalized_parts) != 4:
        raise ScoreFormRetainedPageError(
            "Retained source must be beneath the active scans/source hierarchy."
        )
    if normalized_parts[2] != intake_date.isoformat():
        raise ScoreFormRetainedPageError(
            "Retained source date bucket does not match intake_date."
        )

    recorded_path = retained_source.retained_source_path
    if not isinstance(recorded_path, Path):
        raise ScoreFormRetainedPageError("retained_source_path must be a Path.")
    retained_filename = normalized_parts[3]
    try:
        canonical_path = retained_source_scan_path(
            workspace_root,
            intake_date=intake_date,
            retained_filename=retained_filename,
        )
    except (ScanRouteError, TypeError, ValueError) as error:
        raise ScoreFormRetainedPageError(
            "Retained source does not use Core's canonical active-scan path."
        ) from error
    expected_relative = canonical_path.relative_to(workspace_root).as_posix()
    if (
        recorded_path != canonical_path
        or relative_text != expected_relative
        or source_suffix != canonical_path.suffix.lower()
    ):
        raise ScoreFormRetainedPageError(
            "Retained source path, relative path, filename extension, and Core "
            "canonical path must agree exactly."
        )
    try:
        root_resolved = workspace_root.resolve(strict=True)
        path_resolved = recorded_path.resolve(strict=True)
        path_resolved.relative_to(root_resolved)
    except (OSError, RuntimeError, ValueError) as error:
        raise ScoreFormRetainedPageError(
            "Retained source is missing or outside the derived workspace."
        ) from error
    if recorded_path.is_symlink():
        raise ScoreFormRetainedPageError("Symlinked retained sources are not allowed.")
    if not recorded_path.is_file():
        raise ScoreFormRetainedPageError(
            "Retained source must be an existing regular file."
        )
    if not os.access(recorded_path, os.R_OK):
        raise ScoreFormRetainedPageError("Retained source is not readable.")
    if recorded_path.suffix.lower() not in SUPPORTED_RETAINED_SOURCE_EXTENSIONS:
        raise ScoreFormRetainedPageError(
            f"Unsupported retained-source extension: {recorded_path.suffix.lower() or '(none)'}."
        )
    return recorded_path


def _valid_bgr(image: object) -> np.ndarray:
    if not isinstance(image, np.ndarray) or image.size == 0:
        raise ScoreFormRetainedPageError("Retained page did not produce an image.")
    if image.ndim != 3 or image.shape[2] != 3:
        raise ScoreFormRetainedPageError("Retained page must normalize to BGR image data.")
    if image.dtype != np.uint8:
        raise ScoreFormRetainedPageError("Retained page image must use uint8 pixels.")
    return image


def _load_pdf_page(path: Path, page_number: int) -> np.ndarray:
    try:
        from pdf2image import convert_from_path
        from pdf2image.exceptions import (
            PDFInfoNotInstalledError,
            PDFPageCountError,
            PDFSyntaxError,
        )
    except ImportError as error:
        raise ScoreFormRetainedPageError(
            "PDF page extraction requires the pdf2image package."
        ) from error
    try:
        pages = convert_from_path(
            path,
            first_page=page_number,
            last_page=page_number,
        )
    except PDFInfoNotInstalledError as error:
        raise ScoreFormRetainedPageError(
            "PDF page extraction requires an available Poppler installation."
        ) from error
    except PDFPageCountError as error:
        raise ScoreFormRetainedPageError(
            "The retained PDF page count could not be determined."
        ) from error
    except PDFSyntaxError as error:
        raise ScoreFormRetainedPageError("The retained PDF is malformed.") from error
    except Exception as error:
        raise ScoreFormRetainedPageError("Retained PDF conversion failed.") from error
    if not pages:
        raise ScoreFormRetainedPageError(
            "The requested source page is outside the retained PDF."
        )
    if len(pages) != 1:
        raise ScoreFormRetainedPageError(
            "PDF extraction must produce exactly one requested page."
        )
    try:
        rgb = np.asarray(pages[0].convert("RGB"), dtype=np.uint8)
        return _valid_bgr(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
    except (ValueError, TypeError, cv2.error) as error:
        raise ScoreFormRetainedPageError(
            "The converted PDF page is not valid image data."
        ) from error


def load_retained_source_page(
    retained_source: RetainedSourceScan,
    source_page_number: int,
    *,
    workspace_root: Path,
) -> RetainedPageImage:
    """Load only the requested retained-source page as OpenCV BGR."""
    page_number = _page_number(source_page_number)
    path = validate_retained_source(retained_source, workspace_root=workspace_root)
    if path.suffix.lower() == ".pdf":
        image = _load_pdf_page(path, page_number)
    else:
        if page_number != 1:
            raise ScoreFormRetainedPageError(
                "Image retained sources contain only source page one."
            )
        try:
            image = _valid_bgr(cv2.imread(os.fspath(path), cv2.IMREAD_COLOR))
        except cv2.error as error:
            raise ScoreFormRetainedPageError(
                "Retained image could not be decoded."
            ) from error
    height, width = image.shape[:2]
    return RetainedPageImage(
        image=image,
        source_scan_id=retained_source.source_scan_id,
        source_page_number=page_number,
        retained_source_relative_path=(
            retained_source.retained_source_relative_path
        ),
        source_sha256=retained_source.source_sha256,
        width=width,
        height=height,
    )
