"""Guided exact-supersession coverage for ScoreForm issue #191."""

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
    ShareResultsSupersessionPreview,
    commit_share_results_supersession,
    prepare_share_results_supersession,
)
from scoreform.pds_contract import ACADEMIC_RESULT_MANIFEST_CONTRACT_VERSION
from scoreform.publication_revision_policy import (
    SCOREFORM_ACADEMIC_RESULT_PUBLICATION_KIND,
    SCOREFORM_ACADEMIC_RESULT_RECORD_SET_ID,
)
from scoreform.work_paths import academic_result_manifest_relative_path

WORK = ModuleWorkRef("scoreform", "english10_p2", "unit_quiz")
PREDECESSOR_ID = "pub_" + ("1" * 32)
SUCCESSOR_ID = "pub_" + ("2" * 32)


def _record(
    *,
    publication_id: str,
    revision: int,
    supersedes: str | None = None,
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
        manifest_digest=("a" if revision == 1 else "b") * 64,
        published_at=datetime(2026, 8, 24, 12 + revision, 0, tzinfo=UTC),
        academic_work_registration_revision=1,
        supersedes_publication_id=supersedes,
    )


def _readiness(
    *,
    step: ShareResultsNextStep = ShareResultsNextStep.SUPERSEDE,
    title: str = "Unit Quiz",
    predecessor_id: str = PREDECESSOR_ID,
    predecessor_revision: int = 1,
    successor_revision: int = 2,
):
    return SimpleNamespace(
        next_step=step,
        work=WORK,
        title=title,
        core_head_publication_id=predecessor_id,
        core_head_revision=predecessor_revision,
        producer_head_revision=successor_revision,
    )


def _preview(
    *,
    predecessor_id: str = PREDECESSOR_ID,
    predecessor_revision: int = 1,
    successor_revision: int = 2,
) -> ShareResultsSupersessionPreview:
    return ShareResultsSupersessionPreview(
        work=WORK,
        title="Unit Quiz",
        predecessor_publication_id=predecessor_id,
        predecessor_manifest_revision=predecessor_revision,
        successor_manifest_revision=successor_revision,
    )


def _requirement(
    *,
    predecessor_id: str = PREDECESSOR_ID,
    predecessor_revision: int = 1,
    successor_revision: int = 2,
):
    return SimpleNamespace(
        expected_current_publication_id=predecessor_id,
        predecessor_revision=predecessor_revision,
        successor_revision=successor_revision,
    )


def _service_result(
    *,
    disposition: str = "created",
    predecessor_id: str = PREDECESSOR_ID,
    successor_id: str = SUCCESSOR_ID,
    predecessor_revision: int = 1,
    successor_revision: int = 2,
):
    successor = _record(
        publication_id=successor_id,
        revision=successor_revision,
        supersedes=predecessor_id,
    )
    return SimpleNamespace(
        operation="supersede",
        disposition=disposition,
        publication=successor,
        withdrawal=None,
        supersession_requirement=_requirement(
            predecessor_id=predecessor_id,
            predecessor_revision=predecessor_revision,
            successor_revision=successor_revision,
        ),
    )


def _series(
    *,
    predecessor_id: str = PREDECESSOR_ID,
    successor_id: str = SUCCESSOR_ID,
    predecessor_revision: int = 1,
    successor_revision: int = 2,
    withdrawn: bool = False,
    catalog_available: bool = True,
):
    predecessor = _record(
        publication_id=predecessor_id,
        revision=predecessor_revision,
    )
    successor = _record(
        publication_id=successor_id,
        revision=successor_revision,
        supersedes=predecessor_id,
    )
    return SimpleNamespace(
        publications=(predecessor, successor),
        core_head=successor,
        core_head_withdrawal=(object() if withdrawn else None),
        current_selectable_publication=(None if withdrawn else successor),
        derived_catalog_available=catalog_available,
    )


def test_prepare_supersession_resolves_exact_canonical_head_without_write(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "scoreform.guided_share_results.plan_share_results_readiness",
        lambda *args, **kwargs: _readiness(),
    )
    calls = {"supersede": 0}
    monkeypatch.setattr(
        "scoreform.guided_share_results.supersede_scoreform_academic_results",
        lambda *args, **kwargs: calls.__setitem__(
            "supersede", calls["supersede"] + 1
        ),
    )

    preview = prepare_share_results_supersession(
        tmp_path,
        "english10_p2",
        "unit_quiz",
    )

    assert preview.predecessor_publication_id == PREDECESSOR_ID
    assert preview.predecessor_manifest_revision == 1
    assert preview.successor_manifest_revision == 2
    assert preview.expected_current_publication_id == PREDECESSOR_ID
    assert calls["supersede"] == 0


def test_prepare_requires_exact_supersession_readiness(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "scoreform.guided_share_results.plan_share_results_readiness",
        lambda *args, **kwargs: _readiness(
            step=ShareResultsNextStep.ALREADY_CURRENT
        ),
    )

    with pytest.raises(ScoreFormShareResultsPublicationNotReadyError):
        prepare_share_results_supersession(
            tmp_path,
            "english10_p2",
            "unit_quiz",
        )


def test_preview_without_commit_is_safe_supersession_cancellation(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "scoreform.guided_share_results.plan_share_results_readiness",
        lambda *args, **kwargs: _readiness(),
    )
    calls = {"supersede": 0}
    monkeypatch.setattr(
        "scoreform.guided_share_results.supersede_scoreform_academic_results",
        lambda *args, **kwargs: calls.__setitem__(
            "supersede", calls["supersede"] + 1
        ),
    )

    prepare_share_results_supersession(
        tmp_path,
        "english10_p2",
        "unit_quiz",
    )

    assert calls["supersede"] == 0


def test_commit_passes_exact_predecessor_unchanged_and_reloads_state(
    monkeypatch,
    tmp_path: Path,
) -> None:
    preview = _preview(successor_revision=4)
    monkeypatch.setattr(
        "scoreform.guided_share_results.plan_share_results_readiness",
        lambda *args, **kwargs: _readiness(successor_revision=4),
    )
    calls = {"supersede": [], "status": 0}

    def supersede(
        workspace_root,
        class_id,
        assignment_id,
        *,
        manifest_revision,
        expected_current_publication_id,
    ):
        calls["supersede"].append(
            (
                workspace_root,
                class_id,
                assignment_id,
                manifest_revision,
                expected_current_publication_id,
            )
        )
        return _service_result(successor_revision=4)

    def status(*args, **kwargs):
        calls["status"] += 1
        return _series(successor_revision=4)

    monkeypatch.setattr(
        "scoreform.guided_share_results.supersede_scoreform_academic_results",
        supersede,
    )
    monkeypatch.setattr(
        "scoreform.guided_share_results.load_scoreform_publication_series_status",
        status,
    )

    outcome = commit_share_results_supersession(tmp_path, preview)

    assert calls["supersede"] == [
        (
            tmp_path,
            "english10_p2",
            "unit_quiz",
            4,
            PREDECESSOR_ID,
        )
    ]
    assert calls["status"] == 1
    assert outcome.publication_id == SUCCESSOR_ID
    assert outcome.previous_publication_id == PREDECESSOR_ID
    assert outcome.manifest_revision == 4
    assert outcome.available_for_meridian_consumption


def test_idempotent_existing_supersession_is_normal(
    monkeypatch,
    tmp_path: Path,
) -> None:
    preview = _preview()
    monkeypatch.setattr(
        "scoreform.guided_share_results.plan_share_results_readiness",
        lambda *args, **kwargs: _readiness(),
    )
    monkeypatch.setattr(
        "scoreform.guided_share_results.supersede_scoreform_academic_results",
        lambda *args, **kwargs: _service_result(disposition="existing"),
    )
    monkeypatch.setattr(
        "scoreform.guided_share_results.load_scoreform_publication_series_status",
        lambda *args, **kwargs: _series(),
    )

    outcome = commit_share_results_supersession(tmp_path, preview)

    assert outcome.disposition == "existing"
    assert outcome.previous_publication_id == PREDECESSOR_ID


@pytest.mark.parametrize(
    "changed",
    [
        _readiness(predecessor_id="pub_" + ("3" * 32)),
        _readiness(predecessor_revision=3, successor_revision=4),
        _readiness(successor_revision=3),
        _readiness(title="Renamed Unit Quiz"),
        _readiness(step=ShareResultsNextStep.ALREADY_CURRENT),
    ],
)
def test_stale_preview_fails_before_supersession_write(
    monkeypatch,
    tmp_path: Path,
    changed,
) -> None:
    preview = _preview()
    monkeypatch.setattr(
        "scoreform.guided_share_results.plan_share_results_readiness",
        lambda *args, **kwargs: changed,
    )
    calls = {"supersede": 0}

    def supersede(*args, **kwargs):
        calls["supersede"] += 1
        return _service_result()

    monkeypatch.setattr(
        "scoreform.guided_share_results.supersede_scoreform_academic_results",
        supersede,
    )

    with pytest.raises(ScoreFormShareResultsPublicationConflictError) as caught:
        commit_share_results_supersession(tmp_path, preview)

    assert calls["supersede"] == 0
    assert "fresh teacher confirmation" in str(caught.value).lower() or (
        "review the new canonical head" in str(caught.value).lower()
    )


def test_service_stale_head_conflict_is_never_retried_or_substituted(
    monkeypatch,
    tmp_path: Path,
) -> None:
    preview = _preview()
    monkeypatch.setattr(
        "scoreform.guided_share_results.plan_share_results_readiness",
        lambda *args, **kwargs: _readiness(),
    )
    calls = []

    def conflict(
        workspace_root,
        class_id,
        assignment_id,
        *,
        manifest_revision,
        expected_current_publication_id,
    ):
        calls.append(expected_current_publication_id)
        raise ScoreFormAcademicResultPublicationConflictError("stale head")

    monkeypatch.setattr(
        "scoreform.guided_share_results.supersede_scoreform_academic_results",
        conflict,
    )

    with pytest.raises(ScoreFormShareResultsPublicationConflictError) as caught:
        commit_share_results_supersession(tmp_path, preview)

    assert calls == [PREDECESSOR_ID]
    assert "nothing will be substituted automatically" in str(caught.value).lower()
    assert "fresh teacher confirmation" in str(caught.value).lower()


def test_supersession_integrity_failure_requires_exact_repair(
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
        "scoreform.guided_share_results.supersede_scoreform_academic_results",
        fail,
    )

    with pytest.raises(
        ScoreFormShareResultsPublicationRepairRequiredError
    ) as caught:
        commit_share_results_supersession(tmp_path, preview)

    assert "C:\\private" not in str(caught.value)


def test_supersession_write_failure_is_bounded(
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
        "scoreform.guided_share_results.supersede_scoreform_academic_results",
        fail,
    )

    with pytest.raises(ScoreFormShareResultsPublicationWriteError) as caught:
        commit_share_results_supersession(tmp_path, preview)

    assert "C:\\private" not in str(caught.value)


def test_supersession_partial_success_preserves_exact_known_transition(
    monkeypatch,
    tmp_path: Path,
) -> None:
    preview = _preview()
    monkeypatch.setattr(
        "scoreform.guided_share_results.plan_share_results_readiness",
        lambda *args, **kwargs: _readiness(),
    )
    successor = _record(
        publication_id=SUCCESSOR_ID,
        revision=2,
        supersedes=PREDECESSOR_ID,
    )
    state = PublicationPartialSuccessState(
        operation="supersede",
        publication=successor,
        withdrawal=None,
        manifest=None,
        canonical_state="confirmed",
        catalog_rebuild_attempted=True,
        catalog_replacement_completed=False,
        catalog_verification_completed=False,
        recommended_next_action="Reload exact publication status.",
    )
    calls = {"supersede": 0}

    def partial(*args, **kwargs):
        calls["supersede"] += 1
        raise ScoreFormAcademicResultPublicationPartialSuccessError(
            "partial",
            state,
        )

    monkeypatch.setattr(
        "scoreform.guided_share_results.supersede_scoreform_academic_results",
        partial,
    )

    with pytest.raises(
        ScoreFormShareResultsPublicationPartialSuccessError
    ) as caught:
        commit_share_results_supersession(tmp_path, preview)

    recovery = caught.value.recovery
    assert calls["supersede"] == 1
    assert recovery.operation == "supersede"
    assert recovery.canonical_state == "confirmed"
    assert recovery.publication_id == SUCCESSOR_ID
    assert recovery.manifest_revision == 2
    assert recovery.guidance == "Reload exact publication status."


@pytest.mark.parametrize(
    "series",
    [
        _series(successor_id="pub_" + ("4" * 32)),
        _series(successor_revision=3),
        _series(predecessor_id="pub_" + ("5" * 32)),
        _series(catalog_available=False),
        _series(withdrawn=True),
    ],
)
def test_post_commit_reload_must_preserve_exact_transition(
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
        "scoreform.guided_share_results.supersede_scoreform_academic_results",
        lambda *args, **kwargs: _service_result(),
    )
    monkeypatch.setattr(
        "scoreform.guided_share_results.load_scoreform_publication_series_status",
        lambda *args, **kwargs: series,
    )

    with pytest.raises(
        ScoreFormShareResultsPublicationPostCommitStateError
    ) as caught:
        commit_share_results_supersession(tmp_path, preview)

    assert caught.value.publication_id == SUCCESSOR_ID
    assert caught.value.manifest_revision == 2


def test_service_result_must_supersede_exact_confirmed_predecessor(
    monkeypatch,
    tmp_path: Path,
) -> None:
    preview = _preview()
    monkeypatch.setattr(
        "scoreform.guided_share_results.plan_share_results_readiness",
        lambda *args, **kwargs: _readiness(),
    )
    wrong_predecessor = "pub_" + ("6" * 32)
    monkeypatch.setattr(
        "scoreform.guided_share_results.supersede_scoreform_academic_results",
        lambda *args, **kwargs: _service_result(
            predecessor_id=wrong_predecessor,
        ),
    )

    with pytest.raises(ScoreFormShareResultsPublicationWriteError):
        commit_share_results_supersession(tmp_path, preview)


def test_service_requirement_must_match_confirmed_exact_transition(
    monkeypatch,
    tmp_path: Path,
) -> None:
    preview = _preview()
    monkeypatch.setattr(
        "scoreform.guided_share_results.plan_share_results_readiness",
        lambda *args, **kwargs: _readiness(),
    )
    result = _service_result()
    result.supersession_requirement = _requirement(successor_revision=3)
    monkeypatch.setattr(
        "scoreform.guided_share_results.supersede_scoreform_academic_results",
        lambda *args, **kwargs: result,
    )

    with pytest.raises(ScoreFormShareResultsPublicationWriteError):
        commit_share_results_supersession(tmp_path, preview)


def test_supersession_preview_keeps_no_student_or_meridian_payload() -> None:
    slots = set(ShareResultsSupersessionPreview.__slots__)

    assert slots == {
        "work",
        "title",
        "predecessor_publication_id",
        "predecessor_manifest_revision",
        "successor_manifest_revision",
    }
