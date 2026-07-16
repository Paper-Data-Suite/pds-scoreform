import csv

import pytest

from scoreform import results_viewer
from scoreform.page_scoring import ScoredAnswer
from scoreform.results import (
    ScoreFormRoutedResult,
    ScoreFormRoutedResultHistoryRow,
    _export_result_models,
)


def _manual(*, score=1, student_id="1001"):
    selected = "A" if score else "B"
    return ScoreFormRoutedResult(
        "plain_paper_manual",
        "class1",
        "quiz1",
        student_id,
        "Doe",
        "Jane",
        "1",
        "manual",
        score,
        1,
        (ScoredAnswer(1, selected, bool(score)),),
        source_file="plain_paper_manual_entry",
    )


def _write_current_history(path):
    first = _export_result_models(
        (_manual(score=0),),
        workspace_root=path.parent,
        explicit_output_file=path,
    )
    second = _export_result_models(
        (_manual(score=1),),
        workspace_root=path.parent,
        explicit_output_file=path,
    )
    assert first.succeeded and second.succeeded


def test_viewer_loads_strict_v2_and_summarizes_current_attempts(tmp_path):
    path = tmp_path / "results.csv"
    _write_current_history(path)

    rows = results_viewer.load_assignment_results(path)
    assert all(isinstance(row, ScoreFormRoutedResultHistoryRow) for row in rows)
    summary = results_viewer.summarize_assignment_results(rows)

    assert len(summary) == 1
    assert summary[0] == results_viewer.AssignmentResultSummary(
        "1001", "Doe, Jane", "1", "1", 2
    )
    assert results_viewer.MULTIPLE_ATTEMPTS_NOTE in (
        results_viewer.format_assignment_results_table(summary)
    )


def test_viewer_uses_shared_strict_history_loader(tmp_path, monkeypatch):
    path = tmp_path / "results.csv"
    _write_current_history(path)
    calls = []
    actual = results_viewer.load_routed_results_history

    def tracked(selected):
        calls.append(selected)
        return actual(selected)

    monkeypatch.setattr(results_viewer, "load_routed_results_history", tracked)
    results_viewer.load_assignment_results(path)
    assert calls == [path]


@pytest.mark.parametrize(
    "contents",
    (
        "student_id,Score,Total\n1001,1,1\n",
        "Student ID,Last Name,First Name,score,Total Points,timestamp\n"
        "1001,Doe,Jane,1,1,2026-07-15 12:00:00\n",
        "Page,class_id,assignment_id,student_id,last_name,first_name,period,"
        "source_file,attempt_number,scan_timestamp,Score,Total,Q1,Q1_Correct\n"
        "1,class1,quiz1,1001,Doe,Jane,1,old.pdf,1,"
        "2026-07-15 12:00:00,1,1,A,True\n",
    ),
)
def test_viewer_rejects_historical_headers_without_mutation(tmp_path, contents):
    path = tmp_path / "results.csv"
    path.write_text(contents, encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(results_viewer.ResultsViewError):
        results_viewer.load_assignment_results(path)
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("scan_timestamp", "2026-07-15 12:00:00"),
        ("result_origin", "legacy_scan"),
        ("result_schema_version", "1"),
    ),
)
def test_viewer_rejects_invalid_current_rows_without_mutation(tmp_path, field, value):
    path = tmp_path / "results.csv"
    _write_current_history(path)
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        names = reader.fieldnames
    assert names is not None
    rows[0][field] = value
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=names)
        writer.writeheader()
        writer.writerows(rows)
    before = path.read_bytes()

    with pytest.raises(results_viewer.ResultsViewError):
        results_viewer.load_assignment_results(path)
    assert path.read_bytes() == before


def test_viewer_reports_missing_empty_and_malformed_files(tmp_path):
    with pytest.raises(FileNotFoundError):
        results_viewer.load_assignment_results(tmp_path / "missing.csv")

    empty = tmp_path / "empty.csv"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(results_viewer.ResultsViewError):
        results_viewer.load_assignment_results(empty)

    malformed = tmp_path / "malformed.csv"
    malformed.write_text("student_id,Score\n1001,1,extra\n", encoding="utf-8")
    with pytest.raises(results_viewer.ResultsViewError):
        results_viewer.load_assignment_results(malformed)


def test_summarizer_rejects_unvalidated_mapping_rows():
    with pytest.raises(results_viewer.ResultsViewError):
        results_viewer.summarize_assignment_results([{"student_id": "1001"}])
