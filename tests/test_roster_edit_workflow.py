from pathlib import Path

from pds_core.rosters import RosterReadError

from scoreform import roster, workflows


def _write_roster(path, rows, header=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = header or ["class_id", "student_id", "last_name", "first_name", "period"]
    lines = [",".join(columns)]
    for row in rows:
        lines.append(",".join(row.get(column, "") for column in columns))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _class_roster_path(tmp_path, class_id="english_9_period_2"):
    return tmp_path / "classes" / class_id / "roster.csv"


def _load_students(path):
    loaded = roster.load_roster(path)
    assert loaded is not None
    return loaded["students"]


def test_edit_roster_handles_no_available_rosters(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    assert workflows.prompt_edit_class_roster() == 1

    output = capsys.readouterr().out
    assert "No class rosters found." in output


def test_edit_roster_reports_invalid_load_cleanly(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        workflows,
        "discover_class_rosters",
        lambda: [{
            "class_id": "english_9_period_2",
            "roster_path": str(_class_roster_path(tmp_path)),
            "roster": {"students": []},
        }],
    )
    monkeypatch.setattr(
        workflows,
        "load_class_roster",
        lambda _workspace_root, _class_id: (_ for _ in ()).throw(
            RosterReadError(_class_roster_path(tmp_path), "bad csv")
        ),
    )
    responses = iter(["1"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(responses))

    assert workflows.prompt_edit_class_roster() == 1

    output = capsys.readouterr().out
    assert "Could not load class roster" in output
    assert "Traceback" not in output


def test_add_student_is_staged_until_save_and_preserves_optional_columns(
    tmp_path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    roster_path = _class_roster_path(tmp_path)
    _write_roster(
        roster_path,
        [{
            "class_id": "english_9_period_2",
            "student_id": "1001",
            "last_name": "Doe",
            "first_name": "Jane",
            "period": "2",
            "preferred_name": "Janie",
        }],
        header=[
            "class_id",
            "student_id",
            "last_name",
            "first_name",
            "period",
            "preferred_name",
        ],
    )
    before_save = roster_path.read_text(encoding="utf-8")
    calls = []
    real_write = workflows.write_class_roster

    def spy_write(workspace_root, staged_roster, *, overwrite=False):
        assert roster_path.read_text(encoding="utf-8") == before_save
        calls.append((Path(workspace_root), staged_roster.class_id, overwrite))
        return real_write(workspace_root, staged_roster, overwrite=overwrite)

    monkeypatch.setattr(workflows, "write_class_roster", spy_write)
    responses = iter([
        "1",
        "1",
        "1002",
        "Smith",
        "Marcus",
        "2",
        "Marc",
        "5",
        "SAVE",
    ])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(responses))

    assert workflows.prompt_edit_class_roster() == 0

    students = _load_students(roster_path)
    assert [student["student_id"] for student in students] == ["1001", "1002"]
    assert students[1]["preferred_name"] == "Marc"
    assert calls == [(tmp_path, "english_9_period_2", True)]


def test_duplicate_student_add_is_rejected_without_saving(
    tmp_path,
    monkeypatch,
    capsys,
):
    monkeypatch.chdir(tmp_path)
    roster_path = _class_roster_path(tmp_path)
    _write_roster(
        roster_path,
        [{
            "class_id": "english_9_period_2",
            "student_id": "1001",
            "last_name": "Doe",
            "first_name": "Jane",
            "period": "2",
        }],
    )
    before = roster_path.read_text(encoding="utf-8")
    responses = iter(["1", "1", "1001", "Smith", "Sam", "2", "6"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(responses))

    assert workflows.prompt_edit_class_roster() == 0

    assert roster_path.read_text(encoding="utf-8") == before
    output = capsys.readouterr().out
    assert "duplicate student_id" in output


def test_edit_student_preserves_entered_blanks_and_cannot_change_student_id(
    tmp_path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    roster_path = _class_roster_path(tmp_path)
    _write_roster(
        roster_path,
        [{
            "class_id": "english_9_period_2",
            "student_id": "1001",
            "last_name": "Doe",
            "first_name": "Jane",
            "period": "2",
            "preferred_name": "Janie",
        }],
        header=[
            "class_id",
            "student_id",
            "last_name",
            "first_name",
            "period",
            "preferred_name",
        ],
    )
    responses = iter(["1", "2", "1", "", "Alicia", "", "", "5", "SAVE"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(responses))

    assert workflows.prompt_edit_class_roster() == 0

    [student] = _load_students(roster_path)
    assert student["student_id"] == "1001"
    assert student["last_name"] == "Doe"
    assert student["first_name"] == "Alicia"
    assert student["period"] == "2"
    assert student["preferred_name"] == "Janie"


def test_remove_student_requires_confirmation_and_final_removal_is_rejected(
    tmp_path,
    monkeypatch,
    capsys,
):
    monkeypatch.chdir(tmp_path)
    roster_path = _class_roster_path(tmp_path)
    _write_roster(
        roster_path,
        [{
            "class_id": "english_9_period_2",
            "student_id": "1001",
            "last_name": "Doe",
            "first_name": "Jane",
            "period": "2",
        }],
    )
    before = roster_path.read_text(encoding="utf-8")
    responses = iter(["1", "3", "1001", "no", "3", "1", "REMOVE", "6"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(responses))

    assert workflows.prompt_edit_class_roster() == 0

    assert roster_path.read_text(encoding="utf-8") == before
    output = capsys.readouterr().out
    assert "removal not confirmed" in output
    assert "cannot remove the final student" in output


def test_remove_student_save_does_not_touch_generated_or_historical_files(
    tmp_path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    roster_path = _class_roster_path(tmp_path)
    _write_roster(
        roster_path,
        [
            {
                "class_id": "english_9_period_2",
                "student_id": "1001",
                "last_name": "Doe",
                "first_name": "Jane",
                "period": "2",
            },
            {
                "class_id": "english_9_period_2",
                "student_id": "1002",
                "last_name": "Smith",
                "first_name": "Marcus",
                "period": "2",
            },
        ],
    )
    assignment_dir = (
        tmp_path
        / "classes"
        / "english_9_period_2"
        / "assignments"
        / "unit_1"
    )
    templates_dir = assignment_dir / "templates"
    templates_dir.mkdir(parents=True)
    packet = templates_dir / "class_packet.pdf"
    results = assignment_dir / "results.csv"
    assignment_json = assignment_dir / "assignment.json"
    scan = tmp_path / "scans_inbox" / "scan.pdf"
    scan.parent.mkdir()
    for path, text in (
        (packet, "pdf"),
        (results, "results"),
        (assignment_json, '{"assignment_id":"unit_1"}'),
        (scan, "scan"),
    ):
        path.write_text(text, encoding="utf-8")

    responses = iter(["1", "3", "1002", "REMOVE", "5", "SAVE"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(responses))

    assert workflows.prompt_edit_class_roster() == 0

    students = _load_students(roster_path)
    assert [student["student_id"] for student in students] == ["1001"]
    assert packet.read_text(encoding="utf-8") == "pdf"
    assert results.read_text(encoding="utf-8") == "results"
    assert assignment_json.read_text(encoding="utf-8") == '{"assignment_id":"unit_1"}'
    assert scan.read_text(encoding="utf-8") == "scan"


def test_discard_confirmation_exits_without_writing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    roster_path = _class_roster_path(tmp_path)
    _write_roster(
        roster_path,
        [{
            "class_id": "english_9_period_2",
            "student_id": "1001",
            "last_name": "Doe",
            "first_name": "Jane",
            "period": "2",
        }],
    )
    before = roster_path.read_text(encoding="utf-8")
    responses = iter(["1", "1", "1002", "Smith", "Sam", "2", "6", "DISCARD"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(responses))

    assert workflows.prompt_edit_class_roster() == 0

    assert roster_path.read_text(encoding="utf-8") == before


def test_failed_save_does_not_claim_success(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    roster_path = _class_roster_path(tmp_path)
    _write_roster(
        roster_path,
        [{
            "class_id": "english_9_period_2",
            "student_id": "1001",
            "last_name": "Doe",
            "first_name": "Jane",
            "period": "2",
        }],
    )
    before = roster_path.read_text(encoding="utf-8")

    def fail_write(_workspace_root, _staged_roster, *, overwrite=False):
        raise RosterReadError(roster_path, "simulated failure")

    monkeypatch.setattr(workflows, "write_class_roster", fail_write)
    responses = iter([
        "1",
        "1",
        "1002",
        "Smith",
        "Sam",
        "2",
        "5",
        "SAVE",
        "6",
        "DISCARD",
    ])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(responses))

    assert workflows.prompt_edit_class_roster() == 0

    assert roster_path.read_text(encoding="utf-8") == before
    output = capsys.readouterr().out
    assert "Could not save roster" in output
    assert "Saved roster:" not in output
