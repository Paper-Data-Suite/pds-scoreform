import pytest

from pds_core.identifiers import IdentifierValidationError

from scoreform import validation
from scoreform.validation import is_safe_identifier, validate_identifier


@pytest.mark.parametrize(
    "value",
    ["english9_p2", "rj_act1_quiz", "1001", "student-1001"],
)
def test_is_safe_identifier_accepts_valid_examples(value):
    assert is_safe_identifier(value)


@pytest.mark.parametrize(
    "value",
    [
        "../secret",
        "classes/foo",
        "rj.act1.quiz",
        r"C:\Users\Teacher",
        "english 9 p2",
        "",
        None,
    ],
)
def test_is_safe_identifier_rejects_unsafe_examples(value):
    assert not is_safe_identifier(value)


def test_validate_identifier_prints_field_and_value(capsys):
    assert not validate_identifier("class_id", "../secret", context="roster row 2")

    out = capsys.readouterr().out
    assert "class_id" in out
    assert "../secret" in out


def test_is_safe_identifier_delegates_to_pds_core(monkeypatch):
    calls = []

    def fake_is_valid_identifier(value):
        calls.append(value)
        return value == "accepted_by_core"

    monkeypatch.setattr(
        validation.core_identifiers,
        "is_valid_identifier",
        fake_is_valid_identifier,
    )

    assert is_safe_identifier("accepted_by_core")
    assert not is_safe_identifier("english9_p2")
    assert calls == ["accepted_by_core", "english9_p2"]


def test_validate_identifier_delegates_to_pds_core(monkeypatch, capsys):
    calls = []

    def fake_validate_identifier(value, field_name):
        calls.append((value, field_name))
        raise IdentifierValidationError("rejected by core")

    monkeypatch.setattr(
        validation.core_identifiers,
        "validate_identifier",
        fake_validate_identifier,
    )

    assert not validate_identifier("student_id", "1001", context="roster")
    assert calls == [("1001", "student_id")]
    assert "Error: roster student_id is unsafe: '1001'." in capsys.readouterr().out
