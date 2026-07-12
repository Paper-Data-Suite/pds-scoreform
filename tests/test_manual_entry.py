import csv

import pytest

from scoreform.manual_entry import (
    MANUAL_ENTRY_PAGE,
    MANUAL_ENTRY_SOURCE,
    build_manual_result,
    is_manual_entry_cancel,
    normalize_manual_response,
)
from scoreform.results import export_routed_results


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        ("A", "A"), (" b ", "B"), ("c", "C"), ("D", "D"),
        ("blank", "BLANK"), ("BL", "BLANK"), ("empty", "BLANK"),
        ("ambiguous", "AMBIGUOUS"), ("amb", "AMBIGUOUS"),
        ("double", "AMBIGUOUS"),
    ],
)
def test_normalize_manual_response(raw_value, expected):
    assert normalize_manual_response(raw_value, ["A", "B", "C", "D"]) == expected


def test_normalize_manual_response_rejects_invalid_values():
    assert normalize_manual_response("E", ["A", "B", "C", "D"]) is None
    assert normalize_manual_response("", ["A", "B", "C", "D"]) is None


@pytest.mark.parametrize("raw_value", ["q", " QUIT ", "Cancel"])
def test_manual_entry_cancel_values(raw_value):
    assert is_manual_entry_cancel(raw_value)


def test_b_is_an_answer_not_cancel():
    assert normalize_manual_response("b") == "B"
    assert not is_manual_entry_cancel("b")


def _assignment():
    return {
        "assignment_id": "quiz",
        "title": "Quiz",
        "question_count": 4,
        "choices": ["A", "B", "C", "D"],
        "answer_key": {1: "A", 2: "B", 3: "C", 4: "D"},
    }


def test_build_manual_result_scores_and_preserves_all_questions():
    result = build_manual_result(
        class_id="class_a",
        assignment=_assignment(),
        student={"student_id": "0001"},
        responses={1: "A", 2: "BLANK", 3: "AMBIGUOUS", 4: "D"},
    )

    assert result["page_num"] == MANUAL_ENTRY_PAGE
    assert result["source_file"] == MANUAL_ENTRY_SOURCE
    assert result["class_id"] == "class_a"
    assert result["assignment_id"] == "quiz"
    assert result["student_id"] == "0001"
    assert result["score"] == 2
    assert result["total_points"] == 4
    assert result["answers"] == [
        {"Q": 1, "Answer": "A", "Correct": True},
        {"Q": 2, "Answer": "BLANK", "Correct": False},
        {"Q": 3, "Answer": "AMBIGUOUS", "Correct": False},
        {"Q": 4, "Answer": "D", "Correct": True},
    ]


def test_manual_result_uses_routed_export_and_attempt_numbering(tmp_path):
    class_dir = tmp_path / "classes" / "class_a"
    assignment_dir = class_dir / "assignments" / "quiz"
    assignment_dir.mkdir(parents=True)
    (class_dir / "roster.csv").write_text(
        "class_id,student_id,last_name,first_name,period\n"
        "class_a,0001,Johnson,Mack,2\n",
        encoding="utf-8",
    )
    manual_result = build_manual_result(
        class_id="class_a",
        assignment=_assignment(),
        student={"student_id": "0001"},
        responses={1: "A", 2: "B", 3: "C", 4: "D"},
    )
    scanned_result = dict(manual_result, page_num=1, source_file="scan.pdf")

    assert export_routed_results([scanned_result], workspace_root=tmp_path)
    assert export_routed_results([manual_result], workspace_root=tmp_path)
    with (assignment_dir / "results.csv").open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        rows = list(reader)
        headers = reader.fieldnames

    assert rows[1]["Page"] == "manual"
    assert rows[1]["source_file"] == "plain_paper_manual_entry"
    assert rows[1]["attempt_number"] == "2"
    assert rows[1]["last_name"] == "Johnson"
    assert rows[1]["first_name"] == "Mack"
    assert rows[1]["period"] == "2"
    assert headers == [
        "Page", "class_id", "assignment_id", "student_id", "last_name",
        "first_name", "period", "source_file", "attempt_number",
        "scan_timestamp", "Score", "Total", "Q1", "Q1_Correct", "Q2",
        "Q2_Correct", "Q3", "Q3_Correct", "Q4", "Q4_Correct",
    ]
