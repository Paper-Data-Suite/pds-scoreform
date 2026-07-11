import datetime
import json
from pathlib import Path

from scoreform import scan_filing
from scoreform.scan_filing_settings import (
    get_scan_filing_mode,
    inspect_scan_filing_settings,
    reset_scan_filing_mode,
    set_scan_filing_mode,
)


def _result(assignment_id="quiz"):
    return {
        "class_id": "class_a",
        "assignment_id": assignment_id,
        "student_id": "1001",
    }


def test_missing_settings_defaults_to_copy(tmp_path):
    settings = inspect_scan_filing_settings(tmp_path)

    assert settings.effective_mode == "copy"
    assert not settings.exists
    assert settings.path == tmp_path / ".pds" / "scoreform.json"


def test_set_modes_and_reset_preserve_unrelated_keys(tmp_path):
    path = tmp_path / ".pds" / "scoreform.json"
    path.parent.mkdir()
    path.write_text('{"future_key": 42}', encoding="utf-8")

    for mode in ("copy", "move", "off"):
        assert set_scan_filing_mode(mode, tmp_path).effective_mode == mode
        assert get_scan_filing_mode(tmp_path) == mode
        assert json.loads(path.read_text(encoding="utf-8"))["future_key"] == 42

    settings = reset_scan_filing_mode(tmp_path)
    assert settings.effective_mode == "copy"
    assert json.loads(path.read_text(encoding="utf-8")) == {"future_key": 42}


def test_invalid_settings_fall_back_to_copy(tmp_path):
    path = tmp_path / ".pds" / "scoreform.json"
    path.parent.mkdir()
    path.write_text('{"scan_filing_mode": "unsafe"}', encoding="utf-8")

    settings = inspect_scan_filing_settings(tmp_path)

    assert settings.configured_mode == "unsafe"
    assert settings.effective_mode == "copy"
    assert settings.warning


def test_move_copies_verifies_then_removes_direct_inbox_child(tmp_path):
    source = tmp_path / "scans_inbox" / "batch.pdf"
    source.parent.mkdir()
    source.write_bytes(b"scan data")
    retained = tmp_path / "scans" / "source" / "2026-07-11" / "batch.pdf"
    retained.parent.mkdir(parents=True)
    retained.write_bytes(b"scan data")

    result = scan_filing.file_original_scan_after_success(
        [_result()],
        source,
        mode="move",
        now=datetime.datetime(2026, 7, 11, 9, 30),
        workspace_root=tmp_path,
    )

    assert result.filed
    assert result.original_removed
    assert not source.exists()
    assert Path(result.filed_path).read_bytes() == b"scan data"
    assert retained.read_bytes() == b"scan data"


def test_move_preserves_external_and_nested_sources(tmp_path):
    for source in (
        tmp_path / "custom" / "batch.pdf",
        tmp_path / "scans_inbox" / "nested" / "batch.pdf",
    ):
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"scan")

        result = scan_filing.file_original_scan_after_success(
            [_result()], source, mode="move", workspace_root=tmp_path
        )

        assert result.filed
        assert not result.original_removed
        assert source.exists()
        assert "not a direct child" in result.cleanup_skipped_reason


def test_move_preserves_source_when_verification_fails(tmp_path):
    source = tmp_path / "scans_inbox" / "batch.pdf"
    source.parent.mkdir()
    source.write_bytes(b"source")

    def corrupt_copy(_source, destination):
        Path(destination).write_bytes(b"different")

    result = scan_filing.file_original_scan_after_success(
        [_result()],
        source,
        mode="move",
        copy_func=corrupt_copy,
        workspace_root=tmp_path,
    )

    assert source.exists()
    assert not result.original_removed
    assert "verification failed" in result.cleanup_skipped_reason


def test_move_unlink_failure_keeps_filed_copy_and_original(tmp_path):
    source = tmp_path / "scans_inbox" / "batch.pdf"
    source.parent.mkdir()
    source.write_bytes(b"scan")

    def fail_unlink(_path):
        raise PermissionError("locked")

    result = scan_filing.file_original_scan_after_success(
        [_result()],
        source,
        mode="move",
        unlink_func=fail_unlink,
        workspace_root=tmp_path,
    )

    assert result.filed
    assert Path(result.filed_path).exists()
    assert source.exists()
    assert "locked" in result.warning


def test_off_skips_only_assignment_local_copy(tmp_path):
    source = tmp_path / "scans_inbox" / "batch.pdf"
    source.parent.mkdir()
    source.write_bytes(b"scan")
    retained = tmp_path / "scans" / "source" / "2026-07-11" / "batch.pdf"
    retained.parent.mkdir(parents=True)
    retained.write_bytes(b"scan")

    result = scan_filing.file_original_scan_after_success(
        [_result()], source, mode="off", workspace_root=tmp_path
    )

    assert not result.filed
    assert result.skipped_reason == "scan filing mode is off"
    assert source.exists()
    assert retained.exists()
    assert not (tmp_path / "classes").exists()


def test_symlink_source_is_never_eligible_for_inbox_cleanup(tmp_path):
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"scan")
    inbox = tmp_path / "scans_inbox"
    inbox.mkdir()
    link = inbox / "linked.pdf"
    try:
        link.symlink_to(outside)
    except OSError:
        return

    assert not scan_filing.is_direct_child_of_scans_inbox(link, tmp_path)
