"""Teacher-first scan-review menu rendering and cancellation coverage for #190."""

from __future__ import annotations

from types import MappingProxyType, SimpleNamespace

import scoreform.menu_scan_review as menu_review
from scoreform.scan_review_resolution import ScoreFormReviewIdentity
from scoreform.scan_teacher_diagnostics import TeacherScanDiagnostic


def _item(**overrides):
    values = {
        "failure_id": "failure1",
        "status": "unresolved",
        "failure_category": "payload_missing",
        "scoreform_failure_category": "missing_qr",
        "failure_message": "No QR was detected.",
        "stage": "payload_detection",
        "source_filename": "scan.pdf",
        "source_page_number": 1,
        "source_scan_id": "scan_20260824",
        "source_sha256": "a" * 64,
        "class_id": None,
        "assignment_id": None,
        "student_id": None,
        "identity": ScoreFormReviewIdentity("none"),
        "diagnostic_identity": ScoreFormReviewIdentity("none"),
        "retained_source_path": "scans/source/2026-08-24/scan.pdf",
        "review_copy_path": None,
        "detected_payload": "PDS2|secret\\nline",
        "route_locator": None,
        "target": None,
        "failure_metadata_relative_path": "scans/review/failure1.json",
        "resolution_history": (),
        "latest_resolution_details": None,
        "details": SimpleNamespace(
            failure_origin="page_decode",
            diagnostic_paths=(
                "classes/class1/modules/scoreform/work/quiz/debug/page.png",
            ),
            diagnostic_errors=(),
            context=MappingProxyType({}),
        ),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _diagnostic() -> TeacherScanDiagnostic:
    return TeacherScanDiagnostic(
        family="qr",
        headline="No usable routing code was found",
        explanation="ScoreForm could not detect a usable PDS2 QR code on this page.",
        evidence_status="retained",
        evidence_message="The original scan is safely retained in the PDS workspace.",
        guidance="Rescan the complete generated page with the QR area clear and readable.",
        recommended_actions=("rescan_needed", "defer"),
        diagnostic_artifacts_available=True,
    )


def test_primary_teacher_view_excludes_raw_payload_and_opaque_ids(capsys) -> None:
    item = _item(
        identity=ScoreFormReviewIdentity(
            "validated_locator",
            "class1",
            "quiz",
            route_id="rt_10000000000000000000000000000000",
        )
    )

    menu_review._render_teacher_review(item, _diagnostic())
    output = capsys.readouterr().out

    assert "Problem" in output
    assert "No usable routing code was found" in output
    assert "Evidence" in output
    assert "safely retained" in output
    assert "Recommended next step" in output
    assert "Technical details" in output
    assert "PDS2|secret" not in output
    assert "rt_10000000000000000000000000000000" not in output
    assert "failure1" not in output
    assert "aaaaaaaa" not in output


def test_technical_details_preserve_bounded_exact_recovery_information(capsys) -> None:
    item = _item(
        identity=ScoreFormReviewIdentity(
            "validated_locator",
            "class1",
            "quiz",
            route_id="rt_10000000000000000000000000000000",
        ),
        diagnostic_identity=ScoreFormReviewIdentity(
            "scoreform_diagnostic",
            "observed_class",
            "observed_quiz",
        ),
    )

    menu_review._render_technical_details(item)
    output = capsys.readouterr().out

    assert "Technical Scan Details" in output
    assert "Failure ID: failure1" in output
    assert "Core category: payload_missing" in output
    assert "ScoreForm category: missing_qr" in output
    assert "Validated locator identity" in output
    assert "Observed diagnostic identity" in output
    assert "Raw payload: 'PDS2|secret\\\\nline'" in output
    assert "modules/scoreform/work/quiz/debug/page.png" in output


def test_recommended_actions_are_rendered_separately_from_all_available_actions(
    capsys,
) -> None:
    menu_review._render_available_actions(
        ("route_selected", "rescan_needed", "defer"),
        recommended_actions=("rescan_needed", "defer"),
    )
    output = capsys.readouterr().out

    assert "Available actions" in output
    assert "1. Select existing route" in output
    assert "2. Mark rescan needed (recommended)" in output
    assert "3. Defer for later (recommended)" in output
    assert "T. Technical details" in output


def test_non_manual_cancel_is_never_labeled_manual_entry_cancelled(capsys) -> None:
    menu_review._render_cancelled_action("rescan_needed")
    output = capsys.readouterr().out

    assert "Scan Review Not Updated" in output
    assert "Manual Entry Cancelled" not in output
    assert "No result or resolution record was written." in output
    assert "retained evidence" in output


def test_action_specific_cancel_labels_remain_truthful(capsys) -> None:
    menu_review._render_cancelled_action("manual_entry")
    manual_output = capsys.readouterr().out
    assert "Manual Entry Cancelled" in manual_output

    menu_review._render_cancelled_action("route_corrected")
    route_output = capsys.readouterr().out
    assert "Route Correction Cancelled" in route_output
    assert "Manual Entry Cancelled" not in route_output


def test_menu_uses_teacher_projection_before_action_selection(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    item = _item()
    discovery = SimpleNamespace(items=(item,), warning_count=0)
    monkeypatch.setattr(
        menu_review.workspace,
        "get_scoreform_workspace_root",
        lambda: tmp_path,
    )
    monkeypatch.setattr(menu_review, "discover_scan_review_items", lambda _root: discovery)
    monkeypatch.setattr(menu_review, "clear_screen", lambda: None)
    monkeypatch.setattr(menu_review, "pause_for_user", lambda: None)
    monkeypatch.setattr(
        menu_review,
        "allowed_review_actions",
        lambda _root, _item: ("rescan_needed", "defer"),
    )
    monkeypatch.setattr(
        menu_review,
        "project_teacher_scan_diagnostic",
        lambda _item, *, allowed_actions: _diagnostic(),
    )
    choices = iter(("1", "B", "B"))
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(choices))

    assert menu_review.launch_scan_review_menu() == 0
    output = capsys.readouterr().out

    assert "Problem" in output
    assert "Recommended next step" in output
    assert "Available actions" in output
    assert "Raw payload:" not in output


def test_menu_technical_details_are_explicit_secondary_choice(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    item = _item()
    discovery = SimpleNamespace(items=(item,), warning_count=0)
    monkeypatch.setattr(
        menu_review.workspace,
        "get_scoreform_workspace_root",
        lambda: tmp_path,
    )
    monkeypatch.setattr(menu_review, "discover_scan_review_items", lambda _root: discovery)
    monkeypatch.setattr(menu_review, "clear_screen", lambda: None)
    monkeypatch.setattr(menu_review, "pause_for_user", lambda: None)
    monkeypatch.setattr(
        menu_review,
        "allowed_review_actions",
        lambda _root, _item: ("rescan_needed",),
    )
    choices = iter(("1", "T", "B", "B"))
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(choices))

    assert menu_review.launch_scan_review_menu() == 0
    output = capsys.readouterr().out

    assert "T. Technical details" in output
    assert "Technical Scan Details" in output
    assert "Raw payload: 'PDS2|secret\\\\nline'" in output


def test_cancelled_nonmanual_menu_action_preserves_no_write_message(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    item = _item()
    discovery = SimpleNamespace(items=(item,), warning_count=0)
    monkeypatch.setattr(
        menu_review.workspace,
        "get_scoreform_workspace_root",
        lambda: tmp_path,
    )
    monkeypatch.setattr(menu_review, "discover_scan_review_items", lambda _root: discovery)
    monkeypatch.setattr(menu_review, "clear_screen", lambda: None)
    monkeypatch.setattr(menu_review, "pause_for_user", lambda: None)
    monkeypatch.setattr(
        menu_review,
        "allowed_review_actions",
        lambda _root, _item: ("rescan_needed",),
    )
    monkeypatch.setattr(menu_review, "_perform_action", lambda *_args: None)
    choices = iter(("1", "1", "B"))
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(choices))

    assert menu_review.launch_scan_review_menu() == 0
    output = capsys.readouterr().out

    assert "Scan Review Not Updated" in output
    assert "Manual Entry Cancelled" not in output
    assert "No result or resolution record was written." in output
