from scoreform import assignment, roster, workflows


def test_suggest_class_id_examples():
    assert workflows.suggest_class_id("English 9 Period 2") == "english_9_period_2"
    assert workflows.suggest_class_id("English 12 P5") == "english_12_p5"
    assert workflows.suggest_class_id("AP Computer Science") == "ap_computer_science"
    assert workflows.suggest_class_id("English-12 / Period 3") == "english-12_period_3"
    assert workflows.suggest_class_id("Extra   Spaces") == "extra_spaces"
    assert workflows.suggest_class_id("!!!") == ""


def test_suggest_assignment_id_examples():
    assert workflows.suggest_assignment_id("Romeo and Juliet Act 1 Quiz") == "romeo_and_juliet_act_1_quiz"
    assert workflows.suggest_assignment_id("AP CSP Unit 3 Test") == "ap_csp_unit_3_test"
    assert workflows.suggest_assignment_id("No Country / There Will Be Blood") == "no_country_there_will_be_blood"
    assert workflows.suggest_assignment_id("Essay: Hero's Journey") == "essay_heros_journey"
    assert workflows.suggest_assignment_id("Extra   Spaces") == "extra_spaces"
    assert workflows.suggest_assignment_id("!!!") == ""


def test_discover_class_rosters_finds_valid_rosters_deterministically(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "classes" / "z_class").mkdir(parents=True)
    workflows.write_roster_csv(
        str(tmp_path / "classes" / "z_class" / "roster.csv"),
        "z_class",
        "1",
        [{"student_id": "1001", "last_name": "Doe", "first_name": "Jane"}],
    )
    workflows.write_roster_csv(
        str(tmp_path / "classes" / "a_class" / "roster.csv"),
        "a_class",
        "2",
        [{"student_id": "1002", "last_name": "Smith", "first_name": "Marcus"}],
    )
    (tmp_path / "classes" / "no_roster").mkdir()
    (tmp_path / "classes" / "bad_class").mkdir()
    (tmp_path / "classes" / "bad_class" / "roster.csv").write_text("not,a,roster\n", encoding="utf-8")

    discovered = workflows.discover_class_rosters()

    assert [item["class_id"] for item in discovered] == ["a_class", "z_class"]


def test_discover_class_rosters_missing_classes_dir_returns_empty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    assert workflows.discover_class_rosters() == []


def test_discover_class_rosters_ignores_mismatched_folder_and_roster_class_id(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    workflows.write_roster_csv(
        str(tmp_path / "classes" / "folder_id" / "roster.csv"),
        "roster_id",
        "1",
        [{"student_id": "1001", "last_name": "Doe", "first_name": "Jane"}],
    )

    assert workflows.discover_class_rosters() == []


def test_parse_class_selection_accepts_single_multiple_whitespace_and_duplicates():
    available = [{"class_id": "a"}, {"class_id": "b"}, {"class_id": "c"}]

    assert workflows.parse_class_selection("1", available) == [available[0]]
    assert workflows.parse_class_selection("1,3", available) == [available[0], available[2]]
    assert workflows.parse_class_selection(" 2 , 3 ", available) == [available[1], available[2]]
    assert workflows.parse_class_selection("2,2,1", available) == [available[1], available[0]]


def test_parse_class_selection_rejects_empty_invalid_and_out_of_range():
    available = [{"class_id": "a"}, {"class_id": "b"}]

    for selection in ["", " ", "1,", "x", "0", "3"]:
        try:
            workflows.parse_class_selection(selection, available)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Expected ValueError for selection {selection!r}")


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


def test_prompt_create_assignment_writes_class_centered_assignment(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    workflows.write_roster_csv(
        str(tmp_path / "classes" / "english_9_period_2" / "roster.csv"),
        "english_9_period_2",
        "2",
        [{"student_id": "1001", "last_name": "Doe", "first_name": "Jane"}],
    )
    responses = iter([
        "1",
        "Romeo and Juliet Act 1 Quiz",
        "",
        "2",
        "A",
        "B",
    ])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(responses))

    assert workflows.prompt_create_assignment() == 0

    output_path = tmp_path / "classes" / "english_9_period_2" / "assignments" / "romeo_and_juliet_act_1_quiz" / "assignment.json"
    loaded = assignment.load_assignment(str(output_path))
    assert loaded is not None
    assert loaded["assignment_id"] == "romeo_and_juliet_act_1_quiz"
    assert loaded["title"] == "Romeo and Juliet Act 1 Quiz"
    assert loaded["question_count"] == 2
    assert loaded["answer_key"] == {1: "A", 2: "B"}


def test_prompt_create_assignment_writes_multiple_classes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for class_id in ["class_a", "class_b"]:
        workflows.write_roster_csv(
            str(tmp_path / "classes" / class_id / "roster.csv"),
            class_id,
            "1",
            [{"student_id": f"{class_id}_1001", "last_name": "Doe", "first_name": "Jane"}],
        )
    responses = iter([
        "1,2",
        "AP CSP Unit 3 Test",
        "unit_3_test",
        "1",
        "C",
    ])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(responses))

    assert workflows.prompt_create_assignment() == 0

    for class_id in ["class_a", "class_b"]:
        output_path = tmp_path / "classes" / class_id / "assignments" / "unit_3_test" / "assignment.json"
        loaded = assignment.load_assignment(str(output_path))
        assert loaded is not None
        assert loaded["title"] == "AP CSP Unit 3 Test"


def test_prompt_create_assignment_skips_existing_without_confirmation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    workflows.write_roster_csv(
        str(tmp_path / "classes" / "class_a" / "roster.csv"),
        "class_a",
        "1",
        [{"student_id": "1001", "last_name": "Doe", "first_name": "Jane"}],
    )
    output_path = tmp_path / "classes" / "class_a" / "assignments" / "existing_assignment" / "assignment.json"
    output_path.parent.mkdir(parents=True)
    original_content = '{"assignment_id": "existing_assignment", "title": "Original"}'
    output_path.write_text(original_content, encoding="utf-8")
    responses = iter([
        "1",
        "Existing Assignment",
        "",
        "1",
        "A",
        "n",
    ])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(responses))

    assert workflows.prompt_create_assignment() == 1
    assert output_path.read_text(encoding="utf-8") == original_content


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
