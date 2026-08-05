from __future__ import annotations

import json
from pathlib import Path

import scoreform.academic_result_manifest_generation as generation_module
from scoreform import menu_manifest
from scoreform.cli import main
from scoreform.page_scoring import ScoredAnswer
from scoreform.results import ScoreFormRoutedResult, export_scoreform_result_models
from scoreform.work_paths import scoreform_work_paths


def _workspace(tmp_path):
    paths = scoreform_work_paths(tmp_path, "class1", "quiz1")
    paths.work_root.mkdir(parents=True)
    paths.assignment_path.write_text(
        json.dumps(
            {
                "assignment_id": "quiz1",
                "title": "Quiz",
                "question_count": 1,
                "choices": ["A", "B", "C", "D"],
                "layout_id": "standard_15q_abcd_v1",
                "answer_key": {"1": "A"},
                "standards": {"1": []},
            }
        ),
        encoding="utf-8",
    )
    assert export_scoreform_result_models(
        (
            ScoreFormRoutedResult(
                result_origin="plain_paper_manual",
                class_id="class1",
                assignment_id="quiz1",
                student_id="student1",
                last_name="PrivateLast",
                first_name="PrivateFirst",
                period="9",
                page_display="manual",
                score=1,
                total_points=1,
                answers=(ScoredAnswer(1, "A", True),),
                source_file="plain_paper_manual_entry",
            ),
        ),
        workspace_root=tmp_path,
    ).succeeded


def _identity():
    return ["--class-id", "class1", "--assignment-id", "quiz1"]


def _fail_lock_unlink(monkeypatch):
    real_unlink = Path.unlink

    def fail_lock(path, *args, **kwargs):
        if path.name == ".write.lock":
            raise PermissionError("injected lock cleanup failure")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_lock)


def test_cli_help_generate_replay_list_show_validate(tmp_path, capsys):
    _workspace(tmp_path)
    assert main(["manifest", "help"], default_to_menu=False) == 0
    assert "scoreform manifest generate" in capsys.readouterr().out
    assert main(["manifest", "generate", *_identity()], default_to_menu=False) == 0
    generated = capsys.readouterr().out
    assert "disposition: create_initial" in generated
    assert "PrivateLast" not in generated
    assert "student1" not in generated
    assert main(["manifest", "generate", *_identity()], default_to_menu=False) == 0
    assert "disposition: reuse_existing" in capsys.readouterr().out
    assert main(["manifest", "list", *_identity()], default_to_menu=False) == 0
    assert "revision: 1" in capsys.readouterr().out
    assert main(["manifest", "show", *_identity(), "--revision", "1"], default_to_menu=False) == 0
    shown = capsys.readouterr().out
    assert "record-set ID: academic_results" in shown
    assert "PrivateFirst" not in shown and "student1" not in shown
    assert main(["manifest", "validate", *_identity(), "--revision", "1"], default_to_menu=False) == 0
    assert "Valid academic-result manifest revision: 1" in capsys.readouterr().out


def test_cli_rejects_bad_options_and_revisions_without_traceback(tmp_path, capsys):
    _workspace(tmp_path)
    cases = (
        ["manifest", "show", *_identity(), "--revision", "01"],
        ["manifest", "show", *_identity(), "--revision", "0"],
        ["manifest", "list", *_identity(), "--unknown", "x"],
        ["manifest", "list", *_identity(), "extra"],
        ["manifest", "list", *_identity(), "--class-id", "class1"],
    )
    for args in cases:
        assert main(args, default_to_menu=False) == 1
        output = capsys.readouterr().out
        assert "Error:" in output
        assert "Traceback" not in output


def test_menu_requires_typed_confirmation_and_keeps_registration_informational(
    tmp_path, monkeypatch, capsys
):
    _workspace(tmp_path)
    monkeypatch.setattr(
        menu_manifest,
        "discover_class_rosters",
        lambda: ({"class_id": "class1"},),
    )
    paths = scoreform_work_paths(tmp_path, "class1", "quiz1")
    monkeypatch.setattr(
        menu_manifest,
        "discover_class_assignments",
        lambda _class_id: (
            {
                "assignment_id": "quiz1",
                "assignment": {"title": "Quiz"},
                "results_path": paths.results_path,
            },
        ),
    )
    answers = iter(("1", "1", "1", "NO"))
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))
    assert menu_manifest.launch_academic_result_manifests_menu() == 0
    assert "Cancelled" in capsys.readouterr().out
    assert not paths.academic_result_manifests_dir.exists()

    answers = iter(("1", "1", "1", "GENERATE"))
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))
    assert menu_manifest.launch_academic_result_manifests_menu() == 0
    output = capsys.readouterr().out
    assert "Registration status (informational)" in output
    assert "disposition: create_initial" in output
    assert "PrivateLast" not in output and "student1" not in output


def test_generation_write_boundary_is_only_referenced_by_explicit_surfaces():
    references = set()
    for path in Path("scoreform").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "generate_academic_result_manifest(" in text:
            references.add(path.name)
    assert references == {
        "academic_result_manifest_generation.py",
        "cli_manifest.py",
        "menu_manifest.py",
    }


def test_cli_validation_and_lock_cleanup_failure_reports_no_durable_revision(
    tmp_path, monkeypatch, capsys
):
    _workspace(tmp_path)
    paths = scoreform_work_paths(tmp_path, "class1", "quiz1")
    paths.assignment_path.write_bytes(b"{")
    _fail_lock_unlink(monkeypatch)

    assert main(["manifest", "generate", *_identity()], default_to_menu=False) == 1
    output = capsys.readouterr().out
    assert "no manifest revision was confirmed durable" in output
    assert "manifest generation lock could not be removed" in output
    assert "Inspect and resolve the lock before retrying generation" in output
    assert "classes/class1/modules/scoreform/work/quiz1/exports/manifests/academic_results/.write.lock" in output
    assert str(tmp_path) not in output
    assert "Traceback" not in output
    assert not (paths.academic_result_manifests_dir / "1.json").exists()
    assert (paths.academic_result_manifests_dir / ".write.lock").exists()


def test_cli_directory_sync_and_lock_failure_reports_durable_allocation(
    tmp_path, monkeypatch, capsys
):
    _workspace(tmp_path)
    paths = scoreform_work_paths(tmp_path, "class1", "quiz1")

    def fail_directory_sync(_directory):
        raise OSError("injected directory sync failure")

    monkeypatch.setattr(generation_module, "_sync_directory", fail_directory_sync)
    _fail_lock_unlink(monkeypatch)

    assert main(["manifest", "generate", *_identity()], default_to_menu=False) == 1
    output = capsys.readouterr().out
    assert "immutable manifest revision is durably allocated" in output
    assert "revision: 1" in output
    assert "manifest generation lock could not be removed" in output
    assert str(tmp_path) not in output
    assert "Traceback" not in output
    assert (paths.academic_result_manifests_dir / "1.json").exists()
    assert (paths.academic_result_manifests_dir / ".write.lock").exists()


def test_menu_surfaces_nondurable_lock_cleanup_warning(
    tmp_path, monkeypatch, capsys
):
    _workspace(tmp_path)
    paths = scoreform_work_paths(tmp_path, "class1", "quiz1")
    paths.assignment_path.write_bytes(b"{")
    monkeypatch.setattr(
        menu_manifest,
        "discover_class_rosters",
        lambda: ({"class_id": "class1"},),
    )
    monkeypatch.setattr(
        menu_manifest,
        "discover_class_assignments",
        lambda _class_id: (
            {
                "assignment_id": "quiz1",
                "assignment": {"title": "Quiz"},
                "results_path": paths.results_path,
            },
        ),
    )
    answers = iter(("1", "1", "1", "GENERATE"))
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))
    _fail_lock_unlink(monkeypatch)

    assert menu_manifest.launch_academic_result_manifests_menu() == 1
    output = capsys.readouterr().out
    assert "no manifest revision was confirmed durable" in output
    assert "manifest generation lock could not be removed" in output
    assert "Inspect and resolve the lock before retrying generation" in output
    assert str(paths.academic_result_manifests_dir / ".write.lock") not in output
    assert "Traceback" not in output
