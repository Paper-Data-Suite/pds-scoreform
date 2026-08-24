from __future__ import annotations

from pathlib import Path

import pytest
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu

from scoreform import guided_scan_context
from scoreform.assignment_context import (
    AssignmentContextRef,
    AssignmentContextResolution,
    AssignmentContextSession,
)
from scoreform.guided_scan_results import GuidedScanResultTarget


def _target(
    class_id: str = "english10",
    assignment_id: str = "unit1",
    *,
    appended: int = 1,
    already: int = 0,
) -> GuidedScanResultTarget:
    return GuidedScanResultTarget(
        class_id=class_id,
        assignment_id=assignment_id,
        appended_attempts=appended,
        already_present_attempts=already,
    )


def test_single_durable_target_requires_no_teacher_selection(monkeypatch) -> None:
    target = _target()
    monkeypatch.setattr(
        "builtins.input",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("one exact target must not prompt")
        ),
    )

    assert guided_scan_context.select_guided_result_target((target,)) is target


def test_multiple_targets_require_explicit_selection(monkeypatch, capsys) -> None:
    first = _target("apcsp", "binary_quiz")
    second = _target("english10", "unit1", appended=0, already=2)
    answers = iter(("9", "2"))
    monkeypatch.setattr("builtins.input", lambda *_args: next(answers))

    chosen = guided_scan_context.select_guided_result_target(
        (first, second),
        clear_screen_fn=lambda: None,
    )

    assert chosen is second
    output = capsys.readouterr().out
    assert "more than one ScoreForm assignment" in output
    assert "apcsp / binary_quiz" in output
    assert "english10 / unit1" in output
    assert "Error:" in output


@pytest.mark.parametrize(
    ("choice", "error_type"),
    (("m", ReturnToMainMenu), ("q", QuitPDS)),
)
def test_multiple_target_choice_preserves_shared_navigation(
    monkeypatch,
    choice: str,
    error_type: type[Exception],
) -> None:
    targets = (_target("apcsp", "binary_quiz"), _target("english10", "unit1"))
    monkeypatch.setattr("builtins.input", lambda *_args: choice)

    with pytest.raises(error_type):
        guided_scan_context.select_guided_result_target(
            targets,
            clear_screen_fn=lambda: None,
        )


def test_valid_target_is_canonically_resolved_then_activated(
    monkeypatch,
    tmp_path: Path,
) -> None:
    session = AssignmentContextSession()
    target = _target()
    record = {
        "class_id": "english10",
        "assignment_id": "unit1",
        "assignment": {"title": "Unit 1"},
    }
    calls = []

    def resolve(actual_session, ref, *, workspace_root):
        calls.append((actual_session, ref, workspace_root))
        return AssignmentContextResolution(ref=ref, record=record)

    monkeypatch.setattr(guided_scan_context, "resolve_assignment_context_ref", resolve)

    resolution = guided_scan_context.activate_guided_result_target(
        session,
        target,
        workspace_root=tmp_path,
    )

    assert resolution.record is record
    assert session.active == AssignmentContextRef("english10", "unit1")
    assert session.recent == (AssignmentContextRef("english10", "unit1"),)
    assert len(calls) == 1
    assert calls[0][2] == tmp_path.resolve()


def test_stale_scan_target_never_falls_through_to_prior_active_context(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    session = AssignmentContextSession()
    old_ref = AssignmentContextRef("english10", "old_quiz")
    session.activate(old_ref, workspace_root=tmp_path)
    target = _target("english10", "deleted_quiz")
    launched = []

    def resolve(_session, ref, *, workspace_root):
        assert ref == AssignmentContextRef("english10", "deleted_quiz")
        assert workspace_root == tmp_path.resolve()
        return AssignmentContextResolution(
            ref=ref,
            stale_reason="Assignment 'deleted_quiz' is no longer available.",
        )

    monkeypatch.setattr(guided_scan_context, "resolve_assignment_context_ref", resolve)

    status = guided_scan_context.open_guided_result_target(
        session,
        target,
        workspace_root=tmp_path,
        launch_results_fn=lambda **kwargs: launched.append(kwargs) or 0,
    )

    assert status == 1
    assert launched == []
    assert session.active == old_ref
    output = capsys.readouterr().out
    assert "deleted_quiz" in output
    assert "No different active assignment was substituted." in output


def test_valid_target_hands_existing_context_session_to_review_results(
    monkeypatch,
    tmp_path: Path,
) -> None:
    session = AssignmentContextSession()
    target = _target("english10", "unit1")
    ref = AssignmentContextRef("english10", "unit1")
    record = {
        "class_id": "english10",
        "assignment_id": "unit1",
        "assignment": {"title": "Unit 1"},
    }
    launches = []

    monkeypatch.setattr(
        guided_scan_context,
        "resolve_assignment_context_ref",
        lambda *_args, **_kwargs: AssignmentContextResolution(
            ref=ref,
            record=record,
        ),
    )

    status = guided_scan_context.open_guided_result_target(
        session,
        target,
        workspace_root=tmp_path,
        launch_results_fn=lambda **kwargs: launches.append(kwargs) or 0,
    )

    assert status == 0
    assert session.active == ref
    assert launches == [{"context_session": session}]
