from scoreform import roster


def test_load_roster_accepts_valid(tmp_path):
    p = tmp_path / "roster.csv"
    p.write_text("class_id,student_id,last_name,first_name,period\nenglish9_p2,1001,Doe,Jane,2\nenglish9_p2,1002,Smith,Marcus,2\n", encoding="utf-8")
    res = roster.load_roster(str(p))
    assert res is not None
    assert res["class_id"] == "english9_p2"
    assert len(res["students"]) == 2


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
