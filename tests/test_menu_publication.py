from __future__ import annotations

import pytest

from scoreform import menu_publication
from scoreform.academic_result_publication import (
    ScoreFormAcademicResultPublicationConflictError,
)


def test_assignment_selection_cancellation_creates_no_state(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        menu_publication,
        "discover_class_rosters",
        lambda: [{"class_id": "class1"}],
    )
    monkeypatch.setattr("builtins.input", lambda _prompt="": "B")
    assert menu_publication.launch_academic_result_publications_menu() == 0
    assert "Cancelled" in capsys.readouterr().out
    assert not (tmp_path / "registry").exists()


def test_menu_exposes_all_management_actions(monkeypatch, capsys):
    assignment = {
        "assignment_id": "quiz1",
        "assignment": {"title": "Quiz"},
    }
    monkeypatch.setattr(
        menu_publication, "_select_assignment", lambda: ("class1", assignment)
    )

    class State:
        producer_head_revision = None
        publications = ()
        withdrawals = ()
        head = None
        catalog_available = False
        catalog_rows = ()

    monkeypatch.setattr(
        menu_publication, "load_scoreform_publication_series_status", lambda *_: State()
    )
    monkeypatch.setattr("builtins.input", lambda _prompt="": "9")
    assert menu_publication.launch_academic_result_publications_menu() == 0
    output = capsys.readouterr().out
    assert "Publish producer head" in output
    assert "Supersede exact Core head" in output
    assert "Republish after head withdrawal" in output
    assert "Withdraw exact publication" in output
    assert "Rebuild full Core catalog" in output


@pytest.mark.parametrize(
    ("action", "confirmation", "inputs"),
    [
        ("publish", "PUBLISH", ["4", "1"]),
        ("supersede", "SUPERSEDE", ["5", "2", "pub_" + "1" * 32]),
        ("republish", "REPUBLISH", ["6", "pub_" + "1" * 32]),
        ("withdraw", "WITHDRAW", ["7", "pub_" + "1" * 32, "private reason"]),
        ("rebuild", "REBUILD", ["8"]),
    ],
)
@pytest.mark.parametrize("response", ["WRONG", ""])
def test_exact_menu_confirmation_wrong_or_cancelled_creates_no_state(
    tmp_path, monkeypatch, capsys, action, confirmation, inputs, response
):
    assignment = {"assignment_id": "quiz1", "assignment": {"title": "Quiz"}}
    monkeypatch.setattr(menu_publication, "_select_assignment", lambda: ("class1", assignment))
    monkeypatch.setattr(menu_publication.workspace, "get_scoreform_workspace_root", lambda: tmp_path)

    class State:
        producer_head_revision = 1
        publications = ()
        withdrawals = ()
        head = None
        catalog_available = False
        catalog_rows = ()

    monkeypatch.setattr(
        menu_publication, "load_scoreform_publication_series_status", lambda *_: State()
    )
    guarded = {
        "publish": "publish_scoreform_academic_results",
        "supersede": "supersede_scoreform_academic_results",
        "republish": "republish_scoreform_academic_results_after_withdrawal",
        "withdraw": "withdraw_scoreform_academic_result_publication",
        "rebuild": "rebuild_full_academic_catalog",
    }
    called = False

    def forbidden(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError(f"{action} ran without {confirmation}")

    monkeypatch.setattr(menu_publication, guarded[action], forbidden)
    answers = iter([*inputs, response])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))
    assert menu_publication.launch_academic_result_publications_menu() == 0
    assert "Cancelled" in capsys.readouterr().out
    assert not called
    assert not (tmp_path / "registry").exists()
    assert not (tmp_path / "exports/manifests").exists()


def test_catalog_lock_path_is_not_exposed_by_menu(
    tmp_path, monkeypatch, capsys
):
    assignment = {
        "assignment_id": "quiz1",
        "assignment": {"title": "Quiz"},
    }
    monkeypatch.setattr(
        menu_publication,
        "_select_assignment",
        lambda: ("class1", assignment),
    )
    monkeypatch.setattr(
        menu_publication.workspace,
        "get_scoreform_workspace_root",
        lambda: tmp_path,
    )

    class State:
        producer_head_revision = 1
        publications = ()
        withdrawals = ()
        head = None
        catalog_available = False
        catalog_rows = ()

    monkeypatch.setattr(
        menu_publication,
        "load_scoreform_publication_series_status",
        lambda *_args, **_kwargs: State(),
    )
    private_path = tmp_path / "registry" / ".locks" / "catalog.lock"
    error = ScoreFormAcademicResultPublicationConflictError(
        f"Academic catalog rebuild lock already exists: {private_path}"
    )
    monkeypatch.setattr(
        menu_publication,
        "rebuild_full_academic_catalog",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(error),
    )
    answers = iter(["8", "REBUILD"])
    monkeypatch.setattr(
        "builtins.input",
        lambda _prompt="": next(answers),
    )

    assert menu_publication.launch_academic_result_publications_menu() == 1
    output = capsys.readouterr().out
    assert "conflicts with current canonical state" in output
    assert str(tmp_path) not in output
    assert str(private_path) not in output
    assert "Traceback" not in output
