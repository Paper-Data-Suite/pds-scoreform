from scoreform import roster, workflows


def test_suggest_class_id_examples():
    assert workflows.suggest_class_id("English 9 Period 2") == "english_9_period_2"
    assert workflows.suggest_class_id("English 12 P5") == "english_12_p5"
    assert workflows.suggest_class_id("AP Computer Science") == "ap_computer_science"
    assert workflows.suggest_class_id("English-12 / Period 3") == "english-12_period_3"
    assert workflows.suggest_class_id("Extra   Spaces") == "extra_spaces"
    assert workflows.suggest_class_id("!!!") == ""


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
    monkeypatch.chdir(tmp_path)
    responses = iter([
        "!!!",
        "classes/foo",
    ])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(responses))

    assert workflows.prompt_create_roster() == 1
    assert not (tmp_path / "classes" / "classes" / "foo" / "roster.csv").exists()


def test_prompt_create_roster_rejects_unsafe_student_id(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    responses = iter([
        "English 9 Period 2",
        "",
        "2",
        "../secret",
    ])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(responses))

    assert workflows.prompt_create_roster() == 1
    assert not (tmp_path / "classes" / "english_9_period_2" / "roster.csv").exists()


def test_prompt_create_roster_writes_class_centered_roster(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    responses = iter([
        "English 9 Period 2",
        "",
        "2",
        "1001",
        "Doe",
        "Jane",
        "n",
    ])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(responses))

    assert workflows.prompt_create_roster() == 0

    output_path = tmp_path / "classes" / "english_9_period_2" / "roster.csv"
    assert output_path.exists()
    assert output_path.read_text(encoding="utf-8").splitlines() == [
        "class_id,student_id,last_name,first_name,period",
        "english_9_period_2,1001,Doe,Jane,2",
    ]

    loaded = roster.load_roster(str(output_path))
    assert loaded is not None
    assert loaded["class_id"] == "english_9_period_2"
    assert len(loaded["students"]) == 1


def test_roster_menu_create_class_roster_flow(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    responses = iter([
        "1",
        "English 12 P5",
        "",
        "5",
        "1002",
        "Smith",
        "Marcus",
        "n",
        "3",
    ])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(responses))

    assert workflows.launch_roster_menu() == 0

    output_path = tmp_path / "classes" / "english_12_p5" / "roster.csv"
    loaded = roster.load_roster(str(output_path))
    assert loaded is not None
    assert loaded["class_id"] == "english_12_p5"
    assert loaded["students"][0]["student_id"] == "1002"


def test_prompt_create_roster_does_not_overwrite_without_confirmation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    output_path = tmp_path / "classes" / "english_9_period_2" / "roster.csv"
    output_path.parent.mkdir(parents=True)
    original_content = (
        "class_id,student_id,last_name,first_name,period\n"
        "english_9_period_2,1001,Doe,Jane,2\n"
    )
    output_path.write_text(original_content, encoding="utf-8")
    responses = iter([
        "English 9 Period 2",
        "",
        "n",
    ])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(responses))

    assert workflows.prompt_create_roster() == 1
    assert output_path.read_text(encoding="utf-8") == original_content
