from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
from pds_core.registry_services import (
    RegistryServicePartialState,
    RegistryServicePartialSuccessError,
)

import scoreform.academic_work_registration as registration_module
from scoreform.academic_work_registration import (
    SCOREFORM_ACADEMIC_WORK_CONTRACT_VERSION,
    SCOREFORM_ACADEMIC_WORK_KIND,
    SCOREFORM_ASSIGNMENT_SOURCE_RECORD_KIND,
    ScoreFormAcademicWorkRegistrationConflictError,
    ScoreFormAcademicWorkRegistrationNotFoundError,
    ScoreFormAcademicWorkRegistrationValidationError,
    build_scoreform_academic_work_registration_request,
    load_managed_assignment_registration_context,
    register_scoreform_academic_work,
    update_scoreform_academic_work_registration,
)
from scoreform.work_paths import scoreform_work_paths


def _managed_assignment(tmp_path, *, title="Unit Quiz"):
    paths = scoreform_work_paths(tmp_path, "class1", "quiz1")
    paths.work_root.mkdir(parents=True)
    assignment = {
        "assignment_id": "quiz1",
        "title": title,
        "question_count": 1,
        "choices": ["A", "B", "C", "D"],
        "layout_id": "standard_15q_abcd_v1",
        "answer_key": {"1": "A"},
        "standards": {"1": []},
    }
    paths.assignment_path.write_text(json.dumps(assignment), encoding="utf-8")
    return paths


def test_exact_contract_mapping_is_immutable_and_pure(tmp_path):
    paths = _managed_assignment(tmp_path)
    context = load_managed_assignment_registration_context(
        tmp_path, "class1", "quiz1"
    )
    request = build_scoreform_academic_work_registration_request(
        context, academic_intent="summative", lifecycle="active"
    )

    assert request.work.module_id == "scoreform"
    assert request.work.class_id == "class1"
    assert request.work.work_id == "quiz1"
    assert request.producer_contract_version == SCOREFORM_ACADEMIC_WORK_CONTRACT_VERSION
    assert request.producer_contract_version == "scoreform_academic_work_v1"
    assert request.title == "Unit Quiz"
    assert request.work_kind == SCOREFORM_ACADEMIC_WORK_KIND == "assignment"
    assert request.academic_intent == "summative"
    assert request.lifecycle == "active"
    assert len(request.source_records) == 1
    source = request.source_records[0]
    assert source.module_id == "scoreform"
    assert source.record_kind == SCOREFORM_ASSIGNMENT_SOURCE_RECORD_KIND
    assert source.record_id == "quiz1"
    assert source.contract_version is None
    assert not (tmp_path / "registry").exists()
    assert paths.assignment_path.exists()
    with pytest.raises(FrozenInstanceError):
        request.title = "Changed"


@pytest.mark.parametrize(
    "intent,lifecycle",
    [("exam", "active"), ("summative", "finished")],
)
def test_request_rejects_unsupported_explicit_values(tmp_path, intent, lifecycle):
    _managed_assignment(tmp_path)
    context = load_managed_assignment_registration_context(
        tmp_path, "class1", "quiz1"
    )
    with pytest.raises(ScoreFormAcademicWorkRegistrationValidationError):
        build_scoreform_academic_work_registration_request(
            context, academic_intent=intent, lifecycle=lifecycle
        )
    assert not (tmp_path / "registry").exists()


def test_missing_or_mismatched_assignment_is_rejected_without_registry(tmp_path):
    with pytest.raises(ScoreFormAcademicWorkRegistrationNotFoundError):
        load_managed_assignment_registration_context(tmp_path, "class1", "quiz1")

    paths = _managed_assignment(tmp_path)
    data = json.loads(paths.assignment_path.read_text(encoding="utf-8"))
    data["assignment_id"] = "other"
    paths.assignment_path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ScoreFormAcademicWorkRegistrationValidationError):
        load_managed_assignment_registration_context(tmp_path, "class1", "quiz1")
    assert not (tmp_path / "registry").exists()


def test_create_exact_replay_and_update_preserve_producer_bytes(tmp_path):
    paths = _managed_assignment(tmp_path)
    assignment_bytes = paths.assignment_path.read_bytes()
    paths.roster_path.write_bytes(b"class_id,student_id\nclass1,student1\n")
    paths.results_path.write_bytes(b"result_history\n")
    roster_bytes = paths.roster_path.read_bytes()
    results_bytes = paths.results_path.read_bytes()

    created = register_scoreform_academic_work(
        tmp_path,
        "class1",
        "quiz1",
        academic_intent="formative",
        lifecycle="planned",
    )
    assert created.disposition == "created"
    assert created.registration.registration_revision == 1
    assert created.registration.created_at.tzinfo is not None
    revision_one = (
        tmp_path
        / "registry/work/class1/scoreform/quiz1/revisions/1.json"
    )
    current = tmp_path / "registry/work/class1/scoreform/quiz1/current.json"
    revision_bytes = revision_one.read_bytes()
    current_bytes = current.read_bytes()

    replay = register_scoreform_academic_work(
        tmp_path,
        "class1",
        "quiz1",
        academic_intent="formative",
        lifecycle="planned",
    )
    assert replay.disposition == "existing"
    assert replay.registration == created.registration
    assert revision_one.read_bytes() == revision_bytes
    assert current.read_bytes() == current_bytes
    assert not revision_one.with_name("2.json").exists()

    updated = update_scoreform_academic_work_registration(
        tmp_path,
        "class1",
        "quiz1",
        academic_intent="summative",
        lifecycle="active",
        expected_current_revision=1,
    )
    assert updated.disposition == "updated"
    assert updated.registration.registration_revision == 2
    assert updated.registration.created_at == created.registration.created_at
    assert updated.registration.updated_at >= created.registration.updated_at
    assert revision_one.read_bytes() == revision_bytes
    assert paths.assignment_path.read_bytes() == assignment_bytes
    assert paths.roster_path.read_bytes() == roster_bytes
    assert paths.results_path.read_bytes() == results_bytes
    assert not (tmp_path / "registry/publications").exists()
    assert not (tmp_path / "registry/withdrawals").exists()
    assert not (tmp_path / "registry/catalog.sqlite").exists()
    assert not (tmp_path / "settings/academic_periods").exists()
    assert not (tmp_path / "registry/.locks").exists()


def test_conflicting_initial_and_stale_update_fail_closed(tmp_path):
    _managed_assignment(tmp_path)
    register_scoreform_academic_work(
        tmp_path,
        "class1",
        "quiz1",
        academic_intent="formative",
        lifecycle="planned",
    )
    with pytest.raises(ScoreFormAcademicWorkRegistrationConflictError):
        register_scoreform_academic_work(
            tmp_path,
            "class1",
            "quiz1",
            academic_intent="summative",
            lifecycle="planned",
        )
    update_scoreform_academic_work_registration(
        tmp_path,
        "class1",
        "quiz1",
        academic_intent="summative",
        lifecycle="active",
        expected_current_revision=1,
    )
    with pytest.raises(ScoreFormAcademicWorkRegistrationConflictError):
        update_scoreform_academic_work_registration(
            tmp_path,
            "class1",
            "quiz1",
            academic_intent="diagnostic",
            lifecycle="active",
            expected_current_revision=1,
        )


@pytest.mark.parametrize("revision", [True, 0, -1])
def test_update_requires_positive_non_boolean_revision(tmp_path, revision):
    _managed_assignment(tmp_path)
    with pytest.raises(ScoreFormAcademicWorkRegistrationValidationError):
        update_scoreform_academic_work_registration(
            tmp_path,
            "class1",
            "quiz1",
            academic_intent="formative",
            lifecycle="active",
            expected_current_revision=revision,
        )
    assert not (tmp_path / "registry").exists()


def test_core_partial_success_state_and_cause_are_preserved(tmp_path, monkeypatch):
    _managed_assignment(tmp_path)
    state = RegistryServicePartialState(
        operation="register_academic_work",
        registration=None,
        publication=None,
        withdrawal=None,
        canonical_path=tmp_path / "registry/work/candidate.json",
        current_selected=False,
        message="revision durable; pointer uncertain",
    )
    core_error = RegistryServicePartialSuccessError("partial", state)

    def fail(*_args, **_kwargs):
        raise core_error

    monkeypatch.setattr(registration_module, "register_academic_work", fail)
    with pytest.raises(
        registration_module.ScoreFormAcademicWorkRegistrationPartialSuccessError
    ) as captured:
        register_scoreform_academic_work(
            tmp_path,
            "class1",
            "quiz1",
            academic_intent="formative",
            lifecycle="planned",
        )
    assert captured.value.state is state
    assert captured.value.__cause__ is core_error
    assert state.canonical_path.exists() is False
    assert not (tmp_path / "registry").exists()


def test_registration_writes_are_isolated_to_explicit_scoreform_boundary():
    scoreform_root = Path(registration_module.__file__).parent
    for source_path in scoreform_root.glob("*.py"):
        if source_path.name == "academic_work_registration.py":
            continue
        source = source_path.read_text(encoding="utf-8")
        assert "register_academic_work(" not in source, source_path.name
        assert "update_academic_work_registration(" not in source, source_path.name

    boundary_source = Path(registration_module.__file__).read_text(encoding="utf-8")
    assert "write_academic_work_registration" not in boundary_source
