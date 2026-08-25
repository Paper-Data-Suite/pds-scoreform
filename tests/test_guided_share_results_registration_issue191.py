"""Guided registration-stage coverage for ScoreForm issue #191."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from pds_core.registry_services import AcademicWorkRegistrationRequest
from pds_core.routing_models import ModuleRecordRef, ModuleWorkRef

from scoreform.academic_work_registration import (
    ScoreFormAcademicWorkRegistrationConflictError,
    ScoreFormAcademicWorkRegistrationPartialSuccessError,
)
from scoreform.guided_share_results import (
    ScoreFormShareResultsRegistrationConflictError,
    ScoreFormShareResultsRegistrationNotReadyError,
    ScoreFormShareResultsRegistrationPartialSuccessError,
    ScoreFormShareResultsRegistrationWriteError,
    ShareResultsNextStep,
    ShareResultsRegistrationPreview,
    commit_share_results_registration,
    prepare_share_results_registration,
)


def _request(
    *,
    title: str = "Unit Quiz",
    intent: str = "formative",
    lifecycle: str = "active",
) -> AcademicWorkRegistrationRequest:
    work = ModuleWorkRef("scoreform", "english10_p2", "unit_quiz")
    return AcademicWorkRegistrationRequest(
        work=work,
        producer_contract_version="scoreform_academic_work_v1",
        title=title,
        work_kind="assignment",
        academic_intent=intent,
        lifecycle=lifecycle,
        source_records=(
            ModuleRecordRef(
                module_id="scoreform",
                record_kind="assignment",
                record_id="unit_quiz",
                contract_version=None,
            ),
        ),
    )


def _registration(
    request: AcademicWorkRegistrationRequest,
    *,
    revision: int = 1,
):
    return SimpleNamespace(
        work=request.work,
        registration_revision=revision,
        producer_contract_version=request.producer_contract_version,
        title=request.title,
        work_kind=request.work_kind,
        academic_intent=request.academic_intent,
        lifecycle=request.lifecycle,
        source_records=request.source_records,
    )


def _managed(request: AcademicWorkRegistrationRequest):
    return SimpleNamespace(
        work=request.work,
        title=request.title,
        work_root=Path("unused"),
    )


def _ready(monkeypatch, request: AcademicWorkRegistrationRequest) -> None:
    monkeypatch.setattr(
        "scoreform.guided_share_results.plan_share_results_readiness",
        lambda *args, **kwargs: SimpleNamespace(
            next_step=ShareResultsNextStep.REGISTER
        ),
    )
    monkeypatch.setattr(
        "scoreform.guided_share_results."
        "load_managed_assignment_registration_context",
        lambda *args, **kwargs: _managed(request),
    )
    monkeypatch.setattr(
        "scoreform.guided_share_results."
        "build_scoreform_academic_work_registration_request",
        lambda context, *, academic_intent, lifecycle: _request(
            title=context.title,
            intent=str(academic_intent),
            lifecycle=str(lifecycle),
        ),
    )


def test_prepare_builds_exact_read_only_registration_request(
    monkeypatch,
    tmp_path: Path,
) -> None:
    request = _request()
    _ready(monkeypatch, request)
    calls = {"register": 0}
    monkeypatch.setattr(
        "scoreform.guided_share_results.register_scoreform_academic_work",
        lambda *args, **kwargs: calls.__setitem__(
            "register", calls["register"] + 1
        ),
    )

    preview = prepare_share_results_registration(
        tmp_path,
        "english10_p2",
        "unit_quiz",
        academic_intent="formative",
        lifecycle="active",
    )

    assert preview.request == request
    assert preview.work == request.work
    assert preview.title == "Unit Quiz"
    assert preview.academic_intent == "formative"
    assert preview.lifecycle == "active"
    assert calls["register"] == 0


def test_prepare_requires_register_readiness(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "scoreform.guided_share_results.plan_share_results_readiness",
        lambda *args, **kwargs: SimpleNamespace(
            next_step=ShareResultsNextStep.GENERATE_MANIFEST
        ),
    )

    with pytest.raises(ScoreFormShareResultsRegistrationNotReadyError):
        prepare_share_results_registration(
            tmp_path,
            "english10_p2",
            "unit_quiz",
            academic_intent="formative",
            lifecycle="active",
        )


def test_prepare_rejects_invalid_choices_without_write(
    monkeypatch,
    tmp_path: Path,
) -> None:
    request = _request()
    _ready(monkeypatch, request)

    def invalid(*args, **kwargs):
        raise ValueError("bad intent")

    monkeypatch.setattr(
        "scoreform.guided_share_results."
        "build_scoreform_academic_work_registration_request",
        invalid,
    )

    with pytest.raises(ScoreFormShareResultsRegistrationNotReadyError):
        prepare_share_results_registration(
            tmp_path,
            "english10_p2",
            "unit_quiz",
            academic_intent="made_up",
            lifecycle="active",
        )


def test_preview_without_commit_is_safe_cancellation(
    monkeypatch,
    tmp_path: Path,
) -> None:
    request = _request()
    _ready(monkeypatch, request)
    calls = {"register": 0}
    monkeypatch.setattr(
        "scoreform.guided_share_results.register_scoreform_academic_work",
        lambda *args, **kwargs: calls.__setitem__(
            "register", calls["register"] + 1
        ),
    )

    prepare_share_results_registration(
        tmp_path,
        "english10_p2",
        "unit_quiz",
        academic_intent="formative",
        lifecycle="active",
    )

    assert calls["register"] == 0


def test_commit_calls_exact_registration_service_once(
    monkeypatch,
    tmp_path: Path,
) -> None:
    request = _request()
    preview = ShareResultsRegistrationPreview(request)
    _ready(monkeypatch, request)
    monkeypatch.setattr(
        "scoreform.guided_share_results."
        "load_current_scoreform_academic_work_registration",
        lambda *args, **kwargs: None,
    )
    calls = []

    def register(
        workspace_root,
        class_id,
        assignment_id,
        *,
        academic_intent,
        lifecycle,
    ):
        calls.append(
            (
                workspace_root,
                class_id,
                assignment_id,
                academic_intent,
                lifecycle,
            )
        )
        return SimpleNamespace(
            disposition="created",
            registration=_registration(request),
        )

    monkeypatch.setattr(
        "scoreform.guided_share_results.register_scoreform_academic_work",
        register,
    )

    result = commit_share_results_registration(tmp_path, preview)

    assert result.disposition == "created"
    assert result.registration.registration_revision == 1
    assert calls == [
        (
            tmp_path,
            "english10_p2",
            "unit_quiz",
            "formative",
            "active",
        )
    ]


def test_concurrent_identical_registration_is_reused_without_write(
    monkeypatch,
    tmp_path: Path,
) -> None:
    request = _request()
    preview = ShareResultsRegistrationPreview(request)
    _ready(monkeypatch, request)
    existing = _registration(request, revision=2)
    monkeypatch.setattr(
        "scoreform.guided_share_results."
        "load_current_scoreform_academic_work_registration",
        lambda *args, **kwargs: existing,
    )
    calls = {"register": 0}
    monkeypatch.setattr(
        "scoreform.guided_share_results.register_scoreform_academic_work",
        lambda *args, **kwargs: calls.__setitem__(
            "register", calls["register"] + 1
        ),
    )

    result = commit_share_results_registration(tmp_path, preview)

    assert result.disposition == "existing"
    assert result.registration is existing
    assert calls["register"] == 0


def test_different_current_registration_is_never_updated_implicitly(
    monkeypatch,
    tmp_path: Path,
) -> None:
    request = _request()
    preview = ShareResultsRegistrationPreview(request)
    _ready(monkeypatch, request)
    different = _registration(_request(intent="summative"))
    monkeypatch.setattr(
        "scoreform.guided_share_results."
        "load_current_scoreform_academic_work_registration",
        lambda *args, **kwargs: different,
    )
    calls = {"register": 0}
    monkeypatch.setattr(
        "scoreform.guided_share_results.register_scoreform_academic_work",
        lambda *args, **kwargs: calls.__setitem__(
            "register", calls["register"] + 1
        ),
    )

    with pytest.raises(ScoreFormShareResultsRegistrationConflictError) as caught:
        commit_share_results_registration(tmp_path, preview)

    assert "will not update it implicitly" in str(caught.value)
    assert calls["register"] == 0


def test_assignment_change_after_preview_requires_new_preview(
    monkeypatch,
    tmp_path: Path,
) -> None:
    request = _request(title="Original Title")
    preview = ShareResultsRegistrationPreview(request)
    changed = _request(title="Renamed Title")
    monkeypatch.setattr(
        "scoreform.guided_share_results."
        "load_managed_assignment_registration_context",
        lambda *args, **kwargs: _managed(changed),
    )
    monkeypatch.setattr(
        "scoreform.guided_share_results."
        "build_scoreform_academic_work_registration_request",
        lambda *args, **kwargs: changed,
    )
    calls = {"register": 0}
    monkeypatch.setattr(
        "scoreform.guided_share_results.register_scoreform_academic_work",
        lambda *args, **kwargs: calls.__setitem__(
            "register", calls["register"] + 1
        ),
    )

    with pytest.raises(ScoreFormShareResultsRegistrationConflictError):
        commit_share_results_registration(tmp_path, preview)

    assert calls["register"] == 0


def test_service_race_conflict_fails_without_retry(
    monkeypatch,
    tmp_path: Path,
) -> None:
    request = _request()
    preview = ShareResultsRegistrationPreview(request)
    _ready(monkeypatch, request)
    monkeypatch.setattr(
        "scoreform.guided_share_results."
        "load_current_scoreform_academic_work_registration",
        lambda *args, **kwargs: None,
    )
    calls = {"register": 0}

    def conflict(*args, **kwargs):
        calls["register"] += 1
        raise ScoreFormAcademicWorkRegistrationConflictError("stale")

    monkeypatch.setattr(
        "scoreform.guided_share_results.register_scoreform_academic_work",
        conflict,
    )

    with pytest.raises(ScoreFormShareResultsRegistrationConflictError):
        commit_share_results_registration(tmp_path, preview)

    assert calls["register"] == 1


def test_partial_success_is_projected_without_canonical_path(
    monkeypatch,
    tmp_path: Path,
) -> None:
    request = _request()
    preview = ShareResultsRegistrationPreview(request)
    _ready(monkeypatch, request)
    monkeypatch.setattr(
        "scoreform.guided_share_results."
        "load_current_scoreform_academic_work_registration",
        lambda *args, **kwargs: None,
    )
    durable = _registration(request, revision=1)
    state = SimpleNamespace(
        registration=durable,
        current_selected=True,
        canonical_path=Path(r"C:\private\registry.json"),
    )

    def partial(*args, **kwargs):
        raise ScoreFormAcademicWorkRegistrationPartialSuccessError(
            "partial",
            state,
        )

    monkeypatch.setattr(
        "scoreform.guided_share_results.register_scoreform_academic_work",
        partial,
    )

    with pytest.raises(
        ScoreFormShareResultsRegistrationPartialSuccessError
    ) as caught:
        commit_share_results_registration(tmp_path, preview)

    recovery = caught.value.recovery
    assert recovery.durable_registration_revision == 1
    assert recovery.current_selected is True
    assert "reload" in recovery.guidance.lower()
    assert not hasattr(recovery, "canonical_path")
    assert "C:\\private" not in str(caught.value)


def test_partial_success_uncertain_state_requires_reload(
    monkeypatch,
    tmp_path: Path,
) -> None:
    request = _request()
    preview = ShareResultsRegistrationPreview(request)
    _ready(monkeypatch, request)
    monkeypatch.setattr(
        "scoreform.guided_share_results."
        "load_current_scoreform_academic_work_registration",
        lambda *args, **kwargs: None,
    )
    state = SimpleNamespace(
        registration=None,
        current_selected=None,
        canonical_path=Path(r"C:\private\registry.json"),
    )

    def partial(*args, **kwargs):
        raise ScoreFormAcademicWorkRegistrationPartialSuccessError(
            "partial",
            state,
        )

    monkeypatch.setattr(
        "scoreform.guided_share_results.register_scoreform_academic_work",
        partial,
    )

    with pytest.raises(
        ScoreFormShareResultsRegistrationPartialSuccessError
    ) as caught:
        commit_share_results_registration(tmp_path, preview)

    assert caught.value.recovery.durable_registration_revision is None
    assert caught.value.recovery.current_selected is None
    assert "uncertain" in caught.value.recovery.guidance.lower()


def test_service_result_must_match_confirmed_preview(
    monkeypatch,
    tmp_path: Path,
) -> None:
    request = _request()
    preview = ShareResultsRegistrationPreview(request)
    _ready(monkeypatch, request)
    monkeypatch.setattr(
        "scoreform.guided_share_results."
        "load_current_scoreform_academic_work_registration",
        lambda *args, **kwargs: None,
    )
    different = _registration(_request(intent="summative"))
    monkeypatch.setattr(
        "scoreform.guided_share_results.register_scoreform_academic_work",
        lambda *args, **kwargs: SimpleNamespace(
            disposition="created",
            registration=different,
        ),
    )

    with pytest.raises(ScoreFormShareResultsRegistrationWriteError):
        commit_share_results_registration(tmp_path, preview)


def test_preview_model_contains_no_student_or_result_payloads() -> None:
    slots = set(ShareResultsRegistrationPreview.__slots__)

    assert slots == {"request"}
    preview = ShareResultsRegistrationPreview(_request())
    assert not hasattr(preview, "students")
    assert not hasattr(preview, "results")
    assert not hasattr(preview, "answers")
