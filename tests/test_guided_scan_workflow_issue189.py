from __future__ import annotations

from pathlib import Path

from scoreform import guided_scan_workflow
from scoreform.assignment_context import AssignmentContextSession
from scoreform.guided_scan_results import GuidedScanResultTarget, GuidedScanSummary


class _Operation:
    def __init__(self, exit_code: int = 0) -> None:
        self.exit_code = exit_code


def _summary(
    *,
    targets: tuple[GuidedScanResultTarget, ...] = (),
    review_items: int = 0,
    retained: bool = True,
) -> GuidedScanSummary:
    return GuidedScanSummary(
        source_filename="returned.pdf",
        retention_succeeded=retained,
        source_scan_id="scan_synthetic_189" if retained else None,
        source_pages_processed=2,
        completed_attempts=sum(target.durable_attempts for target in targets),
        attempts_appended=sum(target.appended_attempts for target in targets),
        attempts_already_present=sum(
            target.already_present_attempts for target in targets
        ),
        export_failures=0,
        review_items_persisted=review_items,
        review_persistence_failures=0,
        foreign_success_pages=0,
        targets=targets,
        scoring_status="full_success" if targets and not review_items else "partial_success",
        outcome="complete" if targets and not review_items else (
            "needs_review" if review_items and not targets else "partial"
        ),
    )


def test_one_target_continues_to_results_without_extra_target_selection(
    monkeypatch,
    tmp_path: Path,
) -> None:
    session = AssignmentContextSession()
    target = GuidedScanResultTarget("english10", "unit1", 1, 0)
    operation = _Operation()
    summary = _summary(targets=(target,))
    calls = []

    monkeypatch.setattr(
        guided_scan_workflow.workspace,
        "get_scoreform_workspace_root",
        lambda: tmp_path,
    )
    monkeypatch.setattr(
        guided_scan_workflow,
        "execute_routed_scoring_operation",
        lambda source, *, workspace_root: calls.append(
            ("process", source, workspace_root)
        )
        or operation,
    )
    monkeypatch.setattr(
        guided_scan_workflow,
        "build_guided_scan_summary",
        lambda actual, source: summary,
    )
    monkeypatch.setattr(
        guided_scan_workflow,
        "select_guided_result_target",
        lambda targets, **kwargs: calls.append(("target", targets)) or targets[0],
    )
    monkeypatch.setattr(
        guided_scan_workflow,
        "open_guided_result_target",
        lambda actual_session, actual_target, **kwargs: calls.append(
            ("results", actual_session, actual_target, kwargs["workspace_root"])
        )
        or 0,
    )
    responses = iter(("1", "2"))
    monkeypatch.setattr("builtins.input", lambda *_args: next(responses))

    assert (
        guided_scan_workflow.launch_guided_scan_to_results(
            "returned.pdf",
            context_session=session,
            clear_screen_fn=lambda: None,
            pause_for_user_fn=lambda: None,
        )
        == 0
    )
    assert calls[0] == ("process", "returned.pdf", tmp_path)
    assert ("target", (target,)) in calls
    assert ("results", session, target, tmp_path) in calls
    assert sum(call[0] == "process" for call in calls) == 1


def test_partial_success_can_review_exact_source_then_results(
    monkeypatch,
    tmp_path: Path,
) -> None:
    session = AssignmentContextSession()
    target = GuidedScanResultTarget("english10", "unit1", 1, 0)
    operation = _Operation(1)
    summary = _summary(targets=(target,), review_items=2)
    events = []

    monkeypatch.setattr(
        guided_scan_workflow.workspace,
        "get_scoreform_workspace_root",
        lambda: tmp_path,
    )
    monkeypatch.setattr(
        guided_scan_workflow,
        "execute_routed_scoring_operation",
        lambda *_args, **_kwargs: events.append("process") or operation,
    )
    monkeypatch.setattr(
        guided_scan_workflow,
        "build_guided_scan_summary",
        lambda *_args, **_kwargs: summary,
    )
    monkeypatch.setattr(
        guided_scan_workflow,
        "launch_scan_review_menu",
        lambda *, source_scan_id: events.append(("review", source_scan_id)) or 0,
    )
    monkeypatch.setattr(
        guided_scan_workflow,
        "select_guided_result_target",
        lambda targets, **kwargs: targets[0],
    )
    monkeypatch.setattr(
        guided_scan_workflow,
        "open_guided_result_target",
        lambda *_args, **_kwargs: events.append("results") or 0,
    )
    responses = iter(("2", "1", "3"))
    monkeypatch.setattr("builtins.input", lambda *_args: next(responses))

    assert (
        guided_scan_workflow.launch_guided_scan_to_results(
            "returned.pdf",
            context_session=session,
            clear_screen_fn=lambda: None,
            pause_for_user_fn=lambda: None,
        )
        == 1
    )
    assert events == [
        "process",
        ("review", "scan_synthetic_189"),
        "results",
    ]


def test_no_durable_target_never_offers_results(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    session = AssignmentContextSession()
    operation = _Operation(1)
    summary = _summary(review_items=1)
    opened = []

    monkeypatch.setattr(
        guided_scan_workflow.workspace,
        "get_scoreform_workspace_root",
        lambda: tmp_path,
    )
    monkeypatch.setattr(
        guided_scan_workflow,
        "execute_routed_scoring_operation",
        lambda *_args, **_kwargs: operation,
    )
    monkeypatch.setattr(
        guided_scan_workflow,
        "build_guided_scan_summary",
        lambda *_args, **_kwargs: summary,
    )
    monkeypatch.setattr(
        guided_scan_workflow,
        "open_guided_result_target",
        lambda *_args, **_kwargs: opened.append(True) or 0,
    )
    monkeypatch.setattr(
        guided_scan_workflow,
        "launch_scan_review_menu",
        lambda **_kwargs: 0,
    )
    responses = iter(("2",))
    monkeypatch.setattr("builtins.input", lambda *_args: next(responses))

    assert (
        guided_scan_workflow.launch_guided_scan_to_results(
            "returned.pdf",
            context_session=session,
            clear_screen_fn=lambda: None,
            pause_for_user_fn=lambda: None,
        )
        == 1
    )
    assert opened == []
    output = capsys.readouterr().out
    assert "Review recorded assignment results" not in output
    assert "Review unresolved items from this scan" in output


def test_retained_post_processing_back_truthfully_preserves_durable_state(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    session = AssignmentContextSession()
    operation = _Operation(1)
    summary = _summary(review_items=1)

    monkeypatch.setattr(
        guided_scan_workflow.workspace,
        "get_scoreform_workspace_root",
        lambda: tmp_path,
    )
    monkeypatch.setattr(
        guided_scan_workflow,
        "execute_routed_scoring_operation",
        lambda *_args, **_kwargs: operation,
    )
    monkeypatch.setattr(
        guided_scan_workflow,
        "build_guided_scan_summary",
        lambda *_args, **_kwargs: summary,
    )
    monkeypatch.setattr("builtins.input", lambda *_args: "b")

    assert (
        guided_scan_workflow.launch_guided_scan_to_results(
            "returned.pdf",
            context_session=session,
            clear_screen_fn=lambda: None,
            pause_for_user_fn=lambda: None,
        )
        == 1
    )
    output = capsys.readouterr().out
    assert "Returning does not delete retained evidence, results, or review records." in output
