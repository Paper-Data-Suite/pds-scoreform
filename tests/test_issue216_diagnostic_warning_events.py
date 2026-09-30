"""Issue #216 Slice 4 tests for fail-soft diagnostic warning events."""

from __future__ import annotations

from pathlib import Path

import pytest

import scoreform.route_handler as route_handler
from scoreform.answer_sheet_persistence import AnswerSheetPageContext
from scoreform.answer_sheet_records import build_answer_sheet_record_set
from scoreform.diagnostic_artifacts import DiagnosticArtifactWarning
from scoreform.diagnostic_events import (
    DiagnosticEventValidationError,
    build_diagnostic_event,
    list_diagnostic_events,
    try_emit_diagnostic_event,
)

CLASS_ID = "class1"
ASSIGNMENT_ID = "quiz1"


def _context() -> AnswerSheetPageContext:
    assignment = {
        "assignment_id": ASSIGNMENT_ID,
        "title": "Quiz",
        "question_count": 1,
        "choices": ["A", "B", "C", "D"],
        "layout_id": "standard_15q_abcd_v1",
        "answer_key": {"1": "A"},
        "standards": {"1": []},
    }
    student = {
        "class_id": CLASS_ID,
        "student_id": "student1",
        "last_name": "Doe",
        "first_name": "Jane",
        "period": "1",
    }
    records = build_answer_sheet_record_set(
        CLASS_ID,
        assignment,
        student,
        generation_id="gen_" + "1" * 32,
        artifact_id="art_" + "2" * 32,
        output_kind="individual_pdf",
        reason="initial",
        issuance_id="iss_" + "3" * 32,
        page_ids=("pg_" + "4" * 32,),
        clock=lambda: "2026-01-01T00:00:00+00:00",
    )
    return AnswerSheetPageContext(
        records.pages[0],
        records.issuance,
        records.pages,
    )


def _debug_dir(root: Path) -> Path:
    return (
        root
        / "classes"
        / CLASS_ID
        / "modules"
        / "scoreform"
        / "work"
        / ASSIGNMENT_ID
        / "debug"
    )


def test_diagnostic_artifact_event_contract_is_privacy_bounded(tmp_path):
    event = build_diagnostic_event(
        component="scoring",
        workflow="score_scan",
        stage="diagnostic_persistence",
        outcome="partial_success",
        code="diagnostic_artifact_write_failed",
        class_id=CLASS_ID,
        assignment_id=ASSIGNMENT_ID,
        exception_type="PermissionError",
        workspace_root=tmp_path,
        path=_debug_dir(tmp_path),
    )

    assert event.category == "diagnostics"
    assert event.safe_summary == (
        "Optional scoring diagnostic artifact could not be persisted."
    )
    assert event.exception_type == "PermissionError"
    assert event.path_context == (
        "classes/class1/modules/scoreform/work/quiz1/debug/<diagnostic>"
    )


def test_explicit_exception_type_is_strict_and_cannot_conflict_with_exception():
    with pytest.raises(DiagnosticEventValidationError):
        build_diagnostic_event(
            component="scoring",
            workflow="score_scan",
            stage="diagnostic_persistence",
            outcome="partial_success",
            code="diagnostic_artifact_write_failed",
            exception_type="Permission Error: private path",
        )

    with pytest.raises(DiagnosticEventValidationError):
        build_diagnostic_event(
            component="scoring",
            workflow="score_scan",
            stage="diagnostic_persistence",
            outcome="partial_success",
            code="diagnostic_artifact_write_failed",
            exception=PermissionError("private"),
            exception_type="PermissionError",
        )


def test_try_emit_persists_warning_event_without_free_form_failure_text(tmp_path):
    attempt = try_emit_diagnostic_event(
        tmp_path,
        component="scoring",
        workflow="score_scan",
        stage="diagnostic_persistence",
        outcome="partial_success",
        code="diagnostic_artifact_write_failed",
        class_id=CLASS_ID,
        assignment_id=ASSIGNMENT_ID,
        exception_type="PermissionError",
        path=_debug_dir(tmp_path),
    )

    assert attempt.recorded is True
    assert attempt.warning_code is None
    listing = list_diagnostic_events(tmp_path)
    assert len(listing.events) == 1
    event = listing.events[0]
    assert event.code == "diagnostic_artifact_write_failed"
    assert event.exception_type == "PermissionError"
    assert "private" not in repr(event).lower()


def test_route_warning_projection_emits_one_page_event_for_multiple_warnings(
    tmp_path,
    monkeypatch,
):
    context = _context()
    debug_dir = _debug_dir(tmp_path)
    warnings = (
        DiagnosticArtifactWarning(
            kind="registration_marks",
            stage="write",
            exception_type="PermissionError",
        ),
        DiagnosticArtifactWarning(
            kind="warped_page",
            stage="encode",
            exception_type="RuntimeError",
        ),
    )
    calls: list[dict[str, object]] = []

    def capture(_workspace_root, **kwargs):
        calls.append(kwargs)
        return object()

    monkeypatch.setattr(route_handler, "try_emit_diagnostic_event", capture)

    route_handler._emit_diagnostic_artifact_warning_event(
        tmp_path,
        context=context,
        debug_dir=debug_dir,
        warnings=warnings,
    )

    assert len(calls) == 1
    call = calls[0]
    assert call["component"] == "scoring"
    assert call["workflow"] == "score_scan"
    assert call["stage"] == "diagnostic_persistence"
    assert call["outcome"] == "partial_success"
    assert call["code"] == "diagnostic_artifact_write_failed"
    assert call["class_id"] == CLASS_ID
    assert call["assignment_id"] == ASSIGNMENT_ID
    assert call["exception_type"] == "PermissionError"
    assert call["path"] == debug_dir


def test_route_warning_projection_is_strictly_noninterfering(tmp_path, monkeypatch):
    context = _context()
    warning = DiagnosticArtifactWarning(
        kind="registration_marks",
        stage="write",
        exception_type="PermissionError",
    )

    def explode(*args, **kwargs):
        raise RuntimeError("instrumentation failure")

    monkeypatch.setattr(route_handler, "try_emit_diagnostic_event", explode)

    assert (
        route_handler._emit_diagnostic_artifact_warning_event(
            tmp_path,
            context=context,
            debug_dir=_debug_dir(tmp_path),
            warnings=(warning,),
        )
        is None
    )
