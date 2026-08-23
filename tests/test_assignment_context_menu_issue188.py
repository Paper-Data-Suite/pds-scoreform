"""Teacher-facing recent/active context integration for ScoreForm issue #188."""

from __future__ import annotations

from pathlib import Path

from pds_core.menu_navigation import ReturnToMainMenu

from scoreform import assignment_workflows, cli, menu_assignment_tasks
from scoreform.assignment_context import AssignmentContextRef, AssignmentContextSession
from scoreform.menu_assignment_context import launch_assignment_context_menu


def _no_screen() -> None:
    return None


def _record(
    class_id: str = "english10_p2",
    assignment_id: str = "unit_quiz",
    title: str = "Unit Quiz",
) -> dict[str, object]:
    return {
        "class_id": class_id,
        "assignment_id": assignment_id,
        "assignment": {"assignment_id": assignment_id, "title": title},
        "results_path": f"classes/{class_id}/modules/scoreform/work/{assignment_id}/results.csv",
    }


def _install_valid_context(monkeypatch, tmp_path: Path, session: AssignmentContextSession):
    record = _record()
    monkeypatch.setattr(
        "scoreform.assignment_context._current_workspace_root",
        lambda workspace_root: tmp_path,
    )
    monkeypatch.setattr(
        "scoreform.workflows.discover_class_rosters",
        lambda workspace_root=None: [{"class_id": "english10_p2"}],
    )
    monkeypatch.setattr(
        "scoreform.workflows.discover_class_assignments",
        lambda class_id, workspace_root=None: [record],
    )
    session.activate(
        AssignmentContextRef("english10_p2", "unit_quiz"),
        workspace_root=tmp_path,
    )
    return record


def test_assignment_management_keeps_seven_numbered_tasks_and_adds_context_control(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr("builtins.input", lambda _prompt="": "b")
    session = AssignmentContextSession()

    assert menu_assignment_tasks.launch_assignment_menu(
        context_session=session,
        clear_screen_fn=_no_screen,
        pause_for_user_fn=_no_screen,
    ) == 0

    output = capsys.readouterr().out
    assert "Active assignment: none" in output
    assert "7. Advanced Tools" in output
    assert "8." not in output
    assert "C. Assignment Context" in output


def test_valid_active_context_banner_uses_current_canonical_title(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    session = AssignmentContextSession()
    _install_valid_context(monkeypatch, tmp_path, session)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "b")

    assert menu_assignment_tasks.launch_assignment_menu(
        context_session=session,
        clear_screen_fn=_no_screen,
        pause_for_user_fn=_no_screen,
    ) == 0

    output = capsys.readouterr().out
    assert "Active assignment: english10_p2 / unit_quiz — Unit Quiz" in output
    assert "results.csv" not in output


def test_context_menu_clear_active_does_not_clear_recent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    session = AssignmentContextSession()
    ref = AssignmentContextRef("english10_p2", "unit_quiz")
    session.activate(ref, workspace_root=tmp_path)
    responses = iter(["3", "b"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))
    monkeypatch.setattr(
        "scoreform.menu_assignment_context.format_active_context_lines",
        lambda _session: ("Active assignment: synthetic",),
    )

    assert launch_assignment_context_menu(
        session,
        clear_screen_fn=_no_screen,
        pause_for_user_fn=_no_screen,
    ) == 0
    assert session.active is None
    assert session.recent == (ref,)


def test_review_results_uses_active_context_without_identity_reselection(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    session = AssignmentContextSession()
    record = _install_valid_context(monkeypatch, tmp_path, session)
    monkeypatch.setattr(
        assignment_workflows,
        "load_assignment_results",
        lambda path: [{"student_id": "synthetic"}],
    )
    monkeypatch.setattr(
        assignment_workflows,
        "summarize_assignment_results",
        lambda rows: rows,
    )
    monkeypatch.setattr(
        assignment_workflows,
        "format_assignment_results_table",
        lambda rows: "RESULT TABLE",
    )

    def unexpected_input(_prompt=""):
        raise AssertionError("active-context result review must not reselect identity")

    monkeypatch.setattr("builtins.input", unexpected_input)

    assert assignment_workflows.launch_view_assignment_results_menu(
        context_session=session
    ) == 0

    output = capsys.readouterr().out
    assert "Using active assignment: english10_p2 / unit_quiz — Unit Quiz" in output
    assert f"Source: {record['results_path']}" in output
    assert "RESULT TABLE" in output


def test_main_menu_reuses_same_context_session_after_main_navigation(
    monkeypatch,
) -> None:
    session = AssignmentContextSession()
    seen: list[AssignmentContextSession] = []

    def fake_assignment_menu(*, context_session=None):
        assert context_session is not None
        seen.append(context_session)
        raise ReturnToMainMenu()

    monkeypatch.setattr(
        assignment_workflows,
        "launch_assignment_menu",
        fake_assignment_menu,
    )
    responses = iter(["1", "q"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    assert cli.launch_menu(context_session=session) == 0
    assert seen == [session]
