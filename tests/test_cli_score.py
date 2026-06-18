import sys
import types
from pathlib import Path

import numpy as np

from scoreform import cli, cli_score, scoring


class Results(list):
    def __init__(self, values=None, summary=None):
        super().__init__(values or [])
        self.summary = summary or scoring.QRBatchSummary()


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


def test_qr_aware_no_scored_pages_prints_and_saves_summary(
    tmp_path,
    monkeypatch,
    capsys,
):
    calls = []
    results = Results()

    monkeypatch.setattr(
        cli_score,
        "process_file_qr_aware",
        lambda input_file, workspace_root=None: calls.append(
            ("process", input_file, workspace_root)
        )
        or results,
    )
    monkeypatch.setattr(
        cli_score,
        "get_qr_batch_summary",
        lambda all_results: calls.append(("summary", all_results)) or all_results.summary,
    )
    monkeypatch.setattr(
        cli_score,
        "print_qr_batch_summary",
        lambda summary: calls.append(("print_summary", summary)),
    )
    monkeypatch.setattr(
        cli_score,
        "save_qr_batch_summary",
        lambda summary, source, workspace_root=None: calls.append(
            ("save_summary", summary, source, workspace_root)
        ),
    )

    assert cli_score.run_score(["scan.pdf"]) == 1

    assert calls == [
        ("process", "scan.pdf", tmp_path),
        ("summary", results),
        ("print_summary", results.summary),
        ("save_summary", results.summary, "scan.pdf", tmp_path),
    ]


def test_qr_aware_no_scored_pages_prints_and_saves_file_failure_reason(
    tmp_path,
    monkeypatch,
    capsys,
):
    results = scoring.QRBatchResults()
    results.summary.record_file_failure(
        "unsupported_input_type",
        "Unsupported input type: .txt",
    )
    monkeypatch.setattr(
        cli_score,
        "process_file_qr_aware",
        lambda input_file, workspace_root=None: results,
    )

    assert cli_score.run_score(["scan.txt"]) == 1

    output = capsys.readouterr().out
    assert "File/batch failures: 1" in output
    assert "- Unsupported input type: .txt" in output
    assert "Error: No pages were scored successfully." in output

    summaries = list(
        (tmp_path / "local_outputs" / "qr_batch_summaries").rglob(
            "scan_*_summary.txt"
        )
    )
    assert len(summaries) == 1
    saved_text = summaries[0].read_text(encoding="utf-8")
    assert "File/batch failures: 1" in saved_text
    assert "- Unsupported input type: .txt" in saved_text


def test_qr_aware_export_failure_updates_summary_and_skips_filing(
    tmp_path,
    monkeypatch,
    capsys,
):
    calls = []
    results = Results([_result()])
    results.summary.record_scored_page()

    monkeypatch.setattr(
        cli_score,
        "process_file_qr_aware",
        lambda input_file, workspace_root=None: results,
    )
    monkeypatch.setattr(
        cli_score,
        "export_routed_results",
        lambda all_results, workspace_root=None: False,
    )
    monkeypatch.setattr(
        cli_score,
        "update_qr_batch_result_write_status",
        lambda all_results,
        export_success,
        output_file=None,
        workspace_root=None: (
            calls.append(
                (
                    "write_status",
                    all_results,
                    export_success,
                    output_file,
                    workspace_root,
                )
            ),
            all_results.summary.record_result_write_failed(),
        )[-1],
    )
    monkeypatch.setattr(
        cli_score,
        "get_qr_batch_summary",
        lambda all_results: calls.append(("summary", all_results)) or all_results.summary,
    )
    monkeypatch.setattr(
        cli_score,
        "print_qr_batch_summary",
        lambda summary: calls.append(("print_summary", summary)),
    )
    monkeypatch.setattr(
        cli_score,
        "save_qr_batch_summary",
        lambda summary, source, workspace_root=None: calls.append(
            ("save_summary", summary, source, workspace_root)
        ),
    )
    monkeypatch.setattr(
        cli_score,
        "file_original_scan_copy",
        lambda all_results, source, workspace_root=None: calls.append(
            ("file", all_results, source, workspace_root)
        ),
    )

    assert cli_score.run_score(["scan.pdf"]) == 1

    assert calls == [
        ("write_status", results, False, None, tmp_path),
        ("summary", results),
        ("print_summary", results.summary),
        ("save_summary", results.summary, "scan.pdf", tmp_path),
    ]


def test_qr_aware_full_success_exits_zero(tmp_path, monkeypatch, capsys):
    results = scoring.QRBatchResults([_result()])
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
    monkeypatch.setattr(cli_score, "file_original_scan_copy", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli_score, "print_scan_filing_result", lambda result: None)

    assert cli_score.run_score(["scan.pdf"]) == 0

    output = capsys.readouterr().out
    assert "Batch status: FULL SUCCESS" in output
    assert "PARTIAL SUCCESS" not in output


def test_qr_aware_partial_success_exits_zero_and_warns_in_saved_summary(
    tmp_path,
    monkeypatch,
    capsys,
):
    results = scoring.QRBatchResults([_result()])
    results.summary.record_processed_page()
    results.summary.record_processed_page()
    results.summary.record_scored_page()
    results.summary.record_failure(2, "missing_qr", "missing QR code")

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
    monkeypatch.setattr(cli_score, "file_original_scan_copy", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli_score, "print_scan_filing_result", lambda result: None)

    assert cli_score.run_score(["scan.pdf"]) == 0

    output = capsys.readouterr().out
    assert "Batch status: PARTIAL SUCCESS" in output
    assert scoring.QR_PARTIAL_SUCCESS_WARNING in output
    assert "- Page 2: missing QR code" in output

    summaries = list(
        (tmp_path / "local_outputs" / "qr_batch_summaries").rglob(
            "scan_*_summary.txt"
        )
    )
    assert len(summaries) == 1
    saved_text = summaries[0].read_text(encoding="utf-8")
    assert "Batch status: PARTIAL SUCCESS" in saved_text
    assert scoring.QR_PARTIAL_SUCCESS_WARNING in saved_text
    assert "- Page 2: missing QR code" in saved_text


def test_manual_pdf_tracks_partial_success_and_registration_failure(
    tmp_path,
    monkeypatch,
    capsys,
):
    scan_path = tmp_path / "scan.pdf"
    scan_path.write_bytes(b"synthetic")
    pages = [
        np.ones((20, 20, 3), dtype=np.uint8),
        np.ones((20, 20, 3), dtype=np.uint8),
        np.ones((20, 20, 3), dtype=np.uint8),
    ]
    score_results = [_result(), None, _result()]
    score_results[0]["page_num"] = 1
    score_results[2]["page_num"] = 3

    monkeypatch.setitem(
        sys.modules,
        "pdf2image",
        types.SimpleNamespace(convert_from_path=lambda _path: pages),
    )
    monkeypatch.setitem(
        sys.modules,
        "pdf2image.exceptions",
        types.SimpleNamespace(PDFInfoNotInstalledError=RuntimeError),
    )
    monkeypatch.setattr(
        scoring,
        "score_image",
        lambda *_args, **_kwargs: score_results.pop(0),
    )

    results = scoring.process_file(str(scan_path), {1: "A"})

    assert [result["page_num"] for result in results] == [1, 3]
    assert results.summary.pages_processed == 3
    assert results.summary.pages_scored == 2
    assert results.summary.pages_failed_skipped == 1
    assert results.summary.failures[0].page_num == 2
    assert "registration/corner detection failed" in capsys.readouterr().out


def test_manual_partial_success_exports_and_prints_incomplete_warning(
    monkeypatch,
    capsys,
):
    results = scoring.ManualScoringResults([_result(), _result()])
    results[1]["page_num"] = 3
    results.summary.pages_processed = 3
    results.summary.pages_scored = 2
    results.summary.record_failure(2, "registration/corner detection failed.")
    exported = []

    monkeypatch.setattr(cli_score, "load_answer_key", lambda _path: {1: "A"})
    monkeypatch.setattr(cli_score, "process_file", lambda _path, _key: results)
    monkeypatch.setattr(
        cli_score,
        "export_to_csv",
        lambda rows, output, workspace_root=None: exported.append((rows, output)) or True,
    )

    assert cli_score.run_score(["scan.pdf", "answers.json"]) == 0

    output = capsys.readouterr().out
    assert exported and exported[0][0] is results
    assert "Manual scoring summary" in output
    assert "Pages processed: 3" in output
    assert "Pages scored: 2" in output
    assert "Pages failed/skipped: 1" in output
    assert "Page 2" in output
    assert "registration" in output
    assert "results may be incomplete" in output
    assert "Review failed pages before treating results as final." in output


def test_manual_zero_success_fails_with_visible_counts(monkeypatch, capsys):
    results = scoring.ManualScoringResults()
    results.summary.pages_processed = 2
    results.summary.record_failure(1, "registration/corner detection failed.")
    results.summary.record_failure(2, "image could not be read or loaded.")

    monkeypatch.setattr(cli_score, "load_answer_key", lambda _path: {1: "A"})
    monkeypatch.setattr(cli_score, "process_file", lambda _path, _key: results)
    monkeypatch.setattr(
        cli_score,
        "export_to_csv",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("zero-success batches must not export")
        ),
    )

    assert cli_score.run_score(["scan.pdf", "answers.json"]) == 1

    output = capsys.readouterr().out
    assert "Manual scoring summary" in output
    assert "Pages processed: 2" in output
    assert "Pages scored: 0" in output
    assert "Pages failed/skipped: 2" in output
    assert "No pages were scored." in output


def test_main_score_dispatch_still_routes_to_cli_run_score(monkeypatch):
    calls = []

    monkeypatch.setattr(cli, "run_score", lambda args: calls.append(args) or 0)

    assert cli.main(["score", "scan.pdf", "out.csv"]) == 0
    assert calls == [["scan.pdf", "out.csv"]]


def test_cli_score_does_not_use_signature_reflection():
    source = Path(cli_score.__file__).resolve().read_text(encoding="utf-8")

    assert "inspect.signature" not in source
    assert "_call_with_workspace_root" not in source
