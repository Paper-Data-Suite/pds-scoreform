from scoreform import roster


def test_load_roster_accepts_valid(tmp_path):
    p = tmp_path / "roster.csv"
    p.write_text("class_id,student_id,last_name,first_name,period\nenglish9_p2,1001,Doe,Jane,2\nenglish9_p2,1002,Smith,Marcus,2\n", encoding="utf-8")
    res = roster.load_roster(str(p))
    assert res is not None
    assert res["class_id"] == "english9_p2"
    assert len(res["students"]) == 2
    assert res["students"][0] == {
        "class_id": "english9_p2",
        "student_id": "1001",
        "last_name": "Doe",
        "first_name": "Jane",
        "period": "2",
    }


def test_load_roster_accepts_and_preserves_optional_columns(tmp_path):
    p = tmp_path / "roster.csv"
    p.write_text(
        "class_id,student_id,last_name,first_name,period,preferred_name,email,notes\n"
        "english9_p2,1001,Doe,Jane,2,Janie,jdoe@example.com,extra time\n",
        encoding="utf-8",
    )
    res = roster.load_roster(str(p))
    assert res is not None
    assert res["students"][0] == {
        "class_id": "english9_p2",
        "student_id": "1001",
        "last_name": "Doe",
        "first_name": "Jane",
        "period": "2",
        "preferred_name": "Janie",
        "email": "jdoe@example.com",
        "notes": "extra time",
    }


def test_load_roster_allows_empty_optional_fields(tmp_path):
    p = tmp_path / "roster.csv"
    p.write_text(
        "class_id,student_id,last_name,first_name,period,preferred_name,email,notes\n"
        "english9_p2,1001,Doe,Jane,2,Janie,,\n",
        encoding="utf-8",
    )
    res = roster.load_roster(str(p))
    assert res is not None
    assert res["students"][0]["preferred_name"] == "Janie"
    assert res["students"][0]["email"] == ""
    assert res["students"][0]["notes"] == ""


def test_load_roster_strips_optional_fields(tmp_path):
    p = tmp_path / "roster.csv"
    p.write_text(
        "class_id,student_id,last_name,first_name,period,preferred_name\n"
        " english9_p2 , 1001 , Doe , Jane , 2 , Janie \n",
        encoding="utf-8",
    )
    res = roster.load_roster(str(p))
    assert res is not None
    assert res["students"][0]["class_id"] == "english9_p2"
    assert res["students"][0]["student_id"] == "1001"
    assert res["students"][0]["preferred_name"] == "Janie"


def test_load_roster_rejects_invalid_class_id(tmp_path):
    p = tmp_path / "roster.csv"
    p.write_text(
        "class_id,student_id,last_name,first_name,period\n"
        "../secret,1001,Doe,Jane,2\n",
        encoding="utf-8",
    )
    assert roster.load_roster(str(p)) is None


def test_load_roster_rejects_invalid_student_id(tmp_path):
    p = tmp_path / "roster.csv"
    p.write_text(
        "class_id,student_id,last_name,first_name,period\n"
        "english9_p2,classes/foo,Doe,Jane,2\n",
        encoding="utf-8",
    )
    assert roster.load_roster(str(p)) is None


def test_load_roster_rejects_duplicate_student_id(tmp_path):
    p = tmp_path / "roster.csv"
    p.write_text(
        "class_id,student_id,last_name,first_name,period\n"
        "english9_p2,1001,Doe,Jane,2\n"
        "english9_p2,1001,Smith,Marcus,2\n",
        encoding="utf-8",
    )
    assert roster.load_roster(str(p)) is None


def test_load_roster_missing_column(tmp_path):
    p = tmp_path / "roster.csv"
    p.write_text("student_id,last_name,first_name,period\n1001,Doe,Jane,2\n", encoding="utf-8")
    assert roster.load_roster(str(p)) is None


def test_load_roster_empty_required_field(tmp_path):
    p = tmp_path / "roster.csv"
    p.write_text("class_id,student_id,last_name,first_name,period\nenglish9_p2,1001,,Jane,2\n", encoding="utf-8")
    assert roster.load_roster(str(p)) is None


def test_load_roster_header_only(tmp_path):
    p = tmp_path / "roster.csv"
    p.write_text("class_id,student_id,last_name,first_name,period\n", encoding="utf-8")
    assert roster.load_roster(str(p)) is None
