import json
from pathlib import Path

from pds_core.standards import (
    StandardDefinition,
    StandardsLibrary,
    StandardsProfile,
    load_workspace_standard_usage_events,
    load_workspace_standards_library,
    standards_library_to_dict,
    write_workspace_standards_library,
)

from scoreform import assignment_workflows, workflows


def _write_roster(tmp_path, class_id="test_class"):
    workflows.write_roster_csv(
        str(tmp_path / "classes" / class_id / "roster.csv"),
        class_id,
        "1",
        [{"student_id": "1001", "last_name": "Doe", "first_name": "Jane"}],
    )


def _assignment_path(tmp_path, class_id="test_class", assignment_id="unit_1"):
    return tmp_path / "classes" / class_id / "assignments" / assignment_id / "assignment.json"


def _write_assignment(tmp_path, *, assignment_id="unit_1", title="Unit 1 Quiz"):
    path = _assignment_path(tmp_path, assignment_id=assignment_id)
    workflows.write_assignment_json(
        str(path),
        {
            "assignment_id": assignment_id,
            "title": title,
            "question_count": 3,
            "choices": ["A", "B", "C", "D"],
            "answer_key": {"1": "A", "2": "B", "3": "C"},
            "standards_profile_id": "local_profile",
            "standards": {
                "1": ["local:evidence"],
                "2": [],
                "3": ["local:theme"],
            },
        },
    )
    return path


def _load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _standard(standard_id, code):
    return StandardDefinition(
        standard_id=standard_id,
        code=code,
        source="Local",
        short_name=code,
        description="Local classroom standard.",
        available_modules=("pds-scoreform",),
    )


def test_edit_assignment_handles_no_available_classes(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    assert assignment_workflows.prompt_edit_assignment() == 1

    output = capsys.readouterr().out
    assert "No class rosters found." in output


def test_edit_assignment_handles_class_with_no_assignments(
    tmp_path,
    monkeypatch,
    capsys,
):
    monkeypatch.chdir(tmp_path)
    _write_roster(tmp_path)
    responses = iter(["1"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    assert assignment_workflows.prompt_edit_assignment() == 1

    output = capsys.readouterr().out
    assert "No assignments found for class 'test_class'." in output


def test_edit_assignment_reports_invalid_load_cleanly(
    tmp_path,
    monkeypatch,
    capsys,
):
    monkeypatch.chdir(tmp_path)
    _write_roster(tmp_path)
    path = _assignment_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("{bad json", encoding="utf-8")
    monkeypatch.setattr(
        assignment_workflows,
        "discover_class_assignments",
        lambda _class_id: [{
            "assignment_id": "unit_1",
            "assignment_path": str(path),
            "assignment": {
                "assignment_id": "unit_1",
                "title": "Broken",
            },
        }],
    )
    responses = iter(["1", "1"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    assert assignment_workflows.prompt_edit_assignment() == 1

    output = capsys.readouterr().out
    assert "Could not load assignment" in output
    assert "Traceback" not in output


def test_title_change_is_staged_until_save(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_roster(tmp_path)
    path = _write_assignment(tmp_path)
    before = path.read_text(encoding="utf-8")
    writes = []
    real_write = assignment_workflows.write_assignment_json

    def spy_write(write_path, assignment):
        assert path.read_text(encoding="utf-8") == before
        writes.append((Path(write_path), assignment["title"]))
        return real_write(write_path, assignment)

    monkeypatch.setattr(assignment_workflows, "write_assignment_json", spy_write)
    responses = iter(["1", "1", "1", "Corrected Title", "5", "SAVE"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    assert assignment_workflows.prompt_edit_assignment() == 0

    saved = _load_json(path)
    assert saved["title"] == "Corrected Title"
    assert saved["assignment_id"] == "unit_1"
    assert writes == [(path, "Corrected Title")]


def test_blank_title_is_rejected_and_discard_writes_nothing(
    tmp_path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    _write_roster(tmp_path)
    path = _write_assignment(tmp_path)
    before = path.read_text(encoding="utf-8")
    responses = iter(["1", "1", "1", "", "6"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    assert assignment_workflows.prompt_edit_assignment() == 0

    assert path.read_text(encoding="utf-8") == before


def test_answer_key_change_preserves_locked_fields_and_saves_only_selected_assignment(
    tmp_path,
    monkeypatch,
    capsys,
):
    monkeypatch.chdir(tmp_path)
    _write_roster(tmp_path)
    path = _write_assignment(tmp_path)
    other_path = _write_assignment(tmp_path, assignment_id="unit_2", title="Unit 2")
    other_before = other_path.read_text(encoding="utf-8")
    responses = iter(["1", "1", "2", "2", "D", "", "5", "SAVE"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    assert assignment_workflows.prompt_edit_assignment() == 0

    saved = _load_json(path)
    assert saved["answer_key"] == {"1": "A", "2": "D", "3": "C"}
    assert saved["question_count"] == 3
    assert saved["choices"] == ["A", "B", "C", "D"]
    assert saved["assignment_id"] == "unit_1"
    assert other_path.read_text(encoding="utf-8") == other_before
    output = capsys.readouterr().out
    assert "Current answer for Q2: B" in output


def test_answer_key_editor_can_stage_multiple_different_answers_in_one_session(
    tmp_path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    _write_roster(tmp_path)
    path = _write_assignment(tmp_path)
    responses = iter([
        "1",
        "1",
        "2",
        "2",
        "A",
        "y",
        "3",
        "D",
        "",
        "5",
        "SAVE",
    ])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    assert assignment_workflows.prompt_edit_assignment() == 0

    saved = _load_json(path)
    assert saved["answer_key"] == {"1": "A", "2": "A", "3": "D"}


def test_answer_key_editor_rejects_comma_separated_bulk_selection(
    tmp_path,
    monkeypatch,
    capsys,
):
    monkeypatch.chdir(tmp_path)
    _write_roster(tmp_path)
    path = _write_assignment(tmp_path)
    before = path.read_text(encoding="utf-8")
    writes = []

    def fail_write(write_path, assignment):
        writes.append((write_path, assignment))
        raise AssertionError("comma-separated answer-key edit should not be saved")

    monkeypatch.setattr(assignment_workflows, "write_assignment_json", fail_write)
    responses = iter(["1", "1", "2", "2,3", "", "5"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    assert assignment_workflows.prompt_edit_assignment() == 0

    assert path.read_text(encoding="utf-8") == before
    assert writes == []
    output = capsys.readouterr().out
    assert "Invalid question selection: 2,3" in output


def test_invalid_answer_key_question_selections_are_rejected_without_saving(
    tmp_path,
    monkeypatch,
    capsys,
):
    monkeypatch.chdir(tmp_path)
    _write_roster(tmp_path)
    path = _write_assignment(tmp_path)
    before = path.read_text(encoding="utf-8")
    responses = iter([
        "1",
        "1",
        "2",
        "",
        "y",
        "abc",
        "yes",
        "4",
        "",
        "5",
    ])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    assert assignment_workflows.prompt_edit_assignment() == 0

    assert path.read_text(encoding="utf-8") == before
    output = capsys.readouterr().out
    assert "Error: Select one question." in output
    assert "Invalid question selection: abc" in output
    assert "Question selection out of range: 4" in output


def test_invalid_answer_key_answer_choice_is_rejected_without_saving(
    tmp_path,
    monkeypatch,
    capsys,
):
    monkeypatch.chdir(tmp_path)
    _write_roster(tmp_path)
    path = _write_assignment(tmp_path)
    before = path.read_text(encoding="utf-8")
    responses = iter(["1", "1", "2", "2", "Z", "", "5"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    assert assignment_workflows.prompt_edit_assignment() == 0

    assert path.read_text(encoding="utf-8") == before
    output = capsys.readouterr().out
    assert "Current answer for Q2: B" in output
    assert "Answer must be one of A, B, C, D." in output


def test_no_op_answer_key_edit_does_not_make_assignment_dirty(
    tmp_path,
    monkeypatch,
    capsys,
):
    monkeypatch.chdir(tmp_path)
    _write_roster(tmp_path)
    path = _write_assignment(tmp_path)
    before = path.read_text(encoding="utf-8")
    writes = []

    def fail_write(write_path, assignment):
        writes.append((write_path, assignment))
        raise AssertionError("no-op answer-key edit should not be saved")

    monkeypatch.setattr(assignment_workflows, "write_assignment_json", fail_write)
    responses = iter(["1", "1", "2", "2", "b", "", "5"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    assert assignment_workflows.prompt_edit_assignment() == 0

    assert path.read_text(encoding="utf-8") == before
    assert writes == []
    output = capsys.readouterr().out
    assert "No change staged for Q2." in output
    assert "No answer-key change staged." in output
    assert "No changes to save." in output


def test_cancel_with_unsaved_changes_requires_discard_confirmation(
    tmp_path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    _write_roster(tmp_path)
    path = _write_assignment(tmp_path)
    before = path.read_text(encoding="utf-8")
    responses = iter(["1", "1", "1", "Draft Title", "6", "no", "6", "DISCARD"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    assert assignment_workflows.prompt_edit_assignment() == 0

    assert path.read_text(encoding="utf-8") == before


def test_staged_answer_key_edits_are_discarded_without_writing(
    tmp_path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    _write_roster(tmp_path)
    path = _write_assignment(tmp_path)
    before = path.read_text(encoding="utf-8")
    responses = iter(["1", "1", "2", "2", "D", "", "6", "DISCARD"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    assert assignment_workflows.prompt_edit_assignment() == 0

    assert path.read_text(encoding="utf-8") == before


def test_standards_can_attach_remove_and_clear_without_usage_or_library_writes(
    tmp_path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    _write_roster(tmp_path)
    path = _write_assignment(tmp_path)
    library = StandardsLibrary(
        standards=(
            _standard("local:evidence", "Evidence"),
            _standard("local:theme", "Theme"),
        ),
        profiles=(StandardsProfile(
            profile_id="local_profile",
            standards=("local:evidence", "local:theme"),
        ),),
    )
    write_workspace_standards_library(tmp_path, library)
    before_library = standards_library_to_dict(load_workspace_standards_library(tmp_path))

    responses = iter([
        "1",
        "1",
        "3",
        "1",
        "2",
        "1,2",
        "4",
        "3",
        "5",
        "5",
        "SAVE",
    ])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    assert assignment_workflows.prompt_edit_assignment() == 0

    saved = _load_json(path)
    assert saved["standards"] == {
        "1": ["local:evidence", "local:theme"],
        "2": ["local:theme"],
        "3": [],
    }
    assert saved["standards_profile_id"] == "local_profile"
    assert standards_library_to_dict(load_workspace_standards_library(tmp_path)) == before_library
    assert load_workspace_standard_usage_events(tmp_path, "2025-2026", "test_class") == ()


def test_save_failure_does_not_claim_success(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    _write_roster(tmp_path)
    path = _write_assignment(tmp_path)
    before = path.read_text(encoding="utf-8")

    def fail_write(_path, _assignment):
        return False

    monkeypatch.setattr(assignment_workflows, "write_assignment_json", fail_write)
    responses = iter([
        "1",
        "1",
        "1",
        "Draft Title",
        "5",
        "SAVE",
        "6",
        "DISCARD",
    ])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    assert assignment_workflows.prompt_edit_assignment() == 0

    assert path.read_text(encoding="utf-8") == before
    output = capsys.readouterr().out
    assert "Error: Failed to save assignment JSON." in output
    assert "Saved assignment:" not in output


def test_assignment_edit_does_not_touch_generated_results_scans_or_roster(
    tmp_path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    _write_roster(tmp_path)
    roster_path = tmp_path / "classes" / "test_class" / "roster.csv"
    roster_before = roster_path.read_text(encoding="utf-8")
    path = _write_assignment(tmp_path)
    assignment_dir = path.parent
    generated_files = {
        assignment_dir / "templates" / "class_packet.pdf": "class packet",
        assignment_dir / "templates" / "individual" / "1001_doe_jane.pdf": "student packet",
        assignment_dir / "results.csv": "historical results",
        tmp_path / "scans_inbox" / "scan.pdf": "scan evidence",
    }
    for generated_path, text in generated_files.items():
        generated_path.parent.mkdir(parents=True, exist_ok=True)
        generated_path.write_text(text, encoding="utf-8")

    responses = iter(["1", "1", "2", "1", "B", "", "5", "SAVE"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    assert assignment_workflows.prompt_edit_assignment() == 0

    assert roster_path.read_text(encoding="utf-8") == roster_before
    for generated_path, text in generated_files.items():
        assert generated_path.read_text(encoding="utf-8") == text
