"""Strict Core-v2 discovery, identity projection, and append-only resolution."""

from __future__ import annotations

import os
import re
import secrets
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Mapping

from pds_core.identifiers import validate_identifier
from pds_core.pds2 import parse_pds2_payload, serialize_pds2_payload
from pds_core.route_registrations import resolve_route_registration
from pds_core.routes import class_roster_path
from pds_core.scan_failure_metadata import (
    ROUTING_FAILURE_CATEGORIES,
    RoutingFailureMetadata,
    RoutingFailureMetadataReadError,
    load_routing_failure_metadata,
)
from pds_core.scan_resolution_metadata import (
    ScanResolutionMetadata,
    ScanResolutionMetadataReadError,
    ScanResolutionMetadataWriteError,
    create_scan_resolution_metadata,
    load_scan_resolution_metadata,
    scan_resolution_metadata_path,
    write_scan_resolution_metadata,
)
from pds_core.scan_routes import routing_review_dir

from scoreform.answer_sheet_persistence import load_answer_sheet_page_context
from scoreform.answer_sheet_records import validate_issuance_id, validate_page_id
from scoreform.answer_sheet_routes import (
    AnswerSheetPageRoute,
    validate_answer_sheet_page_route,
    validate_route_id,
)
from scoreform.assignment import load_assignment
from scoreform.diagnostic_events import try_emit_diagnostic_event
from scoreform.manual_entry import build_manual_result, normalize_manual_response
from scoreform.results import export_scoreform_result_models
from scoreform.roster import load_roster
from scoreform.scan_filing import (
    _reject_symlink_components,
    _sha256,
    file_resolution_scan_copy,
)
from scoreform.scan_review_details import (
    ScoreFormFailureDetails,
    ScoreFormResolutionDetails,
    sanitize_single_line,
    scoreform_resolution_details,
    validate_scoreform_failure_details,
    validate_scoreform_resolution_details,
)
from scoreform.validation import is_safe_identifier
from scoreform.work_paths import scoreform_work_paths

RESOLUTION_ACTIONS = (
    "route_selected",
    "route_corrected",
    "manual_entry",
    "manual_marks",
    "rescan_needed",
    "cannot_route",
    "mixed_assignment",
    "evidence_filed",
    "dismissed_duplicate",
    "other",
    "defer",
)
DEFAULT_MESSAGES = {
    "route_selected": "Teacher selected an existing validated ScoreForm route.",
    "route_corrected": "Teacher corrected the route to an existing validated ScoreForm route.",
    "manual_entry": "Teacher entered the paper result manually.",
    "manual_marks": "Teacher recorded manual marks outside automatic scoring.",
    "rescan_needed": "Teacher determined that the paper must be rescanned.",
    "cannot_route": "Teacher could not safely identify a routing destination.",
    "mixed_assignment": "Teacher identified a source with mixed assignment targets.",
    "evidence_filed": "Teacher confirmed review evidence is filed.",
    "dismissed_duplicate": "Teacher dismissed this duplicate review occurrence.",
    "defer": "Teacher deferred this review item for later follow-up.",
}
_NO_EVIDENCE_ACTIONS = frozenset(
    {
        "rescan_needed",
        "cannot_route",
        "dismissed_duplicate",
        "defer",
        "mixed_assignment",
    }
)
_DIAGNOSTIC_RECOVERY_ACTIONS = frozenset(
    {
        "route_selected",
        "route_corrected",
        "manual_entry",
        "manual_marks",
        "evidence_filed",
        "dismissed_duplicate",
    }
)
_V1_PATTERN = re.compile(rb'"schema_version"\s*:\s*"1"')


class ScanReviewError(ValueError):
    """A requested review operation is unsafe or incomplete."""


def _safe_relative_text(value: str, label: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string.")
    windows, posix = PureWindowsPath(value), PurePosixPath(value)
    if "\\" in value:
        raise ValueError(f"{label} must use forward slashes.")
    parts = value.split("/")
    if (
        not value
        or windows.is_absolute()
        or windows.drive
        or posix.is_absolute()
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise ValueError(f"{label} must be workspace-relative and safe.")
    return value


def _canonical_result_path(value: str) -> tuple[str, str]:
    normalized = _safe_relative_text(value, "result_output_path")
    parts = normalized.split("/")
    if (
        len(parts) != 7
        or parts[0] != "classes"
        or parts[2:5] != ["modules", "scoreform", "work"]
        or parts[6] != "results.csv"
        or not is_safe_identifier(parts[1])
        or not is_safe_identifier(parts[5])
    ):
        raise ValueError("result_output_path is not a canonical managed result path.")
    return parts[1], parts[5]


class ScanReviewPartialOperationError(ScanReviewError):
    """A manual result exists but its linked resolution was not appended."""

    def __init__(
        self,
        *,
        failure_id: str,
        result_output_path: str,
        attempt_number: int,
        result_appended: bool,
        result_already_present: bool,
        error: Exception,
    ) -> None:
        super().__init__(
            "The result row exists, but no resolution event was appended. "
            "Retrying will not create another attempt."
        )
        self.failure_id = failure_id
        self.result_output_path = result_output_path
        self.attempt_number = attempt_number
        self.result_appended = result_appended
        self.result_already_present = result_already_present
        self.error = error
        if not is_safe_identifier(failure_id):
            raise ValueError("failure_id is invalid.")
        _canonical_result_path(result_output_path)
        if isinstance(attempt_number, bool) or not isinstance(attempt_number, int) or attempt_number < 1:
            raise ValueError("attempt_number must be positive.")
        if not isinstance(result_appended, bool) or not isinstance(result_already_present, bool):
            raise TypeError("partial-operation flags must be Boolean.")
        if result_appended == result_already_present:
            raise ValueError("Exactly one result outcome flag must be true.")
        if not isinstance(error, Exception):
            raise TypeError("error must be an Exception.")


@dataclass(frozen=True, slots=True)
class ScoreFormReviewIdentity:
    source: str
    class_id: str | None = None
    assignment_id: str | None = None
    student_id: str | None = None
    route_id: str | None = None
    page_id: str | None = None
    issuance_id: str | None = None
    logical_page: int | None = None
    total_pages: int | None = None

    def __post_init__(self) -> None:
        if self.source not in {
            "validated_target",
            "validated_locator",
            "scoreform_diagnostic",
            "none",
        }:
            raise ValueError("identity source is unsupported.")
        identifiers = {
            "class_id": self.class_id,
            "assignment_id": self.assignment_id,
            "student_id": self.student_id,
            "route_id": self.route_id,
            "page_id": self.page_id,
            "issuance_id": self.issuance_id,
        }
        for name, value in identifiers.items():
            if value is not None and not is_safe_identifier(value):
                raise ValueError(f"{name} is invalid.")
        if self.source in {"validated_locator", "validated_target"}:
            for name, validator in (
                ("route_id", validate_route_id),
                ("page_id", validate_page_id),
                ("issuance_id", validate_issuance_id),
            ):
                value = getattr(self, name)
                if value is not None:
                    try:
                        validator(value)
                    except Exception as error:
                        raise ValueError(f"{name} is invalid.") from error
        for name in ("logical_page", "total_pages"):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 1
            ):
                raise ValueError(f"{name} must be positive or null.")
        populated = {name for name, value in identifiers.items() if value is not None}
        if self.source == "none" and (populated or self.logical_page is not None or self.total_pages is not None):
            raise ValueError("none identity must not contain identity fields.")
        if self.source == "validated_locator" and (
            populated != {"class_id", "assignment_id", "route_id"}
            or self.logical_page is not None
            or self.total_pages is not None
        ):
            raise ValueError("validated_locator identity has an invalid field set.")
        if self.source == "validated_target" and (
            populated != set(identifiers)
            or self.logical_page is None
            or self.total_pages is None
        ):
            raise ValueError("validated_target identity must be complete.")
        if (
            self.logical_page is not None
            and self.total_pages is not None
            and self.logical_page > self.total_pages
        ):
            raise ValueError("logical_page cannot exceed total_pages.")


@dataclass(frozen=True, slots=True)
class ScoreFormReviewItem:
    failure_id: str
    metadata: RoutingFailureMetadata
    failure_metadata_path: Path
    failure_metadata_relative_path: str
    details: ScoreFormFailureDetails | None
    identity: ScoreFormReviewIdentity
    diagnostic_identity: ScoreFormReviewIdentity
    resolution_history: tuple[ScanResolutionMetadata, ...] = ()
    resolution_details: tuple[ScoreFormResolutionDetails, ...] = ()
    resolution_paths: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not is_safe_identifier(self.failure_id):
            raise ValueError("failure_id is invalid.")
        if not isinstance(self.metadata, RoutingFailureMetadata):
            raise TypeError("metadata has the wrong model type.")
        if self.metadata.failure_id != self.failure_id:
            raise ValueError("metadata failure identity is inconsistent.")
        if not isinstance(self.failure_metadata_path, Path):
            raise TypeError("failure_metadata_path must be a Path.")
        expected = f"scans/review/{self.failure_id}.json"
        if self.failure_metadata_relative_path != expected:
            raise ValueError("failure metadata relative path is not canonical.")
        if (
            self.failure_metadata_path.name != f"{self.failure_id}.json"
            or self.failure_metadata_path.parent.name != "review"
            or tuple(self.failure_metadata_path.parts[-3:])
            != ("scans", "review", f"{self.failure_id}.json")
        ):
            raise ValueError("failure metadata Path disagrees with failure identity.")
        if self.details is not None and not isinstance(self.details, ScoreFormFailureDetails):
            raise TypeError("details has the wrong model type.")
        if not isinstance(self.identity, ScoreFormReviewIdentity) or not isinstance(
            self.diagnostic_identity, ScoreFormReviewIdentity
        ):
            raise TypeError("review identities have the wrong model type.")
        collections = (
            self.resolution_history,
            self.resolution_details,
            self.resolution_paths,
        )
        if any(not isinstance(value, tuple) for value in collections):
            raise TypeError("resolution collections must be immutable tuples.")
        if len({len(value) for value in collections}) != 1:
            raise ValueError("resolution collections must be aligned.")
        if any(not isinstance(value, ScanResolutionMetadata) for value in self.resolution_history):
            raise TypeError("resolution_history has the wrong model type.")
        if any(not isinstance(value, ScoreFormResolutionDetails) for value in self.resolution_details):
            raise TypeError("resolution_details has the wrong model type.")
        for metadata, path in zip(self.resolution_history, self.resolution_paths):
            if metadata.failure_id != self.failure_id or path != (
                f"scans/review/resolutions/{metadata.resolution_id}.json"
            ):
                raise ValueError("resolution identity or path is inconsistent.")

    @property
    def failure_category(self):
        return self.metadata.failure_category

    @property
    def failure_message(self):
        return self.metadata.failure_message

    @property
    def stage(self):
        return self.metadata.stage

    @property
    def created_at(self):
        return self.metadata.created_at

    @property
    def source_filename(self):
        return self.metadata.source_filename

    @property
    def retained_source_path(self):
        return self.metadata.retained_source_path

    @property
    def review_copy_path(self):
        return self.metadata.review_copy_path

    @property
    def source_scan_id(self):
        return self.metadata.source_scan_id

    @property
    def source_sha256(self):
        return self.metadata.source_sha256

    @property
    def source_page_number(self):
        return self.metadata.source_page_number

    @property
    def detected_payload(self):
        return self.metadata.detected_payload

    @property
    def route_locator(self):
        return self.metadata.route_locator

    @property
    def target(self):
        return self.metadata.target

    @property
    def scoreform_failure_category(self):
        return None if self.details is None else self.details.scoreform_category

    @property
    def observed_identity(self):
        return self.diagnostic_identity

    @property
    def class_id(self):
        return self.identity.class_id or self.diagnostic_identity.class_id

    @property
    def assignment_id(self):
        return self.identity.assignment_id or self.diagnostic_identity.assignment_id

    @property
    def student_id(self):
        return self.identity.student_id or self.diagnostic_identity.student_id

    @property
    def latest_resolution(self):
        return self.resolution_history[-1] if self.resolution_history else None

    @property
    def latest_resolution_details(self):
        return self.resolution_details[-1] if self.resolution_details else None

    @property
    def latest_resolution_status(self):
        return (
            None
            if self.latest_resolution is None
            else self.latest_resolution.resolution_status
        )

    @property
    def latest_resolution_action(self):
        details = self.latest_resolution_details
        return details.teacher_action if details is not None else None

    @property
    def latest_resolution_time(self):
        return (
            None
            if self.latest_resolution is None
            else self.latest_resolution.resolved_at
        )

    @property
    def latest_resolution_path(self):
        return self.resolution_paths[-1] if self.resolution_paths else None

    @property
    def status(self):
        return self.latest_resolution_status or "unresolved"


@dataclass(frozen=True, slots=True)
class ScoreFormResolutionResult:
    resolution_id: str
    resolution_metadata_path: Path
    resolution_metadata_relative_path: str
    failure_id: str
    resolution_status: str
    resolution_action: str
    result_written: bool = False
    result_already_present: bool = False
    evidence_path: str | None = None

    def __post_init__(self) -> None:
        for name in ("resolution_id", "failure_id"):
            if not is_safe_identifier(getattr(self, name)):
                raise ValueError(f"{name} is invalid.")
        if not isinstance(self.resolution_metadata_path, Path):
            raise TypeError("resolution_metadata_path must be a Path.")
        expected = f"scans/review/resolutions/{self.resolution_id}.json"
        if self.resolution_metadata_relative_path != expected:
            raise ValueError("resolution metadata path is not canonical.")
        if (
            self.resolution_metadata_path.name != f"{self.resolution_id}.json"
            or tuple(self.resolution_metadata_path.parts[-4:])
            != ("scans", "review", "resolutions", f"{self.resolution_id}.json")
        ):
            raise ValueError("resolution metadata Path disagrees with resolution identity.")
        if self.resolution_status not in {"resolved", "deferred"}:
            raise ValueError("resolution_status is invalid.")
        if self.resolution_action not in RESOLUTION_ACTIONS:
            raise ValueError("resolution_action is invalid.")
        if not isinstance(self.result_written, bool) or not isinstance(
            self.result_already_present, bool
        ):
            raise TypeError("result outcome flags must be Boolean.")
        if self.resolution_action == "manual_entry":
            if self.result_written == self.result_already_present:
                raise ValueError(
                    "manual_entry requires exactly one result outcome flag."
                )
        elif self.result_written or self.result_already_present:
            raise ValueError("Only manual_entry can report a result outcome.")
        if self.evidence_path is not None:
            _safe_relative_text(self.evidence_path, "evidence_path")


@dataclass(frozen=True, slots=True)
class ScanReviewDiscovery:
    items: tuple[ScoreFormReviewItem, ...]
    invalid_failure_count: int = 0
    invalid_resolution_count: int = 0
    unsupported_v1_failure_count: int = 0
    unsupported_v1_resolution_count: int = 0
    orphan_resolution_count: int = 0
    provenance_mismatch_count: int = 0
    malformed_scoreform_details_count: int = 0
    foreign_record_count: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.items, tuple) or any(
            not isinstance(item, ScoreFormReviewItem) for item in self.items
        ):
            raise TypeError("items must be an immutable tuple of review items.")
        for name in (
            "invalid_failure_count", "invalid_resolution_count",
            "unsupported_v1_failure_count", "unsupported_v1_resolution_count",
            "orphan_resolution_count", "provenance_mismatch_count",
            "malformed_scoreform_details_count", "foreign_record_count",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a nonnegative integer.")

    @property
    def warning_count(self) -> int:
        return sum(
            (
                self.invalid_failure_count,
                self.invalid_resolution_count,
                self.unsupported_v1_failure_count,
                self.unsupported_v1_resolution_count,
                self.orphan_resolution_count,
                self.provenance_mismatch_count,
                self.malformed_scoreform_details_count,
                self.foreign_record_count,
            )
        )


def _utc(now: datetime | None = None) -> datetime:
    value = datetime.now(timezone.utc) if now is None else now
    if value.tzinfo is None or value.utcoffset() is None:
        raise ScanReviewError("Resolution timestamps must be timezone-aware.")
    return value.astimezone(timezone.utc)


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _id(prefix: str, now: datetime) -> str:
    return f"{prefix}_{now.strftime('%Y%m%dT%H%M%S%fZ')}_{secrets.token_hex(8)}"


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve(strict=False).relative_to(root).as_posix()
    except (OSError, RuntimeError, ValueError) as error:
        raise ScanReviewError("Path must stay inside the PDS workspace.") from error


def _metadata_files(directory: Path):
    if not directory.exists() or directory.is_symlink() or not directory.is_dir():
        return ()
    return tuple(
        path
        for path in sorted(directory.iterdir(), key=lambda item: item.name)
        if path.suffix == ".json"
    )


def _is_v1(path: Path) -> bool:
    try:
        return bool(_V1_PATTERN.search(path.read_bytes()))
    except OSError:
        return False


def _has_scoreform_marker(metadata: RoutingFailureMetadata) -> bool:
    return (
        isinstance(metadata.module_details, dict)
        and "scoreform" in metadata.module_details
    )


def _scoreform_owned(
    metadata: RoutingFailureMetadata, details: ScoreFormFailureDetails | None
) -> bool:
    return bool(
        (
            metadata.route_locator is not None
            and metadata.route_locator.module_id == "scoreform"
        )
        or (metadata.target is not None and metadata.target.module_id == "scoreform")
        or details is not None
    )


def _diagnostic_identity(
    details: ScoreFormFailureDetails | None,
) -> ScoreFormReviewIdentity:
    if details is None:
        return ScoreFormReviewIdentity("none")
    context = details.context
    observed = context.get("observed_identity", context)
    if not isinstance(observed, Mapping):
        return ScoreFormReviewIdentity("none")

    def text(name):
        value = observed.get(name)
        return value if isinstance(value, str) and is_safe_identifier(value) else None

    return ScoreFormReviewIdentity(
        "scoreform_diagnostic",
        text("class_id") or text("raw_class_id"),
        text("assignment_id") or text("raw_assignment_id"),
        text("student_id") or text("raw_student_id"),
        text("route_id") or text("raw_route_id"),
        text("page_id") or text("raw_page_id"),
        text("issuance_id") or text("raw_issuance_id"),
    )


def _project_identity(
    root: Path, metadata: RoutingFailureMetadata
) -> ScoreFormReviewIdentity:
    locator, target = metadata.route_locator, metadata.target
    if target is not None and target.module_id == "scoreform" and locator is not None:
        try:
            resolution = resolve_route_registration(root, locator)
            if resolution.registration.target != target:
                raise ValueError("registration target changed")
            context = load_answer_sheet_page_context(
                root, locator.work, target.record_id
            )
            validate_answer_sheet_page_route(
                AnswerSheetPageRoute(
                    context.page,
                    locator,
                    resolution.registration,
                    serialize_pds2_payload(locator),
                )
            )
            page = context.page
            return ScoreFormReviewIdentity(
                "validated_target",
                page.class_id,
                page.assignment_id,
                page.student_id,
                locator.route_id,
                page.page_id,
                page.issuance_id,
                page.logical_page,
                page.total_pages,
            )
        except Exception:
            pass
    if locator is not None and locator.module_id == "scoreform":
        return ScoreFormReviewIdentity(
            "validated_locator",
            locator.class_id,
            locator.work_id,
            route_id=locator.route_id,
        )
    return ScoreFormReviewIdentity("none")


_PROVENANCE_FIELDS = (
    "source_filename",
    "source_scan_id",
    "source_sha256",
    "retained_source_path",
    "review_copy_path",
    "source_page_number",
)


def _linked(
    resolution: ScanResolutionMetadata, failure: RoutingFailureMetadata
) -> bool:
    return (
        resolution.failure_metadata_path == f"scans/review/{failure.failure_id}.json"
        and all(
            getattr(resolution, name) == getattr(failure, name)
            for name in _PROVENANCE_FIELDS
        )
    )


def _validate_filter_identifier(value: str | None, label: str) -> None:
    if value is not None:
        try:
            validate_identifier(value, label)
        except Exception as error:
            raise ScanReviewError(f"Unsafe {label} filter.") from error


def discover_scan_review_items(
    workspace_root: str | Path,
    *,
    include_resolved: bool = False,
    status: str | None = None,
    limit: int | None = None,
    class_id: str | None = None,
    assignment_id: str | None = None,
    student_id: str | None = None,
    failure_category: str | None = None,
    stage: str | None = None,
    source_scan_id: str | None = None,
) -> ScanReviewDiscovery:
    root = Path(workspace_root).resolve(strict=True)
    if status not in {None, "unresolved", "deferred", "resolved"}:
        raise ScanReviewError("Status must be unresolved, deferred, or resolved.")
    if include_resolved and status in {"unresolved", "deferred"}:
        raise ScanReviewError("--include-resolved contradicts the selected status.")
    if limit is not None and (
        isinstance(limit, bool) or not isinstance(limit, int) or limit < 1
    ):
        raise ScanReviewError("Limit must be a positive integer.")
    for value, label in (
        (class_id, "class_id"),
        (assignment_id, "assignment_id"),
        (student_id, "student_id"),
        (source_scan_id, "source_scan_id"),
    ):
        _validate_filter_identifier(value, label)
    if stage is not None and (not is_safe_identifier(stage) or stage != stage.lower()):
        raise ScanReviewError("Stage filter is invalid.")
    if failure_category is not None and (
        failure_category not in ROUTING_FAILURE_CATEGORIES
        and (
            not is_safe_identifier(failure_category)
            or failure_category != failure_category.lower()
        )
    ):
        raise ScanReviewError("Failure-category filter is invalid.")

    review = routing_review_dir(root)
    failures: dict[
        str, tuple[Path, RoutingFailureMetadata, ScoreFormFailureDetails | None]
    ] = {}
    invalid_failure = v1_failure = malformed_details = foreign = 0
    for path in _metadata_files(review):
        if path.is_symlink() or not path.is_file():
            invalid_failure += 1
            continue
        try:
            metadata = load_routing_failure_metadata(root, path.stem)
        except (RoutingFailureMetadataReadError, ValueError, OSError):
            if _is_v1(path):
                v1_failure += 1
            else:
                invalid_failure += 1
            continue
        details = None
        if _has_scoreform_marker(metadata):
            try:
                details = validate_scoreform_failure_details(metadata.module_details)
            except ValueError:
                malformed_details += 1
                continue
        if not _scoreform_owned(metadata, details):
            foreign += 1
            continue
        failures[metadata.failure_id] = (path, metadata, details)

    histories: dict[
        str, list[tuple[Path, ScanResolutionMetadata, ScoreFormResolutionDetails]]
    ] = {}
    invalid_resolution = v1_resolution = orphan = mismatch = 0
    for path in _metadata_files(review / "resolutions"):
        if path.is_symlink() or not path.is_file():
            invalid_resolution += 1
            continue
        try:
            resolution = load_scan_resolution_metadata(root, path.stem)
        except (ScanResolutionMetadataReadError, ValueError, OSError):
            if _is_v1(path):
                v1_resolution += 1
            else:
                invalid_resolution += 1
            continue
        nested_details = resolution.module_details.get("scoreform")
        if nested_details is None:
            foreign += 1
            continue
        if not isinstance(nested_details, Mapping):
            malformed_details += 1
            continue
        try:
            resolution_detail = validate_scoreform_resolution_details(
                resolution.module_details
            )
        except ValueError:
            malformed_details += 1
            continue
        failure_entry = failures.get(resolution.failure_id)
        if failure_entry is None:
            orphan += 1
            continue
        if not _linked(resolution, failure_entry[1]):
            mismatch += 1
            continue
        histories.setdefault(resolution.failure_id, []).append(
            (path, resolution, resolution_detail)
        )

    items = []
    for failure_id, (path, metadata, details) in failures.items():
        history = histories.get(failure_id, [])
        history.sort(
            key=lambda record: (
                _parse_utc(record[1].resolved_at),
                record[1].resolution_id,
            )
        )
        item = ScoreFormReviewItem(
            failure_id,
            metadata,
            path,
            _relative(root, path),
            details,
            _project_identity(root, metadata),
            _diagnostic_identity(details),
            tuple(record[1] for record in history),
            tuple(record[2] for record in history),
            tuple(_relative(root, record[0]) for record in history),
        )
        if status is not None and item.status != status:
            continue
        if status is None and not include_resolved and item.status == "resolved":
            continue
        if class_id is not None and item.class_id != class_id:
            continue
        if assignment_id is not None and item.assignment_id != assignment_id:
            continue
        if student_id is not None and item.student_id != student_id:
            continue
        if failure_category is not None and failure_category not in {
            item.failure_category,
            item.scoreform_failure_category,
        }:
            continue
        if stage is not None and item.stage != stage:
            continue
        if source_scan_id is not None and item.source_scan_id != source_scan_id:
            continue
        items.append(item)
    items.sort(
        key=lambda item: (_parse_utc(item.created_at), item.failure_id), reverse=True
    )
    if limit is not None:
        items = items[:limit]
    return ScanReviewDiscovery(
        tuple(items),
        invalid_failure,
        invalid_resolution,
        v1_failure,
        v1_resolution,
        orphan,
        mismatch,
        malformed_details,
        foreign,
    )


def get_scan_review_item(
    workspace_root: str | Path, failure_id: str
) -> ScoreFormReviewItem:
    if not is_safe_identifier(failure_id):
        raise ScanReviewError("Unsafe failure ID.")
    root = Path(workspace_root).resolve(strict=True)
    try:
        failure = load_routing_failure_metadata(root, failure_id)
    except RoutingFailureMetadataReadError as error:
        raise ScanReviewError(
            f"Unknown ScoreForm scan review item: {failure_id}"
        ) from error
    details = None
    if _has_scoreform_marker(failure):
        try:
            details = validate_scoreform_failure_details(failure.module_details)
        except ValueError as error:
            raise ScanReviewError(
                "Requested failure has malformed ScoreForm details."
            ) from error
    if not _scoreform_owned(failure, details):
        raise ScanReviewError("Requested failure is not owned by ScoreForm review.")
    discovery = discover_scan_review_items(root, include_resolved=True)
    for item in discovery.items:
        if item.failure_id == failure_id:
            return item
    # Other malformed records cannot block the requested valid failure.
    return ScoreFormReviewItem(
        failure_id,
        failure,
        routing_review_dir(root) / f"{failure_id}.json",
        f"scans/review/{failure_id}.json",
        details,
        _project_identity(root, failure),
        _diagnostic_identity(details),
    )


def _safe_existing_relative(root: Path, value: str | Path) -> str:
    raw = os.fspath(value).strip()
    windows, posix = PureWindowsPath(raw), PurePosixPath(raw)
    if (
        not raw
        or windows.is_absolute()
        or windows.drive
        or posix.is_absolute()
        or any(part in {"", ".", ".."} for part in raw.replace("\\", "/").split("/"))
    ):
        raise ScanReviewError("Evidence must be a safe workspace-relative path.")
    candidate = root / raw
    try:
        _reject_symlink_components(root, candidate)
    except ValueError as error:
        raise ScanReviewError(str(error)) from error
    path = candidate.resolve(strict=True)
    if not path.is_file():
        raise ScanReviewError("Evidence must be a regular file.")
    return _relative(root, path)


def _identity(root: Path, class_id, assignment_id, student_id):
    values = {
        key: value
        for key, value in {
            "class_id": class_id,
            "assignment_id": assignment_id,
            "student_id": student_id,
        }.items()
        if value is not None
    }
    for key, value in values.items():
        if not is_safe_identifier(value):
            raise ScanReviewError(f"Unsafe {key}: {value!r}")
    if class_id and assignment_id:
        assignment = load_assignment(
            scoreform_work_paths(root, class_id, assignment_id).assignment_path
        )
        if assignment is None:
            raise ScanReviewError("Selected managed assignment is invalid.")
    if student_id:
        if not class_id:
            raise ScanReviewError("A class is required to validate a student.")
        roster = load_roster(class_roster_path(root, class_id))
        if roster is None or not any(
            row.get("student_id") == student_id for row in roster.get("students", [])
        ):
            raise ScanReviewError("Student was not found in the current class roster.")
    return values


def _validated_route(root: Path, payload: str | None):
    if payload is None:
        raise ScanReviewError("Route actions require --route-payload.")
    try:
        locator = parse_pds2_payload(payload)
        if serialize_pds2_payload(locator) != payload:
            raise ScanReviewError("Route payload must be canonical PDS2 text.")
        if locator.module_id != "scoreform":
            raise ScanReviewError("The selected route must belong to ScoreForm.")
        resolution = resolve_route_registration(root, locator)
        context = load_answer_sheet_page_context(
            root, locator.work, resolution.registration.target.record_id
        )
        validate_answer_sheet_page_route(
            AnswerSheetPageRoute(
                context.page, locator, resolution.registration, payload
            )
        )
    except ScanReviewError:
        raise
    except Exception as error:
        raise ScanReviewError(f"Route selection is not valid: {error}") from error
    return locator, resolution.registration.target, context


def _resolution_collision(error: ScanResolutionMetadataWriteError) -> bool:
    return isinstance(error.__cause__, FileExistsError)


def _diagnostic_review_identity(
    identity: Mapping[str, object] | None,
) -> tuple[str | None, str | None]:
    if not isinstance(identity, Mapping):
        return None, None
    class_id = identity.get("class_id")
    assignment_id = identity.get("assignment_id")
    return (
        class_id if isinstance(class_id, str) else None,
        assignment_id if isinstance(assignment_id, str) else None,
    )


def _record_scan_review_failure(
    workspace_root: Path,
    identity: Mapping[str, object] | None,
    error: Exception,
    *,
    partial: bool,
) -> None:
    class_id, assignment_id = _diagnostic_review_identity(identity)
    try_emit_diagnostic_event(
        workspace_root,
        component="scan_review",
        workflow="resolve_scan_review",
        stage="write_record",
        outcome="partial_success" if partial else "failure",
        code="scan_review_resolution_failed",
        class_id=class_id,
        assignment_id=assignment_id,
        exception=error,
    )


def _record_scan_review_recovery(
    workspace_root: Path,
    identity: Mapping[str, object] | None,
    action: str,
) -> None:
    if action not in _DIAGNOSTIC_RECOVERY_ACTIONS:
        return
    class_id, assignment_id = _diagnostic_review_identity(identity)
    try_emit_diagnostic_event(
        workspace_root,
        component="recovery",
        workflow="resolve_scan_review",
        stage="recover",
        outcome="recovered",
        code="scan_review_recovered",
        class_id=class_id,
        assignment_id=assignment_id,
    )


def resolve_scan_review_item(
    workspace_root: str | Path,
    failure_id: str,
    action: str,
    *,
    message: str | None = None,
    evidence_path: str | None = None,
    class_id: str | None = None,
    assignment_id: str | None = None,
    student_id: str | None = None,
    answers: Mapping[int | str, str] | None = None,
    route_payload: str | None = None,
    now: datetime | None = None,
) -> ScoreFormResolutionResult:
    if not is_safe_identifier(failure_id):
        raise ScanReviewError("Unsafe failure ID.")
    root = Path(workspace_root).resolve(strict=True)
    try:
        failure = load_routing_failure_metadata(root, failure_id)
    except RoutingFailureMetadataReadError as error:
        raise ScanReviewError(
            f"Unknown ScoreForm scan review item: {failure_id}"
        ) from error
    details = None
    if _has_scoreform_marker(failure):
        try:
            details = validate_scoreform_failure_details(failure.module_details)
        except ValueError as error:
            raise ScanReviewError("Failure has malformed ScoreForm details.") from error
    if not _scoreform_owned(failure, details):
        raise ScanReviewError("Failure is not owned by ScoreForm review.")
    if action not in RESOLUTION_ACTIONS:
        raise ScanReviewError(f"Unsupported scan review action: {action}")
    if action == "dismissed_duplicate" and (
        details is None
        or details.scoreform_category
        not in {"duplicate_page", "duplicate_route", "conflicting_duplicate"}
    ):
        raise ScanReviewError(
            "dismissed_duplicate requires a validated duplicate failure category."
        )
    route_actions = {"route_selected", "route_corrected"}
    if route_payload is not None and action not in route_actions:
        raise ScanReviewError("route_payload is accepted only for route actions.")
    if answers is not None and action != "manual_entry":
        raise ScanReviewError("Answer data is accepted only for manual_entry.")
    if any(value is not None for value in (class_id, assignment_id, student_id)) and action not in {
        "manual_entry", "manual_marks"
    }:
        raise ScanReviewError(
            "Teacher identity overrides are not accepted for this action."
        )
    if action == "other" and (message is None or not message.strip()):
        raise ScanReviewError("The other action requires a nonempty message.")
    if action in _NO_EVIDENCE_ACTIONS and evidence_path is not None:
        raise ScanReviewError(f"{action} cannot include evidence.")
    if action == "manual_marks" and (not class_id or not assignment_id):
        raise ScanReviewError("Manual marks require class and assignment identity.")

    timestamp = _utc(now)
    identity = _identity(root, class_id, assignment_id, student_id)
    identity_source = "teacher_verified" if identity else "none"
    result_details = None
    result_written = result_already_present = False
    attempt = None
    if action == "manual_entry":
        if not class_id or not assignment_id or not student_id or answers is None:
            raise ScanReviewError(
                "Manual entry requires class, assignment, student, and answers."
            )
        assignment = load_assignment(
            scoreform_work_paths(root, class_id, assignment_id).assignment_path
        )
        roster = load_roster(class_roster_path(root, class_id))
        if assignment is None or roster is None:
            raise ScanReviewError("Manual-entry sources are unavailable.")
        student = next(
            (row for row in roster["students"] if row["student_id"] == student_id), None
        )
        if student is None:
            raise ScanReviewError("Student is not in the current roster.")
        if len(answers) != assignment["question_count"]:
            raise ScanReviewError(
                "Manual entry requires exactly one answer per question."
            )
        normalized = {}
        for question in range(1, assignment["question_count"] + 1):
            raw = answers.get(question, answers.get(str(question)))
            value = normalize_manual_response(raw) if isinstance(raw, str) else None
            if value is None:
                raise ScanReviewError(f"Answer {question} is invalid.")
            normalized[question] = value
        review_result = replace(
            build_manual_result(
                class_id=class_id,
                assignment=assignment,
                student=student,
                responses=normalized,
            ),
            result_origin="scan_review_manual",
            page_display="review",
            source_file=f"scan_review_manual:{failure_id}",
        )
        exported = export_scoreform_result_models((review_result,), workspace_root=root)
        if exported.failures:
            raise ScanReviewError(
                f"Manual-entry result writing failed: {exported.failures[0].reason}"
            )
        attempt = next(
            iter((*exported.appended_attempts, *exported.already_present_attempts)),
            None,
        )
        if attempt is None:
            raise ScanReviewError("Manual-entry writer returned no outcome.")
        result_written = bool(exported.appended_attempts)
        result_already_present = bool(exported.already_present_attempts)
        result_details = {
            "result_origin": "scan_review_manual",
            "result_output_path": _relative(root, attempt.output_path),
            "attempt_number": attempt.attempt_number,
            "score": review_result.score,
            "total": review_result.total_points,
            "already_present": result_already_present,
        }

    locator = target = None
    if action in {"route_selected", "route_corrected"}:
        locator, target, context = _validated_route(root, route_payload)
        if context.issuance.lifecycle.status != "issued":
            raise ScanReviewError("Route actions require an issued answer sheet.")
        page = context.page
        identity_source = "validated_target"
        identity = {
            "class_id": page.class_id,
            "assignment_id": page.assignment_id,
            "student_id": page.student_id,
            "route_id": locator.route_id,
            "page_id": page.page_id,
            "issuance_id": page.issuance_id,
            "logical_page": page.logical_page,
            "total_pages": page.total_pages,
        }

    evidence = core_evidence = None
    if action == "evidence_filed":
        if evidence_path is None:
            raise ScanReviewError("evidence_filed requires --evidence-path.")
        core_evidence = _safe_existing_relative(root, evidence_path)
        evidence = {
            "source_path": core_evidence,
            "filed_path": core_evidence,
            "status_tag": "already_filed",
            "sha256": _sha256(root / core_evidence),
        }
    elif action in {"manual_entry", "manual_marks"} and (
        evidence_path is not None or failure.retained_source_path is not None
    ):
        if not class_id or not assignment_id:
            raise ScanReviewError("Evidence copying requires class and assignment.")
        selected_evidence = evidence_path or failure.retained_source_path
        assert selected_evidence is not None
        filing = file_resolution_scan_copy(
            root,
            class_id,
            assignment_id,
            selected_evidence,
            action,
            now=timestamp,
            failure_id=failure_id,
        )
        if not filing.filed:
            filing_error = ScanReviewError(
                "Review evidence copy failed: "
                f"{filing.error}; cleanup error: {filing.cleanup_error}"
            )
            if attempt is not None:
                partial_error = ScanReviewPartialOperationError(
                    failure_id=failure_id,
                    result_output_path=_relative(root, attempt.output_path),
                    attempt_number=attempt.attempt_number,
                    result_appended=result_written,
                    result_already_present=result_already_present,
                    error=filing_error,
                )
                _record_scan_review_failure(
                    root,
                    identity,
                    partial_error,
                    partial=True,
                )
                raise partial_error from filing.error
            raise filing_error from filing.error
        core_evidence = filing.filed_relative_path
        evidence = {
            "source_path": filing.source_relative_path,
            "filed_path": filing.filed_relative_path,
            "status_tag": filing.status_tag,
            "sha256": filing.sha256,
        }
    elif evidence_path is not None:
        raise ScanReviewError(f"{action} does not accept evidence.")

    core_action = {
        "defer": "deferred",
        "manual_entry": "other",
        "manual_marks": "other",
        "mixed_assignment": "cannot_route",
    }.get(action, action)
    status = "deferred" if action == "defer" else "resolved"
    final_message = sanitize_single_line(
        message or DEFAULT_MESSAGES.get(action) or "Teacher resolved the review item.",
        fallback="Teacher resolved the review item.",
    )
    resolution_details = scoreform_resolution_details(
        teacher_action=action,
        identity_source=identity_source,
        identity=identity,
        result=result_details,
        evidence=evidence,
    )
    last_error: Exception | None = None
    for attempt_index in range(8):
        resolution_id = _id("resolution", timestamp)
        path = scan_resolution_metadata_path(root, resolution_id)
        if path.exists() or path.is_symlink():
            last_error = FileExistsError(path)
            continue
        metadata = create_scan_resolution_metadata(
            failure,
            resolution_id=resolution_id,
            resolution_status=status,
            resolution_action=core_action,
            resolved_at=timestamp.isoformat(),
            resolution_message=final_message,
            route_locator=locator,
            target=target,
            resolution_evidence_path=core_evidence,
            module_details=resolution_details,
        )
        try:
            path = write_scan_resolution_metadata(root, metadata)
        except ScanResolutionMetadataWriteError as error:
            last_error = error
            if _resolution_collision(error) and attempt_index + 1 < 8:
                continue
            break
        result = ScoreFormResolutionResult(
            resolution_id,
            path,
            _relative(root, path),
            failure_id,
            status,
            action,
            result_written=result_written,
            result_already_present=result_already_present,
            evidence_path=core_evidence,
        )
        _record_scan_review_recovery(root, identity, action)
        return result
    assert last_error is not None
    if attempt is not None:
        partial_error = ScanReviewPartialOperationError(
            failure_id=failure_id,
            result_output_path=_relative(root, attempt.output_path),
            attempt_number=attempt.attempt_number,
            result_appended=result_written,
            result_already_present=result_already_present,
            error=last_error,
        )
        _record_scan_review_failure(
            root,
            identity,
            partial_error,
            partial=True,
        )
        raise partial_error from last_error
    _record_scan_review_failure(
        root,
        identity,
        last_error,
        partial=False,
    )
    raise ScanReviewError(
        f"Could not append scan resolution: {sanitize_single_line(str(last_error), fallback='write failed')}"
    ) from last_error


def preserve_qr_batch_failures_for_review(*_args, **_kwargs):
    raise ScanReviewError(
        "The QR-summary review writer was removed; persist the complete routed-scoring batch."
    )
