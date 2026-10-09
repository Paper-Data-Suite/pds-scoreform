"""Issue #225 Slice 13: guarded direct CLI and menu recovery surfaces."""

from __future__ import annotations

import pytest
from pds_core.pds2 import serialize_pds2_payload
from test_issue225_scan_recovery_dispatch import _scoring_registry
from test_issue225_scan_recovery_preflight import _record_route, _snapshot, _workspace

import scoreform.cli as cli
import scoreform.cli_scan_recovery as recovery_cli
from scoreform.cli_scan_recovery import (
    ScoreFormRecoveryInterfaceError,
    parse_recovery_page_spec,
    run_recover_scan_review,
)
from scoreform.menu_scan_recovery import run_teacher_scan_recovery
from scoreform.results import load_routed_results_history


def _payload(route):
    return serialize_pds2_payload(route.locator)


def _workspace_cli(tmp_path, monkeypatch):
    route, page, _retained, failure = _workspace(tmp_path)
    monkeypatch.setattr(
        recovery_cli.workspace,
        "get_scoreform_workspace_root",
        lambda: tmp_path,
    )
    return route, page, failure


def test_parse_explicit_and_recorded_route_and_reject_inferred_identity(tmp_path):
    route, _page, _retained, _failure = _workspace(tmp_path)
    explicit = parse_recovery_page_spec(f"failure1={_payload(route)}")
    assert explicit.route_locator == route.locator
    assert not explicit.use_recorded_route
    assert parse_recovery_page_spec("failure1=@recorded").use_recorded_route
    with pytest.raises(ScoreFormRecoveryInterfaceError, match="Recorded-route"):
        parse_recovery_page_spec("failure1=@recorded", allow_route_correction=True)
    with pytest.raises(ScoreFormRecoveryInterfaceError, match="canonical"):
        parse_recovery_page_spec("failure1=guessed", allow_route_correction=True)
    with pytest.raises(ScoreFormRecoveryInterfaceError, match="Each --page"):
        parse_recovery_page_spec("failure1")


def test_cli_preview_has_no_writes_and_shows_teacher_identity(
    tmp_path, monkeypatch, capsys
):
    route, page, _failure = _workspace_cli(tmp_path, monkeypatch)
    before = _snapshot(tmp_path)
    assert run_recover_scan_review(["--page", f"failure1={_payload(route)}"]) == 0
    output = capsys.readouterr().out
    assert "READ ONLY" in output
    assert page.student_id in output
    assert "RECOVER" in output
    assert _snapshot(tmp_path) == before


@pytest.mark.parametrize("args", [
    ["--page", "failure1=@recorded", "--apply"],
    ["--page", "failure1=@recorded", "--apply", "--confirm", "yes"],
    ["--page", "failure1=@recorded", "--confirm", "RECOVER"],
])
def test_cli_requires_exact_mutation_confirmation(tmp_path, monkeypatch, args):
    _workspace_cli(tmp_path, monkeypatch)
    before = _snapshot(tmp_path)
    assert run_recover_scan_review(args) == 1
    assert _snapshot(tmp_path) == before


def test_cli_new_route_persists_and_retry_does_not_duplicate(
    tmp_path, monkeypatch, capsys
):
    route, page, _failure = _workspace_cli(tmp_path, monkeypatch)
    _scoring_registry(monkeypatch, [])  # The installed Core route profile is used.
    params = ["--page", f"failure1={_payload(route)}", "--apply", "--confirm", "RECOVER"]
    assert cli.main(["recover-scan-review", *params]) == 0
    assert "verified_complete" in capsys.readouterr().out
    results_path = tmp_path / "classes" / "class1" / "modules" / "scoreform" / "work" / "quiz1" / "results.csv"
    rows = load_routed_results_history(results_path)
    assert len(rows) == 1
    assert rows[0].result.student_id == page.student_id
    before = _snapshot(tmp_path)
    assert cli.main(["recover-scan-review", *params]) == 0
    assert "already_complete" in capsys.readouterr().out
    assert _snapshot(tmp_path) == before


def test_recorded_cli_route_reuses_existing_decision(tmp_path, monkeypatch, capsys):
    route, page, failure = _workspace_cli(tmp_path, monkeypatch)
    _record_route(tmp_path, route, page, failure)
    _scoring_registry(monkeypatch, [])
    before = len(list((tmp_path / "scans" / "review" / "resolutions").glob("*.json")))
    args = ["--page", "failure1=@recorded", "--apply", "--confirm", "RECOVER"]
    assert run_recover_scan_review(args) == 0
    assert "verified_complete" in capsys.readouterr().out
    assert len(list((tmp_path / "scans" / "review" / "resolutions").glob("*.json"))) == before


def test_cli_rejects_unknown_correction_id_before_preview(tmp_path, monkeypatch):
    route, _page, _failure = _workspace_cli(tmp_path, monkeypatch)
    before = _snapshot(tmp_path)
    assert run_recover_scan_review([
        "--page", f"failure1={_payload(route)}", "--correct-failure", "unknown"
    ]) == 1
    assert _snapshot(tmp_path) == before


def test_menu_cancel_before_preview_has_no_effect(tmp_path, monkeypatch):
    _route, _page, _retained, failure = _workspace(tmp_path)
    before = _snapshot(tmp_path)
    answers = iter(["", "B"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    assert run_teacher_scan_recovery(tmp_path, failure) is False
    assert _snapshot(tmp_path) == before


def test_menu_rejects_confirmation_other_than_recover(tmp_path, monkeypatch):
    route, _page, _retained, failure = _workspace(tmp_path)
    before = _snapshot(tmp_path)
    answers = iter(["", _payload(route), "", "WRITE"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    assert run_teacher_scan_recovery(tmp_path, failure) is False
    assert _snapshot(tmp_path) == before


def test_cli_wrong_page_group_fails_closed(tmp_path, monkeypatch):
    route, _page, _failure = _workspace_cli(tmp_path, monkeypatch)
    before = _snapshot(tmp_path)
    assert run_recover_scan_review([
        "--page", f"failure1={_payload(route)}",
        "--page", f"failure1={_payload(route)}",
    ]) == 1
    assert _snapshot(tmp_path) == before


def test_cli_correction_flag_is_explicit(tmp_path, monkeypatch):
    route, _page, _failure = _workspace_cli(tmp_path, monkeypatch)
    selection = parse_recovery_page_spec(
        f"failure1={_payload(route)}", allow_route_correction=True
    )
    assert selection.allow_route_correction


def test_cli_one_page_of_two_returns_explicit_incomplete_state(
    tmp_path, monkeypatch, capsys
):
    from test_issue225_scan_recovery_assembly import _two_page_workspace

    routes, _retained = _two_page_workspace(tmp_path)
    monkeypatch.setattr(
        recovery_cli.workspace, "get_scoreform_workspace_root", lambda: tmp_path
    )
    _scoring_registry(monkeypatch, [])
    args = [
        "--page", f"failure1={_payload(routes[0])}",
        "--apply", "--confirm", "RECOVER",
    ]
    assert run_recover_scan_review(args) == 2
    output = capsys.readouterr().out
    assert "needs_pages" in output
    assert "Missing logical pages: 2" in output
    assert not list(tmp_path.rglob("results.csv"))


def test_scan_review_menu_reaches_confirmed_recovery(
    tmp_path, monkeypatch, capsys
):
    from scoreform import menu_scan_review

    route, _page, _retained, _failure = _workspace(tmp_path)
    _scoring_registry(monkeypatch, [])
    monkeypatch.setattr(
        menu_scan_review.workspace,
        "get_scoreform_workspace_root",
        lambda: tmp_path,
    )
    monkeypatch.setattr(menu_scan_review, "clear_screen", lambda: None)
    monkeypatch.setattr(menu_scan_review, "pause_for_user", lambda: None)
    choices = iter(["1", "R", "", _payload(route), "", "RECOVER", ""])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(choices))
    assert menu_scan_review.launch_scan_review_menu() == 0
    assert "verified_complete" in capsys.readouterr().out
    assert len(list(tmp_path.rglob("results.csv"))) == 1
