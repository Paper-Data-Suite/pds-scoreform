"""Issue #225 Slice 7: read-only registered-route recovery preflight.

An unreadable QR may be associated with an existing, issued ScoreForm page
only through explicit teacher intent or a prior validated route selection.
This preview is NOT proof of dispatch, grading, result persistence, or recovery.
Execution must repeat the entire preflight before making any changes.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Literal

from pds_core.pds2 import serialize_pds2_payload
from pds_core.route_registrations import resolve_route_registration
from pds_core.routing_models import ModuleRecordRef, RouteLocator
from pds_core.scan_retention import RetainedSourceScan

from scoreform.answer_sheet_persistence import load_answer_sheet_page_context
from scoreform.answer_sheet_routes import (
    AnswerSheetPageRoute,
    validate_answer_sheet_page_route,
)
from scoreform.pds_module import validate_scoreform_registration
from scoreform.retained_page import (
    load_retained_source_page,
    retained_source_page_count,
    validate_canonical_retained_source_relative_path,
    validate_retained_source,
)
from scoreform.scan_review_resolution import (
    ScoreFormReviewItem,
    discover_scan_review_items,
)
from scoreform.validation import is_safe_identifier

_ROUTE_ACTIONS = frozenset({"route_selected", "route_corrected"})
_READ_CHUNK = 1024 * 1024


class ScoreFormScanRecoveryPreflightError(ValueError):
    """The proposed recovery cannot proceed without violating a safety check."""


@dataclass(frozen=True, slots=True)
class PreparedScoreFormScanRecovery:
    """Read-only preview only. No future writer may trust a stale preview."""

    failure_id: str
    failure_category: str
    retained_source: RetainedSourceScan
    source_page_number: int
    source_page_count: int
    route_locator: RouteLocator
    target: ModuleRecordRef
    class_id: str
    assignment_id: str
    student_id: str
    page_id: str
    issuance_id: str
    logical_page: int
    total_pages: int
    route_origin: Literal["explicit", "recorded"]
    historical_resolution_id: str | None
    prior_review_action: str | None
    route_correction_confirmed: bool


def _source_from_failure(root: Path, item: ScoreFormReviewItem) -> RetainedSourceScan:
    """Reconstruct the original Core event; NEVER retain the scan again."""
    try:
        relative_text = item.retained_source_path
        if not isinstance(relative_text, str):
            raise ValueError("Retained source path is missing.")
        validate_canonical_retained_source_relative_path(relative_text)
        parts = PurePosixPath(relative_text).parts
        if len(parts) != 4 or "/".join(parts) != relative_text:
            raise ValueError("Retained source path is not exact canonical text.")
        filename = parts[3]
        suffix = Path(filename).suffix.lower()
        source_filename = item.source_filename
        if (
            not isinstance(source_filename, str)
            or not source_filename
            or source_filename != source_filename.strip()
            or "/" in source_filename
            or "\\" in source_filename
            or Path(source_filename).suffix.lower() != suffix
        ):
            raise ValueError("Original source filename is inconsistent.")
        source_scan_id = item.source_scan_id
        if source_scan_id != f"scan_{Path(filename).stem}":
            raise ValueError("Core source scan ID disagrees with retained filename.")
        source_sha256 = item.source_sha256
        if (
            not isinstance(source_sha256, str)
            or len(source_sha256) != 64
            or any(character not in "0123456789abcdef" for character in source_sha256)
        ):
            raise ValueError("Retained source has no valid SHA-256.")
        stamp, delimiter, remainder = filename.partition("__")
        if not delimiter or not remainder or len(stamp) != 22:
            raise ValueError("Retained source filename lacks the Core timestamp.")
        timestamp = datetime.strptime(stamp, "%Y%m%dT%H%M%S%fZ").replace(
            tzinfo=timezone.utc
        )
        if not filename.endswith(f"__{source_sha256[:12]}{suffix}"):
            raise ValueError("Retained filename digest contradicts source SHA-256.")
        intake_date = date.fromisoformat(parts[2])
        path = root.joinpath(*parts)
        return RetainedSourceScan(
            source_scan_id=source_scan_id,
            source_filename=source_filename,
            source_sha256=source_sha256,
            retained_source_path=path,
            retained_source_relative_path=relative_text,
            intake_timestamp=timestamp,
            intake_date=intake_date,
        )
    except (AttributeError, TypeError, ValueError, OSError) as error:
        raise ScoreFormScanRecoveryPreflightError(
            f"Cannot reconstruct original Core retention: {error}"
        ) from error


def _reject_linked_path(root: Path, candidate: Path) -> None:
    """Reject symlinks and Windows junctions at every original path component."""
    current = root
    for part in candidate.relative_to(root).parts:
        current = current / part
        if current.is_symlink() or (
            hasattr(current, "is_junction") and current.is_junction()
        ):
            raise ScoreFormScanRecoveryPreflightError(
                "Retained-source path contains a filesystem link."
            )


def _verify_original_source(
    root: Path, retained: RetainedSourceScan, physical_page: int
) -> int:
    try:
        _reject_linked_path(root, retained.retained_source_path)
        validate_retained_source(retained, workspace_root=root)
        digest = hashlib.sha256()
        with retained.retained_source_path.open("rb") as stream:
            for block in iter(lambda: stream.read(_READ_CHUNK), b""):
                digest.update(block)
        if not hmac.compare_digest(digest.hexdigest(), retained.source_sha256):
            raise ScoreFormScanRecoveryPreflightError(
                "Original retained-source SHA-256 does not match its failure record."
            )
        count = retained_source_page_count(retained, workspace_root=root)
        if physical_page > count:
            raise ScoreFormScanRecoveryPreflightError(
                "The failed physical page exceeds the retained source page count."
            )
        # Verify that the exact retained page is actually decodable for
        # scoring; a PNG file may exist yet contain invalid image bytes.
        page = load_retained_source_page(
            retained, physical_page, workspace_root=root
        )
        if page.width < 1 or page.height < 1:
            raise ScoreFormScanRecoveryPreflightError(
                "Original retained page is empty."
            )
        return count
    except ScoreFormScanRecoveryPreflightError:
        raise
    except Exception as error:
        raise ScoreFormScanRecoveryPreflightError(
            f"Cannot verify original retained source: {error}"
        ) from error


def prepare_scoreform_scan_recovery(
    workspace_root: str | Path,
    failure_id: str,
    *,
    route_locator: RouteLocator | None = None,
    target: ModuleRecordRef | None = None,
    use_recorded_route: bool = False,
    allow_route_correction: bool = False,
) -> PreparedScoreFormScanRecovery:
    """Read and validate one ScoreForm failed physical page and registered route.

    Explicit selection requires a locator; target is optional but, when given,
    must match its registered page. Recorded reuse is allowed only for the
    latest validated resolved route_selected/route_corrected event. Diagnostic
    hints and OCR are NEVER sufficient to establish authority.
    """
    if not isinstance(failure_id, str) or not is_safe_identifier(failure_id):
        raise ScoreFormScanRecoveryPreflightError("Failure ID is invalid.")
    if type(use_recorded_route) is not bool or type(allow_route_correction) is not bool:
        raise ScoreFormScanRecoveryPreflightError("Recovery flags must be Boolean.")
    if use_recorded_route:
        if route_locator is not None or target is not None or allow_route_correction:
            raise ScoreFormScanRecoveryPreflightError(
                "Recorded route reuse cannot include an explicit route or correction."
            )
    elif not isinstance(route_locator, RouteLocator):
        raise ScoreFormScanRecoveryPreflightError(
            "An explicit registered RouteLocator is required."
        )
    if target is not None and not isinstance(target, ModuleRecordRef):
        raise ScoreFormScanRecoveryPreflightError("Route target has the wrong type.")
    try:
        root = Path(workspace_root).resolve(strict=True)
        if not root.is_dir():
            raise ValueError("Workspace root must be a directory.")
        discovery = discover_scan_review_items(root, include_resolved=True)
    except (OSError, ValueError, RuntimeError, TypeError) as error:
        raise ScoreFormScanRecoveryPreflightError(
            f"Cannot inspect ScoreForm scan review: {error}"
        ) from error
    matches = [item for item in discovery.items if item.failure_id == failure_id]
    if len(matches) != 1:
        raise ScoreFormScanRecoveryPreflightError(
            "No unique valid ScoreForm failure matches this ID."
        )
    item = matches[0]
    physical_page = item.source_page_number
    if (
        item.metadata.scope != "page"
        or type(physical_page) is not int
        or physical_page < 1
    ):
        raise ScoreFormScanRecoveryPreflightError(
            "Recovery requires an exact failed physical source page."
        )
    if not all(
        isinstance(value, str) and value
        for value in (
            item.source_scan_id,
            item.source_sha256,
            item.retained_source_path,
        )
    ):
        raise ScoreFormScanRecoveryPreflightError(
            "The failure lacks original retained-source provenance."
        )

    origin: Literal["explicit", "recorded"] = "explicit"
    history_id = None
    if use_recorded_route:
        selected = item.latest_resolution
        if (
            selected is None
            or selected.resolution_status != "resolved"
            or item.latest_resolution_action not in _ROUTE_ACTIONS
            or selected.resolution_action != item.latest_resolution_action
        ):
            raise ScoreFormScanRecoveryPreflightError(
                "No latest validated route decision is eligible for reuse."
            )
        route_locator, target = selected.route_locator, selected.target
        history_id, origin = selected.resolution_id, "recorded"

    if not isinstance(route_locator, RouteLocator):
        raise ScoreFormScanRecoveryPreflightError("Selected route is missing.")
    if route_locator.module_id != "scoreform":
        raise ScoreFormScanRecoveryPreflightError(
            "Recovery requires a ScoreForm answer-sheet route."
        )
    # An observed locator can be incorrect. Replacing it requires deliberate
    # teacher correction, never automatic cross-work or cross-page selection.
    prior_locator = item.route_locator
    corrected = prior_locator is not None and prior_locator != route_locator
    if corrected and not (
        allow_route_correction
        or (origin == "recorded" and item.latest_resolution_action == "route_corrected")
    ):
        raise ScoreFormScanRecoveryPreflightError(
            "Observed route differs; an explicit route correction is required."
        )
    if item.target is not None and not corrected and target is not None:
        if item.target != target:
            raise ScoreFormScanRecoveryPreflightError(
                "Selected target disagrees with the original authoritative target."
            )

    retained = _source_from_failure(root, item)
    count = _verify_original_source(root, retained, physical_page)
    try:
        resolution = resolve_route_registration(root, route_locator)
        registration = resolution.registration
        validate_scoreform_registration(registration)
        if registration.locator != route_locator:
            raise ValueError("Resolved registration locator changed.")
        if target is not None and registration.target != target:
            raise ValueError("Selected target does not match registered target.")
        target = registration.target
        context = load_answer_sheet_page_context(
            root, route_locator.work, target.record_id
        )
        validate_answer_sheet_page_route(
            AnswerSheetPageRoute(
                context.page,
                route_locator,
                registration,
                serialize_pds2_payload(route_locator),
            )
        )
        if context.issuance.lifecycle.status != "issued":
            raise ValueError("Answer-sheet issuance is not issued.")
        if item.target is not None and not corrected and item.target != target:
            raise ValueError("Registered target contradicts failed page authority.")
    except Exception as error:
        raise ScoreFormScanRecoveryPreflightError(
            f"Selected route is not currently authorized: {error}"
        ) from error
    page = context.page
    # If original failure already had a validated registered target, its
    # immutable student/work identity cannot be changed by a correction flag.
    if item.identity.source == "validated_target" and (
        page.class_id,
        page.assignment_id,
        page.student_id,
        page.page_id,
    ) != (
        item.identity.class_id,
        item.identity.assignment_id,
        item.identity.student_id,
        item.identity.page_id,
    ):
        raise ScoreFormScanRecoveryPreflightError(
            "Selected route contradicts an authoritative original page identity."
        )
    if item.identity.source == "validated_locator" and (
        route_locator.class_id,
        route_locator.work_id,
    ) != (item.identity.class_id, item.identity.assignment_id):
        raise ScoreFormScanRecoveryPreflightError(
            "Selected route crosses the original validated class or assignment."
        )
    if origin == "recorded":
        recorded_details = item.latest_resolution_details
        expected_identity = {
            "class_id": page.class_id,
            "assignment_id": page.assignment_id,
            "student_id": page.student_id,
            "route_id": route_locator.route_id,
            "page_id": page.page_id,
            "issuance_id": page.issuance_id,
            "logical_page": page.logical_page,
            "total_pages": page.total_pages,
        }
        if (
            recorded_details is None
            or recorded_details.identity_source != "validated_target"
            or dict(recorded_details.identity) != expected_identity
        ):
            raise ScoreFormScanRecoveryPreflightError(
                "Recorded route decision contradicts the issued page identity."
            )
    return PreparedScoreFormScanRecovery(
        failure_id=failure_id,
        failure_category=item.failure_category,
        retained_source=retained,
        source_page_number=physical_page,
        source_page_count=count,
        route_locator=route_locator,
        target=target,
        class_id=page.class_id,
        assignment_id=page.assignment_id,
        student_id=page.student_id,
        page_id=page.page_id,
        issuance_id=page.issuance_id,
        logical_page=page.logical_page,
        total_pages=page.total_pages,
        route_origin=origin,
        historical_resolution_id=history_id,
        prior_review_action=item.latest_resolution_action,
        route_correction_confirmed=bool(corrected),
    )


__all__ = [
    "PreparedScoreFormScanRecovery",
    "ScoreFormScanRecoveryPreflightError",
    "prepare_scoreform_scan_recovery",
]
