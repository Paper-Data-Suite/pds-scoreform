import pytest
from scoreform import scoring


def test_parse_qr_valid():
    payload = "OMR1|class=english9_p2|aid=rj_act1_quiz|sid=1001"
    parsed = scoring.parse_qr_payload(payload)
    assert parsed == {
        "class_id": "english9_p2",
        "assignment_id": "rj_act1_quiz",
        "student_id": "1001",
    }


@pytest.mark.parametrize("payload", [None, "", "class=english9_p2|aid=rj_act1_quiz|sid=1001", "OMR1|class=|aid=a|sid=1", "OMR1|class=english9_p2|aid"])
def test_parse_qr_rejects_malformed(payload):
    assert scoring.parse_qr_payload(payload) is None


def test_is_safe_qr_identifier_accepts():
    ok = ["english9_p2", "rj_act1_quiz", "student-1001", "1001"]
    for v in ok:
        assert scoring.is_safe_qr_identifier(v)


def test_is_safe_qr_identifier_rejects():
    bad = ["../secret", "..\\secret", "classes/foo", "C:\\Users\\Teacher", "/absolute/path", "rj.act1.quiz", "english 9 p2", "", None]
    for v in bad:
        assert not scoring.is_safe_qr_identifier(v)


def test_validate_qr_metadata():
    good = {"class_id": "english9_p2", "assignment_id": "rj_act1_quiz", "student_id": "1001"}
    assert scoring.validate_qr_metadata(good)

    bad = {"class_id": "../secret", "assignment_id": "rj_act1_quiz", "student_id": "1001"}
    assert not scoring.validate_qr_metadata(bad)
