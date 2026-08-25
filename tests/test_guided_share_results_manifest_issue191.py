"""Guided immutable-manifest stage coverage for ScoreForm issue #191."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from pds_core.routing_models import ModuleWorkRef

from scoreform.academic_result_manifest_generation import (
    ManifestGenerationPartialSuccessState,
    ScoreFormManifestGenerationConflictError,
    ScoreFormManifestGenerationIntegrityError,
    ScoreFormManifestGenerationPartialSuccessError,
    ScoreFormManifestGenerationWriteError,
)
from scoreform.guided_share_results import (
    ScoreFormShareResultsManifestConflictError,
    ScoreFormShareResultsManifestNotReadyError,
    ScoreFormShareResultsManifestPartialSuccessError,
    ScoreFormShareResultsManifestRepairRequiredError,
    ScoreFormShareResultsManifestWriteError,
    ShareResultsManifestPreview,
    ShareResultsNextStep,
    commit_share_results_manifest,
    prepare_share_results_manifest,
)
from scoreform.publication_revision_policy import (
    ManifestRevisionDisposition,
    ManifestRevisionReason,
)

WORK = ModuleWorkRef("scoreform", "english10_p2", "unit_quiz")
SHA = "a" * 64


def _readiness(
    *,
    next_step: ShareResultsNextStep = ShareResultsNextStep.GENERATE_MANIFEST,
    title: str = "Unit Quiz",
    registration_revision: int | None = 1,
    producer_head_revision: int | None = None,
):
    return SimpleNamespace(
        work=WORK,
        title=title,
        registration_revision=registration_revision,
        producer_head_revision=producer_head_revision,
        next_step=next_step,
    )


def _preview(
    *,
    title: str = "Unit Quiz",
    registration_revision: int = 1,
    producer_head_revision_before: int | None = None,
) -> ShareResultsManifestPreview:
    return ShareResultsManifestPreview(
        work=WORK,
        title=title,
        registration_revision=registration_revision,
        producer_head_revision_before=producer_head_revision_before,
    )


def _generation_result(
    revision: int,
    disposition: ManifestRevisionDisposition,
    reason: ManifestRevisionReason,
    *,
    work: ModuleWorkRef = WORK,
):
    return SimpleNamespace(
        disposition=disposition,
        reason=reason,
        revision=revision,
        relative_path=(
            "modules/scoreform/work/"
            f"{work.class_id}/{work.work_id}/academic_result_manifests/{revision}.json"
        ),
        sha256=SHA,
        manifest=SimpleNamespace(
            work=SimpleNamespace(
                module_id=work.module_id,
                class_id=work.class_id,
                work_id=work.work_id,
            )
        ),
    )


def test_prepare_manifest_is_read_only_and_does_not_allocate_revision(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "scoreform.guided_share_results.plan_share_results_readiness",
        lambda *args, **kwargs: _readiness(
            producer_head_revision=4,
        ),
    )
    calls = {"generate": 0}
    monkeypatch.setattr(
        "scoreform.guided_share_results.generate_academic_result_manifest",
        lambda *args, **kwargs: calls.__setitem__(
            "generate", calls["generate"] + 1
        ),
    )

    preview = prepare_share_results_manifest(
        tmp_path,
        "english10_p2",
        "unit_quiz",
    )

    assert preview.work == WORK
    assert preview.registration_revision == 1
    assert preview.producer_head_revision_before == 4
    assert not hasattr(preview, "revision")
    assert calls["generate"] == 0


def test_prepare_requires_manifest_generation_readiness(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "scoreform.guided_share_results.plan_share_results_readiness",
        lambda *args, **kwargs: _readiness(
            next_step=ShareResultsNextStep.PUBLISH_FIRST,
            producer_head_revision=1,
        ),
    )

    with pytest.raises(ScoreFormShareResultsManifestNotReadyError):
        prepare_share_results_manifest(
            tmp_path,
            "english10_p2",
            "unit_quiz",
        )


def test_prepare_requires_ready_registration(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "scoreform.guided_share_results.plan_share_results_readiness",
        lambda *args, **kwargs: _readiness(registration_revision=None),
    )

    with pytest.raises(ScoreFormShareResultsManifestNotReadyError):
        prepare_share_results_manifest(
            tmp_path,
            "english10_p2",
            "unit_quiz",
        )


def test_preview_without_commit_is_safe_generate_cancellation(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "scoreform.guided_share_results.plan_share_results_readiness",
        lambda *args, **kwargs: _readiness(),
    )
    calls = {"generate": 0}
    monkeypatch.setattr(
        "scoreform.guided_share_results.generate_academic_result_manifest",
        lambda *args, **kwargs: calls.__setitem__(
            "generate", calls["generate"] + 1
        ),
    )

    prepare_share_results_manifest(
        tmp_path,
        "english10_p2",
        "unit_quiz",
    )

    assert calls["generate"] == 0


def test_commit_calls_generator_once_and_uses_returned_initial_revision(
    monkeypatch,
    tmp_path: Path,
) -> None:
    preview = _preview()
    monkeypatch.setattr(
        "scoreform.guided_share_results.plan_share_results_readiness",
        lambda *args, **kwargs: _readiness(),
    )
    calls = []

    def generate(workspace_root, class_id, assignment_id):
        calls.append((workspace_root, class_id, assignment_id))
        return _generation_result(
            1,
            ManifestRevisionDisposition.CREATE_INITIAL,
            ManifestRevisionReason.INITIAL_PUBLICATION,
        )

    monkeypatch.setattr(
        "scoreform.guided_share_results.generate_academic_result_manifest",
        generate,
    )

    result = commit_share_results_manifest(tmp_path, preview)

    assert calls == [(tmp_path, "english10_p2", "unit_quiz")]
    assert result.revision == 1
    assert result.disposition is ManifestRevisionDisposition.CREATE_INITIAL
    assert result.reason is ManifestRevisionReason.INITIAL_PUBLICATION
    assert result.created_new_revision


def test_commit_carries_generator_returned_successor_revision_without_guessing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    preview = _preview(producer_head_revision_before=7)
    monkeypatch.setattr(
        "scoreform.guided_share_results.plan_share_results_readiness",
        lambda *args, **kwargs: _readiness(producer_head_revision=7),
    )
    monkeypatch.setattr(
        "scoreform.guided_share_results.generate_academic_result_manifest",
        lambda *args, **kwargs: _generation_result(
            9,
            ManifestRevisionDisposition.CREATE_SUCCESSOR,
            ManifestRevisionReason.NATIVE_SOURCE_CHANGED,
        ),
    )

    result = commit_share_results_manifest(tmp_path, preview)

    assert result.revision == 9
    assert result.disposition is ManifestRevisionDisposition.CREATE_SUCCESSOR
    assert result.reason is ManifestRevisionReason.NATIVE_SOURCE_CHANGED
    assert result.created_new_revision


def test_exact_replay_is_normal_idempotent_result(
    monkeypatch,
    tmp_path: Path,
) -> None:
    preview = _preview(producer_head_revision_before=3)
    monkeypatch.setattr(
        "scoreform.guided_share_results.plan_share_results_readiness",
        lambda *args, **kwargs: _readiness(producer_head_revision=3),
    )
    monkeypatch.setattr(
        "scoreform.guided_share_results.generate_academic_result_manifest",
        lambda *args, **kwargs: _generation_result(
            3,
            ManifestRevisionDisposition.REUSE_EXISTING,
            ManifestRevisionReason.EXACT_REPLAY,
        ),
    )

    result = commit_share_results_manifest(tmp_path, preview)

    assert result.revision == 3
    assert result.disposition is ManifestRevisionDisposition.REUSE_EXISTING
    assert not result.created_new_revision


@pytest.mark.parametrize(
    ("changed_readiness", "message_fragment"),
    [
        (
            _readiness(
                next_step=ShareResultsNextStep.PUBLISH_FIRST,
                producer_head_revision=2,
            ),
            "readiness changed",
        ),
        (
            _readiness(
                registration_revision=2,
                producer_head_revision=None,
            ),
            "state changed",
        ),
        (
            _readiness(
                title="Renamed Unit Quiz",
                producer_head_revision=None,
            ),
            "state changed",
        ),
        (
            _readiness(
                producer_head_revision=1,
            ),
            "state changed",
        ),
    ],
)
def test_commit_rejects_stale_preview_before_generator_call(
    monkeypatch,
    tmp_path: Path,
    changed_readiness,
    message_fragment: str,
) -> None:
    preview = _preview()
    monkeypatch.setattr(
        "scoreform.guided_share_results.plan_share_results_readiness",
        lambda *args, **kwargs: changed_readiness,
    )
    calls = {"generate": 0}
    monkeypatch.setattr(
        "scoreform.guided_share_results.generate_academic_result_manifest",
        lambda *args, **kwargs: calls.__setitem__(
            "generate", calls["generate"] + 1
        ),
    )

    with pytest.raises(ScoreFormShareResultsManifestConflictError) as caught:
        commit_share_results_manifest(tmp_path, preview)

    assert message_fragment in str(caught.value)
    assert calls["generate"] == 0


def test_generator_conflict_is_not_retried(
    monkeypatch,
    tmp_path: Path,
) -> None:
    preview = _preview()
    monkeypatch.setattr(
        "scoreform.guided_share_results.plan_share_results_readiness",
        lambda *args, **kwargs: _readiness(),
    )
    calls = {"generate": 0}

    def conflict(*args, **kwargs):
        calls["generate"] += 1
        raise ScoreFormManifestGenerationConflictError("write lock")

    monkeypatch.setattr(
        "scoreform.guided_share_results.generate_academic_result_manifest",
        conflict,
    )

    with pytest.raises(ScoreFormShareResultsManifestConflictError):
        commit_share_results_manifest(tmp_path, preview)

    assert calls["generate"] == 1


def test_integrity_failure_requires_exact_repair(
    monkeypatch,
    tmp_path: Path,
) -> None:
    preview = _preview()
    monkeypatch.setattr(
        "scoreform.guided_share_results.plan_share_results_readiness",
        lambda *args, **kwargs: _readiness(),
    )

    def fail(*args, **kwargs):
        raise ScoreFormManifestGenerationIntegrityError(
            r"bad manifest at C:\private\student-data"
        )

    monkeypatch.setattr(
        "scoreform.guided_share_results.generate_academic_result_manifest",
        fail,
    )

    with pytest.raises(
        ScoreFormShareResultsManifestRepairRequiredError
    ) as caught:
        commit_share_results_manifest(tmp_path, preview)

    assert "C:\\private" not in str(caught.value)


def test_write_failure_is_bounded_and_does_not_leak_service_message(
    monkeypatch,
    tmp_path: Path,
) -> None:
    preview = _preview()
    monkeypatch.setattr(
        "scoreform.guided_share_results.plan_share_results_readiness",
        lambda *args, **kwargs: _readiness(),
    )

    def fail(*args, **kwargs):
        raise ScoreFormManifestGenerationWriteError(
            r"write failed at C:\private\student-data"
        )

    monkeypatch.setattr(
        "scoreform.guided_share_results.generate_academic_result_manifest",
        fail,
    )

    with pytest.raises(ScoreFormShareResultsManifestWriteError) as caught:
        commit_share_results_manifest(tmp_path, preview)

    assert "C:\\private" not in str(caught.value)


def test_partial_success_projects_durable_relative_state_without_absolute_path(
    monkeypatch,
    tmp_path: Path,
) -> None:
    preview = _preview()
    monkeypatch.setattr(
        "scoreform.guided_share_results.plan_share_results_readiness",
        lambda *args, **kwargs: _readiness(),
    )
    state = ManifestGenerationPartialSuccessState(
        operation="generate",
        work=WORK,
        revision=2,
        path=Path(r"C:\private\academic_result_manifests\2.json"),
        relative_path=(
            "modules/scoreform/work/english10_p2/unit_quiz/"
            "academic_result_manifests/2.json"
        ),
        expected_sha256=SHA,
        durable_file_exists=True,
        lock_cleanup_failure=None,
    )
    calls = {"generate": 0}

    def partial(*args, **kwargs):
        calls["generate"] += 1
        raise ScoreFormManifestGenerationPartialSuccessError(
            "durable but cleanup failed",
            state,
        )

    monkeypatch.setattr(
        "scoreform.guided_share_results.generate_academic_result_manifest",
        partial,
    )

    with pytest.raises(
        ScoreFormShareResultsManifestPartialSuccessError
    ) as caught:
        commit_share_results_manifest(tmp_path, preview)

    recovery = caught.value.recovery
    assert calls["generate"] == 1
    assert recovery.revision == 2
    assert recovery.durable_file_exists
    assert recovery.expected_sha256 == SHA
    assert recovery.relative_path.endswith(
        "academic_result_manifests/2.json"
    )
    assert not hasattr(recovery, "path")
    assert "C:\\private" not in str(caught.value)
    assert "do not generate again automatically" in recovery.guidance


def test_partial_success_can_report_uncertain_file_durability(
    monkeypatch,
    tmp_path: Path,
) -> None:
    preview = _preview()
    monkeypatch.setattr(
        "scoreform.guided_share_results.plan_share_results_readiness",
        lambda *args, **kwargs: _readiness(),
    )
    state = ManifestGenerationPartialSuccessState(
        operation="generate",
        work=WORK,
        revision=2,
        path=Path(r"C:\private\academic_result_manifests\2.json"),
        relative_path=(
            "modules/scoreform/work/english10_p2/unit_quiz/"
            "academic_result_manifests/2.json"
        ),
        expected_sha256=None,
        durable_file_exists=False,
        lock_cleanup_failure=None,
    )

    def partial(*args, **kwargs):
        raise ScoreFormManifestGenerationPartialSuccessError(
            "uncertain",
            state,
        )

    monkeypatch.setattr(
        "scoreform.guided_share_results.generate_academic_result_manifest",
        partial,
    )

    with pytest.raises(
        ScoreFormShareResultsManifestPartialSuccessError
    ) as caught:
        commit_share_results_manifest(tmp_path, preview)

    recovery = caught.value.recovery
    assert not recovery.durable_file_exists
    assert recovery.expected_sha256 is None
    assert "uncertain" in recovery.guidance.lower()


def test_generator_result_must_target_previewed_work(
    monkeypatch,
    tmp_path: Path,
) -> None:
    preview = _preview()
    monkeypatch.setattr(
        "scoreform.guided_share_results.plan_share_results_readiness",
        lambda *args, **kwargs: _readiness(),
    )
    other = ModuleWorkRef("scoreform", "english10_p2", "other_quiz")
    monkeypatch.setattr(
        "scoreform.guided_share_results.generate_academic_result_manifest",
        lambda *args, **kwargs: _generation_result(
            1,
            ManifestRevisionDisposition.CREATE_INITIAL,
            ManifestRevisionReason.INITIAL_PUBLICATION,
            work=other,
        ),
    )

    with pytest.raises(ScoreFormShareResultsManifestWriteError):
        commit_share_results_manifest(tmp_path, preview)


def test_manifest_stage_models_do_not_retain_student_or_result_payloads() -> None:
    assert set(ShareResultsManifestPreview.__slots__) == {
        "work",
        "title",
        "registration_revision",
        "producer_head_revision_before",
    }
