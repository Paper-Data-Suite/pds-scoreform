"""Issue #193 Slice 3 current scan-review attention tests."""

from __future__ import annotations

from types import MappingProxyType, SimpleNamespace

import pytest
from pds_core.module_operations import ModuleOperationsRequest
from pds_core.routing_models import ModuleWorkRef

import scoreform.attention_provider as provider
from scoreform.attention_scan import project_scan_attention_fact


def _review_item(
    *,
    core_category: str,
    detail_category: str | None = None,
    identity_source: str = "none",
    class_id: str | None = None,
    assignment_id: str | None = None,
):
    details = None
    if detail_category is not None:
        details = SimpleNamespace(
            scoreform_category=detail_category,
            context=MappingProxyType({}),
            diagnostic_paths=(),
        )
    identity = SimpleNamespace(
        source=identity_source,
        class_id=class_id,
        assignment_id=assignment_id,
    )
    return SimpleNamespace(
        failure_category=core_category,
        scoreform_failure_category=detail_category,
        source_scan_id=None,
        retained_source_path=None,
        details=details,
        identity=identity,
    )


def test_scan_attention_reuses_public_incomplete_attempt_family() -> None:
    item = _review_item(
        core_category="page_conflict",
        detail_category="missing_pages",
    )

    fact = project_scan_attention_fact(item)

    assert fact.code == "scoreform_incomplete_attempt"
    assert fact.class_id is None
    assert fact.work_ref is None


@pytest.mark.parametrize(
    "core_category",
    [
        "payload_missing",
        "route_unknown",
        "module_profile_incompatible",
        "evidence_write_failed",
    ],
)
def test_non_incomplete_teacher_families_share_general_scan_attention(
    core_category: str,
) -> None:
    fact = project_scan_attention_fact(
        _review_item(core_category=core_category)
    )

    assert fact.code == "scoreform_scan_review"


def test_only_validated_identity_becomes_unscoped_shared_context() -> None:
    validated = project_scan_attention_fact(
        _review_item(
            core_category="payload_missing",
            identity_source="validated_locator",
            class_id="class1",
            assignment_id="quiz1",
        )
    )
    diagnostic_only = project_scan_attention_fact(
        _review_item(
            core_category="payload_missing",
            identity_source="scoreform_diagnostic",
            class_id="class1",
            assignment_id="quiz1",
        )
    )

    assert validated.class_id == "class1"
    assert validated.work_ref == ModuleWorkRef(
        "scoreform",
        "class1",
        "quiz1",
    )
    assert diagnostic_only.class_id is None
    assert diagnostic_only.work_ref is None


def test_provider_partitions_incomplete_and_other_scan_attention(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    incomplete = _review_item(
        core_category="page_conflict",
        detail_category="missing_pages",
    )
    ordinary = _review_item(core_category="payload_missing")
    calls = []

    def fake_discover(root, **kwargs):
        calls.append((root, kwargs))
        return SimpleNamespace(
            items=(incomplete, ordinary),
            warning_count=0,
        )

    monkeypatch.setattr(provider, "discover_scan_review_items", fake_discover)

    report = provider.evaluate_scoreform_attention(
        ModuleOperationsRequest(
            workspace_root=tmp_path,
            class_id="class1",
        )
    )

    assert calls == [(tmp_path.resolve(), {"class_id": "class1"})]
    assert tuple(summary.code for summary in report.summaries) == (
        "scoreform_incomplete_attempt",
        "scoreform_scan_review",
    )
    assert tuple(summary.count for summary in report.summaries) == (1, 1)
    assert all(summary.class_id == "class1" for summary in report.summaries)
    assert all(summary.work_ref is None for summary in report.summaries)
    assert tuple(
        summary.action.action_id
        for summary in report.summaries
        if summary.action is not None
    ) == ("open_scan_review", "open_scan_review")


def test_provider_uses_default_open_review_discovery_semantics(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_kwargs = []

    def fake_discover(root, **kwargs):
        observed_kwargs.append(kwargs)
        return SimpleNamespace(items=(), warning_count=0)

    monkeypatch.setattr(provider, "discover_scan_review_items", fake_discover)

    report = provider.evaluate_scoreform_attention(
        ModuleOperationsRequest(workspace_root=tmp_path)
    )

    assert report.evaluation == "evaluated"
    assert observed_kwargs == [{"class_id": None}]
    assert "include_resolved" not in observed_kwargs[0]
    assert "status" not in observed_kwargs[0]


def test_scan_discovery_warning_yields_partial_without_raw_detail(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = "PRIVATE_FAILURE_NAME"

    def fake_discover(root, **kwargs):
        _ = (root, kwargs, sentinel)
        return SimpleNamespace(items=(), warning_count=3)

    monkeypatch.setattr(provider, "discover_scan_review_items", fake_discover)

    report = provider.evaluate_scoreform_attention(
        ModuleOperationsRequest(workspace_root=tmp_path)
    )

    assert report.evaluation == "evaluated"
    assert report.summaries == ()
    assert len(report.notices) == 1
    assert report.notices[0].code == "scoreform_attention_partial"
    assert sentinel not in repr(report)


def test_one_unprojectable_scan_item_does_not_erase_valid_attention(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    good = _review_item(core_category="payload_missing")
    bad = SimpleNamespace()

    monkeypatch.setattr(
        provider,
        "discover_scan_review_items",
        lambda root, **kwargs: SimpleNamespace(
            items=(good, bad),
            warning_count=0,
        ),
    )

    report = provider.evaluate_scoreform_attention(
        ModuleOperationsRequest(workspace_root=tmp_path)
    )

    assert tuple(summary.code for summary in report.summaries) == (
        "scoreform_scan_review",
    )
    assert report.summaries[0].count == 1
    assert len(report.notices) == 1
    assert report.notices[0].code == "scoreform_attention_partial"
