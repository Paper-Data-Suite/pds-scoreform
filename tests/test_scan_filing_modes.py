"""Assignment-local filing preserves Core retention and constrains move cleanup."""

from pathlib import Path

from scoreform.folders import setup_assignment_folder
from scoreform.scan_filing import file_original_scan_after_success
from scoreform.work_paths import scoreform_work_paths


def test_off_mode_remains_a_noop() -> None:
    result = file_original_scan_after_success([], "missing.pdf", mode="off")
    assert result.skipped_reason == "scan filing mode is off"


def test_copy_and_move_modes_skip_when_no_results_exist() -> None:
    for mode in ("copy", "move"):
        result = file_original_scan_after_success([], "missing.pdf", mode=mode)
        assert result.skipped_reason == "no pages scored successfully"


def _workspace(tmp_path):
    roster = {"class_id": "class1", "students": [{
        "student_id": "1001", "last_name": "Doe", "first_name": "Jane", "period": "1",
    }]}
    assignment = {
        "assignment_id": "quiz", "title": "Quiz", "question_count": 1,
        "choices": ["A", "B", "C", "D"], "answer_key": {"1": "A"},
        "standards": {"1": []},
    }
    assert setup_assignment_folder(roster, assignment, workspace_root=tmp_path)
    return [{"class_id": "class1", "assignment_id": "quiz"}]


def test_copy_preserves_original_and_core_retained_source(tmp_path: Path):
    results = _workspace(tmp_path)
    original = tmp_path / "outside.pdf"
    original.write_bytes(b"scan")
    retained = tmp_path / "scans" / "source" / "2026-07-15" / "retained.pdf"
    retained.parent.mkdir(parents=True)
    retained.write_bytes(b"canonical")
    filed = file_original_scan_after_success(
        results, original, mode="copy", workspace_root=tmp_path
    )
    assert filed.filed and original.read_bytes() == b"scan"
    assert retained.read_bytes() == b"canonical"
    assert Path(filed.filed_path).parent == scoreform_work_paths(
        tmp_path, "class1", "quiz"
    ).scans_dir


def test_move_removes_only_verified_direct_inbox_original(tmp_path: Path):
    results = _workspace(tmp_path)
    inbox = tmp_path / "scans_inbox"
    inbox.mkdir()
    original = inbox / "scan.pdf"
    original.write_bytes(b"scan")
    moved = file_original_scan_after_success(
        results, original, mode="move", workspace_root=tmp_path
    )
    assert moved.original_removed and not original.exists()

    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"outside")
    preserved = file_original_scan_after_success(
        results, outside, mode="move", workspace_root=tmp_path
    )
    assert outside.exists()
    assert not preserved.original_removed
    assert preserved.cleanup_skipped_reason


def test_multiple_targets_never_file(tmp_path: Path):
    results = _workspace(tmp_path)
    source = tmp_path / "scan.pdf"
    source.write_bytes(b"scan")
    result = file_original_scan_after_success(
        [*results, {"class_id": "class1", "assignment_id": "other"}],
        source, mode="copy", workspace_root=tmp_path,
    )
    assert not result.filed
    assert "multiple assignment targets" in result.skipped_reason
