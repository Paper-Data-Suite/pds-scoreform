from __future__ import annotations

import csv

from scoreform.results import (
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
