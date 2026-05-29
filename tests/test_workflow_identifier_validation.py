from scoreform import workflows


def test_write_roster_csv_rejects_unsafe_class_id(tmp_path):
    output_path = tmp_path / "roster.csv"
    students = [{"student_id": "1001", "last_name": "Doe", "first_name": "Jane"}]

    assert not workflows.write_roster_csv(str(output_path), "../secret", "2", students)
    assert not output_path.exists()


def test_write_roster_csv_rejects_unsafe_student_id(tmp_path):
    output_path = tmp_path / "roster.csv"
    students = [{"student_id": "classes/foo", "last_name": "Doe", "first_name": "Jane"}]

    assert not workflows.write_roster_csv(str(output_path), "english9_p2", "2", students)
    assert not output_path.exists()


def test_write_assignment_json_rejects_unsafe_assignment_id(tmp_path):
    output_path = tmp_path / "assignment.json"
    assignment = {
        "assignment_id": r"C:\Users\Teacher",
        "title": "Unsafe",
        "question_count": 1,
        "choices": ["A", "B", "C", "D"],
        "answer_key": {"1": "A"},
        "standards": {"1": []},
    }

    assert not workflows.write_assignment_json(str(output_path), assignment)
    assert not output_path.exists()


def test_prompt_create_roster_rejects_unsafe_class_id(tmp_path, monkeypatch):
    output_path = tmp_path / "roster.csv"
    responses = iter([
        str(output_path),
        "classes/foo",
    ])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(responses))

    assert workflows.prompt_create_roster() == 1
    assert not output_path.exists()


def test_prompt_create_roster_rejects_unsafe_student_id(tmp_path, monkeypatch):
    output_path = tmp_path / "roster.csv"
    responses = iter([
        str(output_path),
        "english9_p2",
        "2",
        "../secret",
    ])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(responses))

    assert workflows.prompt_create_roster() == 1
    assert not output_path.exists()
