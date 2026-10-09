"""Issue #225 Slice 15: privacy-bounded real-OMR qualification contracts."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest
from pds_core.pds2 import serialize_pds2_payload
from test_issue225_scan_recovery_preflight import _record_route, _snapshot, _workspace

import scoreform.qr_physical_recovery_qualification as physical
from scoreform.page_scoring import ScoredAnswer, ScoreFormPageDispatchResult
from scoreform.qr_physical_recovery_qualification import (
    PhysicalRecoveryPageQualification,
    PhysicalRecoverySelection,
    build_physical_recovery_report,
    qualify_physical_recovery_page,
)


def _selection(route):
    return PhysicalRecoverySelection("failure1", route_locator=route.locator)


def _fake_omr(monkeypatch, seen):
    def score(_image, **kwargs):
        seen.append(kwargs["debug_dir"])
        page = kwargs["page_context"].page
        numbers = range(page.question_start, page.question_end + 1)
        answers = tuple(ScoredAnswer(number, "A", True) for number in numbers)
        return ScoreFormPageDispatchResult(
            route_id=kwargs["route_id"],
            page_id=page.page_id,
            issuance_id=page.issuance_id,
            generation_id=page.generation_id,
            artifact_id=page.artifact_id,
            class_id=page.class_id,
            assignment_id=page.assignment_id,
            student_id=page.student_id,
            logical_page=page.logical_page,
            total_pages=page.total_pages,
            question_start=page.question_start,
            question_end=page.question_end,
            layout_id=page.layout_id,
            score=len(answers),
            total_points=len(answers),
            answers=answers,
            source_scan_id=kwargs["source_scan_id"],
            source_page_number=kwargs["source_page_number"],
            retained_source_relative_path=kwargs["retained_source_relative_path"],
            source_sha256=kwargs["source_sha256"],
            diagnostic_paths=(),
        )

    monkeypatch.setattr(physical, "score_authoritative_answer_sheet_page", score)
    return score


def test_synthetic_omr_seam_never_writes_and_returns_no_student_data(tmp_path, monkeypatch):
    route, page, retained, _failure = _workspace(tmp_path)
    seen = []
    _fake_omr(monkeypatch, seen)
    before = _snapshot(tmp_path)
    outcome = qualify_physical_recovery_page(tmp_path, _selection(route))
    assert outcome == PhysicalRecoveryPageQualification(1, "omr_scored", "complete", 1, 1, 1, 15, 0, 0)
    assert seen == [None]
    assert _snapshot(tmp_path) == before
    assert not list(tmp_path.rglob("results.csv"))
    report = json.dumps(build_physical_recovery_report((outcome,)))
    for forbidden in (page.student_id, route.locator.route_id, retained.source_scan_id, "source_sha256"):
        assert forbidden not in report


def test_existing_teacher_route_reused_read_only(tmp_path, monkeypatch):
    route, page, _retained, failure = _workspace(tmp_path)
    _record_route(tmp_path, route, page, failure)
    _fake_omr(monkeypatch, [])
    before = _snapshot(tmp_path)
    result = qualify_physical_recovery_page(
        tmp_path, PhysicalRecoverySelection("failure1", use_recorded_route=True)
    )
    assert result.outcome == "omr_scored"
    assert _snapshot(tmp_path) == before


def test_incorrect_recorded_route_rejected_without_score(tmp_path, monkeypatch):
    _workspace(tmp_path)
    monkeypatch.setattr(
        physical, "score_authoritative_answer_sheet_page",
        lambda *_a, **_k: pytest.fail("must not score without route decision"),
    )
    before = _snapshot(tmp_path)
    result = qualify_physical_recovery_page(
        tmp_path, PhysicalRecoverySelection("failure1", use_recorded_route=True)
    )
    assert result.outcome == "authority_rejected"
    assert _snapshot(tmp_path) == before


def test_changed_retained_image_cannot_be_qualified(tmp_path, monkeypatch):
    route, _page, retained, _failure = _workspace(tmp_path)
    retained.retained_source_path.write_bytes(b"altered")
    monkeypatch.setattr(
        physical, "score_authoritative_answer_sheet_page",
        lambda *_a, **_k: pytest.fail("must not score changed source"),
    )
    result = qualify_physical_recovery_page(tmp_path, _selection(route))
    assert result.outcome == "authority_rejected"
    assert not list(tmp_path.rglob("results.csv"))


def test_actual_unmarked_tiny_image_fails_optical_without_result(tmp_path):
    route, _page, _retained, _failure = _workspace(tmp_path)
    before = _snapshot(tmp_path)
    result = qualify_physical_recovery_page(tmp_path, _selection(route))
    assert result.outcome == "omr_failed"
    assert _snapshot(tmp_path) == before


def test_forged_scorer_result_is_not_reported_as_qualified(tmp_path, monkeypatch):
    route, _page, _retained, _failure = _workspace(tmp_path)
    original = _fake_omr(monkeypatch, [])

    def forged(*args, **kwargs):
        return replace(original(*args, **kwargs), student_id="different_student")

    monkeypatch.setattr(physical, "score_authoritative_answer_sheet_page", forged)
    before = _snapshot(tmp_path)
    result = qualify_physical_recovery_page(tmp_path, _selection(route))
    assert result.outcome == "omr_failed"
    assert _snapshot(tmp_path) == before


def test_failure_does_not_leak_internal_error_text(tmp_path, monkeypatch):
    route, _page, _retained, _failure = _workspace(tmp_path)

    def deny(*_a, **_k):
        raise ValueError("private student identifier and raw source path")

    monkeypatch.setattr(physical, "score_authoritative_answer_sheet_page", deny)
    report = build_physical_recovery_report((qualify_physical_recovery_page(tmp_path, _selection(route)),))
    assert report["pages"][0]["outcome"] == "omr_failed"
    assert "private student" not in json.dumps(report)
    assert not report["grade_saved"]
    assert not report["physical_mark_comparison_performed"]


def test_report_rejects_empty_and_reordered_evidence():
    with pytest.raises(ValueError):
        build_physical_recovery_report(())
    with pytest.raises(ValueError):
        build_physical_recovery_report((PhysicalRecoveryPageQualification(3, "omr_failed", "omr"),))


def test_selection_never_guesses_routes():
    with pytest.raises(ValueError):
        PhysicalRecoverySelection("failure1")
    with pytest.raises(ValueError):
        PhysicalRecoverySelection("failure1", use_recorded_route=True, allow_route_correction=True)


def test_final_report_never_claims_grading_or_new_print_acceptance():
    report = build_physical_recovery_report((PhysicalRecoveryPageQualification(1, "omr_scored", "complete", 11, 1, 1, 15, 0, 0),))
    assert report["all_pages_scored"]
    assert report["real_optical_recognition"]
    assert not report["core_result_writer_invoked"]
    assert not report["new_print_geometry_qualified"]
    assert not report["physical_mark_comparison_performed"]


def test_cli_create_only_sanitized_report(tmp_path, monkeypatch, capsys):
    from scripts import qualify_issue225_physical_recovery as cli

    root = tmp_path / "private-workspace"
    root.mkdir()
    route, _page, _retained, _failure = _workspace(root)
    output = tmp_path / "private-qualification.json"
    monkeypatch.setattr(
        cli,
        "qualify_physical_recovery_page",
        lambda *_a, **_k: PhysicalRecoveryPageQualification(
            1, "omr_scored", "complete", 1, 1, 1, 15, 0, 0
        ),
    )
    argv = [
        "--workspace", str(root),
        "--page", f"failure1={serialize_pds2_payload(route.locator)}",
        "--output", str(output),
    ]
    assert cli.main(argv) == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["all_pages_scored"]
    assert not report["grade_saved"]
    assert route.locator.route_id not in output.read_text(encoding="utf-8")
    assert "private-workspace" not in capsys.readouterr().out
    previous = output.read_bytes()
    assert cli.main(argv) == 1
    assert output.read_bytes() == previous


def test_cli_missing_original_failure_is_truthful_without_persisting(tmp_path):
    from scripts import qualify_issue225_physical_recovery as cli

    root = tmp_path / "workspace"
    root.mkdir()
    route, _page, _retained, _failure = _workspace(root)
    output = tmp_path / "report.json"
    assert cli.main([
        "--workspace", str(root),
        "--page", f"absent_failure={serialize_pds2_payload(route.locator)}",
        "--output", str(output),
    ]) == 2
    assert json.loads(output.read_text(encoding="utf-8"))["pages"][0]["outcome"] == "authority_rejected"
    assert not list(root.rglob("results.csv"))
