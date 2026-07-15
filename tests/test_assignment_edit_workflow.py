"""Assignment editing uses module-qualified ScoreForm discovery."""

from scoreform import assignment_workflows
from scoreform.assignment import load_assignment
from scoreform.folders import setup_assignment_folder
from scoreform.work_paths import scoreform_work_paths
from scoreform.workflows import discover_class_assignments


def test_assignment_edit_reports_no_discovered_scoreform_work(monkeypatch) -> None:
    monkeypatch.setattr(
        assignment_workflows,
        "discover_class_rosters",
        lambda: [{"class_id": "class1"}],
    )
    monkeypatch.setattr("builtins.input", lambda _prompt="": "1")

    monkeypatch.setattr(assignment_workflows, "discover_class_assignments", lambda _class: [])

    assert assignment_workflows.prompt_edit_assignment() == 1


def test_assignment_edit_updates_only_canonical_assignment(tmp_path, monkeypatch) -> None:
    roster = {
        "class_id": "class1",
        "students": [{
            "student_id": "1001", "last_name": "Doe",
            "first_name": "Jane", "period": "1",
        }],
    }
    assignment = {
        "assignment_id": "quiz", "title": "Old title", "question_count": 1,
        "choices": ["A", "B", "C", "D"], "answer_key": {"1": "A"},
        "standards": {"1": []},
    }
    assert setup_assignment_folder(
        roster, assignment, workspace_root=tmp_path
    ) is not None
    records = discover_class_assignments("class1", workspace_root=tmp_path)
    monkeypatch.setattr(
        assignment_workflows,
        "discover_class_rosters",
        lambda: [{"class_id": "class1"}],
    )
    monkeypatch.setattr(
        assignment_workflows,
        "discover_class_assignments",
        lambda _class_id: records,
    )
    monkeypatch.setattr(
        assignment_workflows.workspace,
        "get_scoreform_workspace_root",
        lambda: tmp_path,
    )
    responses = iter(["1", "1", "1", "New title", "5", "SAVE"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))
    monkeypatch.setattr(assignment_workflows, "clear_screen", lambda: None)

    assert assignment_workflows.prompt_edit_assignment() == 0

    paths = scoreform_work_paths(tmp_path, "class1", "quiz")
    saved = load_assignment(paths.assignment_path)
    assert saved["title"] == "New title"
    assert not paths.results_path.exists()
    assert not paths.class_packet_path.exists()
