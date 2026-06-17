from scoreform import cli, cli_score


def _result():
    return {
        "page_num": 1,
        "class_id": "english9_p2",
        "assignment_id": "rj_act1_quiz",
        "student_id": "1001",
        "score": 1,
        "total_points": 1,
        "answers": [{"Q": 1, "Answer": "A", "Correct": True}],
    }


def test_qr_routed_scoring_files_scan_after_routed_export(tmp_path, monkeypatch):
    scan = tmp_path / "scan.pdf"
    scan.write_bytes(b"scan")
    calls = []

    monkeypatch.setattr(cli_score, "process_file_qr_aware", lambda input_file: [_result()])

    def export_routed(results):
        calls.append("export")
        return True

    def file_scan(results, source_path):
        calls.append("file")
        assert source_path == str(scan)
        return None

    monkeypatch.setattr(cli_score, "export_routed_results", export_routed)
    monkeypatch.setattr(cli_score, "file_original_scan_copy", file_scan)
    monkeypatch.setattr(cli_score, "print_scan_filing_result", lambda result: None)
    monkeypatch.setattr(cli_score, "print_qr_batch_summary", lambda summary: None)
    monkeypatch.setattr(cli_score, "save_qr_batch_summary", lambda summary, source: None)

    assert cli.run_score([str(scan)]) == 0
    assert calls == ["export", "file"]


def test_explicit_output_csv_skips_scan_filing(tmp_path, monkeypatch):
    scan = tmp_path / "scan.pdf"
    output = tmp_path / "results.csv"
    scan.write_bytes(b"scan")
    filed = []

    monkeypatch.setattr(cli_score, "process_file_qr_aware", lambda input_file: [_result()])
    monkeypatch.setattr(cli_score, "export_to_csv", lambda results, output_file: True)
    monkeypatch.setattr(
        cli_score,
        "file_original_scan_copy",
        lambda results, source_path: filed.append(source_path),
    )
    monkeypatch.setattr(cli_score, "print_qr_batch_summary", lambda summary: None)
    monkeypatch.setattr(cli_score, "save_qr_batch_summary", lambda summary, source: None)

    assert cli.run_score([str(scan), str(output)]) == 0
    assert filed == []


def test_manual_scoring_skips_scan_filing(tmp_path, monkeypatch):
    scan = tmp_path / "scan.pdf"
    answer_key = tmp_path / "answer_key.json"
    scan.write_bytes(b"scan")
    answer_key.write_text("{}", encoding="utf-8")
    filed = []

    monkeypatch.setattr(cli_score, "load_answer_key", lambda path: {1: "A"})
    monkeypatch.setattr(cli_score, "process_file", lambda input_file, key: [_result()])
    monkeypatch.setattr(cli_score, "export_to_csv", lambda results, output_file: True)
    monkeypatch.setattr(
        cli_score,
        "file_original_scan_copy",
        lambda results, source_path: filed.append(source_path),
    )

    assert cli.run_score([str(scan), str(answer_key)]) == 0
    assert filed == []
