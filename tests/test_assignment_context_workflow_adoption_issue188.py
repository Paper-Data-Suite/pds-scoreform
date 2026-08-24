"""Context-aware workflow adoption for ScoreForm issue #188."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from scoreform import menu_assignment_context, menu_assignment_tasks
from scoreform.assignment_context import AssignmentContextRef, AssignmentContextSession


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
        "assignment_path": f"classes/{class_id}/modules/scoreform/work/{assignment_id}/assignment.json",
        "roster_path": f"classes/{class_id}/roster.csv",
        "results_path": f"classes/{class_id}/modules/scoreform/work/{assignment_id}/results.csv",
        "assignment": {
            "assignment_id": assignment_id,
            "title": title,
        },
    }


def test_offer_switch_can_continue_with_active_assignment_without_reselection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AssignmentContextSession()
    ref = AssignmentContextRef("english10_p2", "unit_quiz")
    record = _record()
    session._active = ref

    monkeypatch.setattr(
        menu_assignment_context,
        "resolve_active_assignment_context",
        lambda _session: SimpleNamespace(
            is_valid=True,
            record=record,
            ref=ref,
            stale_reason=None,
        ),
    )
    monkeypatch.setattr(
        menu_assignment_context,
        "select_canonical_assignment",
        lambda *_args, **_kwargs: pytest.fail("canonical reselection was not required"),
    )
    monkeypatch.setattr("builtins.input", lambda _prompt="": "1")

    selected = menu_assignment_context.select_assignment_for_workflow(
        session,
        clear_screen_fn=_no_screen,
        offer_switch=True,
        workflow_title="Edit an Assignment",
    )

    assert selected is record


def test_offer_switch_can_deliberately_select_another_assignment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AssignmentContextSession()
    active_ref = AssignmentContextRef("english10_p2", "unit_quiz")
    active_record = _record()
    replacement_record = _record("english10_p4", "unit_quiz_copy", "Unit Quiz Copy")
    session._active = active_ref

    monkeypatch.setattr(
        menu_assignment_context,
        "resolve_active_assignment_context",
        lambda _session: SimpleNamespace(
            is_valid=True,
            record=active_record,
            ref=active_ref,
            stale_reason=None,
        ),
    )
    monkeypatch.setattr(
        menu_assignment_context,
        "select_canonical_assignment",
        lambda *_args, **_kwargs: replacement_record,
    )
    monkeypatch.setattr("builtins.input", lambda _prompt="": "2")

    selected = menu_assignment_context.select_assignment_for_workflow(
        session,
        clear_screen_fn=_no_screen,
        offer_switch=True,
    )

    assert selected is replacement_record


@pytest.mark.parametrize(
    ("responses", "action_name"),
    [
        (["1", "1", "b", "b"], "_run_create_assignment"),
        (["1", "2", "b", "b"], "_run_copy_assignment"),
        (["1", "3", "b", "b"], "_run_edit_assignment"),
        (["1", "4", "b", "b"], "_run_assignment_presets"),
        (["2", "b"], "_run_print_answer_sheets"),
        (["4", "b"], "_run_review_results"),
        (["5", "b"], "_run_plain_paper_results"),
        (["6", "1", "b", "b"], "_run_academic_work_registration"),
        (["6", "2", "b", "b"], "_run_academic_result_manifests"),
        (["6", "3", "b", "b"], "_run_academic_result_publications"),
    ],
)
def test_task_routes_propagate_one_exact_context_session(
    responses: list[str],
    action_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AssignmentContextSession()
    provided = iter(responses)
    seen: list[AssignmentContextSession | None] = []

    def record(**kwargs: object) -> None:
        value = kwargs.get("context_session")
        seen.append(value if isinstance(value, AssignmentContextSession) else None)

    monkeypatch.setattr(menu_assignment_tasks, action_name, record)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(provided))

    assert (
        menu_assignment_tasks.launch_assignment_menu(
            clear_screen_fn=_no_screen,
            pause_for_user_fn=_no_screen,
            context_session=session,
        )
        == 0
    )
    assert seen == [session]


def test_process_scans_receives_shared_assignment_context_without_mutating_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AssignmentContextSession()
    provided = iter(["3", "1", "b", "b"])
    seen_kwargs: list[dict[str, object]] = []
    before = (session.active, session.recent, session.is_workspace_bound)

    def record(**kwargs: object) -> None:
        seen_kwargs.append(kwargs)

    monkeypatch.setattr(menu_assignment_tasks, "_run_score_scans", record)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(provided))

    assert (
        menu_assignment_tasks.launch_assignment_menu(
            clear_screen_fn=_no_screen,
            pause_for_user_fn=_no_screen,
            context_session=session,
        )
        == 0
    )
    assert len(seen_kwargs) == 1
    assert seen_kwargs[0]["context_session"] is session
    assert (session.active, session.recent, session.is_workspace_bound) == before
