"""Issue #192 Slice 2a Academic Work Registration diagnostic contracts."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest
from pds_core.registry_services import (
    RegistryServicePartialState,
    RegistryServicePartialSuccessError,
)

import scoreform.academic_work_registration as registration
import scoreform.diagnostic_events as diagnostics
from scoreform.work_paths import scoreform_work_paths


def _managed_assignment(tmp_path: Path) -> None:
    paths = scoreform_work_paths(tmp_path, "class1", "quiz1")
    paths.work_root.mkdir(parents=True)
    assignment = {
        "assignment_id": "quiz1",
        "title": "Synthetic Quiz",
        "question_count": 1,
        "choices": ["A", "B", "C", "D"],
        "layout_id": "standard_15q_abcd_v1",
        "answer_key": {"1": "A"},
        "standards": {"1": []},
    }
    paths.assignment_path.write_text(json.dumps(assignment), encoding="utf-8")


def _register(tmp_path: Path):
    return registration.register_scoreform_academic_work(
        tmp_path,
        "class1",
        "quiz1",
        academic_intent="formative",
        lifecycle="planned",
    )


def test_registration_uses_only_nonthrowing_diagnostic_boundary() -> None:
    source = inspect.getsource(registration)
    helper = inspect.getsource(registration._record_registration_service_error)

    assert "try_emit_diagnostic_event" in source
    assert "record_diagnostic_event(" not in source
    assert "build_diagnostic_event(" not in source
    assert "RegistryServicePartialSuccessError" in helper
    assert "registration_partial_success" in helper
    assert "RegistryServiceConflictError" in helper
    assert "registration_conflict" in helper
    assert 'outcome="success"' not in helper


def test_success_and_exact_replay_do_not_create_activity_history(
    tmp_path: Path,
) -> None:
    _managed_assignment(tmp_path)

    created = _register(tmp_path)
    replay = _register(tmp_path)

    assert created.disposition == "created"
    assert replay.disposition == "existing"
    assert diagnostics.list_diagnostic_events(tmp_path).events == ()


def test_registration_conflict_records_one_privacy_minimal_event(
    tmp_path: Path,
) -> None:
    _managed_assignment(tmp_path)
    _register(tmp_path)

    with pytest.raises(registration.ScoreFormAcademicWorkRegistrationConflictError):
        registration.register_scoreform_academic_work(
            tmp_path,
            "class1",
            "quiz1",
            academic_intent="summative",
            lifecycle="planned",
        )

    listing = diagnostics.list_diagnostic_events(tmp_path)
    assert len(listing.events) == 1
    event = listing.events[0]
    assert event.component == "publication"
    assert event.workflow == "register_academic_work"
    assert event.stage == "write_record"
    assert event.outcome == "blocked"
    assert event.code == "registration_conflict"
    assert event.class_id == "class1"
    assert event.assignment_id == "quiz1"
    assert event.exception_type == "RegistryServiceConflictError"
    assert event.path_context is None

    raw = diagnostics.diagnostic_event_path(
        tmp_path, event.event_id
    ).read_text(encoding="utf-8")
    for forbidden in (
        "Synthetic Quiz",
        '"answer_key"',
        '"student_id"',
        "Avery Rivera",
        "PRIVATE-STUDENT-SENTINEL",
    ):
        assert forbidden not in raw


def test_stale_update_conflict_is_instrumented_without_changing_exception(
    tmp_path: Path,
) -> None:
    _managed_assignment(tmp_path)
    _register(tmp_path)
    registration.update_scoreform_academic_work_registration(
        tmp_path,
        "class1",
        "quiz1",
        academic_intent="summative",
        lifecycle="active",
        expected_current_revision=1,
    )

    with pytest.raises(
        registration.ScoreFormAcademicWorkRegistrationConflictError
    ):
        registration.update_scoreform_academic_work_registration(
            tmp_path,
            "class1",
            "quiz1",
            academic_intent="diagnostic",
            lifecycle="active",
            expected_current_revision=1,
        )

    event = diagnostics.list_diagnostic_events(tmp_path).events[0]
    assert event.code == "registration_conflict"
    assert event.outcome == "blocked"


def test_partial_success_state_and_cause_survive_diagnostic_recording(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _managed_assignment(tmp_path)
    state = RegistryServicePartialState(
        operation="register_academic_work",
        registration=None,
        publication=None,
        withdrawal=None,
        canonical_path=tmp_path / "registry/work/private-sentinel.json",
        current_selected=False,
        message="PRIVATE-STUDENT-SENTINEL",
    )
    core_error = RegistryServicePartialSuccessError(
        "PRIVATE-STUDENT-SENTINEL C:\\Users\\Teacher Name\\private",
        state,
    )

    def fail(*_args: object, **_kwargs: object) -> None:
        raise core_error

    monkeypatch.setattr(registration, "register_academic_work", fail)

    with pytest.raises(
        registration.ScoreFormAcademicWorkRegistrationPartialSuccessError
    ) as captured:
        _register(tmp_path)

    assert captured.value.state is state
    assert captured.value.__cause__ is core_error

    listing = diagnostics.list_diagnostic_events(tmp_path)
    assert len(listing.events) == 1
    event = listing.events[0]
    assert event.code == "registration_partial_success"
    assert event.outcome == "partial_success"
    assert event.exception_type == "RegistryServicePartialSuccessError"

    raw = diagnostics.diagnostic_event_path(
        tmp_path, event.event_id
    ).read_text(encoding="utf-8")
    assert "PRIVATE-STUDENT-SENTINEL" not in raw
    assert "Teacher Name" not in raw
    assert "private-sentinel.json" not in raw


def test_diagnostic_storage_failure_cannot_replace_registration_conflict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _managed_assignment(tmp_path)
    _register(tmp_path)

    def fail_diagnostic_write(*_args: object, **_kwargs: object) -> object:
        raise diagnostics.DiagnosticEventStorageError(
            "PRIVATE-STUDENT-SENTINEL"
        )

    monkeypatch.setattr(
        diagnostics,
        "record_diagnostic_event",
        fail_diagnostic_write,
    )

    with pytest.raises(registration.ScoreFormAcademicWorkRegistrationConflictError):
        registration.register_scoreform_academic_work(
            tmp_path,
            "class1",
            "quiz1",
            academic_intent="summative",
            lifecycle="planned",
        )

    assert diagnostics.list_diagnostic_events(tmp_path).events == ()
