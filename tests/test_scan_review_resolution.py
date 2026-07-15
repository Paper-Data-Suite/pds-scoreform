"""Interim service boundaries for scan-review schema migration issue #145."""

import pytest

from scoreform.migration import ScoreFormMigrationPendingError
from scoreform.scan_review_resolution import (
    preserve_qr_batch_failures_for_review,
    resolve_scan_review_item,
)


def test_failure_persistence_waits_for_schema_v2(tmp_path) -> None:
    with pytest.raises(ScoreFormMigrationPendingError, match=r"#145"):
        preserve_qr_batch_failures_for_review([], "scan.pdf", tmp_path)


def test_resolution_waits_for_schema_v2(tmp_path) -> None:
    with pytest.raises(ScoreFormMigrationPendingError, match=r"#145"):
        resolve_scan_review_item(tmp_path, "failure1", "defer")
