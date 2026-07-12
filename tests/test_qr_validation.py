import cv2
import numpy as np
import pytest
import qrcode

from scoreform import scoring
from scoreform.config import IMG_HEIGHT, IMG_WIDTH

VALID_QR_PAYLOAD = (
    "PDS1|module=scoreform|class=english9_p2|"
    "aid=rj_act1_quiz|sid=1001|page=1"
)
OMR1_QR_PAYLOAD = "OMR1|class=english9_p2|aid=rj_act1_quiz|sid=1001"
VALID_QR_METADATA = {
    "class_id": "english9_p2",
    "assignment_id": "rj_act1_quiz",
    "student_id": "1001",
    "page": 1,
}


def _make_qr_image(payload):
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(payload)
    qr.make(fit=True)
    pil_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)


def test_parse_qr_valid_pds1():
    parsed = scoring.parse_qr_payload(VALID_QR_PAYLOAD)
    assert parsed == VALID_QR_METADATA


def test_parse_qr_rejects_omr1(capsys):
    assert scoring.parse_qr_payload(OMR1_QR_PAYLOAD) is None
    assert (
        "Error: QR payload invalid: unsupported payload schema; expected PDS1."
        in capsys.readouterr().out
    )


def test_parse_qr_strips_payload():
    assert scoring.parse_qr_payload(f"  {VALID_QR_PAYLOAD}  ") == VALID_QR_METADATA


@pytest.mark.parametrize(
    "payload",
    [
        None,
        "",
        "PDS1|class=english9_p2|aid=rj_act1_quiz|sid=1001",
        (
            "PDS1|module=quillan|class=english9_p2|"
            "aid=rj_act1_quiz|sid=1001|page=1"
        ),
        "UNKNOWN|class=english9_p2|aid=rj_act1_quiz|sid=1001",
    ],
)
def test_parse_qr_rejects_invalid_payload(payload):
    assert scoring.parse_qr_payload(payload) is None


def test_parse_qr_delegates_pds1_to_pds_core(monkeypatch):
    class ParsedPayload:
        module = "scoreform"
        class_id = "class_from_core"
        assignment_id = "assignment_from_core"
        student_id = "student_from_core"
        page = 2

    seen = []

    def fake_parse(payload):
        seen.append(payload)
        return ParsedPayload()

    monkeypatch.setattr(scoring, "parse_pds1_payload", fake_parse)

    assert scoring.parse_qr_payload("  PDS1|delegated payload  ") == {
        "class_id": "class_from_core",
        "assignment_id": "assignment_from_core",
        "student_id": "student_from_core",
        "page": 2,
    }
    assert seen == ["PDS1|delegated payload"]


def test_parse_qr_result_still_passes_metadata_validation():
    parsed = scoring.parse_qr_payload(VALID_QR_PAYLOAD)

    assert scoring.validate_qr_metadata(parsed)


def test_is_safe_qr_identifier_accepts():
    ok = ["english9_p2", "rj_act1_quiz", "student-1001", "1001"]
    for v in ok:
        assert scoring.is_safe_qr_identifier(v)


def test_is_safe_qr_identifier_rejects():
    bad = ["../secret", "..\\secret", "classes/foo", "C:\\Users\\Teacher", "/absolute/path", "rj.act1.quiz", "english 9 p2", "", None]
    for v in bad:
        assert not scoring.is_safe_qr_identifier(v)


def test_validate_qr_metadata():
    good = {"class_id": "english9_p2", "assignment_id": "rj_act1_quiz", "student_id": "1001", "page": 1}
    assert scoring.validate_qr_metadata(good)

    bad = {"class_id": "../secret", "assignment_id": "rj_act1_quiz", "student_id": "1001", "page": 1}
    assert not scoring.validate_qr_metadata(bad)


def test_decode_qr_from_generated_image():
    img = _make_qr_image(VALID_QR_PAYLOAD)

    assert scoring.decode_qr_from_image(img) == VALID_QR_METADATA


def test_decode_qr_from_image_uses_grayscale_fallback(monkeypatch):
    class FakeDetector:
        def detectAndDecode(self, img):
            if len(img.shape) == 2:
                return VALID_QR_PAYLOAD, None, None
            return "", None, None

    monkeypatch.setattr(scoring.cv2, "QRCodeDetector", lambda: FakeDetector())

    img = np.ones((200, 200, 3), dtype=np.uint8) * 255
    assert scoring.decode_qr_from_image(img) == VALID_QR_METADATA


def test_decode_qr_from_image_uses_expected_region_crop(monkeypatch):
    page = np.ones((IMG_HEIGHT, IMG_WIDTH, 3), dtype=np.uint8) * 255
    qr_img = cv2.resize(_make_qr_image(VALID_QR_PAYLOAD), (100, 100))
    page[220:320, 950:1050] = qr_img

    expected_crop_shape = (int(IMG_HEIGHT * 0.38), IMG_WIDTH - int(IMG_WIDTH * 0.58))

    def fake_try_decode_qr(detector, img):
        if img.shape[:2] == expected_crop_shape:
            return VALID_QR_PAYLOAD
        return None

    monkeypatch.setattr(scoring, "_try_decode_qr", fake_try_decode_qr)

    assert scoring.decode_qr_from_image(page) == VALID_QR_METADATA


def test_decode_qr_from_image_uses_tight_crop_threshold_5x_fallback(monkeypatch):
    page = np.ones((IMG_HEIGHT, IMG_WIDTH, 3), dtype=np.uint8) * 255
    tight_h = int(IMG_HEIGHT * 0.28) - int(IMG_HEIGHT * 0.06)
    tight_w = int(IMG_WIDTH * 0.92) - int(IMG_WIDTH * 0.68)
    expected_shape = (tight_h * 5, tight_w * 5)

    def fake_try_decode_qr(detector, img):
        if img.shape[:2] == expected_shape and len(img.shape) == 2:
            return VALID_QR_PAYLOAD
        return None

    monkeypatch.setattr(scoring, "_try_decode_qr", fake_try_decode_qr)

    assert scoring.decode_qr_from_image(page) == VALID_QR_METADATA


def test_decode_qr_from_image_rejects_omr1_as_malformed(monkeypatch):
    class FakeDetector:
        def detectAndDecode(self, img):
            if len(img.shape) == 2:
                return OMR1_QR_PAYLOAD, None, None
            return "", None, None

    monkeypatch.setattr(scoring.cv2, "QRCodeDetector", lambda: FakeDetector())

    img = np.ones((200, 200, 3), dtype=np.uint8) * 255
    result = scoring._decode_qr_from_image_with_status(img)

    assert result.metadata is None
    assert result.failure_category == "malformed_qr"
