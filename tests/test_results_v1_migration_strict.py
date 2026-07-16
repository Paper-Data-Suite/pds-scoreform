from __future__ import annotations

import csv
from collections.abc import Callable

import pytest

from scoreform.folders import setup_assignment_folder
from scoreform.page_scoring import ScoredAnswer
from scoreform.results import ScoreFormRoutedResult, _export_result_models
from scoreform.work_paths import scoreform_work_paths

V1_HEADERS = [
    "Page", "class_id", "assignment_id", "student_id", "last_name",
    "first_name", "period", "source_file", "attempt_number",
    "scan_timestamp", "Score", "Total", "Q1", "Q1_Correct",
    "Q2", "Q2_Correct",
]


def _setup(tmp_path):
    roster = {"class_id": "class1", "students": [{
        "student_id": "1001", "last_name": "Doe", "first_name": "Jane", "period": "1",
    }]}
    assignment = {
        "assignment_id": "quiz", "title": "Quiz", "question_count": 2,
        "choices": ["A", "B", "C", "D"], "answer_key": {"1": "A", "2": "B"},
        "standards": {"1": [], "2": []},
    }
    assert setup_assignment_folder(roster, assignment, workspace_root=tmp_path)
    return scoreform_work_paths(tmp_path, "class1", "quiz").results_path


def _row(**changes):
    row = {
        "Page": "1", "class_id": "class1", "assignment_id": "quiz",
        "student_id": "1001", "last_name": "Stored", "first_name": "Name",
        "period": "9", "source_file": "old.pdf", "attempt_number": "2",
        "scan_timestamp": "2026-01-01 10:00:00", "Score": "1", "Total": "2",
        "Q1": "A", "Q1_Correct": "True", "Q2": "D", "Q2_Correct": "False",
    }
    row.update(changes)
    return row


def _manual():
    return ScoreFormRoutedResult(
        "plain_paper_manual", "class1", "quiz", "1001", "Doe", "Jane", "1",
        "manual", 2, 2,
        (ScoredAnswer(1, "A", True), ScoredAnswer(2, "B", True)),
        source_file="plain_paper_manual_entry",
    )


def _write(path, row, headers=V1_HEADERS):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerow(row)


def test_valid_scanned_and_manual_v1_rows_preserve_display_and_timestamp(tmp_path):
    path = _setup(tmp_path)
    _write(path, _row())
    batch = _export_result_models((_manual(),), workspace_root=tmp_path)
    assert batch.appended_attempts[0].attempt_number == 3
    with path.open(newline="", encoding="utf-8") as handle:
        migrated = list(csv.DictReader(handle))
    assert migrated[0]["result_origin"] == "legacy_scan"
    assert migrated[0]["last_name"] == "Stored"
    assert migrated[0]["Page"] == "1"
    assert migrated[0]["source_file"] == "old.pdf"
    assert migrated[0]["scan_timestamp"] == "2026-01-01 10:00:00"
    assert migrated[0]["page_ids"] == "[]"

    path.unlink()
    _write(path, _row(
        Page="manual", source_file="plain_paper_manual_entry",
        scan_timestamp="2026-01-01T10:00:00+00:00",
    ))
    assert _export_result_models((_manual(),), workspace_root=tmp_path).succeeded
    with path.open(newline="", encoding="utf-8") as handle:
        assert next(csv.DictReader(handle))["result_origin"] == "plain_paper_manual"


@pytest.mark.parametrize(
    ("page", "source_file", "expected_origin"),
    (
        ("1", "old.pdf", "legacy_scan"),
        ("manual", "plain_paper_manual_entry", "plain_paper_manual"),
    ),
)
def test_historical_timestamp_survives_migration_and_every_later_append(
    tmp_path, page, source_file, expected_origin
):
    path = _setup(tmp_path)
    historical = "2026-01-01 10:00:00"
    _write(path, _row(Page=page, source_file=source_file, scan_timestamp=historical))

    first = _export_result_models((_manual(),), workspace_root=tmp_path)
    assert first.succeeded
    assert first.appended_attempts[0].attempt_number == 3
    with path.open(newline="", encoding="utf-8") as handle:
        migrated = list(csv.DictReader(handle))
    assert migrated[0]["result_origin"] == expected_origin
    assert migrated[0]["scan_timestamp"] == historical

    second = _export_result_models((_manual(),), workspace_root=tmp_path)
    assert second.succeeded
    assert second.appended_attempts[0].attempt_number == 4
    with path.open(newline="", encoding="utf-8") as handle:
        appended = list(csv.DictReader(handle))
    assert appended[0]["scan_timestamp"] == historical
    assert [row["attempt_number"] for row in appended] == ["2", "3", "4"]


@pytest.mark.parametrize(
    "change",
    (
        {"attempt_number": "0"}, {"attempt_number": "01"},
        {"Score": "bad"}, {"Score": "3"},
        {"Score": "0"}, {"Q1": "Z"},
        {"Q2": ""}, {"Q2_Correct": ""},
        {"scan_timestamp": ""}, {"scan_timestamp": "not-a-time"},
        {"class_id": "other"}, {"assignment_id": "other"},
        {"Total": "1", "Q2": "D", "Q2_Correct": "False"},
    ),
)
def test_invalid_v1_row_aborts_without_changing_original(tmp_path, change):
    path = _setup(tmp_path)
    _write(path, _row(**change))
    before = path.read_bytes()
    batch = _export_result_models((_manual(),), workspace_root=tmp_path)
    assert batch.failures
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "writer",
    (
        lambda path: path.write_text("wrong,header\n1,2\n", encoding="utf-8"),
        lambda path: path.write_text(
            "Page,Page,class_id\n1,1,class1\n", encoding="utf-8"
        ),
        lambda path: path.write_text(
            ','.join(V1_HEADERS) + '\n"unterminated', encoding="utf-8"
        ),
        lambda path: path.write_bytes(b"\xff\xfe\x00"),
    ),
)
def test_invalid_v1_file_shape_preserves_original(
    tmp_path, writer: Callable
):
    path = _setup(tmp_path)
    writer(path)
    before = path.read_bytes()
    batch = _export_result_models((_manual(),), workspace_root=tmp_path)
    assert batch.failures
    assert path.read_bytes() == before
