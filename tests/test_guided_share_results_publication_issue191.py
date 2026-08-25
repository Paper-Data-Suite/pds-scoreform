"""Guided first-publication/current-state coverage for ScoreForm issue #191."""

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from pds_core.publication_records import PublicationRecord
from pds_core.routing_models import ModuleWorkRef

from scoreform.academic_result_publication import (
    SCOREFORM_PUBLICATION_CAPABILITIES,
    PublicationPartialSuccessState,
    ScoreFormAcademicResultPublicationConflictError,
    ScoreFormAcademicResultPublicationIntegrityError,
    ScoreFormAcademicResultPublicationPartialSuccessError,
    ScoreFormAcademicResultPublicationWriteError,
)
from scoreform.guided_share_results import (
    ScoreFormShareResultsPublicationConflictError,
    ScoreFormShareResultsPublicationNotReadyError,
    ScoreFormShareResultsPublicationPartialSuccessError,
    ScoreFormShareResultsPublicationPostCommitStateError,
    ScoreFormShareResultsPublicationRepairRequiredError,
    ScoreFormShareResultsPublicationWriteError,
    ShareResultsNextStep,
    ShareResultsPublicationAction,
    ShareResultsPublicationPreview,
    commit_share_results_publication,
    prepare_share_results_publication,
)
from scoreform.pds_contract import ACADEMIC_RESULT_MANIFEST_CONTRACT_VERSION
from scoreform.publication_revision_policy import (
    SCOREFORM_ACADEMIC_RESULT_PUBLICATION_KIND,
    SCOREFORM_ACADEMIC_RESULT_RECORD_SET_ID,
)
from scoreform.work_paths import academic_result_manifest_relative_path

WORK = ModuleWorkRef("scoreform", "english10_p2", "unit_quiz")
PUB_ID = "pub_" + ("0" * 32)


def _readiness(
    *,
    step: ShareResultsNextStep = ShareResultsNextStep.PUBLISH_FIRST,
    title: str = "Unit Quiz",
    revision: int = 1,
    publication_id: str | None = None,
):
    return SimpleNamespace(
        next_step=step,
        work=WORK,
        title=title,
        producer_head_revision=revision,
        core_head_publication_id=publication_id,
    )


def _preview(
    *,
    action: ShareResultsPublicationAction = ShareResultsPublicationAction.PUBLISH_FIRST,
    revision: int = 1,
    publication_id: str | None = None,
):
    return ShareResultsPublicationPreview(
        work=WORK,
        title="Unit Quiz",
        action=action,
        manifest_revision=revision,
        current_publication_id=publication_id,
    )


def _publication(
    *,
    publication_id: str = PUB_ID,
    revision: int = 1,
) -> PublicationRecord:
    return PublicationRecord(
        schema_version="1",
        record_type="publication_record",
        publication_id=publication_id,
        work=WORK,
        source_record=None,
        publication_kind=SCOREFORM_ACADEMIC_RESULT_PUBLICATION_KIND,
        capabilities=SCOREFORM_PUBLICATION_CAPABILITIES,
        record_set_id=SCOREFORM_ACADEMIC_RESULT_RECORD_SET_ID,
        record_set_revision=revision,
        manifest_contract_version=ACADEMIC_RESULT_MANIFEST_CONTRACT_VERSION,
        manifest_path=academic_result_manifest_relative_path(WORK, revision),
        manifest_digest_algorithm="sha256",
        manifest_digest="a" * 64,
        published_at=datetime(2026, 8, 24, 12, 0, tzinfo=UTC),
        academic_work_registration_revision=1,
        supersedes_publication_id=None,
    )


def _service_result(
    *,
    disposition: str = "created",
    publication_id: str = PUB_ID,
    revision: int = 1,
):
    return SimpleNamespace(
        operation="publish",
        disposition=disposition,
        publication=_publication(
            publication_id=publication_id,
            revision=revision,
        ),
        withdrawal=None,
    )


def _series(
    *,
    publication_id: str = PUB_ID,
    revision: int = 1,
    catalog_available: bool = True,
    withdrawn: bool = False,
):
    head = _publication(
        publication_id=publication_id,
        revision=revision,
    )
    return SimpleNamespace(
        core_head=head,
        core_head_withdrawal=(object() if withdrawn else None),
        current_selectable_publication=(None if withdrawn else head),
        derived_catalog_available=catalog_available,
    )


def test_prepare_first_publication_is_read_only(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "scoreform.guided_share_results.plan_share_results_readiness",
        lambda *args, **kwargs: _readiness(),
    )
    calls = {"publish": 0}
    monkeypatch.setattr(
        "scoreform.guided_share_results.publish_scoreform_academic_results",
        lambda *args, **kwargs: calls.__setitem__(
            "publish", calls["publish"] + 1
        ),
    )

    preview = prepare_share_results_publication(
        tmp_path,
        "english10_p2",
        "unit_quiz",
    )

    assert preview.action is ShareResultsPublicationAction.PUBLISH_FIRST
    assert preview.manifest_revision == 1
    assert preview.current_publication_id is None
    assert preview.requires_commit
    assert calls["publish"] == 0


def test_prepare_already_current_is_no_write_state(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "scoreform.guided_share_results.plan_share_results_readiness",
        lambda *args, **kwargs: _readiness(
            step=ShareResultsNextStep.ALREADY_CURRENT,
            publication_id=PUB_ID,
        ),
    )

    preview = prepare_share_results_publication(
        tmp_path,
        "english10_p2",
        "unit_quiz",
    )

    assert preview.action is ShareResultsPublicationAction.ALREADY_CURRENT
    assert preview.current_publication_id == PUB_ID
    assert not preview.requires_commit


def test_prepare_rejects_other_guided_states(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "scoreform.guided_share_results.plan_share_results_readiness",
        lambda *args, **kwargs: _readiness(
            step=ShareResultsNextStep.GENERATE_MANIFEST
        ),
    )

    with pytest.raises(ScoreFormShareResultsPublicationNotReadyError):
        prepare_share_results_publication(
            tmp_path,
            "english10_p2",
            "unit_quiz",
        )


def test_already_current_commit_never_calls_publication_service(
    monkeypatch,
    tmp_path: Path,
) -> None:
    preview = _preview(
        action=ShareResultsPublicationAction.ALREADY_CURRENT,
        publication_id=PUB_ID,
    )
    monkeypatch.setattr(
        "scoreform.guided_share_results.plan_share_results_readiness",
        lambda *args, **kwargs: _readiness(
            step=ShareResultsNextStep.ALREADY_CURRENT,
            publication_id=PUB_ID,
        ),
    )

    def must_not_publish(*args, **kwargs):
        raise AssertionError("already-current path must not publish")

    monkeypatch.setattr(
        "scoreform.guided_share_results.publish_scoreform_academic_results",
        must_not_publish,
    )

    outcome = commit_share_results_publication(tmp_path, preview)

    assert outcome.disposition == "already_current"
    assert outcome.publication_id == PUB_ID
    assert outcome.available_for_meridian_consumption


def test_first_publication_calls_exact_service_once_and_reloads_canonical_state(
    monkeypatch,
    tmp_path: Path,
) -> None:
    preview = _preview(revision=3)
    monkeypatch.setattr(
        "scoreform.guided_share_results.plan_share_results_readiness",
        lambda *args, **kwargs: _readiness(revision=3),
    )
    calls = {"publish": [], "status": 0}

    def publish(workspace_root, class_id, assignment_id, *, manifest_revision):
        calls["publish"].append(
            (workspace_root, class_id, assignment_id, manifest_revision)
        )
        return _service_result(revision=3)

    def status(*args, **kwargs):
        calls["status"] += 1
        return _series(revision=3)

    monkeypatch.setattr(
        "scoreform.guided_share_results.publish_scoreform_academic_results",
        publish,
    )
    monkeypatch.setattr(
        "scoreform.guided_share_results.load_scoreform_publication_series_status",
        status,
    )

    outcome = commit_share_results_publication(tmp_path, preview)

    assert calls["publish"] == [
        (tmp_path, "english10_p2", "unit_quiz", 3)
    ]
    assert calls["status"] == 1
    assert outcome.disposition == "created"
    assert outcome.manifest_revision == 3
    assert outcome.publication_id == PUB_ID
    assert outcome.available_for_meridian_consumption


def test_idempotent_existing_publication_is_normal_outcome(
    monkeypatch,
    tmp_path: Path,
) -> None:
    preview = _preview()
    monkeypatch.setattr(
        "scoreform.guided_share_results.plan_share_results_readiness",
        lambda *args, **kwargs: _readiness(),
    )
    monkeypatch.setattr(
        "scoreform.guided_share_results.publish_scoreform_academic_results",
        lambda *args, **kwargs: _service_result(disposition="existing"),
    )
    monkeypatch.setattr(
        "scoreform.guided_share_results.load_scoreform_publication_series_status",
        lambda *args, **kwargs: _series(),
    )

    outcome = commit_share_results_publication(tmp_path, preview)

    assert outcome.disposition == "existing"
    assert outcome.publication_id == PUB_ID


@pytest.mark.parametrize(
    "changed",
    [
        _readiness(
            step=ShareResultsNextStep.ALREADY_CURRENT,
            publication_id=PUB_ID,
        ),
        _readiness(revision=2),
        _readiness(title="Renamed Unit Quiz"),
    ],
)
def test_stale_first_publication_preview_fails_before_write(
    monkeypatch,
    tmp_path: Path,
    changed,
) -> None:
    preview = _preview()
    monkeypatch.setattr(
        "scoreform.guided_share_results.plan_share_results_readiness",
        lambda *args, **kwargs: changed,
    )
    calls = {"publish": 0}

    def publish(*args, **kwargs):
        calls["publish"] += 1
        return _service_result()

    monkeypatch.setattr(
        "scoreform.guided_share_results.publish_scoreform_academic_results",
        publish,
    )

    with pytest.raises(ScoreFormShareResultsPublicationConflictError):
        commit_share_results_publication(tmp_path, preview)

    assert calls["publish"] == 0


def test_publication_conflict_is_not_retried(
    monkeypatch,
    tmp_path: Path,
) -> None:
    preview = _preview()
    monkeypatch.setattr(
        "scoreform.guided_share_results.plan_share_results_readiness",
        lambda *args, **kwargs: _readiness(),
    )
    calls = {"publish": 0}

    def conflict(*args, **kwargs):
        calls["publish"] += 1
        raise ScoreFormAcademicResultPublicationConflictError("race")

    monkeypatch.setattr(
        "scoreform.guided_share_results.publish_scoreform_academic_results",
        conflict,
    )

    with pytest.raises(ScoreFormShareResultsPublicationConflictError):
        commit_share_results_publication(tmp_path, preview)

    assert calls["publish"] == 1


def test_publication_integrity_failure_requires_exact_repair(
    monkeypatch,
    tmp_path: Path,
) -> None:
    preview = _preview()
    monkeypatch.setattr(
        "scoreform.guided_share_results.plan_share_results_readiness",
        lambda *args, **kwargs: _readiness(),
    )

    def fail(*args, **kwargs):
        raise ScoreFormAcademicResultPublicationIntegrityError(
            r"bad state C:\private\student-data"
        )

    monkeypatch.setattr(
        "scoreform.guided_share_results.publish_scoreform_academic_results",
        fail,
    )

    with pytest.raises(
        ScoreFormShareResultsPublicationRepairRequiredError
    ) as caught:
        commit_share_results_publication(tmp_path, preview)

    assert "C:\\private" not in str(caught.value)


def test_publication_write_failure_is_bounded(
    monkeypatch,
    tmp_path: Path,
) -> None:
    preview = _preview()
    monkeypatch.setattr(
        "scoreform.guided_share_results.plan_share_results_readiness",
        lambda *args, **kwargs: _readiness(),
    )

    def fail(*args, **kwargs):
        raise ScoreFormAcademicResultPublicationWriteError(
            r"write failed C:\private\registry"
        )

    monkeypatch.setattr(
        "scoreform.guided_share_results.publish_scoreform_academic_results",
        fail,
    )

    with pytest.raises(ScoreFormShareResultsPublicationWriteError) as caught:
        commit_share_results_publication(tmp_path, preview)

    assert "C:\\private" not in str(caught.value)


def test_publication_partial_success_preserves_known_durable_state(
    monkeypatch,
    tmp_path: Path,
) -> None:
    preview = _preview(revision=2)
    monkeypatch.setattr(
        "scoreform.guided_share_results.plan_share_results_readiness",
        lambda *args, **kwargs: _readiness(revision=2),
    )
    state = PublicationPartialSuccessState(
        operation="publish",
        publication=_publication(revision=2),
        withdrawal=None,
        manifest=None,
        canonical_state="confirmed",
        catalog_rebuild_attempted=True,
        catalog_replacement_completed=False,
        catalog_verification_completed=False,
        recommended_next_action="Reload exact publication status.",
    )
    calls = {"publish": 0}

    def partial(*args, **kwargs):
        calls["publish"] += 1
        raise ScoreFormAcademicResultPublicationPartialSuccessError(
            "partial",
            state,
        )

    monkeypatch.setattr(
        "scoreform.guided_share_results.publish_scoreform_academic_results",
        partial,
    )

    with pytest.raises(
        ScoreFormShareResultsPublicationPartialSuccessError
    ) as caught:
        commit_share_results_publication(tmp_path, preview)

    recovery = caught.value.recovery
    assert calls["publish"] == 1
    assert recovery.canonical_state == "confirmed"
    assert recovery.publication_id == PUB_ID
    assert recovery.manifest_revision == 2
    assert recovery.catalog_rebuild_attempted
    assert not recovery.catalog_replacement_completed
    assert recovery.guidance == "Reload exact publication status."
    assert not hasattr(recovery, "path")


@pytest.mark.parametrize(
    "series",
    [
        _series(publication_id="pub_" + ("1" * 32)),
        _series(revision=2),
        _series(catalog_available=False),
        _series(withdrawn=True),
    ],
)
def test_successful_write_requires_matching_reloaded_canonical_state(
    monkeypatch,
    tmp_path: Path,
    series,
) -> None:
    preview = _preview()
    monkeypatch.setattr(
        "scoreform.guided_share_results.plan_share_results_readiness",
        lambda *args, **kwargs: _readiness(),
    )
    monkeypatch.setattr(
        "scoreform.guided_share_results.publish_scoreform_academic_results",
        lambda *args, **kwargs: _service_result(),
    )
    monkeypatch.setattr(
        "scoreform.guided_share_results.load_scoreform_publication_series_status",
        lambda *args, **kwargs: series,
    )

    with pytest.raises(
        ScoreFormShareResultsPublicationPostCommitStateError
    ) as caught:
        commit_share_results_publication(tmp_path, preview)

    assert caught.value.publication_id == PUB_ID
    assert caught.value.manifest_revision == 1
    assert "Publication completed" in str(caught.value)


def test_publication_service_result_must_match_confirmed_work_and_revision(
    monkeypatch,
    tmp_path: Path,
) -> None:
    preview = _preview()
    monkeypatch.setattr(
        "scoreform.guided_share_results.plan_share_results_readiness",
        lambda *args, **kwargs: _readiness(),
    )
    bad = _service_result(revision=2)
    monkeypatch.setattr(
        "scoreform.guided_share_results.publish_scoreform_academic_results",
        lambda *args, **kwargs: bad,
    )

    with pytest.raises(ScoreFormShareResultsPublicationWriteError):
        commit_share_results_publication(tmp_path, preview)


def test_publication_outcome_does_not_claim_meridian_ingestion() -> None:
    preview = _preview(
        action=ShareResultsPublicationAction.ALREADY_CURRENT,
        publication_id=PUB_ID,
    )

    assert not hasattr(preview, "meridian_ingested")
    assert not hasattr(preview, "meridian_projection")
