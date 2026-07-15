"""Legacy identifier helpers are inactive while Core owns PDS2 parsing."""

import cv2
import pytest
import qrcode
from pds_core.pds2 import Pds2PayloadError

from scoreform import scoring


@pytest.mark.parametrize("value", ["english9_p2", "rj_act1_quiz", "1001"])
def test_is_safe_qr_identifier_accepts(value) -> None:
    assert scoring.is_safe_qr_identifier(value)


@pytest.mark.parametrize(
    "value", ["", "../secret", "classes/foo", r"C:\Users\Teacher", "quiz.json"]
)
def test_is_safe_qr_identifier_rejects(value) -> None:
    assert not scoring.is_safe_qr_identifier(value)


def test_validate_qr_metadata_remains_available() -> None:
    assert scoring.validate_qr_metadata(
        {
            "class_id": "english9_p2",
            "assignment_id": "rj_act1_quiz",
            "student_id": "1001",
            "page": 1,
        }
    )
    assert not scoring.validate_qr_metadata(
        {
            "class_id": "../secret",
            "assignment_id": "rj_act1_quiz",
            "student_id": "1001",
            "page": 1,
        }
    )


def test_qr_payload_parsing_uses_core_pds2_only() -> None:
    locator = scoring.parse_qr_payload(
        "PDS2|m=scoreform|c=class1|w=quiz1|"
        "r=rt_10000000000000000000000000000000"
    )
    assert locator.module_id == "scoreform"
    with pytest.raises(Pds2PayloadError):
        scoring.parse_qr_payload("any payload")


@pytest.mark.parametrize(
    "payload",
    (
        "PDS2|m=scoreform|c=class1|w=quiz1|"
        "r=rt_10000000000000000000000000000000",
        "PDS2|r=rt_10000000000000000000000000000000|w=quiz1|"
        "c=class1|m=scoreform",
    ),
)
def test_compatibility_image_decoder_returns_core_locator(
    tmp_path, monkeypatch, payload
) -> None:
    path = tmp_path / "qr.png"
    qrcode.make(payload).save(path)
    image = cv2.imread(str(path))
    monkeypatch.setattr(
        scoring,
        "_load_qr_aware_assignment",
        lambda *_args, **_kwargs: pytest.fail("assignment lookup is forbidden"),
    )
    locator = scoring.decode_qr_from_image(image)
    assert locator is not None
    assert locator.module_id == "scoreform"
    assert not isinstance(locator, dict)


@pytest.mark.parametrize(
    "payload",
    ("PDS1|module=scoreform|class=class1", "PDS2|broken"),
)
def test_compatibility_image_decoder_rejects_non_pds2_or_malformed(
    tmp_path, payload
) -> None:
    path = tmp_path / "qr.png"
    qrcode.make(payload).save(path)
    assert scoring.decode_qr_from_image(cv2.imread(str(path))) is None
