"""Issue #192 Slice 2c scan/results/recovery diagnostic contracts."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
import pytest
import qrcode
from pds_core.module_profiles import ModuleRegistry
from pds_core.scan_failure_metadata import (
    RoutingFailureMetadata,
    write_routing_failure_metadata,
)
from pds_core.scan_resolution_metadata import ScanResolutionMetadataWriteError

import scoreform.diagnostic_events as diagnostics
import scoreform.pds2_scan_dispatch as scan_dispatch
import scoreform.results as results
import scoreform.scan_review_resolution as review
from scoreform.module_errors import ScoreFormSourceMissingError
from scoreform.page_scoring import ScoredAnswer
from scoreform.pds_module import get_module_profile
from scoreform.scan_review_details import scoreform_failure_details
from scoreform.work_paths import scoreform_work_paths


def _event_codes(root: Path) -> list[str]:
    return [
        event.code
        for event in diagnostics.list_diagnostic_events(
            root,
            limit=diagnostics.MAX_EVENT_LIST_LIMIT,
        ).events
    ]


def _qr(path: Path, payload: str) -> Path:
    qrcode.make(payload).save(path)
    return path


def test_scan_preflight_failure_is_bounded_and_path_private(tmp_path: Path) -> None:
    private_source = tmp_path / "PRIVATE-STUDENT-FILENAME.png"

    result = scan_dispatch.process_pds2_scan(
        private_source,
        workspace_root=tmp_path,
        registry=ModuleRegistry((get_module_profile(),)),
    )

    assert isinstance(result.file_error, ScoreFormSourceMissingError)
    listing = diagnostics.list_diagnostic_events(tmp_path)
    assert [event.code for event in listing.events] == ["scan_preflight_failed"]
    raw = diagnostics.diagnostic_event_path(
        tmp_path, listing.events[0].event_id
    ).read_text(encoding="utf-8")
    assert "PRIVATE-STUDENT-FILENAME" not in raw
    assert str(tmp_path) not in raw


def test_qr_missing_records_one_event_without_image_or_student_content(
    tmp_path: Path,
) -> None:
    source = tmp_path / "blank.png"
    assert cv2.imwrite(str(source), np.full((120, 120, 3), 255, np.uint8))

    result = scan_dispatch.process_pds2_scan(
        source,
        workspace_root=tmp_path,
        registry=ModuleRegistry((get_module_profile(),)),
    )

    assert result.pages[0].failure_stage == "qr_detection"
    assert "qr_missing" in _event_codes(tmp_path)
    event = next(
        item
        for item in diagnostics.list_diagnostic_events(tmp_path).events
        if item.code == "qr_missing"
    )
    raw = diagnostics.diagnostic_event_path(
        tmp_path, event.event_id
    ).read_text(encoding="utf-8")
    assert "student_id" not in raw
    assert "blank.png" not in raw


def test_invalid_payload_is_not_copied_into_diagnostic_bytes(tmp_path: Path) -> None:
    payload = "PRIVATE-QR-PAYLOAD-SENTINEL|student=PRIVATE-STUDENT"
    source = _qr(tmp_path / "payload.png", payload)

    result = scan_dispatch.process_pds2_scan(
        source,
        workspace_root=tmp_path,
        registry=ModuleRegistry((get_module_profile(),)),
    )

    assert result.pages[0].failure_stage == "payload_parsing"
    event = next(
        item
        for item in diagnostics.list_diagnostic_events(tmp_path).events
        if item.code == "payload_invalid"
    )
    raw = diagnostics.diagnostic_event_path(
        tmp_path, event.event_id
    ).read_text(encoding="utf-8")
    assert "PRIVATE-QR-PAYLOAD-SENTINEL" not in raw
    assert "PRIVATE-STUDENT" not in raw


def test_core_route_failure_records_work_context_without_route_payload(
    tmp_path: Path,
) -> None:
    payload = (
        "PDS2|m=missing|c=class1|w=quiz1|"
        "r=rt_10000000000000000000000000000000"
    )
    source = _qr(tmp_path / "unknown.png", payload)

    result = scan_dispatch.process_pds2_scan(
        source,
        workspace_root=tmp_path,
        registry=ModuleRegistry((get_module_profile(),)),
    )

    assert result.dispatch_failure_count == 1
    event = next(
        item
        for item in diagnostics.list_diagnostic_events(tmp_path).events
        if item.code == "route_dispatch_failed"
    )
    assert (event.class_id, event.assignment_id) == ("class1", "quiz1")
    raw = diagnostics.diagnostic_event_path(
        tmp_path, event.event_id
    ).read_text(encoding="utf-8")
    assert "rt_10000000000000000000000000000000" not in raw
    assert payload not in raw


def _review_result() -> results.ScoreFormRoutedResult:
    return results.ScoreFormRoutedResult(
        result_origin="scan_review_manual",
        class_id="class1",
        assignment_id="quiz1",
        student_id="student_private_1001",
        last_name="Private",
        first_name="Student",
        period="2",
        page_display="review",
        score=1,
        total_points=1,
        answers=(ScoredAnswer(1, "A", True),),
        source_file="scan_review_manual:failure1",
    )


def _managed_assignment(tmp_path: Path) -> None:
    paths = scoreform_work_paths(tmp_path, "class1", "quiz1")
    paths.work_root.mkdir(parents=True)
    paths.assignment_path.write_text(
        json.dumps(
            {
                "assignment_id": "quiz1",
                "title": "PRIVATE-ASSIGNMENT-TITLE",
                "question_count": 1,
                "choices": ["A", "B", "C", "D"],
                "layout_id": "standard_15q_abcd_v1",
                "answer_key": {"1": "A"},
                "standards": {"1": []},
            }
        ),
        encoding="utf-8",
    )


def test_result_append_emits_once_but_exact_review_replay_does_not(
    tmp_path: Path,
) -> None:
    _managed_assignment(tmp_path)
    result = _review_result()

    first = results.export_scoreform_result_models((result,), workspace_root=tmp_path)
    second = results.export_scoreform_result_models((result,), workspace_root=tmp_path)

    assert len(first.appended_attempts) == 1
    assert len(second.already_present_attempts) == 1
    assert _event_codes(tmp_path).count("result_persistence_verified") == 1

    event = next(
        item
        for item in diagnostics.list_diagnostic_events(tmp_path).events
        if item.code == "result_persistence_verified"
    )
    raw = diagnostics.diagnostic_event_path(
        tmp_path, event.event_id
    ).read_text(encoding="utf-8")
    assert "student_private_1001" not in raw
    assert "PRIVATE-ASSIGNMENT-TITLE" not in raw
    assert '"score"' not in raw.lower()
    assert '"answers"' not in raw.lower()


def test_result_failure_does_not_persist_exception_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _managed_assignment(tmp_path)

    def fail(*_args: object, **_kwargs: object) -> Path:
        raise results.ScoreFormRoutedResultWriteError(
            "PRIVATE-STUDENT-SENTINEL C:\\Users\\Teacher Name\\private"
        )

    monkeypatch.setattr(results, "_stage_history", fail)
    batch = results.export_scoreform_result_models(
        (_review_result(),),
        workspace_root=tmp_path,
    )

    assert batch.failures
    event = next(
        item
        for item in diagnostics.list_diagnostic_events(tmp_path).events
        if item.code == "result_persistence_failed"
    )
    raw = diagnostics.diagnostic_event_path(
        tmp_path, event.event_id
    ).read_text(encoding="utf-8")
    assert "PRIVATE-STUDENT-SENTINEL" not in raw
    assert "Teacher Name" not in raw


def test_result_success_survives_diagnostic_storage_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _managed_assignment(tmp_path)

    def fail_record(*_args: object, **_kwargs: object) -> object:
        raise diagnostics.DiagnosticEventStorageError("diagnostics unavailable")

    monkeypatch.setattr(diagnostics, "record_diagnostic_event", fail_record)
    batch = results.export_scoreform_result_models(
        (_review_result(),),
        workspace_root=tmp_path,
    )

    assert batch.succeeded
    assert len(batch.appended_attempts) == 1
    assert diagnostics.list_diagnostic_events(tmp_path).events == ()


def _failure(
    failure_id: str,
    *,
    scoreform_category: str = "missing_qr",
) -> RoutingFailureMetadata:
    return RoutingFailureMetadata(
        schema_version="2",
        failure_id=failure_id,
        scope="page",
        stage="payload_detection",
        created_at="2026-01-01T00:00:00+00:00",
        failure_category="payload_missing",
        failure_message="PRIVATE-STUDENT-SENTINEL",
        source_filename="PRIVATE-SCAN-NAME.pdf",
        source_scan_id=None,
        source_sha256=None,
        retained_source_path=None,
        review_copy_path=None,
        source_page_number=1,
        detected_payload=None,
        route_locator=None,
        target=None,
        module_details=scoreform_failure_details(
            origin="page_decode",
            category=scoreform_category,
        ),
    )


def test_defer_is_not_mislabeled_as_recovery(tmp_path: Path) -> None:
    write_routing_failure_metadata(tmp_path, _failure("failure_defer"))

    result = review.resolve_scan_review_item(
        tmp_path,
        "failure_defer",
        "defer",
        now=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )

    assert result.resolution_status == "deferred"
    assert "scan_review_recovered" not in _event_codes(tmp_path)


def test_verified_duplicate_dismissal_records_recovery_without_failure_body(
    tmp_path: Path,
) -> None:
    write_routing_failure_metadata(
        tmp_path,
        _failure(
            "failure_duplicate",
            scoreform_category="duplicate_page",
        ),
    )

    result = review.resolve_scan_review_item(
        tmp_path,
        "failure_duplicate",
        "dismissed_duplicate",
        now=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )

    assert result.resolution_status == "resolved"
    event = next(
        item
        for item in diagnostics.list_diagnostic_events(tmp_path).events
        if item.code == "scan_review_recovered"
    )
    raw = diagnostics.diagnostic_event_path(
        tmp_path, event.event_id
    ).read_text(encoding="utf-8")
    assert "PRIVATE-STUDENT-SENTINEL" not in raw
    assert "PRIVATE-SCAN-NAME" not in raw


def test_resolution_write_failure_records_bounded_event_and_preserves_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_routing_failure_metadata(tmp_path, _failure("failure_write"))
    storage_error = ScanResolutionMetadataWriteError(
        "PRIVATE-STUDENT-SENTINEL C:\\Users\\Teacher Name\\private"
    )

    def fail(*_args: object, **_kwargs: object) -> None:
        raise storage_error

    monkeypatch.setattr(review, "write_scan_resolution_metadata", fail)

    with pytest.raises(review.ScanReviewError) as captured:
        review.resolve_scan_review_item(
            tmp_path,
            "failure_write",
            "rescan_needed",
            now=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )

    assert captured.value.__cause__ is storage_error
    event = next(
        item
        for item in diagnostics.list_diagnostic_events(tmp_path).events
        if item.code == "scan_review_resolution_failed"
    )
    raw = diagnostics.diagnostic_event_path(
        tmp_path, event.event_id
    ).read_text(encoding="utf-8")
    assert "PRIVATE-STUDENT-SENTINEL" not in raw
    assert "Teacher Name" not in raw
