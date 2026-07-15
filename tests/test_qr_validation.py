"""Identifier validation remains active while QR dispatch waits for issue #143."""

import pytest

from scoreform import scoring
from scoreform.migration import ScoreFormMigrationPendingError


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


def test_qr_payload_parsing_stops_at_pds2_dispatch_boundary() -> None:
    with pytest.raises(ScoreFormMigrationPendingError, match=r"#143"):
        scoring.parse_qr_payload("any payload")
