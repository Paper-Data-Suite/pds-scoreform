"""Issue #192 Slice 2b manifest/publication diagnostic contracts."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest
from pds_core.registry_services import (
    RegistryServiceConflictError,
    RegistryServicePartialState,
    RegistryServicePartialSuccessError,
)

import scoreform.academic_result_manifest_generation as manifest_generation
import scoreform.academic_result_publication as publication
import scoreform.diagnostic_events as diagnostics
from scoreform.academic_work_registration import register_scoreform_academic_work
from scoreform.page_scoring import ScoredAnswer
from scoreform.results import ScoreFormRoutedResult, export_scoreform_result_models
from scoreform.work_paths import scoreform_work_paths


def _result(*, student_id: str, answer: str) -> ScoreFormRoutedResult:
    return ScoreFormRoutedResult(
        result_origin="plain_paper_manual",
        class_id="class1",
        assignment_id="quiz1",
        student_id=student_id,
        last_name="Private",
        first_name="Student",
        period="2",
        page_display="manual",
        score=int(answer == "A"),
        total_points=1,
        answers=(ScoredAnswer(1, answer, answer == "A"),),
        source_file="plain_paper_manual_entry",
    )


def _native_assignment(tmp_path: Path) -> None:
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
    assert export_scoreform_result_models(
        (_result(student_id="student1", answer="A"),),
        workspace_root=tmp_path,
    ).succeeded


def _prepared_publication(tmp_path: Path):
    _native_assignment(tmp_path)
    register_scoreform_academic_work(
        tmp_path,
        "class1",
        "quiz1",
        academic_intent="summative",
        lifecycle="active",
    )
    return manifest_generation.generate_academic_result_manifest(
        tmp_path, "class1", "quiz1"
    )


def _codes(tmp_path: Path) -> list[str]:
    return [
        event.code
        for event in diagnostics.list_diagnostic_events(
            tmp_path,
            limit=diagnostics.MAX_EVENT_LIST_LIMIT,
        ).events
    ]


def test_manifest_instrumentation_uses_only_nonthrowing_boundary() -> None:
    source = inspect.getsource(manifest_generation)
    assert "try_emit_diagnostic_event" in source
    assert "record_diagnostic_event(" not in source
    assert "build_diagnostic_event(" not in source
    assert 'code="manifest_revision_created"' in source
    assert 'code="manifest_partial_success"' in source
    assert '"manifest_generation_failed"' in source


def test_new_manifest_emits_once_but_exact_replay_does_not(
    tmp_path: Path,
) -> None:
    _native_assignment(tmp_path)

    created = manifest_generation.generate_academic_result_manifest(
        tmp_path, "class1", "quiz1"
    )
    assert created.disposition.value != "reuse_existing"
    assert _codes(tmp_path).count("manifest_revision_created") == 1

    replay = manifest_generation.generate_academic_result_manifest(
        tmp_path, "class1", "quiz1"
    )
    assert replay.disposition.value == "reuse_existing"
    assert _codes(tmp_path).count("manifest_revision_created") == 1


def test_manifest_failure_records_no_private_exception_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _native_assignment(tmp_path)

    def fail(*_args: object, **_kwargs: object) -> None:
        raise manifest_generation.ScoreFormManifestGenerationWriteError(
            "PRIVATE-STUDENT-SENTINEL C:\\Users\\Teacher Name\\private"
        )

    monkeypatch.setattr(manifest_generation, "_write_new_revision", fail)

    with pytest.raises(
        manifest_generation.ScoreFormManifestGenerationWriteError
    ):
        manifest_generation.generate_academic_result_manifest(
            tmp_path, "class1", "quiz1"
        )

    event = diagnostics.list_diagnostic_events(tmp_path).events[0]
    assert event.code == "manifest_generation_failed"
    raw = diagnostics.diagnostic_event_path(
        tmp_path, event.event_id
    ).read_text(encoding="utf-8")
    assert "PRIVATE-STUDENT-SENTINEL" not in raw
    assert "Teacher Name" not in raw


def test_manifest_success_survives_diagnostic_storage_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _native_assignment(tmp_path)
    baseline = diagnostics.list_diagnostic_events(
        tmp_path,
        limit=diagnostics.MAX_EVENT_LIST_LIMIT,
    ).events

    def fail_record(*_args: object, **_kwargs: object) -> object:
        raise diagnostics.DiagnosticEventStorageError("diagnostic unavailable")

    monkeypatch.setattr(diagnostics, "record_diagnostic_event", fail_record)

    result = manifest_generation.generate_academic_result_manifest(
        tmp_path, "class1", "quiz1"
    )
    assert result.revision == 1
    assert result.path.is_file()
    after = diagnostics.list_diagnostic_events(
        tmp_path,
        limit=diagnostics.MAX_EVENT_LIST_LIMIT,
    ).events
    assert after == baseline


def test_publication_instrumentation_is_owner_service_only() -> None:
    source = inspect.getsource(publication)
    assert "try_emit_diagnostic_event" in source
    assert "record_diagnostic_event(" not in source
    assert "build_diagnostic_event(" not in source
    assert '"publication_verified"' in source
    assert '"supersession_verified"' in source
    assert '"publication_partial_success"' in source
    assert '"catalog_reconciliation_failed"' in source
    assert '"publication_conflict"' in source


def test_publication_created_emits_once_but_exact_replay_does_not(
    tmp_path: Path,
) -> None:
    manifest = _prepared_publication(tmp_path)

    created = publication.publish_scoreform_academic_results(
        tmp_path,
        "class1",
        "quiz1",
        manifest_revision=manifest.revision,
    )
    assert created.disposition == "created"
    assert _codes(tmp_path).count("publication_verified") == 1

    replay = publication.publish_scoreform_academic_results(
        tmp_path,
        "class1",
        "quiz1",
        manifest_revision=manifest.revision,
    )
    assert replay.disposition == "existing"
    assert _codes(tmp_path).count("publication_verified") == 1


def test_publication_service_conflict_is_privacy_minimal_and_preserved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _prepared_publication(tmp_path)
    core_error = RegistryServiceConflictError(
        "PRIVATE-STUDENT-SENTINEL C:\\Users\\Teacher Name\\private"
    )

    def fail(*_args: object, **_kwargs: object) -> None:
        raise core_error

    monkeypatch.setattr(publication, "publish_manifest_revision", fail)

    with pytest.raises(
        publication.ScoreFormAcademicResultPublicationConflictError
    ) as captured:
        publication.publish_scoreform_academic_results(
            tmp_path,
            "class1",
            "quiz1",
            manifest_revision=manifest.revision,
        )

    assert captured.value.__cause__ is core_error
    event = diagnostics.list_diagnostic_events(tmp_path).events[0]
    assert event.code == "publication_conflict"
    raw = diagnostics.diagnostic_event_path(
        tmp_path, event.event_id
    ).read_text(encoding="utf-8")
    assert "PRIVATE-STUDENT-SENTINEL" not in raw
    assert "Teacher Name" not in raw
    assert "PRIVATE-ASSIGNMENT-TITLE" not in raw


def test_publication_partial_success_state_survives_diagnostics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _prepared_publication(tmp_path)
    state = RegistryServicePartialState(
        operation="publish_manifest_revision",
        registration=None,
        publication=None,
        withdrawal=None,
        canonical_path=tmp_path / "registry/publications/private.json",
        current_selected=False,
        message="PRIVATE-STUDENT-SENTINEL",
    )
    core_error = RegistryServicePartialSuccessError(
        "PRIVATE-STUDENT-SENTINEL",
        state,
    )

    def fail(*_args: object, **_kwargs: object) -> None:
        raise core_error

    monkeypatch.setattr(publication, "publish_manifest_revision", fail)

    with pytest.raises(
        publication.ScoreFormAcademicResultPublicationPartialSuccessError
    ) as captured:
        publication.publish_scoreform_academic_results(
            tmp_path,
            "class1",
            "quiz1",
            manifest_revision=manifest.revision,
        )

    assert captured.value.__cause__ is core_error
    assert captured.value.state.canonical_state == "uncertain"
    event = diagnostics.list_diagnostic_events(tmp_path).events[0]
    assert event.code == "publication_partial_success"


def test_publication_success_survives_diagnostic_storage_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _prepared_publication(tmp_path)

    def fail_record(*_args: object, **_kwargs: object) -> object:
        raise diagnostics.DiagnosticEventStorageError("diagnostic unavailable")

    monkeypatch.setattr(diagnostics, "record_diagnostic_event", fail_record)

    result = publication.publish_scoreform_academic_results(
        tmp_path,
        "class1",
        "quiz1",
        manifest_revision=manifest.revision,
    )
    assert result.disposition == "created"
    assert result.publication.record_set_revision == manifest.revision


def test_verified_supersession_emits_one_success_event(
    tmp_path: Path,
) -> None:
    first_manifest = _prepared_publication(tmp_path)
    first = publication.publish_scoreform_academic_results(
        tmp_path,
        "class1",
        "quiz1",
        manifest_revision=first_manifest.revision,
    )

    assert export_scoreform_result_models(
        (_result(student_id="student2", answer="B"),),
        workspace_root=tmp_path,
    ).succeeded
    second_manifest = manifest_generation.generate_academic_result_manifest(
        tmp_path, "class1", "quiz1"
    )
    second = publication.supersede_scoreform_academic_results(
        tmp_path,
        "class1",
        "quiz1",
        manifest_revision=second_manifest.revision,
        expected_current_publication_id=first.publication.publication_id,
    )

    assert second.disposition == "created"
    assert _codes(tmp_path).count("supersession_verified") == 1
