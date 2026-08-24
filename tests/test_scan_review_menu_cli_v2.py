"""Focused teacher-facing scan-review menu and CLI behavior."""

from types import SimpleNamespace

import scoreform.cli_scan_review as cli_review
import scoreform.menu_scan_review as menu_review
from scoreform.scan_review_resolution import (
    ScanReviewPartialOperationError,
    ScoreFormReviewIdentity,
)


def _item(**overrides):
    values = {
        "failure_id": "failure1",
        "status": "unresolved",
        "failure_category": "payload_missing",
        "scoreform_failure_category": "missing_qr",
        "failure_message": "No QR was detected.",
        "source_filename": "scan.pdf",
        "source_page_number": 1,
        "source_scan_id": None,
        "source_sha256": None,
        "stage": "payload_detection",
        "review_copy_path": None,
        "failure_metadata_relative_path": "scans/review/failure1.json",
        "details": None,
        "class_id": None,
        "assignment_id": None,
        "student_id": None,
        "identity": ScoreFormReviewIdentity("none"),
        "diagnostic_identity": ScoreFormReviewIdentity("none"),
        "retained_source_path": None,
        "detected_payload": "PDS2|line\nunsafe",
        "route_locator": None,
        "target": None,
        "resolution_history": (),
        "latest_resolution_details": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_allowed_actions_follow_validated_item_state(tmp_path, monkeypatch) -> None:
    generic = menu_review.allowed_review_actions(tmp_path, _item())
    assert "dismissed_duplicate" not in generic
    assert "manual_entry" not in generic
    assert "manual_marks" not in generic

    monkeypatch.setattr(menu_review, "load_assignment", lambda _path: {"valid": True})
    duplicate = menu_review.allowed_review_actions(
        tmp_path,
        _item(
            scoreform_failure_category="duplicate_page",
            class_id="class1",
            assignment_id="quiz",
            student_id="student1",
        ),
    )
    assert "dismissed_duplicate" in duplicate
    assert "manual_entry" in duplicate
    assert "manual_marks" in duplicate


def test_manual_confirmation_shows_complete_destinations_and_score(
    tmp_path, monkeypatch, capsys
) -> None:
    item = _item()
    assignment = {
        "question_count": 2,
        "answer_key": {"1": "A", "2": "B"},
    }
    monkeypatch.setattr(menu_review, "clear_screen", lambda: None)
    monkeypatch.setattr(menu_review, "print_menu_header", lambda _title: None)
    monkeypatch.setattr(
        menu_review, "_prompt_identity", lambda _item: ("class1", "quiz", "student1")
    )
    monkeypatch.setattr(
        menu_review, "_prompt_manual_answers", lambda *_args: {1: "A", 2: "B"}
    )
    monkeypatch.setattr(menu_review, "load_assignment", lambda _path: assignment)
    expected = object()
    monkeypatch.setattr(menu_review, "resolve_scan_review_item", lambda *_a, **_k: expected)
    answers = iter(("", "", "WRITE"))
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    assert menu_review._perform_action(tmp_path, item, "manual_entry") is expected
    output = capsys.readouterr().out
    assert "Failure: failure1" in output
    assert "Current status: unresolved" in output
    assert "Action: manual_entry" in output
    assert "Final locator:" in output and "Final target:" in output
    assert "Verified or teacher-entered identity:" in output
    assert "Manual score/total: 2/2" in output
    assert "modules/scoreform/work/quiz/results.csv" in output
    assert "Evidence destination:" in output


def test_detail_labels_identity_and_escapes_raw_payload(
    tmp_path, monkeypatch, capsys
) -> None:
    item = _item(
        identity=ScoreFormReviewIdentity(
            "validated_locator",
            "class1",
            "quiz",
            route_id="rt_10000000000000000000000000000000",
        ),
        diagnostic_identity=ScoreFormReviewIdentity(
            "scoreform_diagnostic", "observed_class", "observed_quiz"
        ),
    )
    discovery = SimpleNamespace(items=(item,), warning_count=0)
    monkeypatch.setattr(menu_review.workspace, "get_scoreform_workspace_root", lambda: tmp_path)
    monkeypatch.setattr(menu_review, "discover_scan_review_items", lambda _root: discovery)
    monkeypatch.setattr(menu_review, "clear_screen", lambda: None)
    monkeypatch.setattr(menu_review, "pause_for_user", lambda: None)
    choices = iter(("1", "T", "B", "B"))
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(choices))

    assert menu_review.launch_scan_review_menu() == 0
    output = capsys.readouterr().out
    assert "Validated locator identity" in output
    assert "Observed diagnostic identity" in output
    assert "Raw payload: 'PDS2|line\\nunsafe'" in output


def test_cli_prints_manual_partial_operation_warning(tmp_path, monkeypatch, capsys) -> None:
    partial = ScanReviewPartialOperationError(
        failure_id="failure1",
        result_output_path=(
            "classes/class1/modules/scoreform/work/quiz/results.csv"
        ),
        attempt_number=1,
        result_appended=True,
        result_already_present=False,
        error=OSError("resolution failed"),
    )
    monkeypatch.setattr(cli_review.workspace, "get_scoreform_workspace_root", lambda: tmp_path)
    monkeypatch.setattr(
        cli_review,
        "resolve_scan_review_item",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(partial),
    )

    assert cli_review.run_resolve_scan_review(
        ["failure1", "--action", "cannot_route"]
    ) == 1
    output = capsys.readouterr().out
    assert "The result row exists, but no resolution event was appended." in output
    assert "Retrying will not create another attempt." in output
