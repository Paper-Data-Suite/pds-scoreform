"""Bounded independent QR recovery after the existing OpenCV scan, Issue #225.

This module never parses PDS2, resolves routing, writes artifacts, or chooses
between distinct payloads. The caller retains all authoritative validation.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Literal

import cv2
import numpy as np

from scoreform.qr_zxing_fallback import (
    MAX_IMAGE_DIMENSION,
    MAX_IMAGE_PIXELS,
    QrZxingDecodeResult,
    decode_qr_with_zxing,
)
from scoreform.scoring import _expected_qr_crop_candidates

MAX_RECOVERY_ATTEMPTS = 5
MAX_RECOVERY_TOTAL_PIXELS = 16_000_000

QrRecoveryStatus = Literal["decoded", "no_qr", "ambiguous", "unavailable"]


@dataclass(frozen=True, slots=True)
class QrZxingRecoveryResult:
    """Untrusted raw QR text with a non-sensitive, reproducible method label."""

    status: QrRecoveryStatus
    raw_payload_text: str | None = None
    decode_method: str | None = None
    attempts: int = 0

    def __post_init__(self) -> None:
        if self.status == "decoded":
            if not self.raw_payload_text or not self.decode_method:
                raise ValueError("A decoded QR needs raw text and method.")
        elif self.raw_payload_text is not None or self.decode_method is not None:
            raise ValueError("Unresolved QR recovery cannot claim decoded text.")
        if not 0 <= self.attempts <= MAX_RECOVERY_ATTEMPTS:
            raise ValueError("QR recovery attempts are out of bounds.")


def _within_single_image_limit(image: np.ndarray) -> bool:
    h, w = image.shape[:2]
    return (
        h > 0
        and w > 0
        and h <= MAX_IMAGE_DIMENSION
        and w <= MAX_IMAGE_DIMENSION
        and h * w <= MAX_IMAGE_PIXELS
    )


def _recovery_candidates(image: np.ndarray) -> Iterator[tuple[str, np.ndarray]]:
    """Offer fixed QR-region candidates, then full page if budget permits.

    Existing positional crops cover both the historical and enlarged layouts.
    Enlarging the tight crop uses nearest-neighbor to avoid new gray edges.
    """
    regions = dict(_expected_qr_crop_candidates(image))
    tight = regions.get("tight")
    if tight is not None:
        yield "tight", tight
        if (
            tight.shape[0] * 2 <= MAX_IMAGE_DIMENSION
            and tight.shape[1] * 2 <= MAX_IMAGE_DIMENSION
            and tight.shape[0] * tight.shape[1] * 4 <= MAX_IMAGE_PIXELS
        ):
            yield "tight-nearest-2x", cv2.resize(
                tight, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_NEAREST
            )
        if _within_single_image_limit(tight):
            gray = (
                tight
                if tight.ndim == 2
                else cv2.cvtColor(tight, cv2.COLOR_BGR2GRAY)
            )
            yield "tight-otsu", cv2.threshold(
                gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU
            )[1]
    broad = regions.get("broad_1")
    if broad is not None:
        yield "broad", broad
    yield "page", image


def recover_qr_with_zxing(
    image: np.ndarray,
    *,
    decoder: Callable[[np.ndarray], QrZxingDecodeResult] | None = None,
) -> QrZxingRecoveryResult:
    """Use a fixed budget and fail closed on any distinct decoded QR texts.

    A missing optional backend, malformed image, or native decoder exception
    must never interfere with ScoreForm's existing unresolved-page handling.
    """
    if (
        not isinstance(image, np.ndarray)
        or image.dtype != np.uint8
        or image.ndim not in (2, 3)
        or (image.ndim == 3 and image.shape[2] != 3)
        or not image.size
    ):
        return QrZxingRecoveryResult("no_qr")

    decode = decoder if decoder is not None else decode_qr_with_zxing
    discovered: dict[str, str] = {}
    attempts = 0
    total_pixels = 0
    try:
        for label, candidate in _recovery_candidates(image):
            if attempts >= MAX_RECOVERY_ATTEMPTS:
                break
            if not _within_single_image_limit(candidate):
                continue
            pixels = candidate.shape[0] * candidate.shape[1]
            if total_pixels + pixels > MAX_RECOVERY_TOTAL_PIXELS:
                continue
            attempts += 1
            total_pixels += pixels
            result = decode(candidate)
            if result.status == "unavailable":
                # Repeated native import/DLL failures cannot reveal more data.
                return QrZxingRecoveryResult("unavailable", attempts=attempts)
            if not result.has_candidates:
                continue
            for raw_text in result.payload_texts:
                discovered.setdefault(raw_text, label)
                if len(discovered) > 1:
                    return QrZxingRecoveryResult("ambiguous", attempts=attempts)
    except Exception:
        # A fallback orchestration error cannot abort PDS2 intake.
        return QrZxingRecoveryResult("no_qr", attempts=attempts)

    if not discovered:
        return QrZxingRecoveryResult("no_qr", attempts=attempts)
    raw_text, label = next(iter(discovered.items()))
    return QrZxingRecoveryResult(
        "decoded", raw_text, f"zxing-cpp:{label}", attempts=attempts
    )
