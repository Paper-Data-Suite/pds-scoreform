"""ScoreForm active scan-review failure and resolution workflows."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Mapping

from pds_core.routes import (
    assignment_config_path,
    class_roster_path,
)
from pds_core.scan_failure_metadata import (
    RoutingFailureMetadata,
    routing_failure_metadata_from_dict,
    write_routing_failure_metadata,
)
from pds_core.scan_resolution_metadata import (
    ScanResolutionMetadata,
    scan_resolution_metadata_from_dict,
    write_scan_resolution_metadata,
)
from pds_core.scan_routes import routing_review_dir

from scoreform.assignment import load_assignment
from scoreform.results import export_routed_results
from scoreform.roster import load_roster
from scoreform.scan_filing import file_resolution_scan_copy
from scoreform.validation import is_safe_identifier

SCOREFORM_REVIEW_STAGE = "scoreform_qr_review"
SCOREFORM_FAILURE_CATEGORY_MAP = {
    "input_file_missing": "source_missing",
    "unsupported_input_type": "source_type_unsupported",
    "source_retention_failed": "source_retention_failed",
    "pdf2image_missing": "processing_error",
    "poppler_missing": "processing_error",
    "pdf_conversion_failed": "source_unreadable",
    "missing_qr": "payload_missing",
    "malformed_qr": "payload_invalid",
    "unsafe_qr": "identifier_invalid",
    "assignment_lookup_failed": "assignment_unknown",
    "image_processing_failed": "source_unreadable",
    "registration_or_scoring_failed": "processing_error",
    "result_write_failed": "processing_error",
    "unknown_failed": "processing_error",
}
RESOLUTION_ACTIONS = (
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
    "manual_entry": (
        "Teacher entered answers manually from paper truth or retained scan evidence."
    ),
    "manual_marks": (
        "Teacher recorded manual marks outside automatic ScoreForm scoring."
    ),
    "rescan_needed": "Teacher determined that the paper must be rescanned.",
    "cannot_route": "Teacher could not safely identify a routing destination.",
    "mixed_assignment": "Teacher identified a source with mixed assignment targets.",
    "evidence_filed": "Teacher confirmed that review evidence is already filed.",
    "dismissed_duplicate": "Teacher dismissed this duplicate review item.",
    "defer": "Teacher deferred this review item for later follow-up.",
}


class ScanReviewError(ValueError):
    """Raised when a requested review operation is unsafe or incomplete."""


@dataclass(frozen=True, slots=True)
class ScoreFormReviewItem:
    failure_id: str
    failure_metadata_path: Path
    failure_metadata_relative_path: str
    failure_category: str
    failure_message: str
    scoreform_failure_category: str | None
    stage: str
    created_at: str
    source_filename: str
    retained_source_path: str | None
    review_copy_path: str | None
    source_scan_id: str | None
    source_sha256: str | None
    source_page_number: int | None
    class_id: str | None
    assignment_id: str | None
    student_id: str | None
    latest_resolution_status: str | None = None
    latest_resolution_action: str | None = None
    latest_resolution_path: str | None = None

    @property
    def status(self) -> str:
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
    evidence_path: str | None = None


@dataclass(frozen=True, slots=True)
class ScanReviewDiscovery:
    items: tuple[ScoreFormReviewItem, ...]
    warning_count: int = 0


def _utc_now(now: datetime | None = None) -> datetime:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _identifier(prefix: str, material: str, now: datetime | None = None) -> str:
    timestamp = _utc_now(now).strftime("%Y%m%dT%H%M%S%fZ")
    digest = hashlib.sha256(f"{material}|{timestamp}".encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{timestamp}_{digest}"


def _relative(workspace_root: Path, path: Path) -> str:
    try:
        return path.resolve(strict=False).relative_to(
            workspace_root.resolve(strict=False)
        ).as_posix()
    except (OSError, RuntimeError, ValueError) as error:
        raise ScanReviewError("Path must stay within the PDS workspace.") from error


def _safe_workspace_relative_path(
    workspace_root: Path, value: str | Path, *, must_exist: bool = True
) -> tuple[Path, str]:
    raw = os.fspath(value).strip()
    if not raw:
        raise ScanReviewError("Evidence path must not be empty.")
    windows = PureWindowsPath(raw)
    posix = PurePosixPath(raw)
    if windows.is_absolute() or windows.drive or posix.is_absolute():
        raise ScanReviewError("Evidence path must be relative to the PDS workspace.")
    if any(part in {".", ".."} for part in raw.replace("\\", "/").split("/")):
        raise ScanReviewError("Evidence path contains an unsafe traversal component.")
    root = workspace_root.resolve(strict=True)
    path = (root / Path(raw)).resolve(strict=False)
    relative = _relative(root, path)
    if must_exist and (not path.exists() or not path.is_file()):
        raise ScanReviewError(f"Evidence file does not exist: {relative}")
    return path, relative


def preserve_qr_batch_failures_for_review(
    results,
    source_file: str | Path,
    workspace_root: str | Path,
    *,
    now: datetime | None = None,
) -> list[Path]:
    """Write one immutable Core failure record per QR-aware batch failure."""
    summary = getattr(results, "summary", None)
    failures = getattr(summary, "failures", ())
    if not failures:
        return []
    root = Path(workspace_root)
    retained = getattr(results, "retained_source", None)
    created_at = _utc_now(now)
    source_filename = getattr(retained, "source_filename", None)
    if not source_filename:
        source_filename = Path(os.fspath(source_file)).name or "scan"
    written: list[Path] = []
    for index, failure in enumerate(failures, start=1):
        category = getattr(failure, "category", "unknown_failed")
        reason = str(getattr(failure, "reason", "QR-aware scoring failed")).strip()
        reason = reason or "QR-aware scoring failed"
        page_num = getattr(failure, "page_num", None)
        material = "|".join(
            str(value)
            for value in (
                category,
                reason,
                source_filename,
                getattr(retained, "retained_source_relative_path", None),
                page_num,
                getattr(failure, "class_id", None),
                getattr(failure, "assignment_id", None),
                getattr(failure, "student_id", None),
                index,
            )
        )
        metadata = RoutingFailureMetadata(
            schema_version="1",
            failure_id=_identifier("failure", material, created_at),
            scope="page" if page_num is not None else "scan",
            stage=SCOREFORM_REVIEW_STAGE,
            created_at=created_at.isoformat(),
            failure_category=SCOREFORM_FAILURE_CATEGORY_MAP.get(
                category, "processing_error"
            ),
            failure_message=reason,
            source_filename=source_filename,
            module_details={
                "scoreform_failure_category": category,
                "scoreform_failure_reason": reason,
                "failure_origin": "scoreform_qr_aware_scoring",
            },
            module="scoreform",
            source_scan_id=getattr(retained, "source_scan_id", None),
            source_sha256=getattr(retained, "source_sha256", None),
            retained_source_path=getattr(
                retained, "retained_source_relative_path", None
            ),
            source_page_number=page_num,
            class_id=getattr(failure, "class_id", None),
            assignment_id=getattr(failure, "assignment_id", None),
            student_id=getattr(failure, "student_id", None),
        )
        try:
            written.append(write_routing_failure_metadata(root, metadata))
        except Exception as error:
            print(
                "Warning: Could not preserve a ScoreForm scan review record: "
                f"{error}"
            )
    return written


def _review_item(root: Path, path: Path, metadata) -> ScoreFormReviewItem:
    details = metadata.module_details
    scoreform_category = details.get("scoreform_failure_category")
    return ScoreFormReviewItem(
        failure_id=metadata.failure_id,
        failure_metadata_path=path,
        failure_metadata_relative_path=_relative(root, path),
        failure_category=metadata.failure_category,
        failure_message=metadata.failure_message,
        scoreform_failure_category=(
            scoreform_category if isinstance(scoreform_category, str) else None
        ),
        stage=metadata.stage,
        created_at=metadata.created_at,
        source_filename=metadata.source_filename,
        retained_source_path=metadata.retained_source_path,
        review_copy_path=metadata.review_copy_path,
        source_scan_id=metadata.source_scan_id,
        source_sha256=metadata.source_sha256,
        source_page_number=metadata.source_page_number,
        class_id=metadata.class_id,
        assignment_id=metadata.assignment_id,
        student_id=metadata.student_id,
    )


def discover_scan_review_items(
    workspace_root: str | Path,
    *,
    include_resolved: bool = False,
    limit: int | None = None,
    class_id: str | None = None,
    assignment_id: str | None = None,
    failure_category: str | None = None,
) -> ScanReviewDiscovery:
    """Discover ScoreForm-owned review records and their latest valid states."""
    root = Path(workspace_root).resolve(strict=True)
    review_dir = routing_review_dir(root)
    warnings = 0
    items: list[ScoreFormReviewItem] = []
    if review_dir.exists():
        for path in sorted(review_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                metadata = routing_failure_metadata_from_dict(data)
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
                warnings += 1
                continue
            if metadata.stage != SCOREFORM_REVIEW_STAGE:
                continue
            items.append(_review_item(root, path, metadata))

    latest: dict[str, tuple[datetime | None, str, ScanResolutionMetadata]] = {}
    resolution_dir = review_dir / "resolutions"
    if resolution_dir.exists():
        for path in sorted(resolution_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                resolution = scan_resolution_metadata_from_dict(data)
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
                warnings += 1
                continue
            if resolution.module != "scoreform":
                continue
            try:
                resolved_at = datetime.fromisoformat(resolution.resolved_at)
            except ValueError:
                resolved_at = None
            candidate = (resolved_at, path.name, resolution)
            current = latest.get(resolution.failure_id)
            if current is None or _latest_key(candidate) > _latest_key(current):
                latest[resolution.failure_id] = candidate

    enriched: list[ScoreFormReviewItem] = []
    for item in items:
        record = latest.get(item.failure_id)
        if record is not None:
            resolution = record[2]
            item = replace(
                item,
                latest_resolution_status=resolution.resolution_status,
                latest_resolution_action=resolution.resolution_action,
                latest_resolution_path=_relative(
                    root, Path(resolution_dir / record[1])
                ),
            )
        if item.status == "resolved" and not include_resolved:
            continue
        if class_id is not None and item.class_id != class_id:
            continue
        if assignment_id is not None and item.assignment_id != assignment_id:
            continue
        if failure_category is not None and not (
            item.failure_category == failure_category
            or item.scoreform_failure_category == failure_category
        ):
            continue
        enriched.append(item)

    enriched.sort(key=lambda item: (item.created_at, item.failure_id), reverse=True)
    if limit is not None:
        if limit < 1:
            raise ScanReviewError("Limit must be a positive integer.")
        enriched = enriched[:limit]
    return ScanReviewDiscovery(tuple(enriched), warnings)


def _latest_key(
    record: tuple[datetime | None, str, ScanResolutionMetadata],
) -> tuple[str, str]:
    timestamp, filename, _ = record
    return (timestamp.isoformat() if timestamp is not None else "", filename)


def get_scan_review_item(
    workspace_root: str | Path, failure_id: str
) -> ScoreFormReviewItem:
    discovery = discover_scan_review_items(workspace_root, include_resolved=True)
    for item in discovery.items:
        if item.failure_id == failure_id:
            return item
    raise ScanReviewError(f"Unknown ScoreForm scan review item: {failure_id}")


def _validated_identity(
    root: Path,
    item: ScoreFormReviewItem,
    class_id: str | None,
    assignment_id: str | None,
    student_id: str | None,
    *,
    require_all: bool,
    require_destination: bool,
) -> tuple[str | None, str | None, str | None, dict | None]:
    values = (
        class_id or item.class_id,
        assignment_id or item.assignment_id,
        student_id or item.student_id,
    )
    labels = ("class_id", "assignment_id", "student_id")
    for label, value in zip(labels, values):
        if value is not None and not is_safe_identifier(value):
            raise ScanReviewError(f"Unsafe {label}: {value!r}")
    resolved_class, resolved_assignment, resolved_student = values
    if require_all and not all(values):
        raise ScanReviewError(
            "Manual entry requires validated class, assignment, and student identity."
        )
    assignment = None
    explicit_destination = class_id is not None or assignment_id is not None
    if resolved_class and resolved_assignment and (
        require_destination or explicit_destination
    ):
        assignment_path = assignment_config_path(
            root, resolved_class, resolved_assignment
        )
        assignment = load_assignment(assignment_path)
        if assignment is None:
            raise ScanReviewError(
                "The selected class and assignment do not exist or are invalid."
            )
    elif require_all:
        raise ScanReviewError("Class and assignment identity are required.")
    if resolved_student and (require_all or student_id is not None):
        if not resolved_class:
            raise ScanReviewError("A class is required to validate the student.")
        roster = load_roster(class_roster_path(root, resolved_class))
        if roster is None or not any(
            student.get("student_id") == resolved_student
            for student in roster.get("students", [])
        ):
            raise ScanReviewError(
                f"Student {resolved_student!r} was not found in the selected class roster."
            )
    return resolved_class, resolved_assignment, resolved_student, assignment


def _evidence_source(
    root: Path, item: ScoreFormReviewItem, evidence_path: str | None
) -> tuple[Path | None, str | None]:
    if evidence_path:
        return _safe_workspace_relative_path(root, evidence_path)
    candidate = item.retained_source_path or item.review_copy_path
    if candidate:
        return _safe_workspace_relative_path(root, candidate)
    return None, None


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
    now: datetime | None = None,
) -> ScoreFormResolutionResult:
    """Safely perform one ScoreForm-specific review resolution action."""
    if action not in RESOLUTION_ACTIONS:
        raise ScanReviewError(f"Unsupported scan review action: {action}")
    if action == "other" and (message is None or not message.strip()):
        raise ScanReviewError("The 'other' action requires a non-empty message.")
    root = Path(workspace_root).resolve(strict=True)
    item = get_scan_review_item(root, failure_id)
    require_all = action == "manual_entry"
    require_destination = action in {"manual_entry", "manual_marks", "rescan_needed"}
    resolved_class, resolved_assignment, resolved_student, assignment = (
        _validated_identity(
            root,
            item,
            class_id,
            assignment_id,
            student_id,
            require_all=require_all,
            require_destination=require_destination,
        )
    )
    if action == "evidence_filed" and not evidence_path:
        raise ScanReviewError("The evidence_filed action requires --evidence-path.")

    timestamp = _utc_now(now)
    evidence_relative: str | None = None
    result_written = False
    manual_score: int | None = None
    manual_total: int | None = None
    source, source_relative = _evidence_source(root, item, evidence_path)

    if action == "evidence_filed":
        evidence_relative = source_relative
    elif action in {"manual_entry", "manual_marks", "rescan_needed"}:
        if source is None:
            if action == "manual_entry":
                raise ScanReviewError(
                    "Manual entry requires retained scan evidence or --evidence-path."
                )
        elif resolved_class and resolved_assignment:
            filing = file_resolution_scan_copy(
                root,
                resolved_class,
                resolved_assignment,
                source,
                action,
                now=timestamp,
            )
            if not filing.filed_path:
                raise ScanReviewError(filing.warning or "Could not file review evidence.")
            evidence_relative = _relative(root, Path(filing.filed_path))

    if action == "manual_entry":
        if assignment is None or answers is None:
            raise ScanReviewError("Manual entry requires a complete answer set.")
        question_count = assignment["question_count"]
        normalized: dict[int, str] = {}
        for question in range(1, question_count + 1):
            raw = answers.get(question, answers.get(str(question)))
            if not isinstance(raw, str) or raw.strip().upper() not in {"A", "B", "C", "D"}:
                raise ScanReviewError(
                    f"Answer {question} must be one of A, B, C, or D."
                )
            normalized[question] = raw.strip().upper()
        if len(answers) != question_count:
            raise ScanReviewError("Manual entry requires exactly one answer per question.")
        key = assignment["answer_key"]
        answer_rows = [
            {
                "Q": question,
                "Answer": normalized[question],
                "Correct": normalized[question] == key[question],
            }
            for question in range(1, question_count + 1)
        ]
        manual_score = sum(1 for row in answer_rows if row["Correct"])
        manual_total = question_count
        result = {
            "page_num": item.source_page_number or 1,
            "class_id": resolved_class,
            "assignment_id": resolved_assignment,
            "student_id": resolved_student,
            "source_file": evidence_relative,
            "score": manual_score,
            "total_points": manual_total,
            "answers": answer_rows,
        }
        if not export_routed_results([result], workspace_root=root):
            raise ScanReviewError("Manual-entry routed result writing failed.")
        result_written = True

    status = "deferred" if action == "defer" else "resolved"
    core_action = "other" if action == "defer" else action
    final_message = (message or DEFAULT_MESSAGES.get(action) or "").strip()
    details: dict[str, object] = {
        "resolved_by": "teacher",
        "resolution_origin": "scoreform_scan_review",
        "original_failure_category": item.failure_category,
        "original_failure_stage": item.stage,
        "scoreform_failure_category": item.scoreform_failure_category,
        "teacher_selected_action": action,
    }
    if action == "manual_entry":
        details.update(
            {
                "manual_entry_result_written": True,
                "manual_entry_score": manual_score,
                "manual_entry_total": manual_total,
            }
        )
    material = f"{failure_id}|{action}|{final_message}"
    resolution_id = _identifier("resolution", material, timestamp)
    metadata = ScanResolutionMetadata(
        schema_version="1",
        resolution_id=resolution_id,
        failure_id=item.failure_id,
        failure_metadata_path=item.failure_metadata_relative_path,
        resolution_status=status,
        resolution_action=core_action,
        resolved_at=timestamp.isoformat(),
        resolution_message=final_message,
        module_details=details,
        module="scoreform",
        source_scan_id=item.source_scan_id,
        source_sha256=item.source_sha256,
        source_filename=item.source_filename,
        retained_source_path=item.retained_source_path,
        review_copy_path=item.review_copy_path,
        resolution_evidence_path=evidence_relative,
        source_page_number=item.source_page_number,
        class_id=resolved_class,
        assignment_id=resolved_assignment,
        student_id=resolved_student,
    )
    path = write_scan_resolution_metadata(root, metadata)
    return ScoreFormResolutionResult(
        resolution_id=resolution_id,
        resolution_metadata_path=path,
        resolution_metadata_relative_path=_relative(root, path),
        failure_id=failure_id,
        resolution_status=status,
        resolution_action=action,
        result_written=result_written,
        evidence_path=evidence_relative,
    )
