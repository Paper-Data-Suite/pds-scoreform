"""Issue #225 Slice 5: bounded independent decode after OpenCV failure."""

from __future__ import annotations

from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from pds_core.scan_retention import retain_source_scan

import scoreform.pds2_scan_dispatch as dispatch
from scoreform.qr_zxing_fallback import QrZxingDecodeResult
from scoreform.qr_zxing_recovery import (
    MAX_RECOVERY_ATTEMPTS,
    MAX_RECOVERY_TOTAL_PIXELS,
    QrZxingRecoveryResult,
    recover_qr_with_zxing,
)

VALID = "PDS2|m=scoreform|c=class1|w=quiz1|r=rt_" + "1" * 32
OTHER = "PDS2|m=scoreform|c=class1|w=quiz1|r=rt_" + "2" * 32


def _image():
    return np.full((420, 330, 3), 255, dtype=np.uint8)


def _source():
    return SimpleNamespace(source_scan_id="synthetic")


def _quiet_diagnostics(monkeypatch):
    monkeypatch.setattr(
        dispatch,
        "save_qr_failure_diagnostics_with_status",
        lambda *_args, **_kwargs: SimpleNamespace(paths=(), errors=()),
    )


def _empty_opencv(monkeypatch):
    monkeypatch.setattr(
        dispatch, "_qr_candidate_images", lambda image: (("raw", image),)
    )

    class Detector:
        def detectAndDecode(self, image):
            return "", None, None

    monkeypatch.setattr(dispatch.cv2, "QRCodeDetector", Detector)


def test_bounded_recovery_retains_one_unique_payload_and_method():
    seen = []

    def decode(image):
        seen.append(image.shape[:2])
        return QrZxingDecodeResult("decoded", (VALID,))

    result = recover_qr_with_zxing(_image(), decoder=decode)
    assert result.status == "decoded"
    assert result.raw_payload_text == VALID
    assert result.decode_method == "zxing-cpp:tight"
    assert 1 <= result.attempts <= MAX_RECOVERY_ATTEMPTS
    assert sum(h * w for h, w in seen) <= MAX_RECOVERY_TOTAL_PIXELS


def test_independent_decoder_conflict_is_never_guessed():
    calls = 0

    def decode(_image):
        nonlocal calls
        calls += 1
        return QrZxingDecodeResult("decoded", (VALID if calls == 1 else OTHER,))

    result = recover_qr_with_zxing(_image(), decoder=decode)
    assert result.status == "ambiguous"
    assert result.raw_payload_text is None
    assert result.decode_method is None
    assert calls == 2


def test_single_candidate_with_two_distinct_payloads_is_ambiguous():
    result = recover_qr_with_zxing(
        _image(),
        decoder=lambda _image: QrZxingDecodeResult("decoded", (VALID, OTHER)),
    )
    assert result.status == "ambiguous"
    assert result.attempts == 1


def test_decoder_unavailable_stops_without_repeating_native_import():
    calls = []

    def decode(image):
        calls.append(image)
        return QrZxingDecodeResult("unavailable")

    result = recover_qr_with_zxing(_image(), decoder=decode)
    assert result.status == "unavailable"
    assert len(calls) == 1


def test_invalid_image_and_backend_error_are_fail_soft():
    assert recover_qr_with_zxing(None).status == "no_qr"
    assert recover_qr_with_zxing(
        _image(), decoder=lambda image: (_ for _ in ()).throw(RuntimeError("native"))
    ).status == "no_qr"


def test_candidate_and_cumulative_pixel_limits_are_enforced():
    seen = []

    def decode(image):
        seen.append(image.shape[:2])
        return QrZxingDecodeResult("no_qr")

    result = recover_qr_with_zxing(
        np.full((3400, 2600, 3), 255, dtype=np.uint8), decoder=decode
    )
    assert result.status == "no_qr"
    assert len(seen) <= MAX_RECOVERY_ATTEMPTS
    assert sum(h * w for h, w in seen) <= MAX_RECOVERY_TOTAL_PIXELS


def test_existing_opencv_success_never_invokes_independent_decoder(monkeypatch, tmp_path):
    _quiet_diagnostics(monkeypatch)
    monkeypatch.setattr(
        dispatch, "_qr_candidate_images", lambda image: (("raw", image),)
    )

    class Detector:
        def detectAndDecode(self, image):
            return VALID, None, None

    monkeypatch.setattr(dispatch.cv2, "QRCodeDetector", Detector)
    monkeypatch.setattr(
        dispatch,
        "recover_qr_with_zxing",
        lambda image: pytest.fail("Fallback ran after successful OpenCV"),
    )
    result = dispatch.detect_qr_payload_text(
        _image(), retained_source=_source(), source_page_number=1,
        workspace_root=tmp_path,
    )
    assert result.raw_payload_text == VALID
    assert result.decode_method == "raw"


def test_opencv_failure_can_be_recovered_by_independent_decoder(monkeypatch, tmp_path):
    _quiet_diagnostics(monkeypatch)
    _empty_opencv(monkeypatch)
    monkeypatch.setattr(
        dispatch, "recover_qr_with_zxing",
        lambda image: QrZxingRecoveryResult("decoded", VALID, "zxing-cpp:tight", 2),
    )
    result = dispatch.detect_qr_payload_text(
        _image(), retained_source=_source(), source_page_number=1,
        workspace_root=tmp_path,
    )
    assert result.raw_payload_text == VALID
    assert result.decode_method == "zxing-cpp:tight"
    assert result.error is None


def test_conflicting_fallback_payloads_remain_unresolved(monkeypatch, tmp_path):
    _quiet_diagnostics(monkeypatch)
    _empty_opencv(monkeypatch)
    monkeypatch.setattr(
        dispatch, "recover_qr_with_zxing",
        lambda image: QrZxingRecoveryResult("ambiguous", attempts=2),
    )
    result = dispatch.detect_qr_payload_text(
        _image(), retained_source=_source(), source_page_number=1,
        workspace_root=tmp_path,
    )
    assert result.raw_payload_text is None
    assert result.decode_method is None
    assert isinstance(result.error, dispatch.ScoreFormQrUnreadableError)
    assert "PDS2|" not in str(result.error)


@pytest.mark.parametrize("status", ["no_qr", "unavailable"])
def test_unavailable_or_empty_fallback_preserves_prior_failure(
    monkeypatch, tmp_path, status
):
    _quiet_diagnostics(monkeypatch)
    _empty_opencv(monkeypatch)
    monkeypatch.setattr(
        dispatch, "recover_qr_with_zxing",
        lambda image: QrZxingRecoveryResult(status, attempts=1),
    )
    result = dispatch.detect_qr_payload_text(
        _image(), retained_source=_source(), source_page_number=1,
        workspace_root=tmp_path,
    )
    assert result.raw_payload_text is None
    assert isinstance(result.error, dispatch.ScoreFormQrMissingError)


def test_fallback_exception_does_not_interfere_with_primary_failure(
    monkeypatch, tmp_path
):
    _quiet_diagnostics(monkeypatch)
    _empty_opencv(monkeypatch)
    monkeypatch.setattr(
        dispatch, "recover_qr_with_zxing",
        lambda image: (_ for _ in ()).throw(RuntimeError("fallback")),
    )
    result = dispatch.detect_qr_payload_text(
        _image(), retained_source=_source(), source_page_number=1,
        workspace_root=tmp_path,
    )
    assert isinstance(result.error, dispatch.ScoreFormQrMissingError)


@pytest.mark.parametrize("raw,stage", [(VALID, None), ("not-a-PDS2-payload", "payload_parsing")])
def test_existing_pds2_parser_remains_authoritative(
    monkeypatch, tmp_path, raw, stage
):
    _quiet_diagnostics(monkeypatch)
    _empty_opencv(monkeypatch)
    monkeypatch.setattr(
        dispatch, "recover_qr_with_zxing",
        lambda image: QrZxingRecoveryResult("decoded", raw, "zxing-cpp:tight", 1),
    )
    monkeypatch.setattr(
        dispatch, "retained_source_page_count", lambda *_args, **_kwargs: 1
    )
    monkeypatch.setattr(
        dispatch, "load_retained_page_for_qr", lambda *_args, **_kwargs: _image()
    )
    incoming = tmp_path / "incoming.png"
    assert cv2.imwrite(str(incoming), _image())
    retained = retain_source_scan(tmp_path, incoming)
    pages = dispatch._decode_pages(tmp_path, retained)
    assert len(pages) == 1
    assert pages[0].raw_payload_text == raw
    assert pages[0].decode_method == "zxing-cpp:tight"
    assert pages[0].failure_stage == stage
    assert (pages[0].dispatch_request is not None) == (stage is None)
    assert (pages[0].locator is not None) == (stage is None)
