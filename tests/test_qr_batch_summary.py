"""Interim QR-processing boundaries for migration issue #143."""

import pytest

from scoreform.migration import ScoreFormMigrationPendingError
from scoreform.scoring import process_file_qr_aware, update_qr_batch_result_write_status


def test_qr_batch_processing_is_deliberately_unavailable() -> None:
    with pytest.raises(ScoreFormMigrationPendingError, match=r"#143"):
        process_file_qr_aware("scan.pdf")


def test_qr_result_status_uses_canonical_storage_path(tmp_path) -> None:
    class Results(list):
        summary = None

    results = Results([{"class_id": "c", "assignment_id": "a"}])
    update_qr_batch_result_write_status(results, True, workspace_root=tmp_path)

    assert list(tmp_path.iterdir()) == []
