"""Create-only output custody tests for ScoreForm Issue #217 Slice 7."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from scoreform.page_scoring import ScoredAnswer
from scoreform.results import (
    ScoreFormRoutedResult,
    ScoreFormRoutedResultHistoryRow,
)
from scoreform.results_report_json import render_results_report_json
from scoreform.results_report_output import (
    ResultsReportOutputError,
    install_rendered_results_report,
    plan_results_report_destination,
)
from scoreform.results_reporting import (
    REPORT_CONFIRMATION_TOKEN,
    confirm_results_report_plan,
    prepare_results_report_plan,
    prepare_results_report_snapshot,
)
from scoreform.work_paths import scoreform_work_paths

GENERATED = datetime(2026, 9, 30, 23, 30, 0, tzinfo=timezone.utc)


def _assignment():
    return {
        "assignment_id": "quiz1",
        "title": "Synthetic Assessment",
        "question_count": 2,
        "choices": ["A", "B", "C", "D"],
        "answer_key": {1: "A", 2: "B"},
        "standards": {"1": ["STD.A"], "2": []},
        "standards_profile_id": "synthetic_profile",
    }


def _history():
    scored = (
        ScoredAnswer(1, "A", True),
        ScoredAnswer(2, "BLANK", False),
    )
    result = ScoreFormRoutedResult(
        "plain_paper_manual",
        "class1",
        "quiz1",
        "1001",
        "Doe",
        "Jane",
        "1",
        "manual",
        1,
        2,
        scored,
        source_file="plain_paper_manual_entry",
    )
    return (
        ScoreFormRoutedResultHistoryRow(
            result,
            1,
            "2026-09-30T18:00:00+00:00",
        ),
    )


def _workspace(tmp_path):
    paths = scoreform_work_paths(tmp_path, "class1", "quiz1")
    paths.work_root.mkdir(parents=True)
    paths.assignment_path.write_text("sentinel assignment\n", encoding="utf-8")
    paths.results_path.write_text("sentinel results\n", encoding="utf-8")
    return paths


def _confirmed_json():
    snapshot = prepare_results_report_snapshot(
        _history(),
        _assignment(),
        class_id="class1",
        scope="class_analysis",
        generated_at=GENERATED,
    )
    plan = prepare_results_report_plan(snapshot, output_format="json")
    confirmed = confirm_results_report_plan(
        plan,
        REPORT_CONFIRMATION_TOKEN,
    )
    assert confirmed is not None
    return snapshot, confirmed


def test_destination_is_assignment_local_privacy_minimized_and_zero_write(tmp_path):
    paths = _workspace(tmp_path)
    snapshot, _confirmed = _confirmed_json()
    before = {path.relative_to(tmp_path) for path in tmp_path.rglob("*")}

    destination = plan_results_report_destination(
        tmp_path,
        class_id="class1",
        assignment_id="quiz1",
        snapshot=snapshot,
        output_format="json",
    )

    after = {path.relative_to(tmp_path) for path in tmp_path.rglob("*")}
    assert after == before
    assert destination.workspace_relative_dir.as_posix() == (
        "classes/class1/modules/scoreform/work/quiz1/exports/"
        "results_analysis/class_analysis_json_20260930T233000Z"
    )
    assert "Doe" not in destination.workspace_relative_dir.as_posix()
    assert "Jane" not in destination.workspace_relative_dir.as_posix()
    assert paths.assignment_path.read_text(encoding="utf-8") == "sentinel assignment\n"
    assert paths.results_path.read_text(encoding="utf-8") == "sentinel results\n"


def test_install_is_create_only_and_changes_only_report_destination(tmp_path):
    paths = _workspace(tmp_path)
    snapshot, confirmed = _confirmed_json()
    destination = plan_results_report_destination(
        tmp_path,
        class_id="class1",
        assignment_id="quiz1",
        snapshot=snapshot,
        output_format="json",
    )
    rendered = render_results_report_json(confirmed)

    installed = install_rendered_results_report(destination, rendered)

    assert installed.workspace_relative_files == (
        destination.workspace_relative_dir / "results_analysis.json",
    )
    target = tmp_path / installed.workspace_relative_files[0]
    assert target.read_bytes() == rendered.artifacts[0].content
    assert paths.assignment_path.read_text(encoding="utf-8") == "sentinel assignment\n"
    assert paths.results_path.read_text(encoding="utf-8") == "sentinel results\n"


def test_existing_report_directory_is_never_overwritten(tmp_path):
    _workspace(tmp_path)
    snapshot, confirmed = _confirmed_json()
    destination = plan_results_report_destination(
        tmp_path,
        class_id="class1",
        assignment_id="quiz1",
        snapshot=snapshot,
        output_format="json",
    )
    destination.report_dir.mkdir(parents=True)
    sentinel = destination.report_dir / "existing.txt"
    sentinel.write_text("keep me\n", encoding="utf-8")

    rendered = render_results_report_json(confirmed)
    with pytest.raises(
        ResultsReportOutputError,
        match="already exists",
    ):
        install_rendered_results_report(destination, rendered)

    assert sentinel.read_text(encoding="utf-8") == "keep me\n"
    assert not (destination.report_dir / "results_analysis.json").exists()


def test_planning_rejects_existing_destination_before_generation(tmp_path):
    _workspace(tmp_path)
    snapshot, _confirmed = _confirmed_json()
    first = plan_results_report_destination(
        tmp_path,
        class_id="class1",
        assignment_id="quiz1",
        snapshot=snapshot,
        output_format="json",
    )
    first.report_dir.mkdir(parents=True)

    with pytest.raises(
        ResultsReportOutputError,
        match="already exists",
    ):
        plan_results_report_destination(
            tmp_path,
            class_id="class1",
            assignment_id="quiz1",
            snapshot=snapshot,
            output_format="json",
        )


def test_destination_rejects_snapshot_identity_mismatch(tmp_path):
    _workspace(tmp_path)
    snapshot, _confirmed = _confirmed_json()

    with pytest.raises(ResultsReportOutputError, match="class does not match"):
        plan_results_report_destination(
            tmp_path,
            class_id="other",
            assignment_id="quiz1",
            snapshot=snapshot,
            output_format="json",
        )

    with pytest.raises(ResultsReportOutputError, match="assignment does not match"):
        plan_results_report_destination(
            tmp_path,
            class_id="class1",
            assignment_id="other",
            snapshot=snapshot,
            output_format="json",
        )
