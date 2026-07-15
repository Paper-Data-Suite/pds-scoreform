"""Interim assignment-local scan filing boundaries."""

import pytest

from scoreform.migration import ScoreFormMigrationPendingError
from scoreform.scan_filing import file_resolution_scan_copy


def test_resolution_copy_stops_before_creating_assignment_artifacts(tmp_path) -> None:
    source = tmp_path / "scan.pdf"
    source.write_bytes(b"scan")

    with pytest.raises(ScoreFormMigrationPendingError, match=r"#139 and #145"):
        file_resolution_scan_copy(tmp_path, "class1", "quiz", source, "deferred")

    assert list(tmp_path.iterdir()) == [source]
