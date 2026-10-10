"""Issue #227 Hardening C: CSV presentation cannot turn text into formulas."""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone

import pytest

from scoreform.csv_spreadsheet_safety import spreadsheet_safe_cell
from scoreform.page_scoring import ScoredAnswer
from scoreform.results import (
    ScoreFormRoutedResult,
    ScoreFormRoutedResultHistoryRow,
    export_to_csv,
)
from scoreform.results_report_csv import _csv_bytes, render_results_report_csv
from scoreform.results_report_json import render_results_report_json
from scoreform.results_reporting import (
    REPORT_CONFIRMATION_TOKEN,
    confirm_results_report_plan,
    prepare_results_report_plan,
    prepare_results_report_snapshot,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    (
        ("=1+2", "'=1+2"),
        ("+SUM(1,2)", "'+SUM(1,2)"),
        ("-HYPERLINK(\"https://example.invalid\")", "'-HYPERLINK(\"https://example.invalid\")"),
        ("@SUM(A1)", "'@SUM(A1)"),
        ("  =1+2", "'  =1+2"),
        ("\t=1+2", "'\t=1+2"),
        ("\r=1+2", "'\r=1+2"),
        ("\n=1+2", "'\n=1+2"),
        ("\ufeff=1+2", "'\ufeff=1+2"),
        ("\u200b@SUM(A1)", "'\u200b@SUM(A1)"),
        ("\x00=1+2", "'\x00=1+2"),
        (" \x00=1+2", "' \x00=1+2"),
        ("\u200b\t=1+2", "'\u200b\t=1+2"),
        ("\x1bNormal", "'\x1bNormal"),
        ("\tNormal", "'\tNormal"),
        ("-123", "'-123"),
        ("=HYPERLINK(\"https://example.invalid\",\"click\")", "'=HYPERLINK(\"https://example.invalid\",\"click\")"),
    ),
)
def test_formula_and_control_prefixes_are_escaped(raw: str, expected: str) -> None:
    assert spreadsheet_safe_cell(raw) == expected
    assert spreadsheet_safe_cell(expected) == expected


@pytest.mark.parametrize(
    "value",
    ("Doe, Jane", 'Doe, "Jane"', "A+B", "Name - Addition", "", " Safe", "Café José", "'=@already_safe", "2026-2027", "njsls-ela:RL.CR.11-12.1", 0, -5, 1.25, False, None),
)
def test_normal_text_and_nontext_values_stay_exact(value: object) -> None:
    assert spreadsheet_safe_cell(value) == value


def test_generic_csv_serializer_escapes_all_text_columns_but_not_numbers() -> None:
    exported = _csv_bytes(
        ("label", "points", "other"),
        (("=SUM(A1:A2)", -3, "text"), ("Normal", 0, "\ufeff+CMD")),
    )
    rows = list(csv.DictReader(io.StringIO(exported.decode("utf-8"))))
    assert rows == [
        {"label": "'=SUM(A1:A2)", "points": "-3", "other": "text"},
        {"label": "Normal", "points": "0", "other": "'\ufeff+CMD"},
    ]
    assert exported == _csv_bytes(
        ("label", "points", "other"),
        (("=SUM(A1:A2)", -3, "text"), ("Normal", 0, "\ufeff+CMD")),
    )


def _confirmed(scope: str):
    assignment = {
        "assignment_id": "unit_quiz",
        "title": '=HYPERLINK("https://example.invalid","click")',
        "question_count": 1,
        "choices": ["A", "B", "C", "D"],
        "answer_key": {1: "A"},
        "standards": {"1": []},
    }
    result = ScoreFormRoutedResult(
        "plain_paper_manual",
        "class_a",
        "unit_quiz",
        "student_a",
        "=SUM(1,2)",
        "Jane",
        "1",
        "manual",
        1,
        1,
        (ScoredAnswer(1, "A", True),),
        source_file="plain_paper_manual_entry",
    )
    rows = (ScoreFormRoutedResultHistoryRow(result, 1, "2026-10-01T00:00:00+00:00"),)
    snapshot = prepare_results_report_snapshot(
        rows,
        assignment,
        class_id="class_a",
        scope=scope,
        generated_at=datetime(2026, 10, 10, tzinfo=timezone.utc),
        **({"student_id": "student_a", "attempt_number": 1} if scope == "student_detail" else {}),
    )
    confirmed = confirm_results_report_plan(
        prepare_results_report_plan(snapshot, output_format="csv"),
        REPORT_CONFIRMATION_TOKEN,
    )
    assert confirmed is not None
    return confirmed, snapshot


@pytest.mark.parametrize("scope", ("class_analysis", "student_detail"))
def test_live_report_paths_escape_names_titles_without_mutating_models(scope: str) -> None:
    confirmed, snapshot = _confirmed(scope)
    report = render_results_report_csv(confirmed)
    metadata = list(csv.DictReader(io.StringIO(report.artifact("report_metadata.csv").content.decode("utf-8"))))
    assert next(r["value"] for r in metadata if r["field"] == "assignment_title") == (
        "'=HYPERLINK(\"https://example.invalid\",\"click\")"
    )
    overview = list(csv.DictReader(io.StringIO(report.artifact("assignment_overview.csv").content.decode("utf-8"))))
    assert overview[0]["name"] == "'=SUM(1,2), Jane"
    assert overview[0]["score"] == "1"
    assert snapshot.assignment.title.startswith("=")
    if scope == "class_analysis":
        assert snapshot.class_analysis is not None
        assert snapshot.class_analysis.students[0].last_name == "=SUM(1,2)"


def test_json_report_remains_exact_unescaped() -> None:
    confirmed, snapshot = _confirmed("class_analysis")
    json_confirmed = confirm_results_report_plan(
        prepare_results_report_plan(snapshot, output_format="json"),
        REPORT_CONFIRMATION_TOKEN,
    )
    assert json_confirmed is not None
    doc = json.loads(render_results_report_json(json_confirmed).artifacts[0].content)
    assert doc["assignment"]["title"] == '=HYPERLINK("https://example.invalid","click")'
    assert doc["class_analysis"]["assignment_overview"][0]["name"] == "=SUM(1,2), Jane"


def test_legacy_manual_export_escapes_text_and_preserves_numeric_cells(tmp_path) -> None:
    path = tmp_path / "manual_report.csv"
    sample = [{
        "page_num": 1,
        "class_id": "class_a",
        "assignment_id": "unit_quiz",
        "student_id": "=HYPERLINK(\"https://example.invalid\")",
        "source_file": "+cmd.txt",
        "score": 1,
        "total_points": 2,
        "answers": [
            {"Q": 1, "Answer": "@SUM(1,2)", "Correct": True},
            {"Q": 2, "Answer": "B", "Correct": False},
        ],
    }]
    assert export_to_csv(sample, path, workspace_root=tmp_path)
    with path.open(newline="", encoding="utf-8") as handle:
        row = next(csv.DictReader(handle))
    assert row["student_id"] == "'=HYPERLINK(\"https://example.invalid\")"
    assert row["source_file"] == "'+cmd.txt"
    assert row["Q1"] == "'@SUM(1,2)"
    assert row["Q2"] == "B"
    assert row["Score"] == "1"
    assert row["Total"] == "2"
    assert sample[0]["student_id"].startswith("=")
    assert sample[0]["answers"][0]["Answer"].startswith("@")
