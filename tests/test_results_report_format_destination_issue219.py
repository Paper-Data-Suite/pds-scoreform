"""Issue #219 Slice 3: format-aware Results Report destination identity."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from scoreform.page_scoring import ScoredAnswer
from scoreform.results import (
    ScoreFormRoutedResult,
    ScoreFormRoutedResultHistoryRow,
)
from scoreform.results_report_csv import render_results_report_csv
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

GENERATED = datetime(2026, 10, 1, 22, 0, 0, tzinfo=timezone.utc)


def _assignment() -> dict[str, object]:
    return {
        "assignment_id": "quiz1",
        "title": "Format-Aware Report Destination",
        "question_count": 2,
        "choices": ["A", "B", "C", "D"],
        "answer_key": {1: "A", 2: "B"},
        "standards": {"1": ["STD.A"], "2": []},
    }


def _history() -> tuple[ScoreFormRoutedResultHistoryRow, ...]:
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
            "2026-10-01T20:00:00+00:00",
        ),
    )


def _workspace(tmp_path):
    paths = scoreform_work_paths(tmp_path, "class1", "quiz1")
    paths.work_root.mkdir(parents=True)
    return paths


def _snapshot():
    return prepare_results_report_snapshot(
        _history(),
        _assignment(),
        class_id="class1",
        scope="class_analysis",
        generated_at=GENERATED,
    )


def _confirmed(snapshot, output_format):
    plan = prepare_results_report_plan(
        snapshot,
        output_format=output_format,
    )
    confirmed = confirm_results_report_plan(
        plan,
        REPORT_CONFIRMATION_TOKEN,
    )
    assert confirmed is not None
    return confirmed


def test_cross_format_same_second_destinations_are_distinct_and_zero_write(tmp_path):
    _workspace(tmp_path)
    snapshot = _snapshot()
    before = {path.relative_to(tmp_path) for path in tmp_path.rglob("*")}

    csv_destination = plan_results_report_destination(
        tmp_path,
        class_id="class1",
        assignment_id="quiz1",
        snapshot=snapshot,
        output_format="csv",
    )
    json_destination = plan_results_report_destination(
        tmp_path,
        class_id="class1",
        assignment_id="quiz1",
        snapshot=snapshot,
        output_format="json",
    )
    pdf_destination = plan_results_report_destination(
        tmp_path,
        class_id="class1",
        assignment_id="quiz1",
        snapshot=snapshot,
        output_format="pdf",
    )

    assert csv_destination.report_dir != json_destination.report_dir
    assert json_destination.report_dir != pdf_destination.report_dir
    assert csv_destination.workspace_relative_dir.as_posix().endswith(
        "results_analysis/class_analysis_csv_20261001T220000Z"
    )
    assert json_destination.workspace_relative_dir.as_posix().endswith(
        "results_analysis/class_analysis_json_20261001T220000Z"
    )
    assert pdf_destination.workspace_relative_dir.as_posix().endswith(
        "results_analysis/class_analysis_pdf_20261001T220000Z"
    )
    assert csv_destination.output_format == "csv"
    assert json_destination.output_format == "json"
    assert pdf_destination.output_format == "pdf"
    assert {path.relative_to(tmp_path) for path in tmp_path.rglob("*")} == before


def test_existing_json_same_second_does_not_block_csv_same_second(tmp_path):
    _workspace(tmp_path)
    snapshot = _snapshot()

    json_destination = plan_results_report_destination(
        tmp_path,
        class_id="class1",
        assignment_id="quiz1",
        snapshot=snapshot,
        output_format="json",
    )
    json_confirmed = _confirmed(snapshot, "json")
    install_rendered_results_report(
        json_destination,
        render_results_report_json(json_confirmed),
    )

    csv_destination = plan_results_report_destination(
        tmp_path,
        class_id="class1",
        assignment_id="quiz1",
        snapshot=snapshot,
        output_format="csv",
    )

    assert not csv_destination.report_dir.exists()
    assert csv_destination.report_dir.name == (
        "class_analysis_csv_20261001T220000Z"
    )


def test_same_format_same_second_still_fails_without_suffix_or_timestamp_change(
    tmp_path,
):
    _workspace(tmp_path)
    snapshot = _snapshot()

    first = plan_results_report_destination(
        tmp_path,
        class_id="class1",
        assignment_id="quiz1",
        snapshot=snapshot,
        output_format="json",
    )
    first.report_dir.mkdir(parents=True)

    with pytest.raises(ResultsReportOutputError, match="already exists"):
        plan_results_report_destination(
            tmp_path,
            class_id="class1",
            assignment_id="quiz1",
            snapshot=snapshot,
            output_format="json",
        )

    siblings = tuple(path.name for path in first.report_dir.parent.iterdir())
    assert siblings == ("class_analysis_json_20261001T220000Z",)


def test_install_rejects_rendered_format_mismatch(tmp_path):
    _workspace(tmp_path)
    snapshot = _snapshot()

    csv_destination = plan_results_report_destination(
        tmp_path,
        class_id="class1",
        assignment_id="quiz1",
        snapshot=snapshot,
        output_format="csv",
    )
    json_confirmed = _confirmed(snapshot, "json")
    rendered_json = render_results_report_json(json_confirmed)

    with pytest.raises(
        ResultsReportOutputError,
        match="format does not match",
    ):
        install_rendered_results_report(
            csv_destination,
            rendered_json,
        )

    assert not csv_destination.report_dir.exists()


def test_matching_csv_destination_installs_normally(tmp_path):
    _workspace(tmp_path)
    snapshot = _snapshot()

    destination = plan_results_report_destination(
        tmp_path,
        class_id="class1",
        assignment_id="quiz1",
        snapshot=snapshot,
        output_format="csv",
    )
    confirmed = _confirmed(snapshot, "csv")
    installed = install_rendered_results_report(
        destination,
        render_results_report_csv(confirmed),
    )

    assert installed.destination.output_format == "csv"
    assert installed.destination.report_dir.name == (
        "class_analysis_csv_20261001T220000Z"
    )
    assert len(installed.workspace_relative_files) == 6
