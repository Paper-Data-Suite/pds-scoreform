"""Retained PDS2 QR-processing result boundary."""

from scoreform.scoring import process_file_qr_aware, update_qr_batch_result_write_status


def test_qr_batch_processing_returns_immutable_file_failure(tmp_path) -> None:
    result = process_file_qr_aware("scan.pdf", workspace_root=tmp_path)
    assert result.retained_source is None
    assert result.file_error is not None
    assert result.pages == ()


def test_qr_result_status_uses_canonical_storage_path(tmp_path) -> None:
    class Results(list):
        summary = None

    results = Results([{"class_id": "c", "assignment_id": "a"}])
    update_qr_batch_result_write_status(results, True, workspace_root=tmp_path)

    assert list(tmp_path.iterdir()) == []
