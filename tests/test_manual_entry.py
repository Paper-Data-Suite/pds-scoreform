"""Plain-paper result routing uses module-qualified managed work."""

import csv

from scoreform.folders import setup_assignment_folder
from scoreform.results import export_routed_results
from scoreform.work_paths import scoreform_work_paths


def test_manual_entry_routed_export_writes_canonical_results(tmp_path) -> None:
    roster = {
        "class_id": "class1",
        "students": [{
            "student_id": "1001",
            "last_name": "Doe",
            "first_name": "Jane",
            "period": "1",
        }],
    }
    assignment = {
        "assignment_id": "quiz",
        "title": "Quiz",
        "question_count": 1,
        "choices": ["A", "B", "C", "D"],
        "answer_key": {"1": "A"},
        "standards": {"1": []},
    }
    assert setup_assignment_folder(
        roster, assignment, workspace_root=tmp_path
    ) is not None
    result = {
        "page_num": "manual",
        "class_id": "class1",
        "assignment_id": "quiz",
        "student_id": "1001",
        "source_file": "plain_paper_manual_entry",
        "score": 1,
        "total_points": 1,
        "answers": [{"Q": 1, "Answer": "A", "Correct": True}],
    }

    assert export_routed_results([result], workspace_root=tmp_path)
    assert export_routed_results([result], workspace_root=tmp_path)

    output = scoreform_work_paths(tmp_path, "class1", "quiz").results_path
    with output.open(newline="", encoding="utf-8") as results_file:
        rows = list(csv.DictReader(results_file))
    assert [row["student_id"] for row in rows] == ["1001", "1001"]
    assert [row["attempt_number"] for row in rows] == ["1", "2"]
    assert all(row["source_file"] == "plain_paper_manual_entry" for row in rows)
