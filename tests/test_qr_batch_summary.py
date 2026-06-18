import builtins
import datetime
import sys
import types
from pathlib import Path

import cv2
import numpy as np

from scoreform import scoring


def _scored_result(
    page_num=1,
    class_id="english9_p2",
    assignment_id="rj_act1_quiz",
    student_id="1001",
):
    return {
        "page_num": page_num,
        "class_id": class_id,
        "assignment_id": assignment_id,
        "student_id": student_id,
        "score": 1,
        "total_points": 1,
        "answers": [{"Q": 1, "Answer": "A", "Correct": True}],
    }


def test_qr_batch_summary_formats_success_with_result_path():
    summary = scoring.QRBatchSummary()
    summary.record_processed_page()
    summary.record_scored_page()
    summary.record_results_written(
        ["classes/english9_p2/assignments/rj_act1_quiz/results.csv"]
    )

    text = summary.format()

    assert summary.outcome() == "full_success"
    assert summary.exit_code() == 0
    assert "QR-Aware Batch Summary" in text
    assert "Batch status: FULL SUCCESS" in text
    assert "Pages processed: 1" in text
    assert "Pages scored: 1" in text
    assert "Pages skipped/failed: 0" in text
    assert "File/batch failures: 0" in text
    assert "classes/english9_p2/assignments/rj_act1_quiz/results.csv" in text
    assert "Skipped pages:" not in text


def test_qr_batch_summary_groups_failures_and_lists_pages():
    summary = scoring.QRBatchSummary()
    for _ in range(3):
        summary.record_processed_page()
    summary.record_scored_page()
    summary.record_failure(2, "missing_qr", "missing QR code")
    summary.record_failure(3, "unsafe_qr", "unsafe QR payload")
    summary.record_results_written(["results.csv"])

    text = summary.format()

    assert summary.outcome() == "partial_success"
    assert summary.exit_code() == 0
    assert "Batch status: PARTIAL SUCCESS" in text
    assert scoring.QR_PARTIAL_SUCCESS_WARNING in text
    assert "Pages processed: 3" in text
    assert "Pages scored: 1" in text
    assert "Pages skipped/failed: 2" in text
    assert "- Missing QR code: 1" in text
    assert "- Unsafe QR payload: 1" in text
    assert "- Page 2: missing QR code" in text
    assert "- Page 3: unsafe QR payload" in text
    assert "Review failures before treating results as final." in text


def test_qr_batch_summary_scored_pages_without_written_results_is_not_success():
    summary = scoring.QRBatchSummary()
    summary.record_processed_page()
    summary.record_scored_page()
    summary.record_failure(2, "missing_qr", "missing QR code")

    assert summary.results_written is False
    assert summary.result_write_failed is False
    assert summary.outcome() == "export_failure"
    assert summary.exit_code() == 1

    text = summary.format()
    assert "Batch status: EXPORT FAILURE" in text


def test_qr_batch_summary_formats_file_level_failure_reason():
    summary = scoring.QRBatchSummary()
    summary.record_file_failure(
        "unsupported_input_type",
        "Unsupported input type: .txt",
    )

    text = summary.format()

    assert summary.outcome() == "zero_success"
    assert summary.exit_code() == 1
    assert "Batch status: ZERO SUCCESS" in text
    assert "Error: No pages were scored successfully." in text
    assert "Pages skipped/failed: 0" in text
    assert "File/batch failures: 1" in text
    assert "- Unsupported input type: 1" in text
    assert "File/batch failure details:" in text
    assert "- Unsupported input type: .txt" in text


def test_qr_batch_summary_records_result_write_failure():
    results = scoring.QRBatchResults([_scored_result()])
    results.summary.record_scored_page()
    scoring.update_qr_batch_result_write_status(
        results,
        export_success=False,
        explicit_output_file="out.csv",
    )

    text = results.summary.format()

    assert results.summary.outcome() == "export_failure"
    assert results.summary.exit_code() == 1
    assert "Batch status: EXPORT FAILURE" in text
    assert "Error: Failed to export results." in text
    assert "- Result writing failure: 1" in text
    assert "No - result writing failed." in text
    assert "out.csv" in text
    assert results.summary.pages_skipped_failed == 0


def test_qr_batch_summary_result_write_failure_flag_keeps_review_warning():
    summary = scoring.QRBatchSummary()
    summary.record_result_write_failed()
    summary.failures.clear()

    text = summary.format()

    assert summary.failures == []
    assert "No - result writing failed." in text
    assert "Review failures before treating results as final." in text


def test_process_file_qr_aware_records_missing_qr_failure(tmp_path, monkeypatch):
    scan_path = tmp_path / "scan.png"
    scan_path.write_bytes(b"synthetic")

    monkeypatch.setattr(
        scoring.cv2,
        "imread",
        lambda path: np.ones((20, 20, 3), dtype=np.uint8),
    )
    monkeypatch.setattr(
        scoring,
        "_decode_qr_from_image_with_status",
        lambda img, **kwargs: scoring.QRDecodeResult(
            None,
            "missing_qr",
            "missing QR code",
        ),
    )

    results = scoring.process_file_qr_aware(str(scan_path))

    assert results == []
    assert results.summary.pages_processed == 1
    assert results.summary.pages_scored == 0
    assert results.summary.pages_skipped_failed == 1
    assert results.summary.failure_counts()["missing_qr"] == 1
    assert results.summary.failures[0].page_num == 1
    assert results.summary.failures[0].reason == "missing QR code"


def test_process_file_qr_aware_records_missing_input_file(tmp_path):
    missing_path = tmp_path / "missing.pdf"

    results = scoring.process_file_qr_aware(str(missing_path))

    assert results == []
    assert results.summary.pages_processed == 0
    assert results.summary.pages_skipped_failed == 0
    assert results.summary.failure_counts() == {"input_file_missing": 1}
    assert results.summary.file_failures[0].reason == (
        f"Input file not found: {missing_path}"
    )


def test_process_file_qr_aware_records_unsupported_input_type(tmp_path):
    scan_path = tmp_path / "scan.txt"
    scan_path.write_text("not a supported scan", encoding="utf-8")

    results = scoring.process_file_qr_aware(str(scan_path))

    assert results == []
    assert results.summary.pages_processed == 0
    assert results.summary.failure_counts() == {"unsupported_input_type": 1}
    assert results.summary.file_failures[0].reason == "Unsupported input type: .txt"


def test_process_file_qr_aware_records_missing_pdf2image(tmp_path, monkeypatch):
    scan_path = tmp_path / "scan.pdf"
    scan_path.write_bytes(b"synthetic")
    real_import = builtins.__import__

    def import_without_pdf2image(name, *args, **kwargs):
        if name == "pdf2image":
            raise ImportError("pdf2image unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_pdf2image)

    results = scoring.process_file_qr_aware(str(scan_path))

    assert results == []
    assert results.summary.failure_counts() == {"pdf2image_missing": 1}
    assert results.summary.file_failures[0].reason == "pdf2image is not installed"


def test_process_file_qr_aware_records_missing_poppler(tmp_path, monkeypatch):
    scan_path = tmp_path / "scan.pdf"
    scan_path.write_bytes(b"synthetic")

    class MissingPopplerError(Exception):
        pass

    monkeypatch.setitem(
        sys.modules,
        "pdf2image",
        types.SimpleNamespace(
            convert_from_path=lambda _path: (_ for _ in ()).throw(
                MissingPopplerError("Unable to get page count")
            )
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "pdf2image.exceptions",
        types.SimpleNamespace(PDFInfoNotInstalledError=MissingPopplerError),
    )

    results = scoring.process_file_qr_aware(str(scan_path))

    assert results == []
    assert results.summary.failure_counts() == {"poppler_missing": 1}
    assert "Poppler / pdftoppm" in results.summary.file_failures[0].reason


def test_process_file_qr_aware_records_pdf_conversion_failure(tmp_path, monkeypatch):
    scan_path = tmp_path / "scan.pdf"
    scan_path.write_bytes(b"synthetic")

    monkeypatch.setitem(
        sys.modules,
        "pdf2image",
        types.SimpleNamespace(
            convert_from_path=lambda _path: (_ for _ in ()).throw(
                RuntimeError("damaged PDF")
            )
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "pdf2image.exceptions",
        types.SimpleNamespace(PDFInfoNotInstalledError=LookupError),
    )

    results = scoring.process_file_qr_aware(str(scan_path))

    assert results == []
    assert results.summary.failure_counts() == {"pdf_conversion_failed": 1}
    assert results.summary.file_failures[0].reason == (
        "PDF conversion/processing failed: damaged PDF"
    )


def test_process_file_qr_aware_records_image_read_failure(tmp_path, monkeypatch):
    scan_path = tmp_path / "scan.png"
    scan_path.write_bytes(b"unreadable")
    monkeypatch.setattr(scoring.cv2, "imread", lambda _path: None)

    results = scoring.process_file_qr_aware(str(scan_path))

    assert results == []
    assert results.summary.pages_processed == 1
    assert results.summary.pages_skipped_failed == 1
    assert results.summary.failure_counts() == {"image_processing_failed": 1}
    assert results.summary.failures[0].page_num == 1
    assert results.summary.failures[0].reason == "image could not be loaded"


def test_process_file_qr_aware_records_success_and_routed_output(tmp_path, monkeypatch):
    scan_path = tmp_path / "scan.png"
    scan_path.write_bytes(b"synthetic")
    assignment_paths = []
    debug_dirs = []

    monkeypatch.setattr(
        scoring.cv2,
        "imread",
        lambda path: np.ones((20, 20, 3), dtype=np.uint8),
    )
    monkeypatch.setattr(
        scoring,
        "_decode_qr_from_image_with_status",
        lambda img, **kwargs: scoring.QRDecodeResult(
            {
                "class_id": "english9_p2",
                "assignment_id": "rj_act1_quiz",
                "student_id": "1001",
            }
        ),
    )
    monkeypatch.setattr(
        scoring,
        "_load_qr_aware_assignment",
        lambda assignment_path, page_num, summary: (
            assignment_paths.append(assignment_path)
            or {
                "answer_key": {1: "A"},
                "question_count": 1,
            }
        ),
    )
    monkeypatch.setattr(
        scoring,
        "score_image",
        lambda *args, **kwargs: (
            debug_dirs.append(kwargs["debug_dir"]) or _scored_result()
        ),
    )

    results = scoring.process_file_qr_aware(str(scan_path))
    scoring.update_qr_batch_result_write_status(results, export_success=True)

    assert len(results) == 1
    assert results.summary.pages_processed == 1
    assert results.summary.pages_scored == 1
    assert results.summary.pages_skipped_failed == 0
    expected_path = (
        tmp_path
        / "classes"
        / "english9_p2"
        / "assignments"
        / "rj_act1_quiz"
        / "results.csv"
    )
    assert results.summary.output_paths == [str(expected_path)]
    assert assignment_paths == [
        str(
            tmp_path
            / "classes"
            / "english9_p2"
            / "assignments"
            / "rj_act1_quiz"
            / "assignment.json"
        )
    ]
    assert debug_dirs == [
        str(
            tmp_path
            / "classes"
            / "english9_p2"
            / "assignments"
            / "rj_act1_quiz"
            / "debug"
        )
    ]


def test_process_file_qr_aware_resolves_workspace_once_for_multi_page_pdf(
    tmp_path,
    monkeypatch,
):
    scan_path = tmp_path / "class_packet.pdf"
    scan_path.write_bytes(b"synthetic")
    workspace_calls = []
    metadata_by_page = {
        1: "1001",
        2: "1002",
        3: "1003",
    }

    def get_workspace_once():
        workspace_calls.append("call")
        if len(workspace_calls) > 1:
            raise AssertionError("workspace root should be resolved once")
        return tmp_path

    monkeypatch.setattr(
        scoring.workspace,
        "get_scoreform_workspace_root",
        get_workspace_once,
    )
    monkeypatch.setitem(
        sys.modules,
        "pdf2image",
        types.SimpleNamespace(
            convert_from_path=lambda _path: [
                np.ones((20, 20, 3), dtype=np.uint8),
                np.ones((20, 20, 3), dtype=np.uint8),
                np.ones((20, 20, 3), dtype=np.uint8),
            ],
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "pdf2image.exceptions",
        types.SimpleNamespace(PDFInfoNotInstalledError=RuntimeError),
    )
    monkeypatch.setattr(
        scoring,
        "_decode_qr_from_image_with_status",
        lambda _img, page_num, **_kwargs: scoring.QRDecodeResult(
            {
                "class_id": "english9_p2",
                "assignment_id": "rj_act1_quiz",
                "student_id": metadata_by_page[page_num],
            }
        ),
    )
    monkeypatch.setattr(
        scoring,
        "_load_qr_aware_assignment",
        lambda _assignment_path, _page_num, _summary: {
            "answer_key": {1: "A"},
            "question_count": 1,
        },
    )
    monkeypatch.setattr(
        scoring,
        "score_image",
        lambda _img, _answer_key, page_num, **_kwargs: _scored_result(
            page_num=page_num,
            student_id=metadata_by_page[page_num],
        ),
    )

    results = scoring.process_file_qr_aware(str(scan_path))

    assert workspace_calls == ["call"]
    assert [result["student_id"] for result in results] == ["1001", "1002", "1003"]
    assert results.summary.pages_processed == 3
    assert results.summary.pages_scored == 3
    assert results.summary.pages_skipped_failed == 0


def test_save_qr_failure_diagnostics_defaults_to_qr_region_images(
    tmp_path,
    monkeypatch,
):
    now = datetime.datetime(2026, 6, 10, 14, 32)
    image = np.ones((400, 300, 3), dtype=np.uint8) * 255

    paths = scoring.save_qr_failure_diagnostics(
        image,
        "English 12 Trial Responses.pdf",
        page_num=2,
        now=now,
    )

    expected_dir = tmp_path / "local_outputs" / "qr_failures" / "2026-06-10"
    assert len(paths) == 5
    assert all(Path(path).parent == expected_dir for path in paths)
    assert all(Path(path).exists() for path in paths)
    assert any(path.endswith("page_2_qr_region.png") for path in paths)
    assert any(path.endswith("qr_region_tight.png") for path in paths)
    assert any(path.endswith("qr_crop_tight_threshold_padded_5x.png") for path in paths)
    assert all(cv2.imread(path).shape[:2] != image.shape[:2] for path in paths)
    assert not any("full_page" in Path(path).name for path in paths)


def test_save_qr_failure_diagnostics_full_page_requires_debug_opt_in(
    tmp_path,
    monkeypatch,
):
    image = np.ones((400, 300, 3), dtype=np.uint8) * 255
    monkeypatch.setenv("PDS_SCOREFORM_FULL_PAGE_DIAGNOSTICS", "1")

    paths = scoring.save_qr_failure_diagnostics(
        image,
        "scan.pdf",
        page_num=3,
    )

    full_page_paths = [
        path for path in paths if Path(path).name.endswith("_full_page_debug.png")
    ]
    assert len(full_page_paths) == 1
    assert cv2.imread(full_page_paths[0]).shape[:2] == image.shape[:2]


def test_missing_qr_decode_saves_failure_diagnostics(tmp_path, monkeypatch):
    monkeypatch.setattr(
        scoring,
        "_qr_candidate_images",
        lambda img: [("raw", img)],
    )

    class MissingDetector:
        def detectAndDecode(self, img):
            return "", None, None

    monkeypatch.setattr(scoring.cv2, "QRCodeDetector", MissingDetector)

    result = scoring._decode_qr_from_image_with_status(
        np.ones((400, 300, 3), dtype=np.uint8) * 255,
        file_path="scan packet.pdf",
        page_num=2,
    )

    assert result.failure_category == "missing_qr"
    assert len(result.diagnostic_paths) == 5
    assert all(Path(path).exists() for path in result.diagnostic_paths)
    assert all("qr_failures" in Path(path).parts for path in result.diagnostic_paths)
    assert any("qr_region" in Path(path).name for path in result.diagnostic_paths)


def test_save_qr_batch_summary_includes_failures_and_result_paths(
    tmp_path,
    monkeypatch,
    capsys,
):
    now = datetime.datetime(2026, 6, 10, 14, 32)
    summary = scoring.QRBatchSummary()
    summary.record_processed_page()
    summary.record_scored_page()
    summary.record_failure(2, "missing_qr", "missing QR code")
    summary.record_diagnostics(
        ["local_outputs/qr_failures/2026-06-10/scan_page_2.png"]
    )
    summary.record_results_written(
        ["classes/english_12_trial/assignments/final_exam_trial/results.csv"]
    )

    scoring.print_qr_batch_summary(summary)
    output_path = scoring.save_qr_batch_summary(
        summary,
        "English 12 Trial Responses.pdf",
        now=now,
    )
    output = capsys.readouterr().out
    text = Path(output_path).read_text(encoding="utf-8")

    assert "QR-Aware Batch Summary" in output
    assert Path(output_path) == (
        tmp_path
        / "local_outputs"
        / "qr_batch_summaries"
        / "2026-06-10"
        / "English_12_Trial_Responses_2026-06-10_1432_summary.txt"
    )
    assert "- Page 2: missing QR code" in text
    assert "Batch status: PARTIAL SUCCESS" in text
    assert scoring.QR_PARTIAL_SUCCESS_WARNING in text
    assert "local_outputs/qr_failures/2026-06-10/scan_page_2.png" in text
    assert "classes/english_12_trial/assignments/final_exam_trial/results.csv" in text
