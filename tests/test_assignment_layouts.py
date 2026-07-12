import pytest

from scoreform.assignment import validate_assignment_data
from scoreform.layouts import DEFAULT_LAYOUT_ID


def _assignment(**overrides):
    data = {
        "assignment_id": "unit1",
        "title": "Unit 1",
        "question_count": 2,
        "choices": ["A", "B", "C", "D"],
        "answer_key": {"1": "A", "2": "B"},
        "standards": {},
    }
    data.update(overrides)
    return data


def test_missing_layout_id_normalizes_to_default():
    normalized = validate_assignment_data(_assignment())
    assert normalized is not None
    assert normalized["layout_id"] == DEFAULT_LAYOUT_ID


def test_explicit_default_layout_id_is_accepted():
    normalized = validate_assignment_data(_assignment(layout_id=DEFAULT_LAYOUT_ID))
    assert normalized is not None
    assert normalized["layout_id"] == DEFAULT_LAYOUT_ID


@pytest.mark.parametrize("layout_id", ["", 42, None])
def test_invalid_layout_id_is_rejected(layout_id, capsys):
    assert validate_assignment_data(_assignment(layout_id=layout_id)) is None
    assert "layout_id" in capsys.readouterr().out


def test_compact_layout_id_is_accepted():
    normalized = validate_assignment_data(
        _assignment(layout_id="compact_25q_abcd_v1")
    )
    assert normalized is not None
    assert normalized["layout_id"] == "compact_25q_abcd_v1"


def test_choices_must_match_layout_choices(capsys):
    assert validate_assignment_data(_assignment(choices=["A", "B"])) is None
    assert "must match layout choices" in capsys.readouterr().out
