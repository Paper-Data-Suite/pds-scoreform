import json
from scoreform import assignment
from scoreform import workflows


def make_assignment(tmp_path, **overrides):
    question_count = overrides.get("question_count", 10)
    if not isinstance(question_count, int):
        try:
            question_count = int(question_count)
        except Exception:
            question_count = 10

    answer_key = overrides.get(
        "answer_key",
        {str(i): ("A" if i % 2 == 1 else "B") for i in range(1, question_count + 1)},
    )
    data = {
        "assignment_id": "test_assignment",
        "title": "Test Assignment",
        "question_count": question_count,
        "choices": ["A", "B", "C", "D"],
        "answer_key": answer_key,
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
    assert loaded["standards"] == {}


def test_load_assignment_rejects_invalid_assignment_id(tmp_path):
    path = make_assignment(tmp_path, assignment_id="rj.act1.quiz")
    assert assignment.load_assignment(path) is None


def test_load_assignment_missing_field(tmp_path):
    p = tmp_path / "assignment.json"
    p.write_text(json.dumps({"title": "No ID"}), encoding="utf-8")
    assert assignment.load_assignment(str(p)) is None


def test_load_assignment_accepts_valid_question_counts(tmp_path):
    for question_count in [1, 10, 15]:
        path = make_assignment(tmp_path, question_count=question_count)
        loaded = assignment.load_assignment(path)
        assert loaded is not None
        assert loaded["question_count"] == question_count
        assert len(loaded["answer_key"]) == question_count


def test_load_assignment_accepts_other_valid_question_count(tmp_path):
    path = make_assignment(tmp_path, question_count=8)
    assert assignment.load_assignment(path) is not None


def test_load_assignment_invalid_question_count_zero(tmp_path):
    path = make_assignment(tmp_path, question_count=0)
    assert assignment.load_assignment(path) is None


def test_load_assignment_invalid_question_count_too_large(tmp_path):
    path = make_assignment(tmp_path, question_count=16)
    assert assignment.load_assignment(path) is None


def test_load_assignment_invalid_question_count_non_integer(tmp_path):
    path = make_assignment(tmp_path, question_count="10")
    assert assignment.load_assignment(path) is None


def test_load_assignment_invalid_choices(tmp_path):
    path = make_assignment(tmp_path, choices=["A", "B"])
    assert assignment.load_assignment(path) is None


def test_load_assignment_missing_answer_key_question(tmp_path):
    # create answer_key missing the final required question
    data = {
        "assignment_id": "x",
        "title": "t",
        "question_count": 5,
        "choices": ["A", "B", "C", "D"],
        "answer_key": {str(i): "A" for i in range(1, 5)},
    }
    p = tmp_path / "assignment.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    assert assignment.load_assignment(str(p)) is None


def test_load_assignment_rejects_extra_answer_key_question(tmp_path):
    data = {
        "assignment_id": "x",
        "title": "t",
        "question_count": 5,
        "choices": ["A", "B", "C", "D"],
        "answer_key": {str(i): "A" for i in range(1, 7)},
    }
    p = tmp_path / "assignment.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    assert assignment.load_assignment(str(p)) is None


def test_load_assignment_rejects_invalid_answer_choice(tmp_path):
    data = {
        "assignment_id": "x",
        "title": "t",
        "question_count": 5,
        "choices": ["A", "B", "C", "D"],
        "answer_key": {str(i): ("Z" if i == 3 else "A") for i in range(1, 6)},
    }
    p = tmp_path / "assignment.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    assert assignment.load_assignment(str(p)) is None


def test_load_assignment_accepts_empty_standards_object(tmp_path):
    path = make_assignment(tmp_path, standards={})
    loaded = assignment.load_assignment(path)
    assert loaded is not None
    assert loaded["standards"] == {}


def test_load_assignment_accepts_valid_standards(tmp_path):
    standards = {
        "1": ["RL.CI.11-12.2"],
        "3": ["RL.IT.11-12.3", "L.VI.11-12.4"],
        "5": ["RL.CR.11-12.1"],
    }
    path = make_assignment(tmp_path, question_count=5, standards=standards)
    loaded = assignment.load_assignment(path)
    assert loaded is not None
    assert loaded["standards"] == {
        1: ["RL.CI.11-12.2"],
        3: ["RL.IT.11-12.3", "L.VI.11-12.4"],
        5: ["RL.CR.11-12.1"],
    }


def test_load_assignment_accepts_empty_per_question_standards(tmp_path):
    standards = {str(i): [] for i in range(1, 4)}
    path = make_assignment(tmp_path, question_count=3, standards=standards)
    loaded = assignment.load_assignment(path)
    assert loaded is not None
    assert loaded["standards"] == {1: [], 2: [], 3: []}


def test_load_assignment_accepts_missing_standards_keys(tmp_path):
    path = make_assignment(
        tmp_path,
        question_count=4,
        standards={"2": ["RL.CI.11-12.2"]},
    )
    loaded = assignment.load_assignment(path)
    assert loaded is not None
    assert loaded["standards"] == {2: ["RL.CI.11-12.2"]}


def test_load_assignment_rejects_standards_key_beyond_question_count(tmp_path):
    path = make_assignment(
        tmp_path,
        question_count=3,
        standards={"4": ["RL.CI.11-12.2"]},
    )
    assert assignment.load_assignment(path) is None


def test_load_assignment_rejects_invalid_standards_key(tmp_path):
    path = make_assignment(
        tmp_path,
        question_count=3,
        standards={"Q1": ["RL.CI.11-12.2"]},
    )
    assert assignment.load_assignment(path) is None


def test_load_assignment_rejects_non_list_standards_value(tmp_path):
    path = make_assignment(
        tmp_path,
        question_count=3,
        standards={"1": "RL.CI.11-12.2"},
    )
    assert assignment.load_assignment(path) is None


def test_load_assignment_rejects_empty_string_standard(tmp_path):
    path = make_assignment(
        tmp_path,
        question_count=3,
        standards={"1": [""]},
    )
    assert assignment.load_assignment(path) is None


def test_load_assignment_rejects_non_string_standard(tmp_path):
    path = make_assignment(
        tmp_path,
        question_count=3,
        standards={"1": ["RL.CI.11-12.2", 42]},
    )
    assert assignment.load_assignment(path) is None


def test_prompt_create_assignment_includes_empty_standards(tmp_path, monkeypatch):
    output_path = tmp_path / "created_assignment.json"
    responses = iter([
        str(output_path),
        "test_assignment_v6",
        "Test Assignment V6",
        "3",
        "A",
        "B",
        "C",
    ])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(responses))

    assert workflows.prompt_create_assignment() == 0
    saved = json.loads(output_path.read_text(encoding="utf-8"))
    assert saved["standards"] == {"1": [], "2": [], "3": []}

    loaded = assignment.load_assignment(str(output_path))
    assert loaded is not None
    assert loaded["standards"] == {1: [], 2: [], 3: []}


def test_prompt_create_assignment_rejects_unsafe_assignment_id(tmp_path, monkeypatch):
    output_path = tmp_path / "created_assignment.json"
    responses = iter([
        str(output_path),
        "../secret",
    ])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(responses))

    assert workflows.prompt_create_assignment() == 1
    assert not output_path.exists()


def test_load_answer_key_accepts(tmp_path):
    data = {str(i): ("A" if i % 2 == 1 else "B") for i in range(1, 11)}
    p = tmp_path / "answer_key.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    ak = assignment.load_answer_key(str(p))
    assert ak is not None
    assert isinstance(ak, dict)


def test_load_answer_key_accepts_five_questions(tmp_path):
    data = {str(i): "A" for i in range(1, 6)}
    p = tmp_path / "answer_key.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    ak = assignment.load_answer_key(str(p))
    assert ak is not None
    assert len(ak) == 5


def test_load_answer_key_rejects_gapped_questions(tmp_path):
    data = {"1": "A", "3": "B"}
    p = tmp_path / "answer_key.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    assert assignment.load_answer_key(str(p)) is None


def test_load_answer_key_rejects_invalid_choice(tmp_path):
    data = {str(i): "Z" for i in range(1, 11)}
    p = tmp_path / "answer_key.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    assert assignment.load_answer_key(str(p)) is None
