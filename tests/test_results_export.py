import csv

from scoreform import results


def _routed_result(student_id, answer="A", page_num=1, source_file=None):
    return {
        "page_num": page_num,
        "class_id": "english9_p2",
        "assignment_id": "rj_act1_quiz",
        "student_id": student_id,
        "source_file": source_file or f"{student_id}.pdf",
        "score": 1,
        "total_points": 1,
        "answers": [{"Q": 1, "Answer": answer, "Correct": True}],
    }


def _prepare_routed_assignment(tmp_path, monkeypatch):
    class_dir = tmp_path / "classes" / "english9_p2"
    assignment_dir = class_dir / "assignments" / "rj_act1_quiz"
    assignment_dir.mkdir(parents=True)
    (class_dir / "roster.csv").write_text(
        "class_id,student_id,last_name,first_name,period\n"
        "english9_p2,0001,Alpha,Ada,2\n"
        "english9_p2,0002,Beta,Ben,2\n"
        "english9_p2,0003,Gamma,Gia,2\n"
        "english9_p2,0004,Delta,Dan,2\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    return assignment_dir


def _read_routed_csv(path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


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


def test_routed_results_preserve_existing_rows_and_append(tmp_path, monkeypatch):
    assignment_dir = _prepare_routed_assignment(tmp_path, monkeypatch)
    results_path = assignment_dir / "results.csv"

    assert results.export_routed_results(
        [
            _routed_result("0001", source_file="class_packet.pdf"),
            _routed_result("0002", source_file="class_packet.pdf"),
            _routed_result("0003", source_file="class_packet.pdf"),
        ]
    )
    original_text = results_path.read_text(encoding="utf-8")

    assert results.export_routed_results([_routed_result("0004", source_file="makeup.pdf")])

    rows = _read_routed_csv(results_path)
    assert [row["student_id"] for row in rows] == ["0001", "0002", "0003", "0004"]
    assert rows[-1]["source_file"] == "makeup.pdf"
    assert rows[-1]["attempt_number"] == "1"

    header = original_text.splitlines()[0]
    assert results_path.read_text(encoding="utf-8").splitlines()[0] == header


def test_routed_results_attempt_number_increments_from_existing_rows(tmp_path, monkeypatch):
    assignment_dir = _prepare_routed_assignment(tmp_path, monkeypatch)
    results_path = assignment_dir / "results.csv"

    assert results.export_routed_results([_routed_result("0003", source_file="first.pdf")])
    assert results.export_routed_results([_routed_result("0003", source_file="rescan.pdf")])

    rows = _read_routed_csv(results_path)
    assert [row["student_id"] for row in rows] == ["0003", "0003"]
    assert [row["attempt_number"] for row in rows] == ["1", "2"]
    assert [row["source_file"] for row in rows] == ["first.pdf", "rescan.pdf"]


def test_routed_results_replace_failure_leaves_original_intact(tmp_path, monkeypatch):
    assignment_dir = _prepare_routed_assignment(tmp_path, monkeypatch)
    results_path = assignment_dir / "results.csv"

    assert results.export_routed_results([_routed_result("0001", source_file="first.pdf")])
    original_text = results_path.read_text(encoding="utf-8")

    def fail_replace(src, dst):
        raise PermissionError("locked file")

    monkeypatch.setattr(results.os, "replace", fail_replace)

    assert not results.export_routed_results([_routed_result("0002", source_file="second.pdf")])
    assert results_path.read_text(encoding="utf-8") == original_text
    assert not list(assignment_dir.glob(".results.*.tmp"))


def test_routed_results_header_mismatch_fails_safely(tmp_path, monkeypatch):
    assignment_dir = _prepare_routed_assignment(tmp_path, monkeypatch)
    results_path = assignment_dir / "results.csv"
    original_text = "Page,student_id,Score,Total,Q1,Q1_Correct\n1,0001,1,1,A,True\n"
    results_path.write_text(original_text, encoding="utf-8")

    assert not results.export_routed_results([_routed_result("0002", source_file="new.pdf")])
    assert results_path.read_text(encoding="utf-8") == original_text
