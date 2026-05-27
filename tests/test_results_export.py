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