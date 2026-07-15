"""Interim QR-processing boundaries for migration issue #143."""

import pytest

from scoreform.migration import ScoreFormMigrationPendingError
from scoreform.scoring import process_file_qr_aware, update_qr_batch_result_write_status


def test_qr_batch_processing_is_deliberately_unavailable() -> None:
    with pytest.raises(ScoreFormMigrationPendingError, match=r"#143"):
        process_file_qr_aware("scan.pdf")


def test_qr_result_routing_is_deliberately_unavailable() -> None:
    with pytest.raises(ScoreFormMigrationPendingError, match=r"#139 and #143"):
        update_qr_batch_result_write_status([{"class_id": "c", "assignment_id": "a"}], True)
