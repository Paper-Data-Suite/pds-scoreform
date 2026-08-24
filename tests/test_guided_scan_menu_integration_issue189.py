from __future__ import annotations

from scoreform import menu_assignment_tasks, menu_scoring
from scoreform.assignment_context import AssignmentContextSession


def test_process_scans_threads_shared_assignment_context_into_scoring(
    monkeypatch,
) -> None:
    session = AssignmentContextSession()
    calls = []
    responses = iter(("1", "b"))
    monkeypatch.setattr("builtins.input", lambda *_args: next(responses))
    monkeypatch.setattr(
        menu_assignment_tasks,
        "_run_score_scans",
        lambda **kwargs: calls.append(kwargs),
    )

    assert (
        menu_assignment_tasks.launch_process_scans_menu(
            clear_screen_fn=lambda: None,
            pause_for_user_fn=lambda: None,
            context_session=session,
        )
        == 0
    )
    assert len(calls) == 1
    assert calls[0]["context_session"] is session


def test_retained_menu_mode_uses_guided_workflow_and_manual_still_uses_direct_cli(
    monkeypatch,
) -> None:
    session = AssignmentContextSession()
    guided = []
    direct = []

    monkeypatch.setattr(
        menu_scoring,
        "launch_guided_scan_to_results",
        lambda source, **kwargs: guided.append((source, kwargs)) or 0,
    )
    monkeypatch.setattr(
        menu_scoring,
        "run_score",
        lambda args: direct.append(args) or 0,
    )
    monkeypatch.setattr(menu_scoring, "clear_screen", lambda: None)
    monkeypatch.setattr(menu_scoring, "pause_for_user", lambda: None)

    responses = iter(("1",))
    monkeypatch.setattr("builtins.input", lambda *_args: next(responses))
    menu_scoring.prompt_scoring_mode("routed.pdf", context_session=session)

    assert guided == [
        ("routed.pdf", {"context_session": session}),
    ]
    assert direct == []

    responses = iter(("2", "answer_key.json", ""))
    monkeypatch.setattr("builtins.input", lambda *_args: next(responses))
    menu_scoring.prompt_scoring_mode("manual.pdf", context_session=session)

    assert direct == [["manual.pdf", "answer_key.json"]]
    assert len(guided) == 1
