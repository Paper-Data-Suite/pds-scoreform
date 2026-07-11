"""Helpers for filing scored source scans into assignment scan folders."""

import hashlib
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime

from pds_core.routes import assignment_scans_dir as core_assignment_scans_dir

from scoreform import workspace
from scoreform.scan_filing_settings import (
    DEFAULT_SCAN_FILING_MODE,
    SCAN_FILING_MODES,
)


@dataclass
class ScanFilingResult:
    filed_path: str | None = None
    source_path: str | None = None
    skipped_reason: str | None = None
    warning: str | None = None
    mode: str = DEFAULT_SCAN_FILING_MODE
    original_removed: bool = False
    cleanup_skipped_reason: str | None = None

    @property
    def filed(self):
        return self.filed_path is not None


def skipped_scan_filing_for_batch_outcome(outcome):
    """Return the conservative filing decision for a non-successful QR batch."""
    if outcome == "partial_success":
        return ScanFilingResult(
            warning=(
                "Scan filing skipped: QR batch was PARTIAL SUCCESS.\n"
                "The source scan was not filed automatically because one or more "
                "pages failed or were skipped.\n"
                "Review the saved QR batch summary before filing the original scan "
                "manually."
            )
        )
    if outcome in {"zero_success", "export_failure"}:
        return ScanFilingResult(
            warning=(
                "Scan filing skipped: QR batch did not complete successfully.\n"
                "The source scan was not filed automatically. Review the QR batch "
                "summary before filing it manually."
            )
        )
    return ScanFilingResult(
        warning=(
            "Scan filing skipped: QR batch status was unavailable.\n"
            "The source scan was not filed automatically."
        )
    )


def _single_assignment_target(results):
    if any(
        not result.get("class_id") or not result.get("assignment_id")
        for result in results
    ):
        return None

    targets = {
        (result.get("class_id"), result.get("assignment_id"))
        for result in results
    }
    if not targets:
        return None
    if len(targets) > 1:
        return "multiple"
    return next(iter(targets))


def _safe_filename_stem(source_path):
    stem = os.path.splitext(os.path.basename(os.fspath(source_path)))[0]
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", stem).strip("_")
    return stem or "scan"


def _non_overwriting_path(path):
    if not os.path.exists(path):
        return path

    root, ext = os.path.splitext(path)
    counter = 2
    while True:
        candidate = f"{root}_{counter}{ext}"
        if not os.path.exists(candidate):
            return candidate
        counter += 1


def build_filed_scan_path(scans_dir, source_path, now=None):
    timestamp = now or datetime.now()
    extension = os.path.splitext(os.path.basename(os.fspath(source_path)))[1]
    filename = (
        f"{_safe_filename_stem(source_path)}_"
        f"{timestamp.strftime('%Y-%m-%d_%H%M%S')}_scored"
        f"{extension}"
    )
    return _non_overwriting_path(os.path.join(os.fspath(scans_dir), filename))


def build_resolution_scan_path(scans_dir, source_path, status_tag, now=None):
    """Return a readable, non-overwriting assignment-local evidence path."""
    if status_tag not in {
        "manual_entry",
        "manual_marks",
        "rescan_needed",
        "scoring_failed",
    }:
        raise ValueError(f"Unsupported scan evidence status tag: {status_tag}")
    timestamp = now or datetime.now()
    extension = os.path.splitext(os.path.basename(os.fspath(source_path)))[1]
    filename = (
        f"{_safe_filename_stem(source_path)}_"
        f"{timestamp.strftime('%Y-%m-%d_%H%M%S')}_{status_tag}{extension}"
    )
    return _non_overwriting_path(os.path.join(os.fspath(scans_dir), filename))


def file_resolution_scan_copy(
    workspace_root,
    class_id,
    assignment_id,
    source_path,
    status_tag,
    now=None,
    copy_func=shutil.copy2,
):
    """Copy retained review evidence without moving or overwriting its source."""
    source = os.fspath(source_path)
    if not os.path.isfile(source):
        return ScanFilingResult(
            source_path=source,
            warning=f"Review evidence is missing or is not a file: {source}",
        )
    try:
        scans_dir = core_assignment_scans_dir(
            workspace_root, class_id, assignment_id
        )
        if not scans_dir.parent.is_dir():
            return ScanFilingResult(
                source_path=source,
                warning="The selected assignment folder does not exist.",
            )
        os.makedirs(scans_dir, exist_ok=True)
        filed_path = build_resolution_scan_path(
            scans_dir, source, status_tag, now=now
        )
        copy_func(source, filed_path)
    except Exception as error:
        return ScanFilingResult(
            source_path=source,
            warning=f"Could not file scan review evidence: {error}",
        )
    return ScanFilingResult(filed_path=os.fspath(filed_path), source_path=source)


def file_original_scan_copy(
    results,
    source_path,
    now=None,
    copy_func=shutil.copy2,
    workspace_root=None,
):
    """Copy a full-success scored source into one assignment scan folder.

    This is assignment-local scored-copy filing, not canonical active source
    retention. Canonical retained sources live under ``scans/source/YYYY-MM-DD/``
    through pds-core.
    """
    return file_original_scan_after_success(
        results,
        source_path,
        mode="copy",
        now=now,
        copy_func=copy_func,
        workspace_root=workspace_root,
    )


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as source_file:
        for block in iter(lambda: source_file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def is_direct_child_of_scans_inbox(path, workspace_root) -> bool:
    """Return whether path is a real file directly inside this workspace inbox."""
    try:
        source_path = os.path.abspath(os.fspath(path))
        workspace_path = os.path.abspath(os.fspath(workspace_root))
        inbox_path = os.path.join(workspace_path, "scans_inbox")
        if os.path.normcase(os.path.dirname(source_path)) != os.path.normcase(
            inbox_path
        ):
            return False

        workspace_real = os.path.realpath(workspace_path)
        inbox_real = os.path.realpath(inbox_path)
        source_real = os.path.realpath(source_path)
        if os.path.normcase(os.path.commonpath([workspace_real, inbox_real])) != (
            os.path.normcase(workspace_real)
        ):
            return False
        return os.path.isfile(source_path) and os.path.normcase(
            os.path.dirname(source_real)
        ) == os.path.normcase(inbox_real)
    except (OSError, TypeError, ValueError):
        return False


def file_original_scan_after_success(
    results,
    source_path,
    *,
    mode,
    now=None,
    copy_func=shutil.copy2,
    unlink_func=os.unlink,
    workspace_root=None,
):
    """Apply one post-success assignment-local scan filing mode safely."""
    if mode not in SCAN_FILING_MODES:
        mode = DEFAULT_SCAN_FILING_MODE

    source = os.fspath(source_path)
    if mode == "off":
        return ScanFilingResult(
            mode=mode,
            source_path=source,
            skipped_reason="scan filing mode is off",
        )

    if not results:
        return ScanFilingResult(
            mode=mode,
            source_path=source,
            skipped_reason="no pages scored successfully",
        )

    target = _single_assignment_target(results)
    if target is None:
        return ScanFilingResult(
            mode=mode,
            source_path=source,
            skipped_reason="no assignment target was detected",
        )
    if target == "multiple":
        return ScanFilingResult(
            mode=mode,
            source_path=source,
            skipped_reason=(
                "source scan was not filed because scored pages resolved to "
                "multiple assignment targets"
            ),
        )

    if not os.path.exists(source):
        return ScanFilingResult(
            mode=mode,
            source_path=source,
            warning=f"Scan filing skipped: source scan is missing: {source}",
        )
    if not os.path.isfile(source):
        return ScanFilingResult(
            mode=mode,
            source_path=source,
            warning=f"Scan filing skipped: source scan is not a file: {source}",
        )

    class_id, assignment_id = target
    try:
        if workspace_root is None:
            workspace_root = workspace.get_scoreform_workspace_root()
        scans_dir = core_assignment_scans_dir(workspace_root, class_id, assignment_id)
        os.makedirs(scans_dir, exist_ok=True)
        filed_path = build_filed_scan_path(scans_dir, source, now=now)
        copy_func(source, filed_path)
    except Exception as error:
        return ScanFilingResult(
            mode=mode,
            source_path=source,
            warning=f"Warning: Scan filing failed after results export: {error}",
        )

    filed = os.fspath(filed_path)
    if mode == "copy":
        return ScanFilingResult(mode=mode, filed_path=filed, source_path=source)

    try:
        if not os.path.isfile(filed):
            raise OSError("filed destination does not exist or is not a file")
        if os.path.islink(filed) or os.path.samefile(source, filed):
            raise OSError("filed destination is not an independent copy")
        if _sha256(source) != _sha256(filed):
            raise OSError("filed destination does not match the source")
    except (OSError, ValueError) as error:
        reason = f"destination verification failed: {error}"
        return ScanFilingResult(
            mode=mode,
            filed_path=filed if os.path.exists(filed) else None,
            source_path=source,
            cleanup_skipped_reason=reason,
            warning=(
                "Scan filing mode is move, but the filed copy could not be verified. "
                "The original source was preserved."
            ),
        )

    if not is_direct_child_of_scans_inbox(source, workspace_root):
        reason = "selected source is not a direct child of scans_inbox"
        return ScanFilingResult(
            mode=mode,
            filed_path=filed,
            source_path=source,
            cleanup_skipped_reason=reason,
            warning=(
                "Scan filing mode is move, but the selected source is not a direct "
                "child of scans_inbox.\nThe assignment-local copy was filed, and "
                "the original source was preserved."
            ),
        )

    try:
        unlink_func(source)
    except OSError as error:
        return ScanFilingResult(
            mode=mode,
            filed_path=filed,
            source_path=source,
            cleanup_skipped_reason=f"could not remove inbox original: {error}",
            warning=(
                "The assignment-local copy was filed, but the scans_inbox original "
                f"could not be removed: {error}"
            ),
        )

    return ScanFilingResult(
        mode=mode,
        filed_path=filed,
        source_path=source,
        original_removed=True,
    )


def print_scan_filing_result(result):
    if result is None:
        return
    if result.filed:
        print("Filed scan copy:")
        print(result.filed_path)
        if result.original_removed:
            print("Removed scans_inbox original after verified filing:")
            print(result.source_path)
        else:
            print("Original scan preserved:")
            print(result.source_path)
        if result.warning:
            print(result.warning)
        return
    if result.warning:
        print(result.warning)
    elif result.skipped_reason:
        print(f"Scan filing skipped: {result.skipped_reason}.")
