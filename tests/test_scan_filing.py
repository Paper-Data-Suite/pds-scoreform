"""Assignment-local scan copies use ScoreForm managed work."""

from pathlib import Path

from scoreform.folders import setup_assignment_folder
from scoreform.scan_filing import file_resolution_scan_copy
from scoreform.work_paths import scoreform_work_paths


def test_resolution_copy_targets_canonical_assignment_scans(tmp_path) -> None:
    roster = {
        "class_id": "class1",
        "students": [{
            "student_id": "1001", "last_name": "Doe",
            "first_name": "Jane", "period": "1",
        }],
    }
    assignment = {
        "assignment_id": "quiz", "title": "Quiz", "question_count": 1,
        "choices": ["A", "B", "C", "D"],
        "answer_key": {"1": "A"}, "standards": {"1": []},
    }
    assert setup_assignment_folder(
        roster, assignment, workspace_root=tmp_path
    ) is not None
    source = tmp_path / "retained" / "scan.pdf"
    source.parent.mkdir()
    source.write_bytes(b"scan")

    result = file_resolution_scan_copy(
        tmp_path, "class1", "quiz", source, "manual_marks"
    )

    scans_dir = scoreform_work_paths(tmp_path, "class1", "quiz").scans_dir
    assert result.filed
    assert Path(result.filed_path).parent == scans_dir
    assert source.read_bytes() == b"scan"
