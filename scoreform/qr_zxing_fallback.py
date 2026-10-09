"""Independent, bounded QR decoder adapter for ScoreForm Issue #225.

Not part of active scanning until an explicitly reviewed integration slice.
No routing, PDS2 interpretation, persistence, or logging is performed here.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Any, Literal, cast

import numpy as np

# A single adapter call performs one native library call on at most this input.
# Candidate/transform orchestration must be bounded separately at integration.
MAX_IMAGE_DIMENSION = 5000
MAX_IMAGE_PIXELS = 12_000_000
MAX_RESULTS = 8
MAX_PAYLOAD_CHARACTERS = 4096

QrZxingStatus = Literal[
    "decoded",
    "no_qr",
    "unavailable",
    "invalid_image",
    "limit_exceeded",
    "decoder_error",
]


@dataclass(frozen=True, slots=True)
class QrZxingDecodeResult:
    """Raw independent QR text candidates, never an authoritative identity.

    Distinct candidate order is preserved; downstream routing must parse and
    validate every candidate and reject ambiguous or conflicting identities.
    """

    status: QrZxingStatus
    payload_texts: tuple[str, ...] = ()

    @property
    def has_candidates(self) -> bool:
        return self.status == "decoded" and bool(self.payload_texts)


def _valid_image(image: object) -> bool:
    if not isinstance(image, np.ndarray) or image.dtype != np.uint8:
        return False
    if image.ndim not in (2, 3):
        return False
    if image.ndim == 3 and image.shape[2] != 3:
        return False
    height, width = image.shape[:2]
    return height > 0 and width > 0


def decode_qr_with_zxing(
    image: np.ndarray, *, backend: object | None = None
) -> QrZxingDecodeResult:
    """Try one independent ZXing-C++ QR-only read, returning raw candidates.

    `backend` is an injection seam for deterministic tests, not a scanner
    configuration. Without a backend, `zxingcpp` is imported lazily so normal
    ScoreForm installation and scanning remain independent of this package.

    Never chooses a result from multiple distinct QR codes, never interprets
    PDS2, and never exposes decoded text in exceptions, messages, or logs.
    """
    if not _valid_image(image):
        return QrZxingDecodeResult("invalid_image")
    height, width = image.shape[:2]
    if (
        height > MAX_IMAGE_DIMENSION
        or width > MAX_IMAGE_DIMENSION
        or height * width > MAX_IMAGE_PIXELS
    ):
        return QrZxingDecodeResult("limit_exceeded")

    if backend is None:
        try:
            backend = import_module("zxingcpp")
        except (ImportError, OSError):
            # Includes missing package and native-extension DLL load failures.
            return QrZxingDecodeResult("unavailable")

    try:
        # Native ZXing and the optional injected test backend share a
        # dynamic interface. Keep runtime checks in the existing guard.
        native = cast(Any, backend)
        qr_format = native.BarcodeFormat.QRCode
        # Copy only when necessary and only after pixel bounds are checked.
        candidate = np.ascontiguousarray(image)
        barcodes = native.read_barcodes(
            candidate,
            formats=qr_format,
            try_rotate=True,
            try_downscale=True,
            try_invert=True,
            return_errors=False,
        )
        if len(barcodes) > MAX_RESULTS:
            return QrZxingDecodeResult("limit_exceeded")

        distinct: list[str] = []
        for barcode in barcodes:
            if barcode.format != qr_format:
                continue
            value = barcode.text
            if not isinstance(value, str) or not value:
                continue
            if len(value) > MAX_PAYLOAD_CHARACTERS:
                return QrZxingDecodeResult("limit_exceeded")
            if value not in distinct:
                distinct.append(value)
        if not distinct:
            return QrZxingDecodeResult("no_qr")
        return QrZxingDecodeResult("decoded", tuple(distinct))
    except Exception:
        # A native decoder failure must not prevent the primary scanner from
        # retaining its normal unresolved/review disposition.
        return QrZxingDecodeResult("decoder_error")
