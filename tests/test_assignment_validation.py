import json
from scoreform import assignment


def make_assignment(tmp_path, **overrides):
    data = {
        "assignment_id": "test_assignment",
        "title": "Test Assignment",
        "question_count": 10,
        "choices": ["A", "B", "C", "D"],
        "answer_key": {str(i): ("A" if i % 2 == 1 else "B") for i in range(1, 11)},
    }
    data.update(overrides)
    p = tmp_path / "assignment.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return str(p)


def test_load_assignment_accepts_valid(tmp_path):
    path = make_assignment(tmp_path)
    loaded = assignment.load_assignment(path)
    assert loaded is not None
    assert loaded["assignment_id"] == "test_assignment"
    assert loaded["question_count"] == 10
    assert isinstance(loaded["answer_key"], dict)


def test_load_assignment_missing_field(tmp_path):
    p = tmp_path / "assignment.json"
    p.write_text(json.dumps({"title": "No ID"}), encoding="utf-8")
    assert assignment.load_assignment(str(p)) is None


def test_load_assignment_wrong_question_count(tmp_path):
    path = make_assignment(tmp_path, question_count=8)
    assert assignment.load_assignment(path) is None


def test_load_assignment_invalid_choices(tmp_path):
    path = make_assignment(tmp_path, choices=["A", "B"])
    assert assignment.load_assignment(path) is None


def test_load_assignment_missing_answer_key_question(tmp_path):
    # create answer_key missing question 10
    data = {
        "assignment_id": "x",
        "title": "t",
        "question_count": 10,
        "choices": ["A", "B", "C", "D"],
        "answer_key": {str(i): "A" for i in range(1, 10)},
    }
    p = tmp_path / "assignment.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    assert assignment.load_assignment(str(p)) is None


def test_load_answer_key_accepts(tmp_path):
    data = {str(i): ("A" if i % 2 == 1 else "B") for i in range(1, 11)}
    p = tmp_path / "answer_key.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    ak = assignment.load_answer_key(str(p))
    assert ak is not None
    assert isinstance(ak, dict)


def test_load_answer_key_rejects_invalid_choice(tmp_path):
    data = {str(i): "Z" for i in range(1, 11)}
    p = tmp_path / "answer_key.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    assert assignment.load_answer_key(str(p)) is None
