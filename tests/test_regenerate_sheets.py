import json
from pathlib import Path

from scoreform import generate_workflows
from scoreform.cli import main


def _managed_files(root, class_id="class1", assignment_id="quiz1"):
    class_dir = root / "classes" / class_id
    assignment_dir = class_dir / "assignments" / assignment_id
    class_dir.mkdir(parents=True, exist_ok=True)
    (class_dir / "roster.csv").write_text(
        "class_id,student_id,last_name,first_name,period\n"
        f"{class_id},1001,Doe,Jane,2\n",
        encoding="utf-8",
    )
    assignment_dir.mkdir(parents=True, exist_ok=True)
    (assignment_dir / "assignment.json").write_text(
        json.dumps({
            "assignment_id": assignment_id,
            "title": "Quiz",
            "question_count": 1,
            "choices": ["A", "B", "C", "D"],
            "answer_key": {"1": "A"},
        }),
        encoding="utf-8",
    )
    return assignment_dir


def _fake_renderers(monkeypatch):
    def render_student(path, _assignment, _student):
        Path(path).write_bytes(b"student")
        return True

    def render_packet(path, _assignment, _roster):
        Path(path).write_bytes(b"packet")
        return True

    monkeypatch.setattr(generate_workflows, "generate_student_pdf", render_student)
    monkeypatch.setattr(generate_workflows, "generate_class_packet_pdf", render_packet)


def test_regenerate_assignment_preserves_and_reports_old_pdf(tmp_path, monkeypatch):
    assignment_dir = _managed_files(tmp_path)
    old_pdf = assignment_dir / "templates" / "individual" / "old_student.pdf"
    old_pdf.parent.mkdir(parents=True)
    old_pdf.write_bytes(b"old")
    _fake_renderers(monkeypatch)

    result = generate_workflows.regenerate_answer_sheets_for_assignment(
        "class1", "quiz1", tmp_path
    )

    assert result.student_count == result.individual_count == 1
    assert result.stale_extra_count == 1
    assert old_pdf.read_bytes() == b"old"
    assert (assignment_dir / "templates" / "class_packet.pdf").is_file()
    assert (assignment_dir / "templates" / "individual" / "1001_doe_jane.pdf").is_file()


def test_regenerate_all_assignments(tmp_path, monkeypatch):
    _managed_files(tmp_path, assignment_id="quiz1")
    _managed_files(tmp_path, assignment_id="quiz2")
    _fake_renderers(monkeypatch)

    results = generate_workflows.regenerate_answer_sheets_for_class("class1", tmp_path)

    assert [result.assignment_id for result in results] == ["quiz1", "quiz2"]


def test_regenerate_cli_argument_rules_and_help(capsys):
    assert main(["regenerate-sheets", "--help"], default_to_menu=False) == 0
    assert main(["regenerate-sheets", "--class-id", "class1"], default_to_menu=False) == 1
    assert main([
        "regenerate-sheets", "--class-id", "class1", "--assignment-id", "quiz1",
        "--all-assignments",
    ], default_to_menu=False) == 1
    assert main([
        "regenerate-sheets", "--class-id", "../bad", "--all-assignments",
    ], default_to_menu=False) == 1
    assert "Usage: scoreform regenerate-sheets" in capsys.readouterr().out


def test_regenerate_cli_one_assignment(tmp_path, monkeypatch, capsys):
    _managed_files(tmp_path)
    _fake_renderers(monkeypatch)

    status = main([
        "regenerate-sheets", "--class-id", "class1", "--assignment-id", "quiz1",
    ], default_to_menu=False)

    assert status == 0
    output = capsys.readouterr().out
    assert "Regenerated answer sheets." in output
    assert "Students: 1" in output
