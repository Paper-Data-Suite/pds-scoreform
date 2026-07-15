"""Interim assignment-local filing boundary coverage."""

from scoreform.scan_filing import file_original_scan_after_success


def test_off_mode_remains_a_noop() -> None:
    result = file_original_scan_after_success([], "missing.pdf", mode="off")
    assert result.skipped_reason == "scan filing mode is off"


def test_copy_and_move_modes_skip_when_no_results_exist() -> None:
    for mode in ("copy", "move"):
        result = file_original_scan_after_success([], "missing.pdf", mode=mode)
        assert result.skipped_reason == "no pages scored successfully"
