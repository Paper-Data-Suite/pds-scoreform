import json

from scoreform import assignment, workflows
from scoreform.config import MAX_QUESTION_COUNT


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
    assert set(loaded["answer_key"].keys()) == set(range(1, 11))
    assert loaded["standards"] == {}


def test_load_assignment_rejects_invalid_assignment_id(tmp_path):
    path = make_assignment(tmp_path, assignment_id="rj.act1.quiz")
    assert assignment.load_assignment(path) is None


def test_load_assignment_missing_field(tmp_path):
    p = tmp_path / "assignment.json"
    p.write_text(json.dumps({"title": "No ID"}), encoding="utf-8")
    assert assignment.load_assignment(str(p)) is None


def test_load_assignment_accepts_valid_question_counts(tmp_path):
    for question_count in [1, 10, MAX_QUESTION_COUNT]:
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
    path = make_assignment(tmp_path, question_count=MAX_QUESTION_COUNT + 1)
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


def test_load_assignment_normalizes_lowercase_answer_choices(tmp_path):
    path = make_assignment(
        tmp_path,
        question_count=3,
        answer_key={"1": "a", "2": " b ", "3": "c"},
    )
    loaded = assignment.load_assignment(path)
    assert loaded is not None
    assert loaded["answer_key"] == {1: "A", 2: "B", 3: "C"}


def test_load_assignment_rejects_answer_key_question_outside_count(tmp_path):
    path = make_assignment(
        tmp_path,
        question_count=5,
        answer_key={"1": "A", "2": "A", "3": "A", "4": "A", "6": "A"},
    )
    assert assignment.load_assignment(path) is None


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
    monkeypatch.chdir(tmp_path)
    workflows.write_roster_csv(
        str(tmp_path / "classes" / "test_class" / "roster.csv"),
        "test_class",
        "1",
        [{"student_id": "1001", "last_name": "Doe", "first_name": "Jane"}],
    )
    responses = iter([
        "1",
        "Test Assignment V6",
        "test_assignment_v6",
        "3",
        "A",
        "B",
        "C",
    ])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(responses))

    assert workflows.prompt_create_assignment() == 0
    output_path = tmp_path / "classes" / "test_class" / "assignments" / "test_assignment_v6" / "assignment.json"
    saved = json.loads(output_path.read_text(encoding="utf-8"))
    assert saved["standards"] == {"1": [], "2": [], "3": []}

    loaded = assignment.load_assignment(str(output_path))
    assert loaded is not None
    assert loaded["standards"] == {1: [], 2: [], 3: []}


def test_prompt_create_assignment_accepts_max_question_count(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    workflows.write_roster_csv(
        str(tmp_path / "classes" / "test_class" / "roster.csv"),
        "test_class",
        "1",
        [{"student_id": "1001", "last_name": "Doe", "first_name": "Jane"}],
    )
    responses = iter(
        [
            "1",
            "Max Assignment",
            "max_assignment",
            str(MAX_QUESTION_COUNT),
            *["A" for _ in range(MAX_QUESTION_COUNT)],
        ]
    )
    prompts = []

    def fake_input(prompt):
        prompts.append(prompt)
        return next(responses)

    monkeypatch.setattr("builtins.input", fake_input)

    assert workflows.prompt_create_assignment() == 0
    assert f"Question count (1-{MAX_QUESTION_COUNT}): " in prompts

    output_path = tmp_path / "classes" / "test_class" / "assignments" / "max_assignment" / "assignment.json"
    saved = json.loads(output_path.read_text(encoding="utf-8"))
    assert saved["question_count"] == MAX_QUESTION_COUNT
    assert len(saved["answer_key"]) == MAX_QUESTION_COUNT


def test_prompt_create_assignment_rejects_question_count_above_max(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    workflows.write_roster_csv(
        str(tmp_path / "classes" / "test_class" / "roster.csv"),
        "test_class",
        "1",
        [{"student_id": "1001", "last_name": "Doe", "first_name": "Jane"}],
    )
    responses = iter(
        [
            "1",
            "Retry Max Assignment",
            "retry_max_assignment",
            str(MAX_QUESTION_COUNT + 1),
            str(MAX_QUESTION_COUNT),
            *["B" for _ in range(MAX_QUESTION_COUNT)],
        ]
    )
    monkeypatch.setattr("builtins.input", lambda _prompt: next(responses))

    assert workflows.prompt_create_assignment() == 0

    captured = capsys.readouterr()
    assert f"Error: question_count must be an integer from 1 to {MAX_QUESTION_COUNT}." in captured.out

    output_path = tmp_path / "classes" / "test_class" / "assignments" / "retry_max_assignment" / "assignment.json"
    saved = json.loads(output_path.read_text(encoding="utf-8"))
    assert saved["question_count"] == MAX_QUESTION_COUNT


def test_prompt_create_assignment_rejects_unsafe_assignment_id(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    workflows.write_roster_csv(
        str(tmp_path / "classes" / "test_class" / "roster.csv"),
        "test_class",
        "1",
        [{"student_id": "1001", "last_name": "Doe", "first_name": "Jane"}],
    )
    responses = iter([
        "1",
        "Test Assignment",
        "../secret",
    ])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(responses))

    assert workflows.prompt_create_assignment() == 1
    assert not (tmp_path / "classes" / "test_class" / "assignments").exists()


def test_load_answer_key_accepts(tmp_path):
    data = {str(i): ("A" if i % 2 == 1 else "B") for i in range(1, 11)}
    p = tmp_path / "answer_key.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    ak = assignment.load_answer_key(str(p))
    assert ak is not None
    assert isinstance(ak, dict)
    assert set(ak.keys()) == set(range(1, 11))


def test_load_answer_key_accepts_five_questions(tmp_path):
    data = {str(i): "A" for i in range(1, 6)}
    p = tmp_path / "answer_key.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    ak = assignment.load_answer_key(str(p))
    assert ak is not None
    assert len(ak) == 5


def test_load_answer_key_normalizes_lowercase_answer_choices(tmp_path):
    data = {"1": "a", "2": " b ", "3": "c"}
    p = tmp_path / "answer_key.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    ak = assignment.load_answer_key(str(p))
    assert ak == {1: "A", 2: "B", 3: "C"}


def test_normalize_answer_key_rejects_duplicate_normalized_question_numbers(capsys):
    assert assignment._normalize_answer_key({1: "A", "1": "B"}) is None

    captured = capsys.readouterr()
    assert "Error: Duplicate question number '1' in answer_key." in captured.out


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


def test_load_answer_key_rejects_question_above_max(tmp_path):
    data = {str(i): "A" for i in range(1, MAX_QUESTION_COUNT + 2)}
    p = tmp_path / "answer_key.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    assert assignment.load_answer_key(str(p)) is None


def test_load_answer_key_rejects_non_dict(tmp_path):
    p = tmp_path / "answer_key.json"
    p.write_text(json.dumps(["A", "B", "C"]), encoding="utf-8")
    assert assignment.load_answer_key(str(p)) is None
