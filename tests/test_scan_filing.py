import datetime
from pathlib import Path

from scoreform import scan_filing


def _result(class_id="english9_p2", assignment_id="rj_act1_quiz", page_num=1):
    return {
        "page_num": page_num,
        "class_id": class_id,
        "assignment_id": assignment_id,
        "student_id": f"100{page_num}",
        "score": 1,
        "total_points": 1,
        "answers": [{"Q": 1, "Answer": "A", "Correct": True}],
    }


def test_files_same_assignment_scan_copy_and_preserves_source(tmp_path):
    source = tmp_path / "scans_inbox" / "Final Exam Scan.PDF"
    source.parent.mkdir()
    source.write_bytes(b"scan evidence")

    result = scan_filing.file_original_scan_copy(
        [_result(), _result(page_num=2)],
        source,
        now=datetime.datetime(2026, 6, 16, 14, 30, 22),
    )

    expected = (
        tmp_path
        / "classes"
        / "english9_p2"
        / "assignments"
        / "rj_act1_quiz"
        / "scans"
        / "Final_Exam_Scan_2026-06-16_143022_scored.PDF"
    )
    assert result.filed
    assert Path(result.filed_path) == expected
    assert expected.read_bytes() == b"scan evidence"
    assert source.exists()
    assert source.read_bytes() == b"scan evidence"


def test_creates_assignment_scan_folder(tmp_path):
    source = tmp_path / "scan.png"
    source.write_bytes(b"image")

    result = scan_filing.file_original_scan_copy(
        [_result()],
        source,
        now=datetime.datetime(2026, 6, 16, 14, 30, 22),
    )

    assert result.filed
    assert (
        tmp_path
        / "classes"
        / "english9_p2"
        / "assignments"
        / "rj_act1_quiz"
        / "scans"
    ).is_dir()


def test_filed_filename_is_timestamped_status_tagged_and_preserves_extension(tmp_path):
    source = tmp_path / "scanner export.tiff"
    source.write_bytes(b"image")

    result = scan_filing.file_original_scan_copy(
        [_result()],
        source,
        now=datetime.datetime(2026, 6, 16, 14, 30, 22),
    )

    filed_name = Path(result.filed_path).name
    assert filed_name == "scanner_export_2026-06-16_143022_scored.tiff"


def test_collision_handling_does_not_overwrite_existing_filed_scan(tmp_path):
    source = tmp_path / "scan.pdf"
    source.write_bytes(b"new scan")
    scans_dir = (
        tmp_path
        / "classes"
        / "english9_p2"
        / "assignments"
        / "rj_act1_quiz"
        / "scans"
    )
    scans_dir.mkdir(parents=True)
    existing = scans_dir / "scan_2026-06-16_143022_scored.pdf"
    existing.write_bytes(b"existing scan")

    result = scan_filing.file_original_scan_copy(
        [_result()],
        source,
        now=datetime.datetime(2026, 6, 16, 14, 30, 22),
    )

    assert Path(result.filed_path).name == "scan_2026-06-16_143022_scored_2.pdf"
    assert existing.read_bytes() == b"existing scan"
    assert Path(result.filed_path).read_bytes() == b"new scan"


def test_mixed_target_results_skip_filing(tmp_path):
    source = tmp_path / "scan.pdf"
    source.write_bytes(b"scan")

    result = scan_filing.file_original_scan_copy(
        [
            _result(class_id="english9_p2", assignment_id="quiz_a"),
            _result(class_id="english9_p2", assignment_id="quiz_b", page_num=2),
        ],
        source,
    )

    assert not result.filed
    assert result.skipped_reason == "multiple assignment targets were detected"
    assert not (tmp_path / "classes").exists()


def test_no_results_skip_filing(tmp_path):
    source = tmp_path / "scan.pdf"
    source.write_bytes(b"scan")

    result = scan_filing.file_original_scan_copy([], source)

    assert not result.filed
    assert result.skipped_reason == "no pages scored successfully"
    assert not (tmp_path / "classes").exists()


def test_missing_source_scan_reports_warning(tmp_path):
    result = scan_filing.file_original_scan_copy(
        [_result()],
        tmp_path / "missing.pdf",
    )

    assert not result.filed
    assert "source scan is missing" in result.warning
    assert not (tmp_path / "classes").exists()


def test_copy_failure_reports_warning_without_filed_path(tmp_path):
    source = tmp_path / "scan.pdf"
    source.write_bytes(b"scan")

    def fail_copy(src, dst):
        raise PermissionError("locked")

    result = scan_filing.file_original_scan_copy(
        [_result()],
        source,
        copy_func=fail_copy,
    )

    assert not result.filed
    assert result.warning == "Warning: Scan filing failed after results export: locked"


def test_scan_filing_output_uses_filing_vocabulary(capsys):
    result = scan_filing.ScanFilingResult(
        filed_path="classes/class_a/assignments/unit/scans/scan_scored.pdf",
        source_path="scans_inbox/scan.pdf",
    )

    scan_filing.print_scan_filing_result(result)

    output = capsys.readouterr().out.lower()
    assert "filed scan copy" in output
    assert "original scan preserved" in output
    assert "archive" not in output
