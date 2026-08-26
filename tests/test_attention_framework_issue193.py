"""Issue #193 Slice 2 attention framework and silent discovery tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pds_core.module_operations import (
    MAX_MODULE_OPERATION_COUNT,
    ModuleOperationsRequest,
)
from pds_core.routing_models import ModuleWorkRef

from scoreform.attention_model import (
    ATTENTION_DEFINITIONS,
    ScoreFormAttentionAccumulator,
    ScoreFormAttentionAggregationError,
)
from scoreform.attention_provider import evaluate_scoreform_attention
from scoreform.attention_work_discovery import discover_scoreform_work

_LAYOUT = "standard_15q_abcd_v1"


def _assignment(assignment_id: str) -> dict[str, object]:
    return {
        "assignment_id": assignment_id,
        "title": "Synthetic Assignment",
        "question_count": 1,
        "choices": ["A", "B", "C", "D"],
        "layout_id": _LAYOUT,
        "answer_key": {"1": "A"},
        "standards": {"1": []},
    }


def _write_assignment(root: Path, class_id: str, assignment_id: str) -> Path:
    work = (
        root
        / "classes"
        / class_id
        / "modules"
        / "scoreform"
        / "work"
        / assignment_id
    )
    work.mkdir(parents=True)
    path = work / "assignment.json"
    path.write_text(
        json.dumps(_assignment(assignment_id), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def test_attention_definition_order_and_actions_are_fixed() -> None:
    assert tuple(definition.code for definition in ATTENTION_DEFINITIONS) == (
        "scoreform_incomplete_attempt",
        "scoreform_scan_review",
        "scoreform_results_registration_pending",
        "scoreform_results_manifest_pending",
        "scoreform_results_publication_pending",
        "scoreform_results_supersession_pending",
        "scoreform_results_publication_recovery",
        "scoreform_results_state_attention",
    )
    assert tuple(definition.action_id for definition in ATTENTION_DEFINITIONS) == (
        "open_scan_review",
        "open_scan_review",
        "open_share_results",
        "open_share_results",
        "open_share_results",
        "open_share_results",
        "open_share_results",
        "open_share_results",
    )


def test_accumulator_single_work_preserves_exact_context() -> None:
    accumulator = ScoreFormAttentionAccumulator()
    work = ModuleWorkRef("scoreform", "class1", "quiz1")
    accumulator.add(
        "scoreform_scan_review",
        2,
        class_id="class1",
        work_ref=work,
    )

    summary = accumulator.summaries(ModuleOperationsRequest())[0]

    assert summary.count == 2
    assert summary.class_id == "class1"
    assert summary.work_ref == work
    assert summary.action is not None
    assert summary.action.module_id == "scoreform"
    assert summary.action.action_id == "open_scan_review"


def test_accumulator_multi_work_keeps_class_but_omits_work() -> None:
    accumulator = ScoreFormAttentionAccumulator()
    for work_id in ("quiz1", "quiz2"):
        accumulator.add(
            "scoreform_results_manifest_pending",
            1,
            class_id="class1",
            work_ref=ModuleWorkRef("scoreform", "class1", work_id),
        )

    summary = accumulator.summaries(ModuleOperationsRequest())[0]

    assert summary.count == 2
    assert summary.class_id == "class1"
    assert summary.work_ref is None


def test_accumulator_multi_class_omits_shared_context() -> None:
    accumulator = ScoreFormAttentionAccumulator()
    for class_id in ("class1", "class2"):
        accumulator.add(
            "scoreform_scan_review",
            1,
            class_id=class_id,
            work_ref=ModuleWorkRef("scoreform", class_id, "quiz1"),
        )

    summary = accumulator.summaries(ModuleOperationsRequest())[0]

    assert summary.count == 2
    assert summary.class_id is None
    assert summary.work_ref is None


def test_accumulator_rejects_cross_class_data_for_class_scoped_request() -> None:
    accumulator = ScoreFormAttentionAccumulator()
    accumulator.add(
        "scoreform_scan_review",
        1,
        class_id="class2",
        work_ref=ModuleWorkRef("scoreform", "class2", "quiz1"),
    )

    with pytest.raises(
        ScoreFormAttentionAggregationError,
        match="requested class scope",
    ):
        accumulator.summaries(ModuleOperationsRequest(class_id="class1"))


def test_accumulator_rejects_unknown_code_and_untruthful_overflow() -> None:
    accumulator = ScoreFormAttentionAccumulator()
    with pytest.raises(ScoreFormAttentionAggregationError, match="Unknown"):
        accumulator.add("scoreform_unknown", 1)

    accumulator.add(
        "scoreform_scan_review",
        MAX_MODULE_OPERATION_COUNT,
        class_id="class1",
    )
    with pytest.raises(ScoreFormAttentionAggregationError, match="bound"):
        accumulator.add(
            "scoreform_scan_review",
            1,
            class_id="class1",
        )


def test_silent_work_discovery_returns_identity_only(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_assignment(tmp_path, "class1", "quiz1")

    discovery = discover_scoreform_work(tmp_path, "class1")

    assert discovery.work_refs == (
        ModuleWorkRef("scoreform", "class1", "quiz1"),
    )
    assert discovery.warning_count == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_malformed_work_is_skipped_silently_and_counted_as_warning(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assignment = _write_assignment(tmp_path, "class1", "bad_quiz")
    assignment.write_text("{not-json", encoding="utf-8")

    discovery = discover_scoreform_work(tmp_path, "class1")

    assert discovery.work_refs == ()
    assert discovery.warning_count == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_provider_reports_partial_for_malformed_workspace_wide_work(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_assignment(tmp_path, "class1", "quiz1")
    malformed = (
        tmp_path
        / "classes"
        / "class1"
        / "modules"
        / "scoreform"
        / "work"
        / "junk.txt"
    )
    malformed.write_text("not managed work\n", encoding="utf-8")

    report = evaluate_scoreform_attention(
        ModuleOperationsRequest(workspace_root=tmp_path)
    )

    assert report.evaluation == "evaluated"
    assert report.summaries == ()
    assert len(report.notices) == 1
    assert report.notices[0].code == "scoreform_attention_partial"
    assert "junk" not in repr(report)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_provider_exact_class_with_no_scoreform_work_is_evaluated_empty(
    tmp_path: Path,
) -> None:
    (tmp_path / "classes" / "class1").mkdir(parents=True)

    report = evaluate_scoreform_attention(
        ModuleOperationsRequest(
            workspace_root=tmp_path,
            class_id="class1",
        )
    )

    assert report.evaluation == "evaluated"
    assert report.summaries == ()
    assert report.notices == ()


def test_provider_exact_class_unsafe_work_collection_is_unavailable(
    tmp_path: Path,
) -> None:
    collection = (
        tmp_path
        / "classes"
        / "class1"
        / "modules"
        / "scoreform"
        / "work"
    )
    collection.parent.mkdir(parents=True)
    collection.write_text("unsafe collection\n", encoding="utf-8")

    report = evaluate_scoreform_attention(
        ModuleOperationsRequest(
            workspace_root=tmp_path,
            class_id="class1",
        )
    )

    assert report.evaluation == "unavailable"
    assert report.summaries == ()
    assert len(report.notices) == 1
    assert report.notices[0].code == "scoreform_attention_unavailable"
    assert str(tmp_path) not in repr(report)
