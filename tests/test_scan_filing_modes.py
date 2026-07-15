"""Interim assignment-local filing boundary coverage."""

import pytest

from scoreform.migration import ScoreFormMigrationPendingError
from scoreform.scan_filing import file_original_scan_after_success


def test_off_mode_remains_a_noop() -> None:
    result = file_original_scan_after_success([], "missing.pdf", mode="off")
    assert result.skipped_reason == "scan filing mode is off"


def test_copy_and_move_modes_wait_for_module_storage() -> None:
    for mode in ("copy", "move"):
        with pytest.raises(ScoreFormMigrationPendingError, match=r"#139 and #143"):
            file_original_scan_after_success([], "missing.pdf", mode=mode)
