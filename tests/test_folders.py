import json
import os
from pathlib import Path

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


def test_ensure_scan_inbox_uses_core_route_without_modifying_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    route_calls = []
    scan_path = tmp_path / "scans_inbox" / "original_scan.pdf"
    scan_path.parent.mkdir()
    scan_path.write_text("raw scan", encoding="utf-8")

    monkeypatch.setattr(
        folders,
        "scans_inbox_dir",
        lambda root: route_calls.append(root) or Path(root) / "scans_inbox",
    )

    assert folders.ensure_scan_inbox() == "scans_inbox"
    assert route_calls == ["."]
    assert scan_path.read_text(encoding="utf-8") == "raw scan"
    assert [path.name for path in scan_path.parent.iterdir()] == ["original_scan.pdf"]


def test_setup_assignment_folder_rejects_unsafe_identifiers_before_creating_dirs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    roster_path = tmp_path / "roster.csv"
    assignment_path = tmp_path / "assignment.json"
    roster_path.write_text("placeholder", encoding="utf-8")
    assignment_path.write_text("{}", encoding="utf-8")

    result = folders.setup_assignment_folder(
        {"class_id": "../secret", "students": []},
        {"assignment_id": "rj_act1_quiz"},
        str(roster_path),
        str(assignment_path),
    )

    assert result is None
    assert not (tmp_path / "classes").exists()
    assert not (tmp_path / "scans_inbox").exists()


def test_setup_assignment_folder_preserves_core_route_layout(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    roster_path = tmp_path / "incoming_roster.csv"
    assignment_path = tmp_path / "incoming_assignment.json"
    roster_path.write_text("placeholder", encoding="utf-8")
    assignment_path.write_text('{"assignment_id": "act_1_quiz"}', encoding="utf-8")

    result = folders.setup_assignment_folder(
        {"class_id": "english9_p2", "students": []},
        {"assignment_id": "act_1_quiz"},
        str(roster_path),
        str(assignment_path),
    )

    assert result is not None
    assert result["class_dir"] == os.path.join("classes", "english9_p2")
    assert result["assignment_dir"] == os.path.join(
        "classes",
        "english9_p2",
        "assignments",
        "act_1_quiz",
    )
    assert result["roster_copy"] == os.path.join(
        "classes",
        "english9_p2",
        "roster.csv",
    )
