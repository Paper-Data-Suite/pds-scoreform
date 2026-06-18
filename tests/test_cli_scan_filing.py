from scoreform import cli, cli_score, scoring


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

    results = scoring.QRBatchResults([_result()])
    results.summary.record_processed_page()
    results.summary.record_scored_page()
    monkeypatch.setattr(
        cli_score,
        "process_file_qr_aware",
        lambda input_file, workspace_root=None: results,
    )

    def export_routed(results, workspace_root=None):
        assert workspace_root == tmp_path
        calls.append("export")
        return True

    def file_scan(results, source_path, workspace_root=None):
        assert workspace_root == tmp_path
        calls.append("file")
        assert source_path == str(scan)
        return None

    monkeypatch.setattr(cli_score, "export_routed_results", export_routed)
    monkeypatch.setattr(cli_score, "file_original_scan_copy", file_scan)
    monkeypatch.setattr(cli_score, "print_scan_filing_result", lambda result: None)
    monkeypatch.setattr(cli_score, "print_qr_batch_summary", lambda summary: None)
    monkeypatch.setattr(
        cli_score,
        "save_qr_batch_summary",
        lambda summary, source, workspace_root=None: None,
    )

    assert cli.run_score([str(scan)]) == 0
    assert calls == ["export", "file"]


def test_partial_success_skips_scan_filing_and_exits_zero(
    tmp_path,
    monkeypatch,
    capsys,
):
    scan = tmp_path / "scan.pdf"
    scan.write_bytes(b"scan")
    results = scoring.QRBatchResults([_result()])
    results.summary.record_processed_page()
    results.summary.record_processed_page()
    results.summary.record_scored_page()
    results.summary.record_failure(2, "missing_qr", "missing QR code")
    filed = []

    monkeypatch.setattr(
        cli_score,
        "process_file_qr_aware",
        lambda input_file, workspace_root=None: results,
    )
    monkeypatch.setattr(
        cli_score,
        "export_routed_results",
        lambda all_results, workspace_root=None: True,
    )
    monkeypatch.setattr(
        cli_score,
        "file_original_scan_copy",
        lambda *args, **kwargs: filed.append(args),
    )

    assert cli.run_score([str(scan)]) == 0

    output = capsys.readouterr().out
    assert filed == []
    assert "Scan filing skipped: QR batch was PARTIAL SUCCESS." in output
    assert "source scan was not filed automatically" in output
    assert "Batch status: PARTIAL SUCCESS" in output


def test_full_success_mixed_targets_skips_scan_filing_with_clear_message(
    tmp_path,
    monkeypatch,
    capsys,
):
    scan = tmp_path / "scan.pdf"
    scan.write_bytes(b"scan")
    results = scoring.QRBatchResults(
        [
            _result(),
            {
                **_result(),
                "page_num": 2,
                "assignment_id": "another_quiz",
                "student_id": "1002",
            },
        ]
    )
    for _ in results:
        results.summary.record_processed_page()
        results.summary.record_scored_page()

    monkeypatch.setattr(
        cli_score,
        "process_file_qr_aware",
        lambda input_file, workspace_root=None: results,
    )
    monkeypatch.setattr(
        cli_score,
        "export_routed_results",
        lambda all_results, workspace_root=None: True,
    )

    assert cli.run_score([str(scan)]) == 0

    output = capsys.readouterr().out
    assert "scored pages resolved to multiple assignment targets" in output
    assert not (tmp_path / "classes").exists()


def test_explicit_output_csv_skips_scan_filing(tmp_path, monkeypatch):
    scan = tmp_path / "scan.pdf"
    output = tmp_path / "results.csv"
    scan.write_bytes(b"scan")
    filed = []

    monkeypatch.setattr(
        cli_score,
        "process_file_qr_aware",
        lambda input_file, workspace_root=None: [_result()],
    )
    monkeypatch.setattr(
        cli_score,
        "export_to_csv",
        lambda results, output_file, workspace_root=None: True,
    )
    monkeypatch.setattr(
        cli_score,
        "file_original_scan_copy",
        lambda results, source_path, workspace_root=None: filed.append(source_path),
    )
    monkeypatch.setattr(cli_score, "print_qr_batch_summary", lambda summary: None)
    monkeypatch.setattr(
        cli_score,
        "save_qr_batch_summary",
        lambda summary, source, workspace_root=None: None,
    )

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
    monkeypatch.setattr(
        cli_score,
        "export_to_csv",
        lambda results, output_file, workspace_root=None: True,
    )
    monkeypatch.setattr(
        cli_score,
        "file_original_scan_copy",
        lambda results, source_path: filed.append(source_path),
    )

    assert cli.run_score([str(scan), str(answer_key)]) == 0
    assert filed == []
