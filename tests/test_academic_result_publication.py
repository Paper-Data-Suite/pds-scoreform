from __future__ import annotations

import json
import sqlite3
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest
from pds_core.academic_catalog import (
    AcademicCatalogBuildError,
    AcademicCatalogCompatibilityError,
    AcademicCatalogConflictError,
    AcademicCatalogIntegrityError,
    AcademicCatalogReadError,
    AcademicCatalogSourceError,
    AcademicCatalogValidationError,
)
from pds_core.publication_compatibility import PublicationCompatibilityResult
from pds_core.publication_storage import (
    get_current_publication_record,
    load_publication_withdrawal,
)
from pds_core.registry_paths import academic_catalog_lock_path
from pds_core.registry_services import (
    RegistryServicePartialState,
    RegistryServicePartialSuccessError,
)
from pds_core.routing_models import ModuleRecordRef

import scoreform.academic_result_publication as publication_module
from scoreform import cli_publication, menu_publication
from scoreform.academic_result_manifest_generation import (
    generate_academic_result_manifest,
    load_academic_result_manifest_revision,
)
from scoreform.academic_result_publication import (
    PublicationPartialSuccessState,
    ScoreFormAcademicResultPublicationConflictError,
    ScoreFormAcademicResultPublicationIntegrityError,
    ScoreFormAcademicResultPublicationPartialSuccessError,
    ScoreFormAcademicResultPublicationValidationError,
    ScoreFormAcademicResultPublicationWriteError,
    load_scoreform_publication_series_status,
    publish_scoreform_academic_results,
    rebuild_full_academic_catalog,
    republish_scoreform_academic_results_after_withdrawal,
    supersede_scoreform_academic_results,
    withdraw_scoreform_academic_result_publication,
)
from scoreform.academic_work_registration import (
    register_scoreform_academic_work,
    update_scoreform_academic_work_registration,
)
from scoreform.page_scoring import ScoredAnswer
from scoreform.publication_revision_policy import PublicationSupersessionRequirement
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


def _prepared(tmp_path):
    paths = scoreform_work_paths(tmp_path, "class1", "quiz1")
    paths.work_root.mkdir(parents=True)
    paths.assignment_path.write_text(
        json.dumps(
            {
                "assignment_id": "quiz1",
                "title": "Unit Quiz",
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
        (_result(student_id="student1", answer="A"),), workspace_root=tmp_path
    ).succeeded
    register_scoreform_academic_work(
        tmp_path,
        "class1",
        "quiz1",
        academic_intent="summative",
        lifecycle="active",
    )
    manifest = generate_academic_result_manifest(tmp_path, "class1", "quiz1")
    return paths, manifest


def test_initial_publish_exact_mapping_replay_and_catalog(tmp_path):
    paths, manifest = _prepared(tmp_path)
    manifest_bytes = paths.academic_result_manifests_dir.joinpath("1.json").read_bytes()

    created = publish_scoreform_academic_results(
        tmp_path, "class1", "quiz1", manifest_revision=manifest.revision
    )
    publication = created.publication
    assert created.disposition == "created"
    assert publication.publication_id.startswith("pub_")
    assert publication.source_record is None
    assert publication.capabilities == (
        "multiple_attempts",
        "points",
        "question_evidence",
    )
    assert publication.manifest_path == manifest.relative_path
    assert publication.manifest_digest == manifest.sha256
    assert publication.academic_work_registration_revision == 1
    assert created.compatibility.compatible
    assert created.catalog.publication.is_series_head
    assert created.catalog.publication.is_current_selectable

    replay = publish_scoreform_academic_results(
        tmp_path, "class1", "quiz1", manifest_revision=manifest.revision
    )
    assert replay.disposition == "existing"
    assert replay.publication == publication
    assert paths.academic_result_manifests_dir.joinpath("1.json").read_bytes() == manifest_bytes


def test_first_publication_accepts_producer_head_revision_greater_than_one(tmp_path):
    paths, first = _prepared(tmp_path)
    assert export_scoreform_result_models(
        (_result(student_id="student2", answer="B"),), workspace_root=tmp_path
    ).succeeded
    second = generate_academic_result_manifest(tmp_path, "class1", "quiz1")
    assert export_scoreform_result_models(
        (_result(student_id="student3", answer="A"),), workspace_root=tmp_path
    ).succeeded
    third = generate_academic_result_manifest(tmp_path, "class1", "quiz1")
    assert (first.revision, second.revision, third.revision) == (1, 2, 3)

    for stale in (1, 2):
        with pytest.raises(ScoreFormAcademicResultPublicationConflictError):
            publish_scoreform_academic_results(
                tmp_path, "class1", "quiz1", manifest_revision=stale
            )
    created = publish_scoreform_academic_results(
        tmp_path, "class1", "quiz1", manifest_revision=3
    )
    state = load_scoreform_publication_series_status(tmp_path, "class1", "quiz1")
    assert created.publication.record_set_revision == 3
    assert len(state.publications) == 1
    assert {item.record_set_revision for item in state.publications} == {3}
    assert {item.record_set_revision for item in state.catalog_rows} == {3}
    assert tuple(paths.academic_result_manifests_dir.glob("*.json"))


def test_initial_publish_rejects_nonempty_core_series(tmp_path):
    _paths, manifest = _prepared(tmp_path)
    publish_scoreform_academic_results(
        tmp_path, "class1", "quiz1", manifest_revision=manifest.revision
    )
    update_scoreform_academic_work_registration(
        tmp_path, "class1", "quiz1", academic_intent="summative",
        lifecycle="closed", expected_current_revision=1,
    )
    with pytest.raises(ScoreFormAcademicResultPublicationIntegrityError):
        publish_scoreform_academic_results(
            tmp_path, "class1", "quiz1", manifest_revision=manifest.revision
        )


def test_supersession_withdrawal_and_republication_preserve_history(tmp_path):
    paths, manifest = _prepared(tmp_path)
    first = publish_scoreform_academic_results(
        tmp_path, "class1", "quiz1", manifest_revision=manifest.revision
    )
    first_record = tmp_path / "registry/publications" / f"{first.publication.publication_id}.json"
    first_bytes = first_record.read_bytes()

    assert export_scoreform_result_models(
        (_result(student_id="student2", answer="B"),), workspace_root=tmp_path
    ).succeeded
    second_manifest = generate_academic_result_manifest(tmp_path, "class1", "quiz1")
    second = supersede_scoreform_academic_results(
        tmp_path,
        "class1",
        "quiz1",
        manifest_revision=second_manifest.revision,
        expected_current_publication_id=first.publication.publication_id,
    )
    assert second.publication.supersedes_publication_id == first.publication.publication_id
    assert second.supersession_requirement is not None
    assert first_record.read_bytes() == first_bytes

    withdrawn = withdraw_scoreform_academic_result_publication(
        tmp_path,
        "class1",
        "quiz1",
        publication_id=second.publication.publication_id,
        reason="Teacher requested correction",
    )
    assert withdrawn.disposition == "created"
    assert withdrawn.catalog.publication.is_series_head
    assert withdrawn.catalog.publication.is_withdrawn
    assert not withdrawn.catalog.publication.is_current_selectable
    replay = withdraw_scoreform_academic_result_publication(
        tmp_path,
        "class1",
        "quiz1",
        publication_id=second.publication.publication_id,
        reason="Teacher requested correction",
    )
    assert replay.disposition == "existing"
    with pytest.raises(ScoreFormAcademicResultPublicationConflictError):
        withdraw_scoreform_academic_result_publication(
            tmp_path,
            "class1",
            "quiz1",
            publication_id=second.publication.publication_id,
            reason="Different reason",
        )

    republished = republish_scoreform_academic_results_after_withdrawal(
        tmp_path,
        "class1",
        "quiz1",
        expected_withdrawn_head_publication_id=second.publication.publication_id,
    )
    assert republished.publication.record_set_revision == second_manifest.revision + 1
    assert republished.publication.supersedes_publication_id == second.publication.publication_id
    assert republished.catalog.publication.is_current_selectable
    assert (tmp_path / "registry/withdrawals" / f"{second.publication.publication_id}.json").exists()
    assert first_record.read_bytes() == first_bytes
    revision_files = tuple(paths.academic_result_manifests_dir.glob("*.json"))
    retry = republish_scoreform_academic_results_after_withdrawal(
        tmp_path,
        "class1",
        "quiz1",
        expected_withdrawn_head_publication_id=second.publication.publication_id,
    )
    assert retry.disposition == "existing"
    assert retry.publication == republished.publication
    assert tuple(paths.academic_result_manifests_dir.glob("*.json")) == revision_files


def test_supersession_uses_exact_policy_requirement(tmp_path, monkeypatch):
    paths, manifest = _prepared(tmp_path)
    first = publish_scoreform_academic_results(
        tmp_path, "class1", "quiz1", manifest_revision=manifest.revision
    )
    assert export_scoreform_result_models(
        (_result(student_id="student2", answer="B"),), workspace_root=tmp_path
    ).succeeded
    successor = generate_academic_result_manifest(tmp_path, "class1", "quiz1")
    real = publication_module.require_publication_supersession
    calls = []

    def observe(predecessor, successor_manifest, *, expected_current_publication_id):
        calls.append((predecessor, successor_manifest, expected_current_publication_id))
        return real(
            predecessor,
            successor_manifest,
            expected_current_publication_id=expected_current_publication_id,
        )

    monkeypatch.setattr(publication_module, "require_publication_supersession", observe)
    result = supersede_scoreform_academic_results(
        tmp_path, "class1", "quiz1", manifest_revision=successor.revision,
        expected_current_publication_id=first.publication.publication_id,
    )
    assert len(calls) == 1
    predecessor, successor_manifest, expected_id = calls[0]
    assert expected_id == first.publication.publication_id
    assert predecessor.record_set.revision == 1
    assert successor_manifest.record_set.revision == 2
    assert result.supersession_requirement == PublicationSupersessionRequirement(
        expected_current_publication_id=first.publication.publication_id,
        publication_kind="academic_result_set",
        record_set_id="academic_results",
        predecessor_revision=1,
        successor_revision=2,
    )
    assert paths.academic_result_manifests_dir.joinpath("1.json").exists()


def test_contradictory_supersession_requirement_fails_before_core_write(
    tmp_path, monkeypatch
):
    _paths, manifest = _prepared(tmp_path)
    first = publish_scoreform_academic_results(
        tmp_path, "class1", "quiz1", manifest_revision=manifest.revision
    )
    assert export_scoreform_result_models(
        (_result(student_id="student2", answer="B"),), workspace_root=tmp_path
    ).succeeded
    successor = generate_academic_result_manifest(tmp_path, "class1", "quiz1")
    monkeypatch.setattr(
        publication_module,
        "require_publication_supersession",
        lambda *_args, **_kwargs: PublicationSupersessionRequirement(
            expected_current_publication_id=first.publication.publication_id,
            publication_kind="academic_result_set",
            record_set_id="academic_results",
            predecessor_revision=1,
            successor_revision=3,
        ),
    )
    core_called = False

    def forbidden(*_args, **_kwargs):
        nonlocal core_called
        core_called = True
        raise AssertionError("Core supersession must not run")

    monkeypatch.setattr(publication_module, "supersede_manifest_revision", forbidden)
    with pytest.raises(ScoreFormAcademicResultPublicationIntegrityError):
        supersede_scoreform_academic_results(
            tmp_path, "class1", "quiz1", manifest_revision=successor.revision,
            expected_current_publication_id=first.publication.publication_id,
        )
    assert not core_called
    assert len(publication_module._load_series(tmp_path, first.publication.work)) == 1


def test_withdrawn_core_head_is_retained_and_republication_supersedes_it(tmp_path):
    _paths, manifest = _prepared(tmp_path)
    first = publish_scoreform_academic_results(
        tmp_path, "class1", "quiz1", manifest_revision=manifest.revision
    )
    assert export_scoreform_result_models(
        (_result(student_id="student2", answer="B"),), workspace_root=tmp_path
    ).succeeded
    second_manifest = generate_academic_result_manifest(tmp_path, "class1", "quiz1")
    second = supersede_scoreform_academic_results(
        tmp_path, "class1", "quiz1", manifest_revision=second_manifest.revision,
        expected_current_publication_id=first.publication.publication_id,
    )
    withdraw_scoreform_academic_result_publication(
        tmp_path, "class1", "quiz1", publication_id=second.publication.publication_id,
        reason="Correction required",
    )
    assert get_current_publication_record(
        tmp_path, second.publication.work, "academic_result_set", "academic_results"
    ) is None
    state = load_scoreform_publication_series_status(tmp_path, "class1", "quiz1")
    assert state.core_head == second.publication
    assert state.core_head_withdrawal is not None
    assert state.current_selectable_publication is None
    republished = republish_scoreform_academic_results_after_withdrawal(
        tmp_path, "class1", "quiz1",
        expected_withdrawn_head_publication_id=second.publication.publication_id,
    )
    assert republished.publication.supersedes_publication_id == second.publication.publication_id
    assert republished.publication.supersedes_publication_id != first.publication.publication_id
    assert load_publication_withdrawal(tmp_path, second.publication.publication_id) is not None


def test_compatibility_uses_exact_referenced_registration_after_current_advances(
    tmp_path, monkeypatch
):
    _paths, manifest = _prepared(tmp_path)
    real_verify = publication_module.verify_publication_manifest
    real_compatibility = publication_module.evaluate_publication_compatibility
    observed = []

    def advance(root, publication):
        resolved = real_verify(root, publication)
        update_scoreform_academic_work_registration(
            root, "class1", "quiz1", academic_intent="summative",
            lifecycle="closed", expected_current_revision=1,
        )
        return resolved

    def observe(publication, profile, registration):
        observed.append(registration.registration_revision)
        return real_compatibility(publication, profile, registration)

    monkeypatch.setattr(publication_module, "verify_publication_manifest", advance)
    monkeypatch.setattr(publication_module, "evaluate_publication_compatibility", observe)
    result = publish_scoreform_academic_results(
        tmp_path, "class1", "quiz1", manifest_revision=manifest.revision
    )
    assert result.registration.registration_revision == 1
    assert observed == [1]
    assert result.compatibility.compatible and result.compatibility.codes == ()


def test_public_result_models_are_frozen_slotted_and_validate_types(tmp_path):
    _paths, manifest = _prepared(tmp_path)
    result = publish_scoreform_academic_results(
        tmp_path, "class1", "quiz1", manifest_revision=manifest.revision
    )
    state = load_scoreform_publication_series_status(tmp_path, "class1", "quiz1")
    for model, attribute in (
        (result, "operation"),
        (result.catalog, "build"),
        (state, "work"),
    ):
        assert not hasattr(model, "__dict__")
        with pytest.raises(FrozenInstanceError):
            setattr(model, attribute, None)
    with pytest.raises(TypeError):
        replace(state, producer_revisions=(True,))
    partial = PublicationPartialSuccessState(
        operation="publish", publication=result.publication, withdrawal=None,
        manifest=state.producer_head, canonical_state="confirmed",
        catalog_rebuild_attempted=True, catalog_replacement_completed=True,
        catalog_verification_completed=True, recommended_next_action="none",
        catalog_build=result.catalog.build,
    )
    assert not hasattr(partial, "__dict__")
    with pytest.raises(FrozenInstanceError):
        partial.canonical_state = "uncertain"
    with pytest.raises(ValueError):
        replace(partial, catalog_rebuild_attempted=False)


def test_status_does_not_create_missing_catalog(tmp_path):
    _prepared(tmp_path)
    state = load_scoreform_publication_series_status(tmp_path, "class1", "quiz1")
    assert not state.catalog_available
    assert not (tmp_path / "registry/catalog.sqlite").exists()


def test_explicit_full_rebuild_creates_missing_and_replaces_healthy_catalog(tmp_path):
    _prepared(tmp_path)
    catalog = tmp_path / "registry/catalog.sqlite"
    assert not catalog.exists()
    first = rebuild_full_academic_catalog(tmp_path)
    assert catalog.is_file()
    assert not first.replaced_existing_catalog
    second = rebuild_full_academic_catalog(tmp_path)
    assert second.replaced_existing_catalog


def test_explicit_rebuild_replaces_stale_catalog(tmp_path):
    _paths, manifest = _prepared(tmp_path)
    first = publish_scoreform_academic_results(
        tmp_path, "class1", "quiz1", manifest_revision=manifest.revision
    )
    old_hash = publication_module.load_academic_catalog_metadata(
        tmp_path
    ).source_snapshot_sha256
    assert export_scoreform_result_models(
        (_result(student_id="student2", answer="B"),), workspace_root=tmp_path
    ).succeeded
    successor = generate_academic_result_manifest(tmp_path, "class1", "quiz1")
    stored_successor = load_academic_result_manifest_revision(
        tmp_path, first.publication.work, successor.revision
    )
    registration = publication_module._current_registration(
        tmp_path, first.publication.work
    )
    publication_module.supersede_manifest_revision(
        tmp_path,
        publication_module._request(stored_successor, registration),
        expected_current_publication_id=first.publication.publication_id,
    )
    rebuilt = rebuild_full_academic_catalog(tmp_path)
    assert rebuilt.replaced_existing_catalog
    assert rebuilt.metadata.source_snapshot_sha256 != old_hash
    state = load_scoreform_publication_series_status(tmp_path, "class1", "quiz1")
    assert len(state.catalog_rows) == 2
    assert state.core_head.record_set_revision == 2


def test_explicit_rebuild_replaces_corrupt_but_identifiable_catalog(tmp_path):
    _paths, manifest = _prepared(tmp_path)
    publish_scoreform_academic_results(
        tmp_path, "class1", "quiz1", manifest_revision=manifest.revision
    )
    catalog = tmp_path / "registry/catalog.sqlite"
    connection = sqlite3.connect(catalog)
    try:
        connection.execute("DROP TABLE publications")
        connection.commit()
    finally:
        connection.close()
    rebuilt = rebuild_full_academic_catalog(tmp_path)
    assert rebuilt.replaced_existing_catalog
    assert load_scoreform_publication_series_status(
        tmp_path, "class1", "quiz1"
    ).catalog_available


def test_catalog_lock_is_never_removed_by_scoreform(tmp_path):
    _prepared(tmp_path)
    lock = academic_catalog_lock_path(tmp_path)
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("owned elsewhere", encoding="utf-8")
    with pytest.raises(ScoreFormAcademicResultPublicationConflictError):
        rebuild_full_academic_catalog(tmp_path)
    assert lock.read_text(encoding="utf-8") == "owned elsewhere"


def test_publication_workflows_are_not_invoked_automatically():
    allowed = {
        "academic_result_publication.py",
        "cli_publication.py",
        "menu_publication.py",
    }
    names = (
        "publish_scoreform_academic_results(",
        "supersede_scoreform_academic_results(",
        "republish_scoreform_academic_results_after_withdrawal(",
        "withdraw_scoreform_academic_result_publication(",
    )
    for name in names:
        references = {
            path.name
            for path in Path("scoreform").glob("*.py")
            if name in path.read_text(encoding="utf-8")
        }
        assert references <= allowed
    generation_callers = {
        path.name
        for path in Path("scoreform").glob("*.py")
        if "generate_academic_result_manifest(" in path.read_text(encoding="utf-8")
    }
    assert generation_callers <= {
        "academic_result_manifest_generation.py",
        "academic_result_publication.py",
        "cli_manifest.py",
        "menu_manifest.py",
    }
    publication_source = Path("scoreform/academic_result_publication.py").read_text(
        encoding="utf-8"
    )
    assert publication_source.count("generate_academic_result_manifest(") == 1
    assert "republish_after_withdrawal=True" in publication_source


def test_nonpublication_cli_help_version_and_import_are_pure(tmp_path, monkeypatch):
    from scoreform.cli import main

    def forbidden(*_args, **_kwargs):
        raise AssertionError("publication workflow invoked")
    for name in (
        "publish_scoreform_academic_results",
        "supersede_scoreform_academic_results",
        "republish_scoreform_academic_results_after_withdrawal",
        "withdraw_scoreform_academic_result_publication",
    ):
        monkeypatch.setattr(publication_module, name, forbidden)
    monkeypatch.chdir(tmp_path)
    assert main(["help"], default_to_menu=False) == 0
    assert main(["--help"], default_to_menu=False) == 0
    assert main(["version"], default_to_menu=False) == 0
    assert main(["--version"], default_to_menu=False) == 0
    assert not (tmp_path / "registry").exists()
    assert not (tmp_path / "exports/manifests").exists()


def test_registration_race_fails_before_publication(tmp_path, monkeypatch):
    _paths, manifest = _prepared(tmp_path)
    real_publish = publication_module.publish_manifest_revision

    def race(root, request):
        update_scoreform_academic_work_registration(
            root,
            "class1",
            "quiz1",
            academic_intent="summative",
            lifecycle="closed",
            expected_current_revision=1,
        )
        return real_publish(root, request)

    monkeypatch.setattr(publication_module, "publish_manifest_revision", race)
    with pytest.raises(ScoreFormAcademicResultPublicationConflictError):
        publish_scoreform_academic_results(
            tmp_path, "class1", "quiz1", manifest_revision=manifest.revision
        )
    assert not (tmp_path / "registry/publications").exists()


def test_manifest_byte_race_fails_before_publication(tmp_path, monkeypatch):
    paths, manifest = _prepared(tmp_path)
    real_publish = publication_module.publish_manifest_revision

    def race(root, request):
        paths.academic_result_manifests_dir.joinpath("1.json").write_bytes(b"{}")
        return real_publish(root, request)

    monkeypatch.setattr(publication_module, "publish_manifest_revision", race)
    with pytest.raises(ScoreFormAcademicResultPublicationIntegrityError):
        publish_scoreform_academic_results(
            tmp_path, "class1", "quiz1", manifest_revision=manifest.revision
        )
    assert not (tmp_path / "registry/publications").exists()


def test_exact_logical_replay_race_reconciles_one_publication(tmp_path, monkeypatch):
    _paths, manifest = _prepared(tmp_path)
    real_publish = publication_module.publish_manifest_revision

    def race(root, request):
        first = real_publish(root, request)
        assert first.disposition == "created"
        return real_publish(root, request)

    monkeypatch.setattr(publication_module, "publish_manifest_revision", race)
    result = publish_scoreform_academic_results(
        tmp_path, "class1", "quiz1", manifest_revision=manifest.revision
    )
    assert result.disposition == "existing"
    assert len(load_scoreform_publication_series_status(tmp_path, "class1", "quiz1").publications) == 1


def test_contradictory_logical_revision_fails_closed(tmp_path):
    _paths, manifest = _prepared(tmp_path)
    publish_scoreform_academic_results(
        tmp_path, "class1", "quiz1", manifest_revision=manifest.revision
    )
    update_scoreform_academic_work_registration(
        tmp_path,
        "class1",
        "quiz1",
        academic_intent="summative",
        lifecycle="closed",
        expected_current_revision=1,
    )
    with pytest.raises(ScoreFormAcademicResultPublicationIntegrityError):
        publish_scoreform_academic_results(
            tmp_path, "class1", "quiz1", manifest_revision=manifest.revision
        )
    assert len(load_scoreform_publication_series_status(tmp_path, "class1", "quiz1").publications) == 1


@pytest.mark.parametrize(
    "dimension",
    ["digest", "manifest_path", "registration_revision", "capabilities", "source_record"],
)
def test_logical_revision_contradictions_create_no_duplicate(
    tmp_path, monkeypatch, dimension
):
    paths, manifest = _prepared(tmp_path)
    created = publish_scoreform_academic_results(
        tmp_path, "class1", "quiz1", manifest_revision=manifest.revision
    )
    if dimension == "registration_revision":
        update_scoreform_academic_work_registration(
            tmp_path, "class1", "quiz1", academic_intent="summative",
            lifecycle="closed", expected_current_revision=1,
        )
    real_request = publication_module._request

    def contradictory(stored, registration):
        request = real_request(stored, registration)
        if dimension == "digest":
            return replace(request, expected_manifest_digest="0" * 64)
        if dimension == "manifest_path":
            alias = paths.academic_result_manifests_dir / "2.json"
            alias.write_bytes(stored.content)
            relative = alias.relative_to(tmp_path).as_posix()
            return replace(request, manifest_path=relative)
        if dimension == "capabilities":
            return replace(request, capabilities=("points",))
        if dimension == "source_record":
            return replace(
                request,
                source_record=ModuleRecordRef("scoreform", "assignment", "quiz1", None),
            )
        return request

    monkeypatch.setattr(publication_module, "_request", contradictory)
    with pytest.raises(ScoreFormAcademicResultPublicationIntegrityError):
        publish_scoreform_academic_results(
            tmp_path, "class1", "quiz1", manifest_revision=manifest.revision
        )
    series = publication_module._load_series(tmp_path, created.publication.work)
    assert len(series) == 1
    assert series[0].publication_id == created.publication.publication_id


def test_logical_revision_contradictory_predecessor_creates_no_duplicate(tmp_path):
    _paths, manifest = _prepared(tmp_path)
    first = publish_scoreform_academic_results(
        tmp_path, "class1", "quiz1", manifest_revision=manifest.revision
    )
    assert export_scoreform_result_models(
        (_result(student_id="student2", answer="B"),), workspace_root=tmp_path
    ).succeeded
    successor_manifest = generate_academic_result_manifest(tmp_path, "class1", "quiz1")
    second = supersede_scoreform_academic_results(
        tmp_path, "class1", "quiz1", manifest_revision=successor_manifest.revision,
        expected_current_publication_id=first.publication.publication_id,
    )
    with pytest.raises(ScoreFormAcademicResultPublicationIntegrityError):
        supersede_scoreform_academic_results(
            tmp_path, "class1", "quiz1", manifest_revision=successor_manifest.revision,
            expected_current_publication_id=second.publication.publication_id,
        )
    assert len(publication_module._load_series(tmp_path, first.publication.work)) == 2


def test_concurrent_same_reason_withdrawal_reconciles(tmp_path, monkeypatch):
    _paths, manifest = _prepared(tmp_path)
    publication = publish_scoreform_academic_results(
        tmp_path, "class1", "quiz1", manifest_revision=manifest.revision
    ).publication
    real_withdraw = publication_module.withdraw_publication

    def race(root, request):
        first = real_withdraw(root, request)
        assert first.disposition == "created"
        return real_withdraw(root, request)

    monkeypatch.setattr(publication_module, "withdraw_publication", race)
    result = withdraw_scoreform_academic_result_publication(
        tmp_path,
        "class1",
        "quiz1",
        publication_id=publication.publication_id,
        reason="Same private reason",
    )
    assert result.disposition == "existing"
    assert load_publication_withdrawal(tmp_path, publication.publication_id) == result.withdrawal


def test_post_write_verification_failure_reports_partial_success(tmp_path, monkeypatch):
    _paths, manifest = _prepared(tmp_path)

    def fail_verify(*_args, **_kwargs):
        raise OSError("injected verification failure")

    monkeypatch.setattr(publication_module, "verify_publication_manifest", fail_verify)
    with pytest.raises(ScoreFormAcademicResultPublicationPartialSuccessError) as caught:
        publish_scoreform_academic_results(
            tmp_path, "class1", "quiz1", manifest_revision=manifest.revision
        )
    state = caught.value.state
    assert state.publication is not None
    assert state.canonical_state_confirmed
    assert not state.catalog_rebuild_attempted
    assert len(publication_module._load_series(tmp_path, state.publication.work)) == 1


@pytest.mark.parametrize(
    "stage",
    [
        "canonical_publication_reload",
        "series_revalidation",
        "profile_compatibility",
        "catalog_rebuild_conflict",
        "catalog_source_conflict",
        "catalog_build_failure",
        "catalog_query_failure",
        "catalog_row_contradiction",
    ],
)
def test_post_write_partial_success_stages_preserve_canonical_publication(
    tmp_path, monkeypatch, stage
):
    _paths, manifest = _prepared(tmp_path)
    if stage == "canonical_publication_reload":
        monkeypatch.setattr(
            publication_module,
            "load_scoreform_publication",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("reload")),
        )
    elif stage == "series_revalidation":
        monkeypatch.setattr(
            publication_module,
            "_load_series",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("series")),
        )
    elif stage == "profile_compatibility":
        monkeypatch.setattr(
            publication_module,
            "evaluate_publication_compatibility",
            lambda *_args, **_kwargs: PublicationCompatibilityResult(False, ("injected",)),
        )
    elif stage.startswith("catalog_") and stage not in {
        "catalog_query_failure", "catalog_row_contradiction"
    }:
        error_type = {
            "catalog_rebuild_conflict": AcademicCatalogConflictError,
            "catalog_source_conflict": AcademicCatalogSourceError,
            "catalog_build_failure": AcademicCatalogBuildError,
        }[stage]
        monkeypatch.setattr(
            publication_module,
            "rebuild_academic_catalog",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(error_type("injected")),
        )
    elif stage == "catalog_query_failure":
        monkeypatch.setattr(
            publication_module,
            "query_publication_catalog",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AcademicCatalogReadError("injected")
            ),
        )
    else:
        monkeypatch.setattr(publication_module, "query_publication_catalog", lambda *_: ())

    with pytest.raises(ScoreFormAcademicResultPublicationPartialSuccessError) as caught:
        publish_scoreform_academic_results(
            tmp_path, "class1", "quiz1", manifest_revision=manifest.revision
        )
    durable = caught.value.state.publication
    assert durable is not None
    assert caught.value.state.canonical_state == "confirmed"
    assert (tmp_path / "registry/publications" / f"{durable.publication_id}.json").exists()


def test_canonical_withdrawal_reload_failure_preserves_durable_withdrawal(
    tmp_path, monkeypatch
):
    _paths, manifest = _prepared(tmp_path)
    publication = publish_scoreform_academic_results(
        tmp_path, "class1", "quiz1", manifest_revision=manifest.revision
    ).publication
    real_load = publication_module.load_scoreform_publication
    calls = 0

    def fail_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("canonical withdrawal reload")
        return real_load(*args, **kwargs)

    monkeypatch.setattr(publication_module, "load_scoreform_publication", fail_second)
    with pytest.raises(ScoreFormAcademicResultPublicationPartialSuccessError) as caught:
        withdraw_scoreform_academic_result_publication(
            tmp_path, "class1", "quiz1", publication_id=publication.publication_id,
            reason="Still durable",
        )
    assert caught.value.state.canonical_state == "confirmed"
    assert load_publication_withdrawal(tmp_path, publication.publication_id) is not None


def test_catalog_source_race_reports_partial_and_exact_replay_repairs(
    tmp_path, monkeypatch
):
    _paths, manifest = _prepared(tmp_path)
    real_rebuild = publication_module.rebuild_academic_catalog

    def fail_rebuild(_root):
        raise AcademicCatalogConflictError("injected source race")

    monkeypatch.setattr(publication_module, "rebuild_academic_catalog", fail_rebuild)
    with pytest.raises(ScoreFormAcademicResultPublicationPartialSuccessError) as caught:
        publish_scoreform_academic_results(
            tmp_path, "class1", "quiz1", manifest_revision=manifest.revision
        )
    publication_id = caught.value.state.publication.publication_id
    assert caught.value.state.catalog_rebuild_attempted
    assert not caught.value.state.catalog_installed

    monkeypatch.setattr(publication_module, "rebuild_academic_catalog", real_rebuild)
    repaired = publish_scoreform_academic_results(
        tmp_path, "class1", "quiz1", manifest_revision=manifest.revision
    )
    assert repaired.disposition == "existing"
    assert repaired.publication.publication_id == publication_id
    assert repaired.catalog.publication.publication_id == publication_id


def test_core_head_race_fails_stale_request_without_branch(tmp_path, monkeypatch):
    paths, manifest = _prepared(tmp_path)
    first = publish_scoreform_academic_results(
        tmp_path, "class1", "quiz1", manifest_revision=manifest.revision
    )
    assert export_scoreform_result_models(
        (_result(student_id="student2", answer="B"),), workspace_root=tmp_path
    ).succeeded
    generate_academic_result_manifest(tmp_path, "class1", "quiz1")
    assert export_scoreform_result_models(
        (_result(student_id="student3", answer="A"),), workspace_root=tmp_path
    ).succeeded
    third = generate_academic_result_manifest(tmp_path, "class1", "quiz1")
    real_supersede = publication_module.supersede_manifest_revision

    def race(root, request, *, expected_current_publication_id):
        second = load_academic_result_manifest_revision(root, paths.work_ref, 2)
        registration = publication_module._current_registration(root, paths.work_ref)
        real_supersede(
            root,
            publication_module._request(second, registration),
            expected_current_publication_id=expected_current_publication_id,
        )
        return real_supersede(
            root,
            request,
            expected_current_publication_id=expected_current_publication_id,
        )

    monkeypatch.setattr(publication_module, "supersede_manifest_revision", race)
    with pytest.raises(ScoreFormAcademicResultPublicationConflictError):
        supersede_scoreform_academic_results(
            tmp_path,
            "class1",
            "quiz1",
            manifest_revision=third.revision,
            expected_current_publication_id=first.publication.publication_id,
        )
    series = publication_module._load_series(tmp_path, paths.work_ref)
    assert len(series) == 2
    assert publication_module._series_head(series).record_set_revision == 2
    assert not any(item.record_set_revision == 3 for item in series)


@pytest.mark.parametrize("operation", ["publish", "supersede", "withdraw"])
def test_core_partial_success_preserves_state_without_retry_or_catalog(
    tmp_path, monkeypatch, operation
):
    paths, manifest = _prepared(tmp_path)
    first = None
    selected_manifest = manifest
    if operation != "publish":
        first = publish_scoreform_academic_results(
            tmp_path, "class1", "quiz1", manifest_revision=manifest.revision
        )
    if operation == "supersede":
        assert export_scoreform_result_models(
            (_result(student_id="student2", answer="B"),), workspace_root=tmp_path
        ).succeeded
        selected_manifest = generate_academic_result_manifest(tmp_path, "class1", "quiz1")

    service_name = {
        "publish": "publish_manifest_revision",
        "supersede": "supersede_manifest_revision",
        "withdraw": "withdraw_publication",
    }[operation]
    real_service = getattr(publication_module, service_name)
    service_calls = 0

    def partial(*args, **kwargs):
        nonlocal service_calls
        service_calls += 1
        durable = real_service(*args, **kwargs)
        state = RegistryServicePartialState(
            operation={
                "publish": "publish_manifest_revision",
                "supersede": "supersede_manifest_revision",
                "withdraw": "withdraw_publication",
            }[operation],
            registration=None,
            publication=durable.publication,
            withdrawal=durable.withdrawal,
            canonical_path=tmp_path / "registry/publications" / f"{durable.publication.publication_id}.json",
            current_selected=None,
            message="injected post-write uncertainty",
        )
        raise RegistryServicePartialSuccessError("injected partial", state)

    catalog_called = False

    def forbidden_catalog(*_args, **_kwargs):
        nonlocal catalog_called
        catalog_called = True
        raise AssertionError("catalog reconciliation must not run")

    monkeypatch.setattr(publication_module, service_name, partial)
    monkeypatch.setattr(
        publication_module, "rebuild_scoreform_publication_catalog", forbidden_catalog
    )
    with pytest.raises(ScoreFormAcademicResultPublicationPartialSuccessError) as caught:
        if operation == "publish":
            publish_scoreform_academic_results(
                tmp_path, "class1", "quiz1", manifest_revision=manifest.revision
            )
        elif operation == "supersede":
            supersede_scoreform_academic_results(
                tmp_path, "class1", "quiz1", manifest_revision=selected_manifest.revision,
                expected_current_publication_id=first.publication.publication_id,
            )
        else:
            withdraw_scoreform_academic_result_publication(
                tmp_path, "class1", "quiz1",
                publication_id=first.publication.publication_id,
                reason="Durable withdrawal",
            )
    assert service_calls == 1
    assert not catalog_called
    assert caught.value.state.canonical_state == "uncertain"
    assert caught.value.__cause__.__class__ is RegistryServicePartialSuccessError
    publication = caught.value.state.publication
    assert publication is not None
    assert (tmp_path / "registry/publications" / f"{publication.publication_id}.json").exists()
    assert paths.academic_result_manifests_dir.joinpath(
        f"{selected_manifest.revision}.json"
    ).exists()
    if operation == "withdraw":
        assert load_publication_withdrawal(tmp_path, publication.publication_id) is not None


def test_catalog_lock_contention_is_partial_success(tmp_path, monkeypatch):
    _paths, manifest = _prepared(tmp_path)

    def lock_conflict(_root):
        raise AcademicCatalogConflictError("injected catalog lock contention")

    monkeypatch.setattr(publication_module, "rebuild_academic_catalog", lock_conflict)
    with pytest.raises(ScoreFormAcademicResultPublicationPartialSuccessError) as caught:
        publish_scoreform_academic_results(
            tmp_path, "class1", "quiz1", manifest_revision=manifest.revision
        )
    assert caught.value.state.publication is not None
    assert caught.value.state.catalog_rebuild_attempted
    assert not caught.value.state.catalog_verified


def test_historical_and_damaged_manifest_publications_can_be_withdrawn(
    tmp_path,
):
    paths, manifest = _prepared(tmp_path)
    first = publish_scoreform_academic_results(
        tmp_path, "class1", "quiz1", manifest_revision=manifest.revision
    )
    assert export_scoreform_result_models(
        (_result(student_id="student2", answer="B"),), workspace_root=tmp_path
    ).succeeded
    successor_manifest = generate_academic_result_manifest(tmp_path, "class1", "quiz1")
    successor = supersede_scoreform_academic_results(
        tmp_path,
        "class1",
        "quiz1",
        manifest_revision=successor_manifest.revision,
        expected_current_publication_id=first.publication.publication_id,
    )
    historical = withdraw_scoreform_academic_result_publication(
        tmp_path,
        "class1",
        "quiz1",
        publication_id=first.publication.publication_id,
        reason="Historical correction",
    )
    assert historical.withdrawal.publication_id == first.publication.publication_id
    assert historical.catalog.publication.is_withdrawn
    assert not historical.catalog.publication.is_series_head
    paths.academic_result_manifests_dir.joinpath("2.json").write_bytes(b"damaged")
    damaged = withdraw_scoreform_academic_result_publication(
        tmp_path,
        "class1",
        "quiz1",
        publication_id=successor.publication.publication_id,
        reason="Damaged evidence withdrawn",
    )
    assert damaged.disposition == "created"
    assert paths.academic_result_manifests_dir.joinpath("2.json").read_bytes() == b"damaged"
    assert load_publication_withdrawal(
        tmp_path, successor.publication.publication_id
    ) is not None


def test_ordinary_publish_does_not_republish_withdrawn_head(tmp_path):
    _paths, manifest = _prepared(tmp_path)
    first = publish_scoreform_academic_results(
        tmp_path, "class1", "quiz1", manifest_revision=manifest.revision
    )
    withdraw_scoreform_academic_result_publication(
        tmp_path, "class1", "quiz1", publication_id=first.publication.publication_id,
        reason="Withdrawn",
    )
    replay = publish_scoreform_academic_results(
        tmp_path, "class1", "quiz1", manifest_revision=manifest.revision
    )
    assert replay.disposition == "existing"
    assert replay.publication == first.publication
    assert replay.withdrawal is not None
    assert not replay.catalog.publication.is_current_selectable
    assert len(publication_module._load_series(tmp_path, first.publication.work)) == 1


def test_republication_failure_after_generation_reuses_successor_on_retry(
    tmp_path, monkeypatch
):
    paths, manifest = _prepared(tmp_path)
    first = publish_scoreform_academic_results(
        tmp_path, "class1", "quiz1", manifest_revision=manifest.revision
    )
    withdraw_scoreform_academic_result_publication(
        tmp_path, "class1", "quiz1", publication_id=first.publication.publication_id,
        reason="Correct then republish",
    )
    real_supersede = publication_module.supersede_scoreform_academic_results
    monkeypatch.setattr(
        publication_module,
        "supersede_scoreform_academic_results",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ScoreFormAcademicResultPublicationConflictError("injected before Core write")
        ),
    )
    with pytest.raises(ScoreFormAcademicResultPublicationPartialSuccessError) as caught:
        republish_scoreform_academic_results_after_withdrawal(
            tmp_path, "class1", "quiz1",
            expected_withdrawn_head_publication_id=first.publication.publication_id,
        )
    assert caught.value.state.publication is None
    assert [path.name for path in paths.academic_result_manifests_dir.glob("*.json")] == [
        "1.json", "2.json"
    ]
    monkeypatch.setattr(
        publication_module, "supersede_scoreform_academic_results", real_supersede
    )
    retry = republish_scoreform_academic_results_after_withdrawal(
        tmp_path, "class1", "quiz1",
        expected_withdrawn_head_publication_id=first.publication.publication_id,
    )
    assert retry.publication.record_set_revision == 2
    assert retry.manifest_generation is None
    assert [path.name for path in paths.academic_result_manifests_dir.glob("*.json")] == [
        "1.json", "2.json"
    ]
    assert load_publication_withdrawal(tmp_path, first.publication.publication_id) is not None


def test_withdrawal_reason_is_not_printed_by_routine_cli_or_menu(
    tmp_path, capsys
):
    _paths, manifest = _prepared(tmp_path)
    publication = publish_scoreform_academic_results(
        tmp_path, "class1", "quiz1", manifest_revision=manifest.revision
    ).publication
    private_reason = "private correction details"
    result = withdraw_scoreform_academic_result_publication(
        tmp_path, "class1", "quiz1", publication_id=publication.publication_id,
        reason=private_reason,
    )
    cli_publication._print_withdrawal_result(result)
    menu_publication._summary(result.publication, result.withdrawal, result.catalog.publication)
    assert private_reason not in capsys.readouterr().out


@pytest.mark.parametrize(
    "dimension",
    [
        "producer_contract",
        "work_kind",
        "no_sources",
        "two_sources",
        "wrong_source_kind",
        "wrong_source_id",
        "versioned_source",
        "cancelled",
    ],
)
def test_incompatible_current_registration_fails_before_core_write(
    tmp_path, monkeypatch, dimension
):
    paths, manifest = _prepared(tmp_path)
    registration = publication_module.load_current_academic_work_registration(
        tmp_path, paths.work_ref
    )
    assert registration is not None
    expected_source = registration.source_records[0]
    if dimension == "producer_contract":
        incompatible = replace(
            registration,
            producer_contract_version="other_academic_work_v1",
        )
    elif dimension == "work_kind":
        incompatible = replace(registration, work_kind="assessment")
    elif dimension == "no_sources":
        incompatible = replace(registration, source_records=())
    elif dimension == "two_sources":
        incompatible = replace(
            registration,
            source_records=(
                expected_source,
                ModuleRecordRef("scoreform", "assignment", "other", None),
            ),
        )
    elif dimension == "wrong_source_kind":
        incompatible = replace(
            registration,
            source_records=(
                ModuleRecordRef("scoreform", "other", "quiz1", None),
            ),
        )
    elif dimension == "wrong_source_id":
        incompatible = replace(
            registration,
            source_records=(
                ModuleRecordRef("scoreform", "assignment", "other", None),
            ),
        )
    elif dimension == "versioned_source":
        incompatible = replace(
            registration,
            source_records=(
                ModuleRecordRef("scoreform", "assignment", "quiz1", "source_v1"),
            ),
        )
    else:
        incompatible = replace(registration, lifecycle="cancelled")

    monkeypatch.setattr(
        publication_module,
        "load_current_academic_work_registration",
        lambda *_args, **_kwargs: incompatible,
    )
    core_called = False
    catalog_called = False

    def forbidden_core(*_args, **_kwargs):
        nonlocal core_called
        core_called = True
        raise AssertionError("Core publication must not run")

    def forbidden_catalog(*_args, **_kwargs):
        nonlocal catalog_called
        catalog_called = True
        raise AssertionError("Catalog rebuild must not run")

    monkeypatch.setattr(
        publication_module, "publish_manifest_revision", forbidden_core
    )
    monkeypatch.setattr(
        publication_module, "rebuild_academic_catalog", forbidden_catalog
    )
    expected_error = (
        ScoreFormAcademicResultPublicationConflictError
        if dimension == "cancelled"
        else ScoreFormAcademicResultPublicationIntegrityError
    )
    with pytest.raises(expected_error):
        publish_scoreform_academic_results(
            tmp_path,
            "class1",
            "quiz1",
            manifest_revision=manifest.revision,
        )
    assert not core_called
    assert not catalog_called
    assert not (tmp_path / "registry/publications").exists()
    assert paths.academic_result_manifests_dir.joinpath("1.json").exists()


@pytest.mark.parametrize(
    "dimension",
    ["source_record", "manifest_contract", "capabilities", "manifest_path"],
)
def test_canonical_publication_contract_is_strict_on_all_read_and_write_surfaces(
    tmp_path, monkeypatch, dimension
):
    _paths, manifest = _prepared(tmp_path)
    created = publish_scoreform_academic_results(
        tmp_path, "class1", "quiz1", manifest_revision=manifest.revision
    )
    publication = created.publication
    if dimension == "source_record":
        contradictory = replace(
            publication,
            source_record=ModuleRecordRef(
                "scoreform", "assignment", "quiz1", None
            ),
        )
    elif dimension == "manifest_contract":
        contradictory = replace(
            publication,
            manifest_contract_version="other_manifest_v1",
        )
    elif dimension == "capabilities":
        contradictory = replace(publication, capabilities=("points",))
    else:
        contradictory = replace(
            publication,
            manifest_path=publication_module.academic_result_manifest_relative_path(
                publication.work, 2
            ),
        )

    monkeypatch.setattr(
        publication_module,
        "get_canonical_publication_record",
        lambda *_args, **_kwargs: contradictory,
    )
    with pytest.raises(ScoreFormAcademicResultPublicationIntegrityError):
        publication_module.load_scoreform_publication(
            tmp_path, "class1", "quiz1", publication.publication_id
        )

    monkeypatch.setattr(
        publication_module,
        "list_publication_record_set",
        lambda *_args, **_kwargs: (contradictory,),
    )
    with pytest.raises(ScoreFormAcademicResultPublicationIntegrityError):
        load_scoreform_publication_series_status(
            tmp_path, "class1", "quiz1"
        )

    core_withdraw_called = False

    def forbidden_withdraw(*_args, **_kwargs):
        nonlocal core_withdraw_called
        core_withdraw_called = True
        raise AssertionError("Withdrawal must not run")

    monkeypatch.setattr(
        publication_module, "withdraw_publication", forbidden_withdraw
    )
    with pytest.raises(ScoreFormAcademicResultPublicationIntegrityError):
        withdraw_scoreform_academic_result_publication(
            tmp_path,
            "class1",
            "quiz1",
            publication_id=publication.publication_id,
            reason="Should not run",
        )
    assert not core_withdraw_called

    assert export_scoreform_result_models(
        (_result(student_id="student2", answer="B"),),
        workspace_root=tmp_path,
    ).succeeded
    successor = generate_academic_result_manifest(
        tmp_path, "class1", "quiz1"
    )
    core_supersede_called = False

    def forbidden_supersede(*_args, **_kwargs):
        nonlocal core_supersede_called
        core_supersede_called = True
        raise AssertionError("Supersession must not run")

    monkeypatch.setattr(
        publication_module, "supersede_manifest_revision", forbidden_supersede
    )
    with pytest.raises(ScoreFormAcademicResultPublicationIntegrityError):
        supersede_scoreform_academic_results(
            tmp_path,
            "class1",
            "quiz1",
            manifest_revision=successor.revision,
            expected_current_publication_id=publication.publication_id,
        )
    assert not core_supersede_called


def test_preexisting_catalog_does_not_imply_replacement_after_publish_failure(
    tmp_path, monkeypatch
):
    _paths, manifest = _prepared(tmp_path)
    rebuild_full_academic_catalog(tmp_path)
    catalog_path = tmp_path / "registry/catalog.sqlite"
    assert catalog_path.is_file()

    def fail(_root):
        raise AcademicCatalogConflictError("injected lock")

    monkeypatch.setattr(publication_module, "rebuild_academic_catalog", fail)
    with pytest.raises(
        ScoreFormAcademicResultPublicationPartialSuccessError
    ) as caught:
        publish_scoreform_academic_results(
            tmp_path, "class1", "quiz1", manifest_revision=manifest.revision
        )
    state = caught.value.state
    assert catalog_path.is_file()
    assert state.catalog_rebuild_attempted
    assert not state.catalog_replacement_completed
    assert not state.catalog_verification_completed
    assert state.catalog_build is None
    assert isinstance(state.catalog_error, AcademicCatalogConflictError)


def test_preexisting_catalog_does_not_imply_replacement_after_withdrawal_failure(
    tmp_path, monkeypatch
):
    _paths, manifest = _prepared(tmp_path)
    publication = publish_scoreform_academic_results(
        tmp_path, "class1", "quiz1", manifest_revision=manifest.revision
    ).publication
    catalog_path = tmp_path / "registry/catalog.sqlite"
    assert catalog_path.is_file()

    def fail(_root):
        raise AcademicCatalogConflictError("injected lock")

    monkeypatch.setattr(publication_module, "rebuild_academic_catalog", fail)
    with pytest.raises(
        ScoreFormAcademicResultPublicationPartialSuccessError
    ) as caught:
        withdraw_scoreform_academic_result_publication(
            tmp_path,
            "class1",
            "quiz1",
            publication_id=publication.publication_id,
            reason="Durable withdrawal",
        )
    state = caught.value.state
    assert load_publication_withdrawal(
        tmp_path, publication.publication_id
    ) is not None
    assert catalog_path.is_file()
    assert state.catalog_rebuild_attempted
    assert not state.catalog_replacement_completed
    assert state.catalog_build is None


@pytest.mark.parametrize("stage", ["query_failure", "row_contradiction"])
def test_successful_catalog_replacement_is_retained_when_later_verification_fails(
    tmp_path, monkeypatch, stage
):
    _paths, manifest = _prepared(tmp_path)
    if stage == "query_failure":
        monkeypatch.setattr(
            publication_module,
            "query_publication_catalog",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AcademicCatalogReadError("injected query failure")
            ),
        )
    else:
        monkeypatch.setattr(
            publication_module,
            "query_publication_catalog",
            lambda *_args, **_kwargs: (),
        )
    with pytest.raises(
        ScoreFormAcademicResultPublicationPartialSuccessError
    ) as caught:
        publish_scoreform_academic_results(
            tmp_path, "class1", "quiz1", manifest_revision=manifest.revision
        )
    state = caught.value.state
    assert state.catalog_rebuild_attempted
    assert state.catalog_replacement_completed
    assert not state.catalog_verification_completed
    assert state.catalog_build is not None
    assert state.catalog_error is not None


def test_healthy_manifest_is_verified_before_withdrawal(tmp_path, monkeypatch):
    _paths, manifest = _prepared(tmp_path)
    publication = publish_scoreform_academic_results(
        tmp_path, "class1", "quiz1", manifest_revision=manifest.revision
    ).publication
    real_verify = publication_module.verify_publication_manifest
    calls = 0

    def observe(root, record):
        nonlocal calls
        calls += 1
        return real_verify(root, record)

    monkeypatch.setattr(
        publication_module, "verify_publication_manifest", observe
    )
    result = withdraw_scoreform_academic_result_publication(
        tmp_path,
        "class1",
        "quiz1",
        publication_id=publication.publication_id,
        reason="Verified evidence",
    )
    assert calls == 1
    assert result.manifest_verification == "verified"


@pytest.mark.parametrize(
    ("damage", "expected_status"),
    [
        ("digest", "digest_mismatch_or_unsafe"),
        ("missing", "missing"),
    ],
)
def test_damaged_or_missing_manifest_withdrawal_is_nonblocking_and_private(
    tmp_path, capsys, damage, expected_status
):
    paths, manifest = _prepared(tmp_path)
    publication = publish_scoreform_academic_results(
        tmp_path, "class1", "quiz1", manifest_revision=manifest.revision
    ).publication
    manifest_path = paths.academic_result_manifests_dir / "1.json"
    publication_path = (
        tmp_path
        / "registry/publications"
        / f"{publication.publication_id}.json"
    )
    publication_bytes = publication_path.read_bytes()
    if damage == "digest":
        manifest_path.write_bytes(b"damaged")
    else:
        manifest_path.unlink()

    result = withdraw_scoreform_academic_result_publication(
        tmp_path,
        "class1",
        "quiz1",
        publication_id=publication.publication_id,
        reason="Evidence unavailable",
    )
    assert result.manifest_verification == expected_status
    assert publication_path.read_bytes() == publication_bytes
    if damage == "digest":
        assert manifest_path.read_bytes() == b"damaged"
    else:
        assert not manifest_path.exists()

    cli_publication._print_withdrawal_result(result)
    output = capsys.readouterr().out
    assert "could not be verified" in output
    assert str(tmp_path) not in output
    assert "Traceback" not in output


@pytest.mark.parametrize(
    ("core_error", "local_error"),
    [
        (
            AcademicCatalogValidationError("validation"),
            ScoreFormAcademicResultPublicationValidationError,
        ),
        (
            AcademicCatalogConflictError("conflict"),
            ScoreFormAcademicResultPublicationConflictError,
        ),
        (
            AcademicCatalogSourceError("source"),
            ScoreFormAcademicResultPublicationIntegrityError,
        ),
        (
            AcademicCatalogIntegrityError("integrity"),
            ScoreFormAcademicResultPublicationIntegrityError,
        ),
        (
            AcademicCatalogCompatibilityError("compatibility"),
            ScoreFormAcademicResultPublicationIntegrityError,
        ),
        (
            AcademicCatalogReadError("read"),
            ScoreFormAcademicResultPublicationIntegrityError,
        ),
        (
            AcademicCatalogBuildError("build"),
            ScoreFormAcademicResultPublicationWriteError,
        ),
    ],
)
def test_explicit_catalog_errors_are_normalized(
    tmp_path, monkeypatch, core_error, local_error
):
    monkeypatch.setattr(
        publication_module,
        "rebuild_academic_catalog",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(core_error),
    )
    with pytest.raises(local_error) as caught:
        rebuild_full_academic_catalog(tmp_path)
    assert caught.value.__cause__ is core_error


def test_series_state_rejects_contradictory_public_invariants(tmp_path):
    _paths, manifest = _prepared(tmp_path)
    result = publish_scoreform_academic_results(
        tmp_path, "class1", "quiz1", manifest_revision=manifest.revision
    )
    state = load_scoreform_publication_series_status(
        tmp_path, "class1", "quiz1"
    )
    with pytest.raises(ValueError):
        replace(state, producer_revisions=(1, 1))
    with pytest.raises(ValueError):
        replace(state, producer_head=None)
    with pytest.raises(ValueError):
        replace(
            state,
            core_head=None,
            current_selectable_publication=None,
        )
    partial = PublicationPartialSuccessState(
        operation="publish",
        publication=result.publication,
        withdrawal=None,
        manifest=state.producer_head,
        canonical_state="confirmed",
        catalog_rebuild_attempted=True,
        catalog_replacement_completed=True,
        catalog_verification_completed=False,
        recommended_next_action="reconcile",
        catalog_build=result.catalog.build,
    )
    with pytest.raises(ValueError):
        replace(partial, catalog_build=None)
