"""Issue #225 Slice 15: read-only optical qualification of Core-retained failed pages.

This is NOT recovery, a grade, or teacher confirmation. It validates the exact
original source and issued registered page before testing actual mark recognition.
Only small privacy-bounded outcomes leave this module; no result row or Core
resolution event is written, and no diagnostic artifacts are created.
"""

from __future__ import annotations

import io
from contextlib import redirect_stdout
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from pds_core.routing_models import RouteLocator

from scoreform.answer_sheet_persistence import load_answer_sheet_page_context
from scoreform.assignment import load_assignment
from scoreform.layouts import require_layout
from scoreform.page_scoring import (
    score_authoritative_answer_sheet_page,
    validate_assignment_page_compatibility,
    validate_page_dispatch_result,
)
from scoreform.qr_scan_recovery_preflight import prepare_scoreform_scan_recovery
from scoreform.retained_page import load_retained_source_page
from scoreform.work_paths import scoreform_work_paths

QualificationOutcome = Literal["omr_scored", "omr_failed", "authority_rejected"]
SCHEMA = "scoreform_issue225_physical_omr_qualification_v1"


@dataclass(frozen=True, slots=True)
class PhysicalRecoverySelection:
    """Exact teacher-provided choice; no identity guessed from an unreadable QR."""

    failure_id: str
    route_locator: RouteLocator | None = None
    use_recorded_route: bool = False
    allow_route_correction: bool = False

    def __post_init__(self) -> None:
        if type(self.failure_id) is not str or not self.failure_id:
            raise ValueError("An exact failure ID is required.")
        if type(self.use_recorded_route) is not bool or type(self.allow_route_correction) is not bool:
            raise TypeError("Recovery selection flags must be Boolean.")
        if self.use_recorded_route:
            if self.route_locator is not None or self.allow_route_correction:
                raise ValueError("Recorded-route reuse cannot request a new route or correction.")
        elif not isinstance(self.route_locator, RouteLocator):
            raise ValueError("A teacher-selected registered route is required.")


@dataclass(frozen=True, slots=True)
class PhysicalRecoveryPageQualification:
    """Public-safe outcome; never include student, source, route, marks, or score."""

    index: int
    outcome: QualificationOutcome
    stage: Literal["authority", "omr", "complete"]
    physical_page: int | None = None
    logical_page: int | None = None
    expected_page_count: int | None = None
    questions_evaluated: int | None = None
    blank_marks: int | None = None
    ambiguous_marks: int | None = None


def _redacted_scoring(prepared, *, root: Path) -> tuple[int, int, int]:
    """Score original physical pixels with diagnostic writes explicitly disabled."""
    context = load_answer_sheet_page_context(root, prepared.route_locator.work, prepared.page_id)
    if context.issuance.lifecycle.status != "issued":
        raise ValueError("Original issuance is no longer issued.")
    paths = scoreform_work_paths(root, prepared.class_id, prepared.assignment_id)
    if paths.assignment_path.is_symlink():
        raise ValueError("Managed assignment must not be linked.")
    # Neither accidental assignment-printing nor OMR chatter belongs in reports.
    with redirect_stdout(io.StringIO()):
        assignment = load_assignment(paths.assignment_path)
    if assignment is None:
        raise ValueError("Managed assignment cannot be loaded.")
    validate_assignment_page_compatibility(context, assignment)
    retained_page = load_retained_source_page(
        prepared.retained_source, prepared.source_page_number, workspace_root=root
    )
    with redirect_stdout(io.StringIO()):
        scored = score_authoritative_answer_sheet_page(
            retained_page.image,
            page_context=context,
            assignment=assignment,
            route_id=prepared.route_locator.route_id,
            source_scan_id=prepared.retained_source.source_scan_id,
            source_page_number=prepared.source_page_number,
            retained_source_relative_path=prepared.retained_source.retained_source_relative_path,
            source_sha256=prepared.retained_source.source_sha256,
            debug_dir=None,
        )
    scored = validate_page_dispatch_result(
        scored, valid_choices=require_layout(context.page.layout_id).choices
    )
    page = context.page
    if (
        scored.route_id != prepared.route_locator.route_id
        or scored.page_id != prepared.page_id
        or scored.issuance_id != prepared.issuance_id
        or scored.class_id != prepared.class_id
        or scored.assignment_id != prepared.assignment_id
        or scored.student_id != prepared.student_id
        or scored.logical_page != prepared.logical_page
        or scored.total_pages != prepared.total_pages
        or scored.source_scan_id != prepared.retained_source.source_scan_id
        or scored.source_page_number != prepared.source_page_number
        or scored.retained_source_relative_path != prepared.retained_source.retained_source_relative_path
        or scored.source_sha256 != prepared.retained_source.source_sha256
        or scored.question_start != page.question_start
        or scored.question_end != page.question_end
        or scored.layout_id != page.layout_id
        or scored.diagnostic_paths
    ):
        raise ValueError("OMR response contradicts original registered page/source authority.")
    answers = tuple(answer.selected_answer for answer in scored.answers)
    blanks = answers.count("BLANK")
    ambiguous = answers.count("AMBIGUOUS")
    return len(answers), blanks, ambiguous


def qualify_physical_recovery_page(
    root: str | Path,
    selection: PhysicalRecoverySelection,
    *,
    index: int = 1,
) -> PhysicalRecoveryPageQualification:
    """Safely assess recognizability; fail closed and never persist grading data."""
    if type(selection) is not PhysicalRecoverySelection:
        raise TypeError("An exact physical recovery selection is required.")
    if type(index) is not int or index < 1:
        raise ValueError("Qualification index must be positive.")
    root = Path(root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Workspace must be an existing directory.")
    try:
        prepared = prepare_scoreform_scan_recovery(
            root,
            selection.failure_id,
            route_locator=selection.route_locator,
            use_recorded_route=selection.use_recorded_route,
            allow_route_correction=selection.allow_route_correction,
        )
    except Exception:
        return PhysicalRecoveryPageQualification(index, "authority_rejected", "authority")
    try:
        marks, blanks, ambiguous = _redacted_scoring(prepared, root=root)
        # Recheck original source and registered route after expensive OMR.
        current = prepare_scoreform_scan_recovery(
            root,
            selection.failure_id,
            route_locator=selection.route_locator,
            use_recorded_route=selection.use_recorded_route,
            allow_route_correction=selection.allow_route_correction,
        )
        if current != prepared:
            raise ValueError("Original source or authority changed during OMR.")
    except Exception:
        return PhysicalRecoveryPageQualification(
            index, "omr_failed", "omr", prepared.source_page_number,
            prepared.logical_page, prepared.total_pages,
        )
    return PhysicalRecoveryPageQualification(
        index, "omr_scored", "complete", prepared.source_page_number,
        prepared.logical_page, prepared.total_pages, marks, blanks, ambiguous,
    )


def build_physical_recovery_report(
    qualifications: tuple[PhysicalRecoveryPageQualification, ...],
) -> dict[str, object]:
    if not qualifications or any(
        type(page) is not PhysicalRecoveryPageQualification or page.index != n
        for n, page in enumerate(qualifications, start=1)
    ):
        raise ValueError("Nonempty ordered qualification evidence is required.")
    return {
        "schema": SCHEMA,
        "scope": "existing_core_retained_failure_real_omr_no_persistence",
        "real_optical_recognition": True,
        "core_result_writer_invoked": False,
        "scan_review_resolution_written": False,
        "grade_saved": False,
        "physical_mark_comparison_performed": False,
        "new_print_geometry_qualified": False,
        "all_pages_scored": all(page.outcome == "omr_scored" for page in qualifications),
        "pages": [asdict(page) for page in qualifications],
    }


__all__ = [
    "PhysicalRecoveryPageQualification",
    "PhysicalRecoverySelection",
    "build_physical_recovery_report",
    "qualify_physical_recovery_page",
]
