"""Helpers for filing scored source scans into assignment scan folders."""

import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime

from pds_core.routes import assignment_scans_dir as core_assignment_scans_dir

from scoreform import workspace


@dataclass
class ScanFilingResult:
    filed_path: str | None = None
    source_path: str | None = None
    skipped_reason: str | None = None
    warning: str | None = None

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


def file_original_scan_copy(
    results,
    source_path,
    now=None,
    copy_func=shutil.copy2,
    workspace_root=None,
):
    """Copy a successfully scored source scan into one assignment scan folder."""
    if not results:
        return ScanFilingResult(skipped_reason="no pages scored successfully")

    target = _single_assignment_target(results)
    if target is None:
        return ScanFilingResult(skipped_reason="no assignment target was detected")
    if target == "multiple":
        return ScanFilingResult(
            skipped_reason=(
                "source scan was not filed because scored pages resolved to "
                "multiple assignment targets"
            ),
        )

    source_path = os.fspath(source_path)
    if not os.path.exists(source_path):
        return ScanFilingResult(
            source_path=source_path,
            warning=f"Scan filing skipped: source scan is missing: {source_path}",
        )
    if not os.path.isfile(source_path):
        return ScanFilingResult(
            source_path=source_path,
            warning=f"Scan filing skipped: source scan is not a file: {source_path}",
        )

    class_id, assignment_id = target
    try:
        if workspace_root is None:
            workspace_root = workspace.get_scoreform_workspace_root()
        scans_dir = core_assignment_scans_dir(workspace_root, class_id, assignment_id)
        os.makedirs(scans_dir, exist_ok=True)
        filed_path = build_filed_scan_path(scans_dir, source_path, now=now)
        copy_func(source_path, filed_path)
    except Exception as error:
        return ScanFilingResult(
            source_path=source_path,
            warning=f"Warning: Scan filing failed after results export: {error}",
        )

    return ScanFilingResult(filed_path=os.fspath(filed_path), source_path=source_path)


def print_scan_filing_result(result):
    if result is None:
        return
    if result.filed:
        print("Filed scan copy:")
        print(result.filed_path)
        print("Original scan preserved:")
        print(result.source_path)
        return
    if result.warning:
        print(result.warning)
    elif result.skipped_reason:
        print(f"Scan filing skipped: {result.skipped_reason}.")
