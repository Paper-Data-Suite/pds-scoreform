from __future__ import annotations

import csv
from dataclasses import replace

from scoreform.folders import setup_assignment_folder
from scoreform.page_scoring import ScoredAnswer
from scoreform.results import (
    ScoreFormRoutedResult,
    _export_result_models,
    export_routed_results,
    export_to_csv,
    privacy_safe_source_file,
)


def test_export_to_csv_variable_question_count(tmp_path) -> None:
    output = tmp_path / "results.csv"
    results = [
        {
            "page_num": 1,
            "score": 2,
            "total_points": 2,
            "answers": [
                {"Q": 1, "Answer": "A", "Correct": True},
                {"Q": 2, "Answer": "B", "Correct": True},
            ],
        }
    ]

    assert export_to_csv(results, output)
    with output.open(newline="", encoding="utf-8") as handle:
        row = next(csv.DictReader(handle))
    assert row["Q1"] == "A"
    assert row["Q1_Correct"] == "True"
    assert row["Q2"] == "B"


def test_privacy_safe_source_file_preserves_safe_workspace_relative_path(tmp_path) -> None:
    source = tmp_path / "scans" / "source" / "2026-07-14" / "scan.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"scan")

    assert privacy_safe_source_file(source, tmp_path) == "scans/source/2026-07-14/scan.pdf"
    assert privacy_safe_source_file("../outside.pdf", tmp_path) == "outside.pdf"


def test_routed_results_require_existing_managed_work(tmp_path) -> None:
    assert not export_routed_results(
        [
            {
                "page_num": "manual",
                "class_id": "class1",
                "assignment_id": "quiz",
                "student_id": "1001",
                "score": 0,
                "total_points": 1,
                "answers": [],
            }
        ],
        tmp_path,
    )

    assert list(tmp_path.iterdir()) == []


def test_v2_scan_export_is_idempotent_and_rescan_appends(tmp_path) -> None:
    roster = {"class_id": "class1", "students": [{"student_id": "1001", "last_name": "Doe", "first_name": "Jane", "period": "1"}]}
    assignment = {"assignment_id": "quiz", "title": "Quiz", "question_count": 1, "choices": ["A", "B", "C", "D"], "answer_key": {"1": "A"}, "standards": {"1": []}}
    assert setup_assignment_folder(roster, assignment, workspace_root=tmp_path)
    result = ScoreFormRoutedResult(
        result_origin="pds2_scan", class_id="class1", assignment_id="quiz",
        student_id="1001", last_name="Doe", first_name="Jane", period="1",
        page_display="1", score=1, total_points=1,
        answers=(ScoredAnswer(1, "A", True),), issuance_id="iss_" + "1" * 32,
        generation_id="gen_" + "2" * 32, artifact_id="art_" + "3" * 32,
        page_ids=("pg_" + "4" * 32,), route_ids=("rt_" + "5" * 32,),
        logical_pages=(1,), source_file="scan.png", source_scan_id="scan_one",
        source_page_numbers=(1,),
        retained_source_relative_path="scans/source/2026-07-15/scan.png",
        source_sha256="a" * 64,
    )
    first = _export_result_models((result,), workspace_root=tmp_path)
    retry = _export_result_models((result,), workspace_root=tmp_path)
    rescan = _export_result_models((replace(result, source_scan_id="scan_two"),), workspace_root=tmp_path)
    assert len(first.appended_attempts) == 1
    assert len(retry.already_present_attempts) == 1
    assert rescan.appended_attempts[0].attempt_number == 2

    conflict = _export_result_models(
        (replace(result, score=0, answers=(ScoredAnswer(1, "B", False),)),),
        workspace_root=tmp_path,
    )
    assert conflict.failures


def test_valid_v1_history_migrates_without_fabricated_identity(tmp_path) -> None:
    roster = {"class_id": "class1", "students": [{"student_id": "1001", "last_name": "Doe", "first_name": "Jane", "period": "1"}]}
    assignment = {"assignment_id": "quiz", "title": "Quiz", "question_count": 1, "choices": ["A", "B", "C", "D"], "answer_key": {"1": "A"}, "standards": {"1": []}}
    assert setup_assignment_folder(roster, assignment, workspace_root=tmp_path)
    output = tmp_path / "classes" / "class1" / "modules" / "scoreform" / "work" / "quiz" / "results.csv"
    output.write_text(
        "Page,class_id,assignment_id,student_id,last_name,first_name,period,source_file,attempt_number,scan_timestamp,Score,Total,Q1,Q1_Correct\n"
        "1,class1,quiz,1001,Doe,Jane,1,old.pdf,2,2026-01-01 10:00:00,1,1,A,True\n",
        encoding="utf-8",
    )
    manual = ScoreFormRoutedResult(
        "plain_paper_manual", "class1", "quiz", "1001", "Doe", "Jane", "1",
        "manual", 1, 1, (ScoredAnswer(1, "A", True),),
        source_file="plain_paper_manual_entry",
    )
    batch = _export_result_models((manual,), workspace_root=tmp_path)
    assert batch.appended_attempts[0].attempt_number == 3
    rows = list(csv.DictReader(output.open(newline="", encoding="utf-8")))
    assert rows[0]["result_origin"] == "legacy_scan"
    assert rows[0]["issuance_id"] == ""
    assert rows[0]["page_ids"] == "[]"
