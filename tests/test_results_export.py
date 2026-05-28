import csv

from scoreform import results


def test_export_to_csv_variable_question_count(tmp_path):
    all_results = [
        {
            "page_num": 1,
            "score": 4,
            "total_points": 5,
            "answers": [
                {"Q": i, "Answer": "A", "Correct": i % 2 == 1}
                for i in range(1, 6)
            ],
        }
    ]

    output_file = tmp_path / "results.csv"
    assert results.export_to_csv(all_results, str(output_file))

    with output_file.open(encoding="utf-8") as f:
        header = next(csv.reader(f))

    assert "Q5" in header
    assert "Q5_Correct" in header
    assert "Q6" not in header
    assert "Q6_Correct" not in header
    assert header[-1] == "Q5_Correct"


def test_routed_results_do_not_export_optional_roster_columns(tmp_path, monkeypatch):
    class_dir = tmp_path / "classes" / "english9_p2"
    assignment_dir = class_dir / "assignments" / "rj_act1_quiz"
    assignment_dir.mkdir(parents=True)
    (class_dir / "roster.csv").write_text(
        "class_id,student_id,last_name,first_name,period,preferred_name,email,notes\n"
        "english9_p2,1001,Doe,Jane,2,Janie,jdoe@example.com,extra time\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    all_results = [
        {
            "page_num": 1,
            "class_id": "english9_p2",
            "assignment_id": "rj_act1_quiz",
            "student_id": "1001",
            "source_file": "scan.pdf",
            "score": 1,
            "total_points": 1,
            "answers": [{"Q": 1, "Answer": "A", "Correct": True}],
        }
    ]

    assert results.export_routed_results(all_results)

    with (assignment_dir / "results.csv").open(encoding="utf-8") as f:
        header = next(csv.reader(f))

    assert "last_name" in header
    assert "first_name" in header
    assert "period" in header
    assert "preferred_name" not in header
    assert "email" not in header
    assert "notes" not in header
