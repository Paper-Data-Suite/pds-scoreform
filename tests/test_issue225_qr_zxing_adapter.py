"""Issue #225 Slice 4: independent ZXing adapter without scan integration."""

from __future__ import annotations

import tomllib
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import scoreform.qr_zxing_fallback as adapter

QR_FORMAT = object()


def _barcode(text, format=QR_FORMAT):
    return SimpleNamespace(text=text, format=format)


def _backend(*results, error=None):
    def read_barcodes(image, **kwargs):
        assert image.dtype == np.uint8
        assert image.flags.c_contiguous
        assert kwargs == {
            "formats": QR_FORMAT,
            "try_rotate": True,
            "try_downscale": True,
            "try_invert": True,
            "return_errors": False,
        }
        if error is not None:
            raise error
        return list(results)

    return SimpleNamespace(
        BarcodeFormat=SimpleNamespace(QRCode=QR_FORMAT),
        read_barcodes=read_barcodes,
    )


@pytest.fixture
def image():
    return np.full((80, 90, 3), 255, dtype=np.uint8)


def test_valid_qr_returns_raw_payload_without_interpretation(image):
    result = adapter.decode_qr_with_zxing(
        image, backend=_backend(_barcode("PDS2|test"))
    )
    assert result.status == "decoded"
    assert result.payload_texts == ("PDS2|test",)
    assert result.has_candidates


def test_distinct_conflicting_payloads_are_returned_without_selection(image):
    result = adapter.decode_qr_with_zxing(
        image,
        backend=_backend(_barcode("PDS2|first"), _barcode("PDS2|second")),
    )
    assert result.payload_texts == ("PDS2|first", "PDS2|second")


def test_duplicate_candidates_are_deduplicated_in_decoder_order(image):
    result = adapter.decode_qr_with_zxing(
        image, backend=_backend(_barcode("same"), _barcode("same"))
    )
    assert result.payload_texts == ("same",)


def test_non_qr_and_empty_results_are_not_promoted(image):
    result = adapter.decode_qr_with_zxing(
        image,
        backend=_backend(_barcode("other", object()), _barcode("")),
    )
    assert result.status == "no_qr"
    assert not result.has_candidates


@pytest.mark.parametrize(
    "bad_image",
    [
        None,
        np.zeros((0, 20), dtype=np.uint8),
        np.zeros((20, 20), dtype=np.float32),
        np.zeros((10, 10, 4), dtype=np.uint8),
        np.zeros((10,), dtype=np.uint8),
    ],
)
def test_invalid_images_rejected_before_native_decode(bad_image):
    assert adapter.decode_qr_with_zxing(bad_image).status == "invalid_image"


def test_oversized_image_rejected_before_native_decode():
    image = np.zeros((5001, 1), dtype=np.uint8)
    assert adapter.decode_qr_with_zxing(image).status == "limit_exceeded"
    image = np.zeros((4000, 4000), dtype=np.uint8)
    assert adapter.decode_qr_with_zxing(image).status == "limit_exceeded"


def test_non_contiguous_inputs_are_copied_boundedly(image):
    non_contiguous = image[:, ::2]
    assert not non_contiguous.flags.c_contiguous
    result = adapter.decode_qr_with_zxing(
        non_contiguous, backend=_backend(_barcode("payload"))
    )
    assert result.payload_texts == ("payload",)


@pytest.mark.parametrize("error", [ImportError("missing"), OSError("dll load")])
def test_missing_backend_is_fail_soft(monkeypatch, image, error):
    def fail_import(name):
        assert name == "zxingcpp"
        raise error

    monkeypatch.setattr(adapter, "import_module", fail_import)
    result = adapter.decode_qr_with_zxing(image)
    assert result.status == "unavailable"
    assert not result.payload_texts


def test_native_decode_exception_is_fail_soft(image):
    result = adapter.decode_qr_with_zxing(
        image, backend=_backend(error=RuntimeError("native failure"))
    )
    assert result.status == "decoder_error"
    assert not result.payload_texts


def test_excessive_candidates_fail_closed(image):
    results = [_barcode(str(i)) for i in range(adapter.MAX_RESULTS + 1)]
    result = adapter.decode_qr_with_zxing(image, backend=_backend(*results))
    assert result.status == "limit_exceeded"
    assert not result.payload_texts


def test_excessive_payload_fails_closed(image):
    text = "x" * (adapter.MAX_PAYLOAD_CHARACTERS + 1)
    result = adapter.decode_qr_with_zxing(image, backend=_backend(_barcode(text)))
    assert result.status == "limit_exceeded"
    assert not result.payload_texts


def test_optional_dependency_is_not_added_to_base_install():
    data = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8"))
    project = data["project"]
    assert not any("zxing-cpp" in req for req in project["dependencies"])
    assert "zxing-cpp>=3.1.1,<4" in project["optional-dependencies"]["qr-zxing"]


def test_real_zxing_round_trip_when_extra_is_installed():
    pytest.importorskip("zxingcpp")
    import qrcode

    payload = "PDS2|m=scoreform|c=class1|w=quiz1|r=rt_" + "1" * 32
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=7, border=4)
    qr.add_data(payload)
    qr.make(fit=True)
    image = np.array(qr.make_image(fill_color="black", back_color="white").convert("RGB"))
    result = adapter.decode_qr_with_zxing(image)
    assert result.status == "decoded"
    assert result.payload_texts == (payload,)
