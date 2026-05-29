import pytest

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
