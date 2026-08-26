"""Issue #193 Slice 4 Share Results attention tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pds_core.module_operations import ModuleOperationsRequest
from pds_core.routing_models import ModuleWorkRef

import scoreform.attention_provider as provider
from scoreform.attention_share_results import project_share_results_attention
from scoreform.guided_share_results import (
    ShareResultsNextStep,
    ShareResultsReadiness,
)


def _readiness(
    next_step: ShareResultsNextStep,
    *,
    work: ModuleWorkRef | None = None,
) -> ShareResultsReadiness:
    work = work or ModuleWorkRef("scoreform", "class1", "quiz1")

    common = dict(
        work=work,
        title="Private title sentinel",
        result_student_count=17,
        result_attempt_count=23,
        registration_revision=1,
        academic_intent="summative",
        registration_lifecycle="active",
        producer_head_revision=2,
        producer_head_is_current=True,
        core_head_publication_id="pub_private_sentinel",
        core_head_revision=1,
        core_head_withdrawn=False,
        catalog_available=True,
        next_step=next_step,
        blocking_reason=None,
    )

    if next_step is ShareResultsNextStep.NOT_READY:
        common.update(
            result_student_count=0,
            result_attempt_count=0,
            registration_revision=None,
            academic_intent=None,
            registration_lifecycle=None,
            producer_head_revision=None,
            producer_head_is_current=False,
            core_head_publication_id=None,
            core_head_revision=None,
            core_head_withdrawn=False,
            catalog_available=False,
            blocking_reason="Private blocking reason sentinel",
        )
    elif next_step is ShareResultsNextStep.REGISTER:
        common.update(
            registration_revision=None,
            academic_intent=None,
            registration_lifecycle=None,
            producer_head_revision=None,
            producer_head_is_current=False,
            core_head_publication_id=None,
            core_head_revision=None,
            catalog_available=False,
        )
    elif next_step is ShareResultsNextStep.GENERATE_MANIFEST:
        common.update(
            producer_head_revision=None,
            producer_head_is_current=False,
            core_head_publication_id=None,
            core_head_revision=None,
            catalog_available=False,
        )
    elif next_step is ShareResultsNextStep.PUBLISH_FIRST:
        common.update(
            producer_head_revision=1,
            producer_head_is_current=True,
            core_head_publication_id=None,
            core_head_revision=None,
            catalog_available=False,
        )
    elif next_step is ShareResultsNextStep.ALREADY_CURRENT:
        common.update(
            producer_head_revision=1,
            producer_head_is_current=True,
            core_head_publication_id="pub_private_sentinel",
            core_head_revision=1,
            core_head_withdrawn=False,
            catalog_available=True,
        )
    elif next_step is ShareResultsNextStep.SUPERSEDE:
        common.update(
            producer_head_revision=2,
            producer_head_is_current=True,
            core_head_publication_id="pub_private_sentinel",
            core_head_revision=1,
            core_head_withdrawn=False,
        )
    elif next_step is ShareResultsNextStep.WITHDRAWN_HEAD_REQUIRES_EXACT_RECOVERY:
        common.update(
            core_head_withdrawn=True,
            blocking_reason="Private withdrawn reason sentinel",
        )
    elif next_step is ShareResultsNextStep.REPAIR_REQUIRED:
        common.update(
            producer_head_is_current=False,
            blocking_reason="Private repair reason sentinel",
        )

    return ShareResultsReadiness(**common)


@pytest.mark.parametrize(
    ("next_step", "expected_code"),
    [
        (
            ShareResultsNextStep.REGISTER,
            "scoreform_results_registration_pending",
        ),
        (
            ShareResultsNextStep.GENERATE_MANIFEST,
            "scoreform_results_manifest_pending",
        ),
        (
            ShareResultsNextStep.PUBLISH_FIRST,
            "scoreform_results_publication_pending",
        ),
        (
            ShareResultsNextStep.SUPERSEDE,
            "scoreform_results_supersession_pending",
        ),
        (
            ShareResultsNextStep.WITHDRAWN_HEAD_REQUIRES_EXACT_RECOVERY,
            "scoreform_results_publication_recovery",
        ),
        (
            ShareResultsNextStep.REPAIR_REQUIRED,
            "scoreform_results_state_attention",
        ),
    ],
)
def test_actionable_share_states_map_to_fixed_attention(
    next_step: ShareResultsNextStep,
    expected_code: str,
) -> None:
    fact = project_share_results_attention(_readiness(next_step))

    assert fact is not None
    assert fact.code == expected_code
    assert fact.work_ref == ModuleWorkRef("scoreform", "class1", "quiz1")


@pytest.mark.parametrize(
    "next_step",
    [
        ShareResultsNextStep.NOT_READY,
        ShareResultsNextStep.ALREADY_CURRENT,
    ],
)
def test_nonattention_share_states_emit_nothing(
    next_step: ShareResultsNextStep,
) -> None:
    assert project_share_results_attention(_readiness(next_step)) is None


def test_projection_does_not_expose_private_planner_fields() -> None:
    readiness = _readiness(ShareResultsNextStep.SUPERSEDE)

    fact = project_share_results_attention(readiness)

    assert fact is not None
    rendered = repr(fact)
    for sentinel in (
        "Private title sentinel",
        "pub_private_sentinel",
        "17",
        "23",
    ):
        assert sentinel not in rendered


def test_provider_counts_assignments_not_students_or_attempts(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refs = (
        ModuleWorkRef("scoreform", "class1", "quiz1"),
        ModuleWorkRef("scoreform", "class1", "quiz2"),
    )
    monkeypatch.setattr(
        provider,
        "discover_scoreform_class_ids",
        lambda root, requested: ("class1",),
    )
    monkeypatch.setattr(
        provider,
        "discover_scoreform_work",
        lambda root, class_id: SimpleNamespace(
            work_refs=refs,
            warning_count=0,
        ),
    )
    monkeypatch.setattr(
        provider,
        "discover_scan_review_items",
        lambda root, **kwargs: SimpleNamespace(items=(), warning_count=0),
    )

    def fake_plan(root, class_id, assignment_id):
        return _readiness(
            ShareResultsNextStep.PUBLISH_FIRST,
            work=ModuleWorkRef("scoreform", class_id, assignment_id),
        )

    monkeypatch.setattr(provider, "plan_share_results_readiness", fake_plan)

    report = provider.evaluate_scoreform_attention(
        ModuleOperationsRequest(workspace_root=tmp_path)
    )

    assert tuple(summary.code for summary in report.summaries) == (
        "scoreform_results_publication_pending",
    )
    summary = report.summaries[0]
    assert summary.count == 2
    assert summary.class_id == "class1"
    assert summary.work_ref is None
    assert summary.action is not None
    assert summary.action.action_id == "open_share_results"


def test_provider_omits_not_ready_and_already_current(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refs = (
        ModuleWorkRef("scoreform", "class1", "quiz1"),
        ModuleWorkRef("scoreform", "class1", "quiz2"),
    )
    states = {
        "quiz1": ShareResultsNextStep.NOT_READY,
        "quiz2": ShareResultsNextStep.ALREADY_CURRENT,
    }
    monkeypatch.setattr(
        provider,
        "discover_scoreform_class_ids",
        lambda root, requested: ("class1",),
    )
    monkeypatch.setattr(
        provider,
        "discover_scoreform_work",
        lambda root, class_id: SimpleNamespace(
            work_refs=refs,
            warning_count=0,
        ),
    )
    monkeypatch.setattr(
        provider,
        "discover_scan_review_items",
        lambda root, **kwargs: SimpleNamespace(items=(), warning_count=0),
    )
    monkeypatch.setattr(
        provider,
        "plan_share_results_readiness",
        lambda root, class_id, assignment_id: _readiness(
            states[assignment_id],
            work=ModuleWorkRef("scoreform", class_id, assignment_id),
        ),
    )

    report = provider.evaluate_scoreform_attention(
        ModuleOperationsRequest(workspace_root=tmp_path)
    )

    assert report.summaries == ()
    assert report.notices == ()


def test_one_share_planning_failure_preserves_other_assignment_attention(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refs = (
        ModuleWorkRef("scoreform", "class1", "bad"),
        ModuleWorkRef("scoreform", "class1", "good"),
    )
    monkeypatch.setattr(
        provider,
        "discover_scoreform_class_ids",
        lambda root, requested: ("class1",),
    )
    monkeypatch.setattr(
        provider,
        "discover_scoreform_work",
        lambda root, class_id: SimpleNamespace(
            work_refs=refs,
            warning_count=0,
        ),
    )
    monkeypatch.setattr(
        provider,
        "discover_scan_review_items",
        lambda root, **kwargs: SimpleNamespace(items=(), warning_count=0),
    )

    def fake_plan(root, class_id, assignment_id):
        if assignment_id == "bad":
            raise RuntimeError("PRIVATE_PLANNER_ERROR")
        return _readiness(
            ShareResultsNextStep.REGISTER,
            work=ModuleWorkRef("scoreform", class_id, assignment_id),
        )

    monkeypatch.setattr(provider, "plan_share_results_readiness", fake_plan)

    report = provider.evaluate_scoreform_attention(
        ModuleOperationsRequest(workspace_root=tmp_path)
    )

    assert tuple(summary.code for summary in report.summaries) == (
        "scoreform_results_registration_pending",
    )
    assert report.summaries[0].count == 1
    assert len(report.notices) == 1
    assert report.notices[0].code == "scoreform_attention_partial"
    assert "PRIVATE_PLANNER_ERROR" not in repr(report)


def test_class_scope_passes_only_discovered_class_work_to_planner(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []
    work = ModuleWorkRef("scoreform", "class2", "quiz1")
    monkeypatch.setattr(
        provider,
        "discover_scoreform_class_ids",
        lambda root, requested: (requested,),
    )
    monkeypatch.setattr(
        provider,
        "discover_scoreform_work",
        lambda root, class_id: SimpleNamespace(
            work_refs=(work,),
            warning_count=0,
        ),
    )
    monkeypatch.setattr(
        provider,
        "discover_scan_review_items",
        lambda root, **kwargs: SimpleNamespace(items=(), warning_count=0),
    )

    def fake_plan(root, class_id, assignment_id):
        calls.append((class_id, assignment_id))
        return _readiness(ShareResultsNextStep.ALREADY_CURRENT, work=work)

    monkeypatch.setattr(provider, "plan_share_results_readiness", fake_plan)

    report = provider.evaluate_scoreform_attention(
        ModuleOperationsRequest(
            workspace_root=tmp_path,
            class_id="class2",
        )
    )

    assert calls == [("class2", "quiz1")]
    assert report.summaries == ()
