import csv

import pytest

from scoreform import results_viewer


def _write_results(path, rows, fieldnames=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = [
            "Page",
            "class_id",
            "assignment_id",
            "student_id",
            "last_name",
            "first_name",
            "period",
            "source_file",
            "attempt_number",
            "scan_timestamp",
            "Score",
            "Total",
        ]
    with path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_load_assignment_results_reads_valid_results_csv(tmp_path):
    path = (
        tmp_path / "classes" / "english12_p3" / "modules" / "scoreform"
        / "work" / "final_exam" / "results.csv"
    )
    _write_results(
        path,
        [
            {
                "Page": "1",
                "class_id": "english12_p3",
                "assignment_id": "final_exam",
                "student_id": "1001",
                "last_name": "Doe",
                "first_name": "Jane",
                "Score": "13",
                "Total": "15",
            },
        ],
    )

    rows = results_viewer.load_assignment_results(path)

    assert rows[0]["student_id"] == "1001"
    assert rows[0]["Score"] == "13"


def test_format_assignment_results_table_includes_required_columns():
    summary = [
        results_viewer.AssignmentResultSummary(
            student_id="1001",
            name="Doe, Jane",
            recent="13",
            total="15",
            attempts=1,
        ),
    ]

    output = results_viewer.format_assignment_results_table(summary)

    assert "Student ID" in output
    assert "Name" in output
    assert "Recent" in output
    assert "Total" in output
    assert "Attempts" in output
    assert "1001" in output
    assert "Doe, Jane" in output
    assert "13" in output
    assert "15" in output


def test_summarize_groups_attempts_and_uses_latest_parseable_scan_timestamp():
    rows = [
        {
            "student_id": "1001",
            "last_name": "Doe",
            "first_name": "Jane",
            "scan_timestamp": "2026-06-17 08:00:00",
            "Score": "11",
            "Total": "15",
        },
        {
            "student_id": "1001",
            "last_name": "Doe",
            "first_name": "Jane",
            "scan_timestamp": "2026-06-17 09:30:00",
            "Score": "13",
            "Total": "15",
        },
        {
            "student_id": "1002",
            "last_name": "Smith",
            "first_name": "John",
            "scan_timestamp": "2026-06-17 08:15:00",
            "Score": "12",
            "Total": "15",
        },
    ]

    summary = results_viewer.summarize_assignment_results(rows)

    assert [(row.student_id, row.recent, row.total, row.attempts) for row in summary] == [
        ("1001", "13", "15", 2),
        ("1002", "12", "15", 1),
    ]


def test_summarize_falls_back_to_last_row_when_timestamp_is_unreliable():
    rows = [
        {
            "student_id": "1001",
            "last_name": "Doe",
            "first_name": "Jane",
            "scan_timestamp": "not a timestamp",
            "Score": "9",
            "Total": "15",
        },
        {
            "student_id": "1001",
            "last_name": "Doe",
            "first_name": "Jane",
            "scan_timestamp": "",
            "Score": "12",
            "Total": "15",
        },
    ]

    summary = results_viewer.summarize_assignment_results(rows)

    assert len(summary) == 1
    assert summary[0].recent == "12"
    assert summary[0].attempts == 2


def test_summarize_falls_back_to_last_row_when_timestamp_reliability_is_mixed():
    rows = [
        {
            "student_id": "1001",
            "last_name": "Doe",
            "first_name": "Jane",
            "scan_timestamp": "2026-06-17 08:00:00",
            "Score": "10",
            "Total": "15",
        },
        {
            "student_id": "1001",
            "last_name": "Doe",
            "first_name": "Jane",
            "scan_timestamp": "",
            "Score": "13",
            "Total": "15",
        },
    ]

    summary = results_viewer.summarize_assignment_results(rows)

    assert len(summary) == 1
    assert summary[0].recent == "13"
    assert summary[0].attempts == 2


def test_summarize_compares_timezone_aware_and_historical_timestamps():
    rows = [
        {"student_id": "1001", "scan_timestamp": "2026-06-17 09:00:00", "Score": "9", "Total": "10"},
        {"student_id": "1001", "scan_timestamp": "2026-06-17T10:00:00+00:00", "Score": "10", "Total": "10"},
    ]
    assert results_viewer.summarize_assignment_results(rows)[0].recent == "10"


def test_format_includes_multiple_attempt_note_when_any_student_has_duplicates():
    output = results_viewer.format_assignment_results_table([
        results_viewer.AssignmentResultSummary("1001", "Doe, Jane", "12", "15", 2),
    ])

    assert results_viewer.MULTIPLE_ATTEMPTS_NOTE in output
    assert "ScoreForm does not decide which attempt counts as the grade." in output


def test_load_assignment_results_reports_missing_empty_and_malformed_files(tmp_path):
    missing = tmp_path / "missing.csv"
    with pytest.raises(FileNotFoundError):
        results_viewer.load_assignment_results(missing)

    empty = tmp_path / "empty.csv"
    empty.write_text("", encoding="utf-8")
    assert results_viewer.load_assignment_results(empty) == []

    malformed = tmp_path / "malformed.csv"
    malformed.write_text("student_id,Score\n1001,12,extra\n", encoding="utf-8")
    with pytest.raises(results_viewer.ResultsViewError):
        results_viewer.load_assignment_results(malformed)


def test_summarize_skips_rows_missing_student_id_without_crashing():
    rows = [
        {"Score": "10", "Total": "15"},
        {"student_id": "1001", "name": "Jane Doe", "score": "12", "total_points": "15"},
    ]

    summary = results_viewer.summarize_assignment_results(rows)

    assert len(summary) == 1
    assert summary[0].student_id == "1001"
    assert summary[0].name == "Jane Doe"
    assert summary[0].recent == "12"
