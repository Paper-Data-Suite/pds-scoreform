from scoreform import assignment_workflows
from scoreform.assignment import load_assignment
from scoreform.work_paths import scoreform_work_paths


def test_assignment_creation_writes_canonical_work_and_reports_partial_failure(
    tmp_path, monkeypatch, capsys
) -> None:
    classes = [
        {"class_id": "class_a", "roster": {"students": [{"student_id": "1"}]}},
        {"class_id": "class_b", "roster": {"students": [{"student_id": "2"}]}},
    ]
    blocked = scoreform_work_paths(tmp_path, "class_b", "unit_quiz")
    blocked.work_root.mkdir(parents=True)
    blocked.templates_dir.write_text("collision", encoding="utf-8")

    monkeypatch.setattr(
        assignment_workflows, "discover_class_rosters", lambda: classes
    )
    monkeypatch.setattr(
        assignment_workflows.workspace,
        "get_scoreform_workspace_root",
        lambda: tmp_path,
    )
    monkeypatch.setattr(assignment_workflows, "clear_screen", lambda: None)
    responses = iter(["1,2", "Unit Quiz", "", "", "1", "A", "1"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    assert assignment_workflows.prompt_create_assignment() == 0

    created = scoreform_work_paths(tmp_path, "class_a", "unit_quiz")
    assignment = load_assignment(created.assignment_path)
    assert assignment is not None
    assert assignment["assignment_id"] == "unit_quiz"
    assert created.templates_dir.is_dir()
    assert created.scans_dir.is_dir()
    assert created.debug_dir.is_dir()
    assert not created.class_packet_path.exists()
    assert not (created.work_root / "routes").exists()
    assert not blocked.assignment_path.exists()
    output = capsys.readouterr().out
    assert "Success! Assignment created and validated for 1 class(es)." in output
    assert "Skipped 1 class(es)" in output
