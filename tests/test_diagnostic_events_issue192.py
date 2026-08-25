"""Issue #192 Slice 1 tests for ScoreForm-local diagnostic events."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import scoreform.diagnostic_events as diagnostics
from scoreform.diagnostic_events import (
    DEFAULT_EVENT_LIST_LIMIT,
    DEFAULT_EVENT_RETENTION_LIMIT,
    MAX_EVENT_LIST_LIMIT,
    DiagnosticEvent,
    DiagnosticEventStorageError,
    DiagnosticEventValidationError,
    build_diagnostic_event,
    diagnostic_event_path,
    diagnostic_events_dir,
    list_diagnostic_events,
    load_diagnostic_event,
    record_diagnostic_event,
    sanitize_diagnostic_path,
    try_emit_diagnostic_event,
    try_record_diagnostic_event,
    validate_diagnostic_event,
)

CLASS_ID = "class_a"
ASSIGNMENT_ID = "assignment_a"
BASE_TIME = datetime(2026, 8, 25, 3, 30, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _fixed_versions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "scoreform.diagnostic_events._scoreform_version",
        lambda: "0.10.0",
    )
    monkeypatch.setattr(
        "scoreform.diagnostic_events._installed_core_version",
        lambda: "0.6.3",
    )


def _event(
    root: Path,
    *,
    event_id: str = "diag_00000000000000000000000000000001",
    occurred_at: datetime = BASE_TIME,
    code: str = "qr_missing",
    path: Path | None = None,
    exception: BaseException | None = None,
) -> DiagnosticEvent:
    return build_diagnostic_event(
        component="scan_intake",
        workflow="process_scan",
        stage="decode",
        outcome="failure",
        code=code,
        class_id=CLASS_ID,
        assignment_id=ASSIGNMENT_ID,
        exception=exception,
        workspace_root=root if path is not None else None,
        path=path,
        occurred_at=occurred_at,
        event_id=event_id,
    )


def test_build_event_uses_fixed_scoreform_safe_contract(tmp_path: Path) -> None:
    event = _event(
        tmp_path,
        exception=RuntimeError(
            "Avery Rivera REAL-STUDENT-ANSWER-SENTINEL "
            "C:\\Users\\Teacher Name\\private\\scan.pdf"
        ),
    )

    assert event.schema_version == "1"
    assert event.module == "scoreform"
    assert event.record_type == "diagnostic_event"
    assert event.scoreform_version == "0.10.0"
    assert event.core_version == "0.6.3"
    assert event.category == "qr"
    assert event.code == "qr_missing"
    assert event.exception_type == "RuntimeError"
    assert event.safe_summary == (
        "QR detection did not find a usable locator on the retained page."
    )
    assert "Avery Rivera" not in repr(event)
    assert "REAL-STUDENT-ANSWER-SENTINEL" not in repr(event)
    assert "Teacher Name" not in repr(event)


def test_model_has_no_generic_student_answer_or_score_field() -> None:
    assert "student_id" not in DiagnosticEvent.__dataclass_fields__
    assert "student_name" not in DiagnosticEvent.__dataclass_fields__
    assert "answers" not in DiagnosticEvent.__dataclass_fields__
    assert "answer_key" not in DiagnosticEvent.__dataclass_fields__
    assert "score" not in DiagnosticEvent.__dataclass_fields__
    assert "percentage" not in DiagnosticEvent.__dataclass_fields__
    assert "metadata" not in DiagnosticEvent.__dataclass_fields__
    assert "payload" not in DiagnosticEvent.__dataclass_fields__


def test_unknown_vocabularies_and_codes_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(DiagnosticEventValidationError):
        build_diagnostic_event(
            component="analytics",
            workflow="process_scan",
            stage="decode",
            outcome="failure",
            code="qr_missing",
            occurred_at=BASE_TIME,
        )
    with pytest.raises(DiagnosticEventValidationError):
        build_diagnostic_event(
            component="scan_intake",
            workflow="student_Avery_Rivera",
            stage="decode",
            outcome="failure",
            code="qr_missing",
            occurred_at=BASE_TIME,
        )
    with pytest.raises(DiagnosticEventValidationError):
        build_diagnostic_event(
            component="scan_intake",
            workflow="process_scan",
            stage="decode",
            outcome="failure",
            code="free_form_PRIVATE_NOTE",
            occurred_at=BASE_TIME,
        )


def test_safe_summary_and_category_cannot_be_replaced(tmp_path: Path) -> None:
    event = _event(tmp_path)
    with pytest.raises(DiagnosticEventValidationError):
        validate_diagnostic_event(
            replace(event, safe_summary="PRIVATE-TEACHER-NOTE-SENTINEL")
        )
    with pytest.raises(DiagnosticEventValidationError):
        validate_diagnostic_event(replace(event, category="results"))


def test_work_path_preserves_only_safe_assignment_context(tmp_path: Path) -> None:
    raw = (
        tmp_path
        / "classes"
        / CLASS_ID
        / "modules"
        / "scoreform"
        / "work"
        / ASSIGNMENT_ID
        / "results.csv"
    )
    assert sanitize_diagnostic_path(
        tmp_path,
        raw,
        class_id=CLASS_ID,
        assignment_id=ASSIGNMENT_ID,
    ) == "classes/class_a/modules/scoreform/work/assignment_a/results.csv"


def test_work_path_generalizes_student_bearing_answer_sheet_artifact(
    tmp_path: Path,
) -> None:
    raw = (
        tmp_path
        / "classes"
        / CLASS_ID
        / "modules"
        / "scoreform"
        / "work"
        / ASSIGNMENT_ID
        / "answer_sheets"
        / "individual"
        / "Avery Rivera stu_1001.pdf"
    )
    assert sanitize_diagnostic_path(
        tmp_path,
        raw,
        class_id=CLASS_ID,
        assignment_id=ASSIGNMENT_ID,
    ) == "classes/class_a/modules/scoreform/work/assignment_a/answer_sheets/<artifact>"


def test_work_path_generalizes_raw_scan_and_debug_names(tmp_path: Path) -> None:
    work = (
        tmp_path
        / "classes"
        / CLASS_ID
        / "modules"
        / "scoreform"
        / "work"
        / ASSIGNMENT_ID
    )
    assert sanitize_diagnostic_path(
        tmp_path,
        work / "scans" / "Avery Rivera Period 3.pdf",
        class_id=CLASS_ID,
        assignment_id=ASSIGNMENT_ID,
    ).endswith("/scans/<source>")
    assert sanitize_diagnostic_path(
        tmp_path,
        work / "debug" / "stu_1001_answers.png",
        class_id=CLASS_ID,
        assignment_id=ASSIGNMENT_ID,
    ).endswith("/debug/<diagnostic>")


def test_qr_failure_path_generalizes_diagnostic_filename(tmp_path: Path) -> None:
    raw = (
        tmp_path
        / "local_outputs"
        / "qr_failures"
        / "2026-08-25"
        / "Avery_Rivera_page_1_full_page_debug.png"
    )
    assert sanitize_diagnostic_path(tmp_path, raw) == (
        "local_outputs/qr_failures/<date>/<diagnostic>"
    )


def test_outside_workspace_and_traversal_paths_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(DiagnosticEventValidationError):
        sanitize_diagnostic_path(tmp_path, tmp_path.parent / "private.txt")
    with pytest.raises(DiagnosticEventValidationError):
        sanitize_diagnostic_path(tmp_path, Path("scans") / ".." / "private.txt")


def test_path_context_requires_matching_class_and_assignment(tmp_path: Path) -> None:
    raw = (
        tmp_path
        / "classes"
        / CLASS_ID
        / "modules"
        / "scoreform"
        / "work"
        / ASSIGNMENT_ID
        / "assignment.json"
    )
    with pytest.raises(DiagnosticEventValidationError):
        sanitize_diagnostic_path(
            tmp_path,
            raw,
            class_id="other_class",
            assignment_id=ASSIGNMENT_ID,
        )
    with pytest.raises(DiagnosticEventValidationError):
        sanitize_diagnostic_path(
            tmp_path,
            raw,
            class_id=CLASS_ID,
            assignment_id="other_assignment",
        )


def test_unsanitized_student_path_cannot_be_injected_into_event(tmp_path: Path) -> None:
    event = _event(tmp_path)
    unsafe = replace(
        event,
        path_context=(
            "classes/class_a/modules/scoreform/work/assignment_a/"
            "answer_sheets/individual/stu_1001.pdf"
        ),
    )
    with pytest.raises(DiagnosticEventValidationError):
        validate_diagnostic_event(unsafe)


def test_record_creates_only_scoreform_diagnostic_chain_and_exact_event(
    tmp_path: Path,
) -> None:
    event = _event(tmp_path)

    result = record_diagnostic_event(tmp_path, event)

    expected_dir = (
        tmp_path / "shared" / "scoreform" / "diagnostics" / "events"
    )
    expected_path = expected_dir / f"{event.event_id}.json"
    assert diagnostic_events_dir(tmp_path) == expected_dir
    assert diagnostic_event_path(tmp_path, event.event_id) == expected_path
    assert result.relative_path == (
        f"shared/scoreform/diagnostics/events/{event.event_id}.json"
    )
    assert expected_path.is_file()
    assert load_diagnostic_event(tmp_path, event.event_id) == event


def test_persisted_bytes_exclude_sensitive_sentinels(tmp_path: Path) -> None:
    raw_path = (
        tmp_path
        / "classes"
        / CLASS_ID
        / "modules"
        / "scoreform"
        / "work"
        / ASSIGNMENT_ID
        / "answer_sheets"
        / "individual"
        / "Avery Rivera stu_real_1001 answers.pdf"
    )
    event = _event(
        tmp_path,
        path=raw_path,
        exception=RuntimeError(
            "Avery Rivera\n"
            "stu_real_1001\n"
            "REAL-STUDENT-ANSWER-SENTINEL A,B,C,D,A\n"
            "SCORE-17-OF-20-SENTINEL\n"
            "PRIVATE-ROSTER-SENTINEL\n"
            "PRIVATE-TEACHER-NOTE-SENTINEL\n"
            "FULL-QR-PAYLOAD-SENTINEL\n"
            "PDS2|m=scoreform|c=private_class|w=private_work|r=private_route\n"
            "C:\\Users\\Teacher Name\\Documents\\School\\private.pdf"
        ),
    )

    result = record_diagnostic_event(tmp_path, event)
    data = (tmp_path / result.relative_path).read_text(encoding="utf-8")

    forbidden = (
        "Avery Rivera",
        "stu_real_1001",
        "REAL-STUDENT-ANSWER-SENTINEL",
        "A,B,C,D,A",
        "SCORE-17-OF-20-SENTINEL",
        "PRIVATE-ROSTER-SENTINEL",
        "PRIVATE-TEACHER-NOTE-SENTINEL",
        "FULL-QR-PAYLOAD-SENTINEL",
        "private_route",
        "Teacher Name",
    )
    for value in forbidden:
        assert value not in data
    assert "<artifact>" in data


def test_event_file_is_create_only_and_cannot_overwrite(tmp_path: Path) -> None:
    event = _event(tmp_path)
    record_diagnostic_event(tmp_path, event)
    path = diagnostic_event_path(tmp_path, event.event_id)
    original = path.read_bytes()

    with pytest.raises(DiagnosticEventStorageError):
        record_diagnostic_event(tmp_path, event)

    assert path.read_bytes() == original


def test_list_missing_directory_is_empty_and_read_only(tmp_path: Path) -> None:
    before = tuple(sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*")))

    listing = list_diagnostic_events(tmp_path)

    after = tuple(sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*")))
    assert listing.events == ()
    assert listing.warning_codes == ()
    assert before == after == ()


def test_list_is_newest_first_and_bounded(tmp_path: Path) -> None:
    for index in range(3):
        record_diagnostic_event(
            tmp_path,
            _event(
                tmp_path,
                event_id=f"diag_{index + 1:032x}",
                occurred_at=BASE_TIME + timedelta(seconds=index),
            ),
        )

    listing = list_diagnostic_events(tmp_path, limit=2)

    assert [event.event_id for event in listing.events] == [
        "diag_00000000000000000000000000000003",
        "diag_00000000000000000000000000000002",
    ]
    assert DEFAULT_EVENT_LIST_LIMIT == 50
    assert MAX_EVENT_LIST_LIMIT == 200
    with pytest.raises(DiagnosticEventValidationError):
        list_diagnostic_events(tmp_path, limit=0)
    with pytest.raises(DiagnosticEventValidationError):
        list_diagnostic_events(tmp_path, limit=MAX_EVENT_LIST_LIMIT + 1)


def test_malformed_and_unknown_entries_are_reported_but_not_modified(
    tmp_path: Path,
) -> None:
    event = _event(tmp_path)
    record_diagnostic_event(tmp_path, event)
    directory = diagnostic_events_dir(tmp_path)
    malformed = directory / "diag_ffffffffffffffffffffffffffffffff.json"
    malformed.write_text('{"schema_version":"1",', encoding="utf-8")
    unknown = directory / "Avery Rivera private.txt"
    unknown.write_text("do not delete", encoding="utf-8")
    before_malformed = malformed.read_bytes()
    before_unknown = unknown.read_bytes()

    listing = list_diagnostic_events(tmp_path)

    assert listing.events == (event,)
    assert "invalid_diagnostic_event" in listing.warning_codes
    assert "unexpected_diagnostic_entry" in listing.warning_codes
    assert malformed.read_bytes() == before_malformed
    assert unknown.read_bytes() == before_unknown


def test_duplicate_json_keys_are_rejected(tmp_path: Path) -> None:
    directory = tmp_path / "shared" / "scoreform" / "diagnostics" / "events"
    directory.mkdir(parents=True)
    event_id = "diag_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    path = directory / f"{event_id}.json"
    path.write_text(
        '{"schema_version":"1","schema_version":"1"}\n',
        encoding="utf-8",
    )

    with pytest.raises(DiagnosticEventStorageError):
        load_diagnostic_event(tmp_path, event_id)


def test_unknown_schema_fields_are_rejected(tmp_path: Path) -> None:
    event = _event(tmp_path)
    data = json.loads(diagnostics._serialize_event(event))
    data["PRIVATE_NOTE"] = "PRIVATE-TEACHER-NOTE-SENTINEL"
    directory = tmp_path / "shared" / "scoreform" / "diagnostics" / "events"
    directory.mkdir(parents=True)
    path = directory / f"{event.event_id}.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(DiagnosticEventStorageError):
        load_diagnostic_event(tmp_path, event.event_id)


def test_filename_event_identity_mismatch_is_rejected(tmp_path: Path) -> None:
    event = _event(tmp_path)
    data = diagnostics._serialize_event(event)
    directory = tmp_path / "shared" / "scoreform" / "diagnostics" / "events"
    directory.mkdir(parents=True)
    other_id = "diag_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    (directory / f"{other_id}.json").write_bytes(data)

    with pytest.raises(DiagnosticEventStorageError):
        load_diagnostic_event(tmp_path, other_id)


def test_retention_removes_only_oldest_proven_canonical_events(
    tmp_path: Path,
) -> None:
    events = []
    for index in range(4):
        event = _event(
            tmp_path,
            event_id=f"diag_{index + 1:032x}",
            occurred_at=BASE_TIME + timedelta(seconds=index),
        )
        record_diagnostic_event(tmp_path, event)
        events.append(event)

    directory = diagnostic_events_dir(tmp_path)
    malformed = directory / "diag_eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee.json"
    malformed.write_text('{"bad":', encoding="utf-8")
    unrelated = directory / "leave-me-alone.txt"
    unrelated.write_text("unrelated", encoding="utf-8")

    removed = diagnostics._prune_retention(tmp_path, max_events=2)

    assert removed == 2
    assert not diagnostic_event_path(tmp_path, events[0].event_id).exists()
    assert not diagnostic_event_path(tmp_path, events[1].event_id).exists()
    assert diagnostic_event_path(tmp_path, events[2].event_id).is_file()
    assert diagnostic_event_path(tmp_path, events[3].event_id).is_file()
    assert malformed.read_text(encoding="utf-8") == '{"bad":'
    assert unrelated.read_text(encoding="utf-8") == "unrelated"
    assert DEFAULT_EVENT_RETENTION_LIMIT == 500


def test_retention_degradation_preserves_created_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    event = _event(tmp_path)

    def fail_retention(_root: Path, *, max_events: int) -> int:
        assert max_events == DEFAULT_EVENT_RETENTION_LIMIT
        raise DiagnosticEventStorageError("simulated retention failure")

    monkeypatch.setattr(diagnostics, "_prune_retention", fail_retention)
    result = record_diagnostic_event(tmp_path, event)

    assert result.retention_warning == "diagnostic_retention_degraded"
    assert diagnostic_event_path(tmp_path, event.event_id).is_file()
    assert load_diagnostic_event(tmp_path, event.event_id) == event


def test_try_record_failure_never_raises_or_repairs_primary_state(
    tmp_path: Path,
) -> None:
    event = _event(tmp_path)
    shared = tmp_path / "shared"
    shared.write_text("not a directory", encoding="utf-8")

    attempt = try_record_diagnostic_event(tmp_path, event)

    assert attempt.recorded is False
    assert attempt.event_id == event.event_id
    assert attempt.warning_code == "diagnostic_write_failed"
    assert shared.read_text(encoding="utf-8") == "not a directory"


def test_try_emit_invalid_instrumentation_never_raises(tmp_path: Path) -> None:
    attempt = try_emit_diagnostic_event(
        tmp_path,
        component="INVALID_PRIVATE_COMPONENT",
        workflow="process_scan",
        stage="decode",
        outcome="failure",
        code="qr_missing",
    )
    assert attempt.recorded is False
    assert attempt.event_id is None
    assert attempt.warning_code == "diagnostic_instrumentation_failed"


def test_reading_event_does_not_rewrite_bytes(tmp_path: Path) -> None:
    event = _event(tmp_path)
    record_diagnostic_event(tmp_path, event)
    path = diagnostic_event_path(tmp_path, event.event_id)
    before = path.read_bytes()

    assert load_diagnostic_event(tmp_path, event.event_id) == event
    assert list_diagnostic_events(tmp_path).events == (event,)

    assert path.read_bytes() == before


def test_event_timestamp_requires_canonical_aware_utc(tmp_path: Path) -> None:
    with pytest.raises(DiagnosticEventValidationError):
        _event(
            tmp_path,
            occurred_at=datetime(2026, 8, 24, 23, 30, 0),
        )

    event = _event(
        tmp_path,
        occurred_at=datetime(
            2026,
            8,
            24,
            23,
            30,
            0,
            tzinfo=timezone(timedelta(hours=-4)),
        ),
    )
    assert event.occurred_at == "2026-08-25T03:30:00.000000Z"


def test_event_id_is_opaque_and_strict(tmp_path: Path) -> None:
    event = build_diagnostic_event(
        component="scan_intake",
        workflow="process_scan",
        stage="decode",
        outcome="failure",
        code="qr_missing",
        occurred_at=BASE_TIME,
    )
    assert event.event_id.startswith("diag_")
    assert len(event.event_id) == 37
    assert CLASS_ID not in event.event_id
    assert ASSIGNMENT_ID not in event.event_id

    with pytest.raises(DiagnosticEventValidationError):
        validate_diagnostic_event(replace(event, event_id="diag_Avery_Rivera"))


def test_diagnostic_module_has_no_remote_or_suite_runtime_dependencies() -> None:
    source = Path(diagnostics.__file__).read_text(encoding="utf-8").casefold()
    forbidden = (
        "requests",
        "urllib",
        "httpx",
        "socket",
        "sentry",
        "opentelemetry",
        "analytics_sdk",
        "paper_data_suite",
        "pds_meridian",
    )
    for token in forbidden:
        assert token not in source


def test_event_serialization_is_deterministic_and_final_newline(tmp_path: Path) -> None:
    event = _event(tmp_path)
    first = diagnostics._serialize_event(event)
    second = diagnostics._serialize_event(event)
    assert first == second
    assert first.endswith(b"\n")
    assert b"\r\n" not in first


def test_nonfinite_json_is_rejected(tmp_path: Path) -> None:
    event = _event(tmp_path)
    payload = json.loads(diagnostics._serialize_event(event))
    payload["unexpected"] = float("nan")
    data = json.dumps(payload, allow_nan=True).encode("utf-8")
    with pytest.raises(DiagnosticEventValidationError):
        diagnostics._strict_json_object(data)
