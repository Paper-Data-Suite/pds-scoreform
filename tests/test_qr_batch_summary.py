from pathlib import Path

import numpy as np

from scoreform import scoring


def _scored_result(page_num=1, class_id="english9_p2", assignment_id="rj_act1_quiz"):
    return {
        "page_num": page_num,
        "class_id": class_id,
        "assignment_id": assignment_id,
        "student_id": "1001",
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

    assert "QR-Aware Batch Summary" in text
    assert "Pages processed: 1" in text
    assert "Pages scored: 1" in text
    assert "Pages skipped/failed: 0" in text
    assert "classes/english9_p2/assignments/rj_act1_quiz/results.csv" in text
    assert "Skipped pages:" not in text


def test_qr_batch_summary_groups_failures_and_lists_pages():
    summary = scoring.QRBatchSummary()
    for _ in range(3):
        summary.record_processed_page()
    summary.record_scored_page()
    summary.record_failure(2, "missing_qr", "missing QR code")
    summary.record_failure(3, "unsafe_qr", "unsafe QR payload")

    text = summary.format()

    assert "Pages processed: 3" in text
    assert "Pages scored: 1" in text
    assert "Pages skipped/failed: 2" in text
    assert "- Missing QR code: 1" in text
    assert "- Unsafe QR payload: 1" in text
    assert "- Page 2: missing QR code" in text
    assert "- Page 3: unsafe QR payload" in text
    assert "Review skipped pages before treating results as final." in text


def test_qr_batch_summary_records_result_write_failure():
    results = scoring.QRBatchResults([_scored_result()])
    scoring.update_qr_batch_result_write_status(
        results,
        export_success=False,
        explicit_output_file="out.csv",
    )

    text = results.summary.format()

    assert "- Result writing failure: 1" in text
    assert "No - result writing failed." in text
    assert "out.csv" in text
    assert results.summary.pages_skipped_failed == 0


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
        lambda img: scoring.QRDecodeResult(None, "missing_qr", "missing QR code"),
    )

    results = scoring.process_file_qr_aware(str(scan_path))

    assert results == []
    assert results.summary.pages_processed == 1
    assert results.summary.pages_scored == 0
    assert results.summary.pages_skipped_failed == 1
    assert results.summary.failure_counts()["missing_qr"] == 1


def test_process_file_qr_aware_records_success_and_routed_output(tmp_path, monkeypatch):
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
        lambda img: scoring.QRDecodeResult(
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
        lambda assignment_path, page_num, summary: {
            "answer_key": {1: "A"},
            "question_count": 1,
        },
    )
    monkeypatch.setattr(scoring, "score_image", lambda *args, **kwargs: _scored_result())

    results = scoring.process_file_qr_aware(str(scan_path))
    scoring.update_qr_batch_result_write_status(results, export_success=True)

    assert len(results) == 1
    assert results.summary.pages_processed == 1
    assert results.summary.pages_scored == 1
    assert results.summary.pages_skipped_failed == 0
    expected_path = (
        Path("classes")
        / "english9_p2"
        / "assignments"
        / "rj_act1_quiz"
        / "results.csv"
    )
    assert results.summary.output_paths == [str(expected_path)]
