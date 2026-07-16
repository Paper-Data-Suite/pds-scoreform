"""Helpers for filing scored source scans into assignment scan folders."""

import hashlib
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath, PureWindowsPath

from scoreform import workspace
from scoreform.assignment import load_assignment
from scoreform.scan_filing_settings import (
    DEFAULT_SCAN_FILING_MODE,
    SCAN_FILING_MODES,
)
from scoreform.validation import is_safe_identifier
from scoreform.work_paths import scoreform_work_paths


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


@dataclass(frozen=True, slots=True)
class ReviewEvidenceFilingResult:
    source_relative_path: str
    filed_relative_path: str | None
    status_tag: str
    sha256: str | None
    error: Exception | None = None
    cleanup_error: Exception | None = None

    def __post_init__(self) -> None:
        for name in ("source_relative_path", "filed_relative_path"):
            value = getattr(self, name)
            if value is None and name == "filed_relative_path":
                continue
            if not isinstance(value, str) or not value or value == "unavailable":
                if name == "source_relative_path" and value == "unavailable":
                    continue
                raise ValueError(f"{name} must be a safe relative path.")
            if "\\" in value:
                raise ValueError(f"{name} must use forward slashes.")
            windows, posix = PureWindowsPath(value), PurePosixPath(value)
            parts = value.split("/")
            if (
                windows.is_absolute()
                or windows.drive
                or posix.is_absolute()
                or any(part in {"", ".", ".."} for part in parts)
            ):
                raise ValueError(f"{name} must be a safe relative path.")
        if self.status_tag not in {
            "manual_entry", "manual_marks", "rescan_needed", "scoring_failed"
        }:
            raise ValueError("status_tag is unsupported.")
        if self.sha256 is not None and re.fullmatch(r"[0-9a-f]{64}", self.sha256) is None:
            raise ValueError("sha256 must be a full hexadecimal digest or null.")
        if self.error is not None and not isinstance(self.error, Exception):
            raise TypeError("error must be an Exception or null.")
        if self.cleanup_error is not None and not isinstance(self.cleanup_error, Exception):
            raise TypeError("cleanup_error must be an Exception or null.")
        if self.cleanup_error is not None and self.error is None:
            raise ValueError("cleanup_error requires a copy or verification error.")
        if self.source_relative_path == "unavailable" and (
            self.error is None or self.filed_relative_path is not None
        ):
            raise ValueError(
                "unavailable source is valid only for failed prevalidation."
            )

    @property
    def filed(self) -> bool:
        return (
            self.filed_relative_path is not None
            and self.error is None
            and self.cleanup_error is None
        )


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
    def value(result, name):
        if hasattr(result, name):
            return getattr(result, name)
        return result.get(name)

    if any(
        not value(result, "class_id") or not value(result, "assignment_id")
        for result in results
    ):
        return None

    targets = {
        (value(result, "class_id"), value(result, "assignment_id"))
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


def _reject_symlink_components(root: Path, candidate: Path) -> None:
    """Reject any existing symlink from root through the lexical candidate path."""
    try:
        relative = candidate.absolute().relative_to(root)
    except ValueError as error:
        raise ValueError("Evidence source must stay inside the workspace.") from error
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("Evidence path cannot contain a symlink component.")


def file_resolution_scan_copy(
    workspace_root,
    class_id,
    assignment_id,
    source_path,
    status_tag,
    now=None,
    copy_func=shutil.copy2,
    failure_id=None,
    unlink_func=Path.unlink,
):
    """Copy and digest-verify assignment evidence; never alter its source."""
    raw_root = Path(workspace_root)
    if raw_root.is_symlink():
        return ReviewEvidenceFilingResult(
            "unavailable", None, status_tag, None,
            ValueError("Review evidence workspace root cannot be a symlink."),
        )
    root = raw_root.resolve(strict=True)
    candidate = Path(source_path)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        _reject_symlink_components(root, candidate)
        source = candidate.resolve(strict=True)
        source_relative = source.relative_to(root).as_posix()
        if not source.is_file():
            raise ValueError("Review evidence source must be a regular file.")
        if not is_safe_identifier(class_id) or not is_safe_identifier(assignment_id):
            raise ValueError("Managed class or assignment identity is invalid.")
        if failure_id is not None and not is_safe_identifier(failure_id):
            raise ValueError("Review failure identity is invalid.")
        paths = scoreform_work_paths(root, class_id, assignment_id)
        assignment = None
        if (
            not paths.work_root.is_symlink()
            and paths.work_root.is_dir()
            and not paths.assignment_path.is_symlink()
            and paths.assignment_path.is_file()
        ):
            assignment = load_assignment(paths.assignment_path)
        if assignment is None or assignment.get("assignment_id") != assignment_id:
            raise ValueError("The selected managed ScoreForm assignment is invalid.")
        managed_root = paths.work_root.resolve(strict=True)
        if managed_root != paths.work_root.absolute():
            raise ValueError("Managed ScoreForm work root resolves unexpectedly.")
        if paths.scans_dir.exists():
            if paths.scans_dir.is_symlink() or not paths.scans_dir.is_dir():
                raise ValueError("Managed scans directory must be a real directory.")
        else:
            paths.scans_dir.mkdir()
        scans_root = paths.scans_dir.resolve(strict=True)
        if scans_root.parent != managed_root:
            raise ValueError("Managed scans directory escapes the exact work root.")
        source_digest = _sha256(source)
        if failure_id is None:
            filed_path = Path(
                build_resolution_scan_path(paths.scans_dir, source, status_tag, now=now)
            )
        else:
            extension = source.suffix
            filed_path = paths.scans_dir / f"review_{failure_id}_{status_tag}{extension}"
        if filed_path.exists() or filed_path.is_symlink():
            if filed_path.is_symlink() or not filed_path.is_file():
                raise FileExistsError(filed_path)
            if failure_id is None or _sha256(filed_path) != source_digest:
                raise ValueError("Contradictory reuse of review evidence identity.")
            return ReviewEvidenceFilingResult(
                source_relative,
                filed_path.relative_to(root).as_posix(),
                status_tag,
                source_digest,
            )
        created = False
        copy_error = None
        cleanup_error = None
        try:
            if copy_func is shutil.copy2:
                with source.open("rb") as input_file, filed_path.open(
                    "xb"
                ) as output_file:
                    created = True
                    shutil.copyfileobj(input_file, output_file, 1024 * 1024)
                    output_file.flush()
                    os.fsync(output_file.fileno())
            else:
                copy_func(source, filed_path)
                created = filed_path.exists()
                with filed_path.open("r+b") as output_file:
                    output_file.flush()
                    os.fsync(output_file.fileno())
            destination_digest = _sha256(filed_path)
            if source_digest != destination_digest:
                raise OSError("Review evidence digest verification failed.")
        except Exception as error:
            copy_error = error
            if created:
                try:
                    unlink_func(filed_path, missing_ok=True)
                except Exception as cleanup:
                    cleanup_error = cleanup
            filed_relative = (
                filed_path.relative_to(root).as_posix()
                if filed_path.exists() or filed_path.is_symlink()
                else None
            )
            return ReviewEvidenceFilingResult(
                source_relative,
                filed_relative,
                status_tag,
                source_digest,
                copy_error,
                cleanup_error,
            )
        return ReviewEvidenceFilingResult(
            source_relative,
            filed_path.relative_to(root).as_posix(),
            status_tag,
            source_digest,
        )
    except Exception as error:
        try:
            relative = candidate.resolve(strict=False).relative_to(root).as_posix()
        except (OSError, RuntimeError, ValueError):
            relative = "unavailable"
        digest = None
        try:
            if not candidate.is_symlink() and candidate.is_file():
                digest = _sha256(candidate)
        except OSError:
            pass
        return ReviewEvidenceFilingResult(relative, None, status_tag, digest, error)


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
        paths = scoreform_work_paths(workspace_root, class_id, assignment_id)
        assignment = (
            load_assignment(paths.assignment_path)
            if (
                not paths.work_root.is_symlink()
                and paths.work_root.is_dir()
                and not paths.assignment_path.is_symlink()
                and paths.assignment_path.is_file()
            )
            else None
        )
        if assignment is None or assignment.get("assignment_id") != assignment_id:
            return ScanFilingResult(
                mode=mode,
                source_path=source,
                warning="The selected ScoreForm assignment does not exist.",
            )
        scans_dir = paths.scans_dir
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
