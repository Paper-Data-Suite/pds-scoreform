"""Assignment-local scan copies use ScoreForm managed work."""

import pytest

import scoreform.scan_filing as scan_filing
from scoreform.folders import setup_assignment_folder
from scoreform.scan_filing import ReviewEvidenceFilingResult, file_resolution_scan_copy
from scoreform.work_paths import scoreform_work_paths


def test_resolution_copy_targets_canonical_assignment_scans(tmp_path) -> None:
    roster = {
        "class_id": "class1",
        "students": [
            {
                "student_id": "1001",
                "last_name": "Doe",
                "first_name": "Jane",
                "period": "1",
            }
        ],
    }
    assignment = {
        "assignment_id": "quiz",
        "title": "Quiz",
        "question_count": 1,
        "choices": ["A", "B", "C", "D"],
        "answer_key": {"1": "A"},
        "standards": {"1": []},
    }
    assert (
        setup_assignment_folder(roster, assignment, workspace_root=tmp_path) is not None
    )
    source = tmp_path / "retained" / "scan.pdf"
    source.parent.mkdir()
    source.write_bytes(b"scan")

    result = file_resolution_scan_copy(
        tmp_path, "class1", "quiz", source, "manual_marks"
    )

    scans_dir = scoreform_work_paths(tmp_path, "class1", "quiz").scans_dir
    assert result.filed
    assert result.filed_relative_path is not None
    assert (tmp_path / result.filed_relative_path).parent == scans_dir
    assert result.sha256 is not None
    assert source.read_bytes() == b"scan"


def test_resolution_copy_rejects_symlink_and_preserves_source(tmp_path) -> None:
    target = tmp_path / "target.pdf"
    target.write_bytes(b"scan")
    link = tmp_path / "link.pdf"
    try:
        link.symlink_to(target)
    except OSError:
        return
    result = file_resolution_scan_copy(tmp_path, "class1", "quiz", link, "manual_marks")
    assert not result.filed
    assert target.read_bytes() == b"scan"


def test_resolution_copy_removes_destination_on_digest_mismatch(
    tmp_path, monkeypatch
) -> None:
    roster = {
        "class_id": "class1",
        "students": [
            {
                "student_id": "1001",
                "last_name": "Doe",
                "first_name": "Jane",
                "period": "1",
            }
        ],
    }
    assignment = {
        "assignment_id": "quiz",
        "title": "Quiz",
        "question_count": 1,
        "choices": ["A", "B", "C", "D"],
        "answer_key": {"1": "A"},
        "standards": {"1": []},
    }
    assert setup_assignment_folder(roster, assignment, workspace_root=tmp_path)
    source = tmp_path / "retained" / "scan.pdf"
    source.parent.mkdir()
    source.write_bytes(b"scan")
    digests = iter(("a" * 64, "b" * 64))
    monkeypatch.setattr(scan_filing, "_sha256", lambda _path: next(digests))

    result = file_resolution_scan_copy(
        tmp_path, "class1", "quiz", source, "manual_marks"
    )

    assert not result.filed
    assert source.read_bytes() == b"scan"
    scans_dir = scoreform_work_paths(tmp_path, "class1", "quiz").scans_dir
    assert list(scans_dir.iterdir()) == []


def test_resolution_copy_rejects_symlinked_scans_directory(tmp_path) -> None:
    _setup_review_assignment(tmp_path)
    source = tmp_path / "source.pdf"
    source.write_bytes(b"scan")
    scans_dir = scoreform_work_paths(tmp_path, "class1", "quiz").scans_dir
    scans_dir.rmdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        scans_dir.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Directory symlinks are unavailable.")
    result = file_resolution_scan_copy(
        tmp_path, "class1", "quiz", source, "manual_marks", failure_id="failure1"
    )
    assert not result.filed
    assert not tuple(outside.iterdir())


def test_resolution_copy_rejects_source_outside_workspace(tmp_path) -> None:
    _setup_review_assignment(tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}_outside.pdf"
    outside.write_bytes(b"private")
    try:
        result = file_resolution_scan_copy(
            tmp_path,
            "class1",
            "quiz",
            outside,
            "manual_marks",
            failure_id="failure1",
        )
        assert not result.filed
        assert outside.read_bytes() == b"private"
    finally:
        outside.unlink(missing_ok=True)


def test_resolution_copy_reports_cleanup_failure_and_preserves_source(
    tmp_path,
) -> None:
    _setup_review_assignment(tmp_path)
    source = tmp_path / "source.pdf"
    source.write_bytes(b"original")

    def corrupt_copy(_source, destination):
        destination.write_bytes(b"corrupt")

    def fail_cleanup(_path, *, missing_ok):
        raise PermissionError("cleanup denied")

    result = file_resolution_scan_copy(
        tmp_path,
        "class1",
        "quiz",
        source,
        "manual_marks",
        failure_id="failure1",
        copy_func=corrupt_copy,
        unlink_func=fail_cleanup,
    )
    assert not result.filed
    assert isinstance(result.error, OSError)
    assert isinstance(result.cleanup_error, PermissionError)
    assert result.filed_relative_path is not None
    assert result.sha256 == scan_filing._sha256(source)
    assert source.read_bytes() == b"original"


def test_resolution_copy_retry_reuses_verified_failure_destination(tmp_path) -> None:
    _setup_review_assignment(tmp_path)
    source = tmp_path / "source.pdf"
    source.write_bytes(b"original")
    first = file_resolution_scan_copy(
        tmp_path, "class1", "quiz", source, "manual_marks", failure_id="failure1"
    )
    second = file_resolution_scan_copy(
        tmp_path, "class1", "quiz", source, "manual_marks", failure_id="failure1"
    )
    assert first.filed and second.filed
    assert first.filed_relative_path == second.filed_relative_path
    scans = scoreform_work_paths(tmp_path, "class1", "quiz").scans_dir
    assert len(tuple(scans.iterdir())) == 1
    source.write_bytes(b"changed")
    contradiction = file_resolution_scan_copy(
        tmp_path, "class1", "quiz", source, "manual_marks", failure_id="failure1"
    )
    assert not contradiction.filed
    assert "Contradictory reuse" in str(contradiction.error)


@pytest.mark.parametrize(
    "source,filed",
    [
        ("C:/private/source.pdf", None),
        ("folder\\source.pdf", None),
        ("folder/../source.pdf", None),
        ("folder//source.pdf", None),
        ("source.pdf", "D:/filed.pdf"),
        ("source.pdf", "folder\\filed.pdf"),
    ],
)
def test_evidence_result_rejects_platform_independent_unsafe_paths(
    source, filed
) -> None:
    with pytest.raises(ValueError):
        ReviewEvidenceFilingResult(
            source,
            filed,
            "manual_marks",
            "a" * 64,
            OSError("failed"),
        )


def test_unavailable_evidence_source_requires_failed_prevalidation() -> None:
    failed = ReviewEvidenceFilingResult(
        "unavailable",
        None,
        "manual_marks",
        None,
        ValueError("prevalidation failed"),
    )
    assert not failed.filed
    with pytest.raises(ValueError, match="failed prevalidation"):
        ReviewEvidenceFilingResult(
            "unavailable", None, "manual_marks", None
        )


def test_resolution_copy_rejects_source_through_symlinked_ancestor(tmp_path) -> None:
    _setup_review_assignment(tmp_path)
    real = tmp_path / "real"
    real.mkdir()
    (real / "source.pdf").write_bytes(b"source")
    link = tmp_path / "link"
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("Directory symlinks are unavailable.")
    result = file_resolution_scan_copy(
        tmp_path,
        "class1",
        "quiz",
        "link/source.pdf",
        "manual_marks",
        failure_id="failure1",
    )
    assert not result.filed
    assert "symlink component" in str(result.error)


def _setup_review_assignment(root) -> None:
    roster = {
        "class_id": "class1",
        "students": [
            {
                "student_id": "1001",
                "last_name": "Doe",
                "first_name": "Jane",
                "period": "1",
            }
        ],
    }
    assignment = {
        "assignment_id": "quiz",
        "title": "Quiz",
        "question_count": 1,
        "choices": ["A", "B", "C", "D"],
        "answer_key": {"1": "A"},
        "standards": {"1": []},
    }
    assert setup_assignment_folder(roster, assignment, workspace_root=root)
