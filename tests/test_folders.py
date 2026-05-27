import json
from scoreform import folders


def test_assignments_match_equivalent(tmp_path):
    a = {"assignment_id": "x", "title": "t"}
    b = {"title": "t", "assignment_id": "x"}
    p1 = tmp_path / "a.json"
    p2 = tmp_path / "b.json"
    p1.write_text(json.dumps(a), encoding="utf-8")
    p2.write_text(json.dumps(b, indent=2), encoding="utf-8")
    assert folders.assignments_match(str(p1), str(p2))


def test_assignments_not_match(tmp_path):
    a = {"assignment_id": "x", "title": "t"}
    b = {"assignment_id": "x", "title": "different"}
    p1 = tmp_path / "a.json"
    p2 = tmp_path / "b.json"
    p1.write_text(json.dumps(a), encoding="utf-8")
    p2.write_text(json.dumps(b), encoding="utf-8")
    assert not folders.assignments_match(str(p1), str(p2))


def test_load_json_for_comparison_unreadable(tmp_path):
    # Nonexistent path should return None
    assert folders.load_json_for_comparison(str(tmp_path / "nope.json")) is None
