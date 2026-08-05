from __future__ import annotations

import json

from scoreform import menu_academic_work
from scoreform.cli import main
from scoreform.work_paths import scoreform_work_paths


def _managed_assignment(tmp_path):
    paths = scoreform_work_paths(tmp_path, "class1", "quiz1")
    paths.work_root.mkdir(parents=True)
    paths.assignment_path.write_text(
        json.dumps(
            {
                "assignment_id": "quiz1",
                "title": "Unit Quiz",
                "question_count": 1,
                "choices": ["A", "B", "C", "D"],
                "layout_id": "standard_15q_abcd_v1",
                "answer_key": {"1": "A"},
                "standards": {"1": []},
            }
        ),
        encoding="utf-8",
    )


def _identity_args():
    return ["--class-id", "class1", "--assignment-id", "quiz1"]


def test_help_advertises_academic_work(capsys):
    assert main(["--help"], default_to_menu=False) == 0
    output = capsys.readouterr().out
    assert "scoreform academic-work show" in output
    assert "scoreform academic-work register" in output
    assert "scoreform academic-work update" in output


def test_cli_register_show_replay_and_update(tmp_path, capsys):
    _managed_assignment(tmp_path)
    register = [
        "academic-work",
        "register",
        *_identity_args(),
        "--academic-intent",
        "formative",
        "--lifecycle",
        "planned",
    ]
    assert main(register, default_to_menu=False) == 0
    assert "disposition: created" in capsys.readouterr().out
    assert main(register, default_to_menu=False) == 0
    assert "disposition: existing" in capsys.readouterr().out

    assert main(["academic-work", "show", *_identity_args()], default_to_menu=False) == 0
    shown = capsys.readouterr().out
    assert "registration revision: 1" in shown
    assert "producer contract version: scoreform_academic_work_v1" in shown
    assert "contract_version=null" in shown

    update = [
        "academic-work",
        "update",
        *_identity_args(),
        "--academic-intent",
        "summative",
        "--lifecycle",
        "active",
        "--expected-current-revision",
        "1",
    ]
    assert main(update, default_to_menu=False) == 0
    output = capsys.readouterr().out
    assert "disposition: updated" in output
    assert "registration revision: 2" in output


def test_cli_missing_invalid_duplicate_unknown_and_unsafe_fail_without_traceback(
    tmp_path, capsys
):
    _managed_assignment(tmp_path)
    cases = [
        ["academic-work", "show", "--class-id", "class1"],
        [
            "academic-work",
            "register",
            *_identity_args(),
            "--academic-intent",
            "exam",
            "--lifecycle",
            "active",
        ],
        [
            "academic-work",
            "show",
            *_identity_args(),
            "--class-id",
            "class1",
        ],
        ["academic-work", "show", *_identity_args(), "--unknown", "x"],
        [
            "academic-work",
            "show",
            "--class-id",
            "../class",
            "--assignment-id",
            "quiz1",
        ],
    ]
    for args in cases:
        assert main(args, default_to_menu=False) == 1
        output = capsys.readouterr().out
        assert "Error:" in output
        assert "Traceback" not in output


def test_show_unregistered_is_explicit_and_nonzero(tmp_path, capsys):
    _managed_assignment(tmp_path)
    assert main(["academic-work", "show", *_identity_args()], default_to_menu=False) == 1
    output = capsys.readouterr().out
    assert "registration status: not registered" in output
    assert "Traceback" not in output


def test_teacher_menu_registers_only_after_typed_confirmation(
    tmp_path, monkeypatch, capsys
):
    _managed_assignment(tmp_path)
    assignment_record = {
        "assignment_id": "quiz1",
        "assignment": {"assignment_id": "quiz1", "title": "Unit Quiz"},
    }
    monkeypatch.setattr(
        menu_academic_work,
        "discover_class_rosters",
        lambda: [{"class_id": "class1"}],
    )
    monkeypatch.setattr(
        menu_academic_work,
        "discover_class_assignments",
        lambda _class_id: [assignment_record],
    )
    responses = iter(["1", "1", "1", "1", "2", "REGISTER"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    assert menu_academic_work.launch_academic_work_registration_menu() == 0
    output = capsys.readouterr().out
    assert "Proposed Academic Work Registration request:" in output
    assert "disposition: created" in output
    assert "academic intent: formative" in output
    assert "lifecycle: active" in output


def test_teacher_menu_cancellation_creates_no_registry(tmp_path, monkeypatch, capsys):
    _managed_assignment(tmp_path)
    monkeypatch.setattr(
        menu_academic_work,
        "discover_class_rosters",
        lambda: [{"class_id": "class1"}],
    )
    monkeypatch.setattr(
        menu_academic_work,
        "discover_class_assignments",
        lambda _class_id: [
            {
                "assignment_id": "quiz1",
                "assignment": {"assignment_id": "quiz1", "title": "Unit Quiz"},
            }
        ],
    )
    responses = iter(["1", "1", "3"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    assert menu_academic_work.launch_academic_work_registration_menu() == 0
    assert "Cancelled" in capsys.readouterr().out
    assert not (tmp_path / "registry").exists()
