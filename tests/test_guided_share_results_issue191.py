"""Read-only guided publication planning for ScoreForm issue #191."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from pds_core.routing_models import ModuleWorkRef

from scoreform.academic_result_manifest_generation import (
    ScoreFormManifestGenerationNotFoundError,
)
from scoreform.academic_result_publication import (
    ScoreFormAcademicResultPublicationIntegrityError,
)
from scoreform.academic_work_registration import (
    ScoreFormAcademicWorkRegistrationValidationError,
)
from scoreform.guided_share_results import (
    ScoreFormShareResultsPlanningError,
    ShareResultsNextStep,
    ShareResultsReadiness,
    plan_share_results_readiness,
)

ASSIGNMENT_SHA = "a" * 64
RESULTS_SHA = "b" * 64
MANIFEST_SHA = "c" * 64
PUB_ID = "pub_" + ("0" * 32)


def _generation_context(
    *,
    students: int = 1,
    attempts_per_student: int = 1,
    assignment_sha: str = ASSIGNMENT_SHA,
    results_sha: str = RESULTS_SHA,
):
    represented = tuple(
        SimpleNamespace(
            attempts=tuple(object() for _ in range(attempts_per_student))
        )
        for _ in range(students)
    )
    return SimpleNamespace(
        assignment_source=SimpleNamespace(sha256=assignment_sha),
        results_source=SimpleNamespace(sha256=results_sha),
        students=represented,
    )


def _stored_manifest(
    revision: int,
    *,
    assignment_sha: str = ASSIGNMENT_SHA,
    results_sha: str = RESULTS_SHA,
    manifest_sha: str = MANIFEST_SHA,
):
    relative_path = f"manifests/{revision}.json"
    return SimpleNamespace(
        revision=revision,
        relative_path=relative_path,
        sha256=manifest_sha,
        manifest=SimpleNamespace(
            source_snapshot=SimpleNamespace(
                assignment=SimpleNamespace(sha256=assignment_sha),
                results_history=SimpleNamespace(sha256=results_sha),
            )
        ),
    )


def _core_head(
    revision: int,
    *,
    publication_id: str = PUB_ID,
    manifest_sha: str = MANIFEST_SHA,
):
    return SimpleNamespace(
        publication_id=publication_id,
        record_set_revision=revision,
        manifest_path=f"manifests/{revision}.json",
        manifest_digest=manifest_sha,
    )


def _registration(revision: int = 1):
    return SimpleNamespace(
        registration_revision=revision,
        academic_intent="formative",
        lifecycle="active",
    )


def _series(
    *,
    producer_head=None,
    core_head=None,
    withdrawn: bool = False,
    catalog_available: bool = True,
):
    return SimpleNamespace(
        producer_head=producer_head,
        core_head=core_head,
        core_head_withdrawal=(object() if withdrawn else None),
        derived_catalog_available=catalog_available,
    )


def _configure(
    monkeypatch,
    tmp_path: Path,
    *,
    generation=None,
    registration=None,
    series=None,
    historical=None,
):
    work = ModuleWorkRef("scoreform", "english10_p2", "unit_quiz")
    work_root = tmp_path / "work"
    work_root.mkdir()
    (work_root / "results.csv").write_text("synthetic\n", encoding="utf-8")
    managed = SimpleNamespace(
        work=work,
        work_root=work_root,
        title="Unit Quiz",
    )
    if generation is None:
        generation = _generation_context()
    if series is None:
        series = _series()

    monkeypatch.setattr(
        "scoreform.guided_share_results."
        "load_managed_assignment_registration_context",
        lambda *args, **kwargs: managed,
    )
    monkeypatch.setattr(
        "scoreform.guided_share_results."
        "load_academic_result_manifest_generation_context",
        lambda *args, **kwargs: generation,
    )
    monkeypatch.setattr(
        "scoreform.guided_share_results."
        "load_current_scoreform_academic_work_registration",
        lambda *args, **kwargs: registration,
    )
    monkeypatch.setattr(
        "scoreform.guided_share_results."
        "load_scoreform_publication_series_status",
        lambda *args, **kwargs: series,
    )
    monkeypatch.setattr(
        "scoreform.guided_share_results.load_academic_result_manifest_revision",
        lambda *args, **kwargs: (
            historical
            if historical is not None
            else _stored_manifest(args[-1])
        ),
    )
    return managed


def test_no_results_without_history_is_not_ready(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure(
        monkeypatch,
        tmp_path,
        generation=_generation_context(students=0),
        registration=_registration(),
        series=_series(),
    )

    readiness = plan_share_results_readiness(
        tmp_path,
        "english10_p2",
        "unit_quiz",
    )

    assert readiness.next_step is ShareResultsNextStep.NOT_READY
    assert readiness.result_attempt_count == 0
    assert "No publishable ScoreForm results" in (readiness.blocking_reason or "")


def test_missing_results_without_history_is_not_ready(
    monkeypatch,
    tmp_path: Path,
) -> None:
    managed = _configure(
        monkeypatch,
        tmp_path,
        registration=_registration(),
        series=_series(),
    )
    (managed.work_root / "results.csv").unlink()

    def missing(*args, **kwargs):
        raise ScoreFormManifestGenerationNotFoundError("results.csv missing")

    monkeypatch.setattr(
        "scoreform.guided_share_results."
        "load_academic_result_manifest_generation_context",
        missing,
    )

    readiness = plan_share_results_readiness(
        tmp_path,
        "english10_p2",
        "unit_quiz",
    )

    assert readiness.next_step is ShareResultsNextStep.NOT_READY


def test_missing_retained_evidence_is_repair_not_no_results(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure(monkeypatch, tmp_path)

    def missing(*args, **kwargs):
        raise ScoreFormManifestGenerationNotFoundError(
            "A retained PDS2 source was not found."
        )

    monkeypatch.setattr(
        "scoreform.guided_share_results."
        "load_academic_result_manifest_generation_context",
        missing,
    )

    readiness = plan_share_results_readiness(
        tmp_path,
        "english10_p2",
        "unit_quiz",
    )

    assert readiness.next_step is ShareResultsNextStep.REPAIR_REQUIRED
    assert "result evidence" in (readiness.blocking_reason or "")


def test_publication_history_with_empty_native_results_requires_repair(
    monkeypatch,
    tmp_path: Path,
) -> None:
    producer = _stored_manifest(1)
    _configure(
        monkeypatch,
        tmp_path,
        generation=_generation_context(students=0),
        registration=_registration(),
        series=_series(producer_head=producer),
    )

    readiness = plan_share_results_readiness(
        tmp_path,
        "english10_p2",
        "unit_quiz",
    )

    assert readiness.next_step is ShareResultsNextStep.REPAIR_REQUIRED
    assert "history already exists" in (readiness.blocking_reason or "")


def test_valid_results_without_registration_plan_registration(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure(monkeypatch, tmp_path, registration=None, series=_series())

    readiness = plan_share_results_readiness(
        tmp_path,
        "english10_p2",
        "unit_quiz",
    )

    assert readiness.next_step is ShareResultsNextStep.REGISTER
    assert readiness.registration_revision is None
    assert readiness.result_attempt_count == 1


def test_ready_registration_without_manifest_plans_generation(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure(
        monkeypatch,
        tmp_path,
        registration=_registration(),
        series=_series(),
    )

    readiness = plan_share_results_readiness(
        tmp_path,
        "english10_p2",
        "unit_quiz",
    )

    assert readiness.next_step is ShareResultsNextStep.GENERATE_MANIFEST
    assert readiness.registration_revision == 1


def test_changed_native_sources_plan_manifest_generation(
    monkeypatch,
    tmp_path: Path,
) -> None:
    producer = _stored_manifest(1, results_sha="d" * 64)
    _configure(
        monkeypatch,
        tmp_path,
        registration=_registration(),
        series=_series(producer_head=producer),
    )

    readiness = plan_share_results_readiness(
        tmp_path,
        "english10_p2",
        "unit_quiz",
    )

    assert readiness.next_step is ShareResultsNextStep.GENERATE_MANIFEST
    assert readiness.producer_head_revision == 1
    assert not readiness.producer_head_is_current


def test_current_manifest_without_core_head_plans_first_publication(
    monkeypatch,
    tmp_path: Path,
) -> None:
    producer = _stored_manifest(1)
    _configure(
        monkeypatch,
        tmp_path,
        registration=_registration(),
        series=_series(producer_head=producer, core_head=None),
    )

    readiness = plan_share_results_readiness(
        tmp_path,
        "english10_p2",
        "unit_quiz",
    )

    assert readiness.next_step is ShareResultsNextStep.PUBLISH_FIRST
    assert readiness.producer_head_is_current
    assert readiness.core_head_publication_id is None


def test_exact_current_publication_is_already_current(
    monkeypatch,
    tmp_path: Path,
) -> None:
    producer = _stored_manifest(1)
    core = _core_head(1)
    _configure(
        monkeypatch,
        tmp_path,
        registration=_registration(),
        series=_series(
            producer_head=producer,
            core_head=core,
            catalog_available=True,
        ),
        historical=producer,
    )

    readiness = plan_share_results_readiness(
        tmp_path,
        "english10_p2",
        "unit_quiz",
    )

    assert readiness.next_step is ShareResultsNextStep.ALREADY_CURRENT
    assert readiness.core_head_revision == readiness.producer_head_revision == 1
    assert readiness.catalog_available


def test_current_publication_without_catalog_requires_exact_repair(
    monkeypatch,
    tmp_path: Path,
) -> None:
    producer = _stored_manifest(1)
    core = _core_head(1)
    _configure(
        monkeypatch,
        tmp_path,
        registration=_registration(),
        series=_series(
            producer_head=producer,
            core_head=core,
            catalog_available=False,
        ),
        historical=producer,
    )

    readiness = plan_share_results_readiness(
        tmp_path,
        "english10_p2",
        "unit_quiz",
    )

    assert readiness.next_step is ShareResultsNextStep.REPAIR_REQUIRED
    assert "catalog" in (readiness.blocking_reason or "").lower()


def test_newer_current_producer_head_plans_exact_supersession(
    monkeypatch,
    tmp_path: Path,
) -> None:
    predecessor = _stored_manifest(1, manifest_sha="d" * 64)
    producer = _stored_manifest(2)
    core = _core_head(1, manifest_sha="d" * 64)
    _configure(
        monkeypatch,
        tmp_path,
        registration=_registration(),
        series=_series(producer_head=producer, core_head=core),
        historical=predecessor,
    )

    readiness = plan_share_results_readiness(
        tmp_path,
        "english10_p2",
        "unit_quiz",
    )

    assert readiness.next_step is ShareResultsNextStep.SUPERSEDE
    assert readiness.producer_head_revision == 2
    assert readiness.core_head_revision == 1
    assert readiness.expected_current_publication_id == PUB_ID


def test_withdrawn_core_head_routes_to_exact_recovery(
    monkeypatch,
    tmp_path: Path,
) -> None:
    producer = _stored_manifest(1)
    core = _core_head(1)
    _configure(
        monkeypatch,
        tmp_path,
        registration=_registration(),
        series=_series(
            producer_head=producer,
            core_head=core,
            withdrawn=True,
        ),
        historical=producer,
    )

    readiness = plan_share_results_readiness(
        tmp_path,
        "english10_p2",
        "unit_quiz",
    )

    assert (
        readiness.next_step
        is ShareResultsNextStep.WITHDRAWN_HEAD_REQUIRES_EXACT_RECOVERY
    )
    assert readiness.core_head_withdrawn
    assert "republish-after-withdrawal" in (readiness.blocking_reason or "")


def test_core_head_without_current_registration_requires_repair(
    monkeypatch,
    tmp_path: Path,
) -> None:
    producer = _stored_manifest(1)
    core = _core_head(1)
    _configure(
        monkeypatch,
        tmp_path,
        registration=None,
        series=_series(producer_head=producer, core_head=core),
        historical=producer,
    )

    readiness = plan_share_results_readiness(
        tmp_path,
        "english10_p2",
        "unit_quiz",
    )

    assert readiness.next_step is ShareResultsNextStep.REPAIR_REQUIRED


def test_core_head_must_match_exact_historical_manifest(
    monkeypatch,
    tmp_path: Path,
) -> None:
    producer = _stored_manifest(2)
    historical = _stored_manifest(1, manifest_sha="d" * 64)
    core = _core_head(1, manifest_sha="e" * 64)
    _configure(
        monkeypatch,
        tmp_path,
        registration=_registration(),
        series=_series(producer_head=producer, core_head=core),
        historical=historical,
    )

    readiness = plan_share_results_readiness(
        tmp_path,
        "english10_p2",
        "unit_quiz",
    )

    assert readiness.next_step is ShareResultsNextStep.REPAIR_REQUIRED


def test_core_head_cannot_be_ahead_of_current_producer_head(
    monkeypatch,
    tmp_path: Path,
) -> None:
    producer = _stored_manifest(1)
    historical = _stored_manifest(2)
    core = _core_head(2)
    _configure(
        monkeypatch,
        tmp_path,
        registration=_registration(),
        series=_series(producer_head=producer, core_head=core),
        historical=historical,
    )

    readiness = plan_share_results_readiness(
        tmp_path,
        "english10_p2",
        "unit_quiz",
    )

    assert readiness.next_step is ShareResultsNextStep.REPAIR_REQUIRED


def test_publication_loader_failure_is_safe_repair_state(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure(monkeypatch, tmp_path, registration=_registration())

    def fail(*args, **kwargs):
        raise ScoreFormAcademicResultPublicationIntegrityError(
            r"bad state at C:\private\student-data"
        )

    monkeypatch.setattr(
        "scoreform.guided_share_results."
        "load_scoreform_publication_series_status",
        fail,
    )

    readiness = plan_share_results_readiness(
        tmp_path,
        "english10_p2",
        "unit_quiz",
    )

    assert readiness.next_step is ShareResultsNextStep.REPAIR_REQUIRED
    assert "C:\\private" not in (readiness.blocking_reason or "")


def test_invalid_assignment_raises_safe_planning_error(
    monkeypatch,
    tmp_path: Path,
) -> None:
    def fail(*args, **kwargs):
        raise ScoreFormAcademicWorkRegistrationValidationError(
            r"invalid assignment at C:\private\student-data"
        )

    monkeypatch.setattr(
        "scoreform.guided_share_results."
        "load_managed_assignment_registration_context",
        fail,
    )

    with pytest.raises(ScoreFormShareResultsPlanningError) as caught:
        plan_share_results_readiness(
            tmp_path,
            "english10_p2",
            "unit_quiz",
        )

    assert "could not be validated safely" in str(caught.value)
    assert "C:\\private" not in str(caught.value)
    assert isinstance(
        caught.value.__cause__,
        ScoreFormAcademicWorkRegistrationValidationError,
    )


def test_readiness_model_does_not_store_student_or_result_payloads() -> None:
    slots = set(ShareResultsReadiness.__slots__)

    assert "student_id" not in slots
    assert "students" not in slots
    assert "results" not in slots
    assert "answers" not in slots
    assert "manifest" not in slots


def test_readiness_model_rejects_partial_registration_metadata() -> None:
    work = ModuleWorkRef("scoreform", "english10_p2", "unit_quiz")

    with pytest.raises(ValueError, match="registration metadata presence"):
        ShareResultsReadiness(
            work=work,
            title="Unit Quiz",
            result_student_count=1,
            result_attempt_count=1,
            registration_revision=1,
            academic_intent="formative",
            registration_lifecycle=None,
            producer_head_revision=None,
            producer_head_is_current=False,
            core_head_publication_id=None,
            core_head_revision=None,
            core_head_withdrawn=False,
            catalog_available=False,
            next_step=ShareResultsNextStep.REPAIR_REQUIRED,
            blocking_reason="repair",
        )
