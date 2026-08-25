"""Share Results submenu integration for ScoreForm issue #191."""

from scoreform import menu_assignment_tasks
from scoreform.assignment_context import AssignmentContextSession


def _no_screen() -> None:
    return None


def test_share_results_submenu_makes_guided_meridian_path_first(
    monkeypatch,
    capsys,
) -> None:
    answers = iter(["b"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    assert (
        menu_assignment_tasks.launch_share_results_menu(
            clear_screen_fn=_no_screen,
            pause_for_user_fn=_no_screen,
        )
        == 0
    )

    output = capsys.readouterr().out
    assert "1. Share Results with Meridian" in output
    assert "2. Academic Work Registration" in output
    assert "3. Academic Result Manifests" in output
    assert "4. Academic Result Publications" in output
    assert "publishes ScoreForm evidence through Core" in output
    assert "does not automatically send results to Meridian" not in output


def test_guided_share_route_receives_same_assignment_context(
    monkeypatch,
) -> None:
    session = AssignmentContextSession()
    seen = []

    def record(**kwargs):
        seen.append(kwargs["context_session"])

    monkeypatch.setattr(
        menu_assignment_tasks,
        "_run_share_results_with_meridian",
        record,
    )
    answers = iter(["1", "b"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    assert (
        menu_assignment_tasks.launch_share_results_menu(
            clear_screen_fn=_no_screen,
            pause_for_user_fn=_no_screen,
            context_session=session,
        )
        == 0
    )
    assert seen == [session]


def test_exact_advanced_share_routes_remain_reachable(
    monkeypatch,
) -> None:
    routes = (
        ("2", "_run_academic_work_registration"),
        ("3", "_run_academic_result_manifests"),
        ("4", "_run_academic_result_publications"),
    )
    for choice, name in routes:
        calls = []

        def record(**kwargs):
            calls.append(kwargs["context_session"])

        monkeypatch.setattr(menu_assignment_tasks, name, record)
        session = AssignmentContextSession()
        answers = iter([choice, "b"])
        monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))
        assert (
            menu_assignment_tasks.launch_share_results_menu(
                clear_screen_fn=_no_screen,
                pause_for_user_fn=_no_screen,
                context_session=session,
            )
            == 0
        )
        assert calls == [session]
