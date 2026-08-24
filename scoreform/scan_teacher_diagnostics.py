"""Teacher-facing projection of validated ScoreForm scan-review failures."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from scoreform.scan_review_resolution import RESOLUTION_ACTIONS, ScoreFormReviewItem

TeacherDiagnosticFamily = Literal[
    "source",
    "registration",
    "qr",
    "route",
    "system",
    "target",
    "incomplete_attempt",
    "duplicate",
    "mixed_identity",
    "ambiguity",
    "persistence",
    "processing",
]
EvidenceStatus = Literal["retained", "not_retained", "uncertain"]

_ASSEMBLY_CATEGORIES = frozenset(
    {
        "missing_pages",
        "duplicate_page",
        "duplicate_route",
        "conflicting_duplicate",
        "inconsistent_issuance",
        "unexpected_page",
        "invalid_page_order",
        "invalid_question_coverage",
        "invalid_result_identity",
    }
)
_ROUTE_CATEGORIES = frozenset(
    {
        "route_unknown",
        "route_inactive",
        "route_ambiguous",
        "route_mismatch",
        "route_registration_invalid",
    }
)
_SYSTEM_CATEGORIES = frozenset(
    {
        "module_unsupported",
        "module_profile_incompatible",
    }
)
_TARGET_CATEGORIES = frozenset(
    {
        "class_unknown",
        "work_unknown",
        "target_unknown",
        "target_incompatible",
    }
)
_QR_INVALID_CATEGORIES = frozenset(
    {
        "payload_invalid",
        "payload_schema_unsupported",
        "payload_too_large",
        "identifier_invalid",
    }
)
_TARGET_DETAIL_CATEGORIES = frozenset(
    {
        "assignment_incompatible",
        "issuance_not_authorized",
        "target_integrity",
        "retained_page_invalid",
        "route_context_invalid",
        "registration_invalid",
        "invalid_result_identity",
    }
)
_PERSISTENCE_DETAIL_CATEGORIES = frozenset(
    {
        "diagnostic_write_failed",
        "write",
        "cleanup",
    }
)


@dataclass(frozen=True, slots=True)
class TeacherScanDiagnostic:
    """Bounded teacher-facing interpretation of one canonical review item."""

    family: TeacherDiagnosticFamily
    headline: str
    explanation: str
    evidence_status: EvidenceStatus
    evidence_message: str
    guidance: str
    recommended_actions: tuple[str, ...]
    diagnostic_artifacts_available: bool
    technical_details_available: bool = True

    def __post_init__(self) -> None:
        if self.family not in {
            "source",
            "registration",
            "qr",
            "route",
            "system",
            "target",
            "incomplete_attempt",
            "duplicate",
            "mixed_identity",
            "ambiguity",
            "persistence",
            "processing",
        }:
            raise ValueError("Unsupported teacher diagnostic family.")
        for name in ("headline", "explanation", "evidence_message", "guidance"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be nonempty teacher-facing text.")
        if self.evidence_status not in {"retained", "not_retained", "uncertain"}:
            raise ValueError("Unsupported evidence status.")
        if (
            not isinstance(self.recommended_actions, tuple)
            or len(self.recommended_actions) != len(set(self.recommended_actions))
            or any(action not in RESOLUTION_ACTIONS for action in self.recommended_actions)
        ):
            raise ValueError("recommended_actions must be unique supported actions.")
        if not isinstance(self.diagnostic_artifacts_available, bool):
            raise TypeError("diagnostic_artifacts_available must be Boolean.")
        if not isinstance(self.technical_details_available, bool):
            raise TypeError("technical_details_available must be Boolean.")


@dataclass(frozen=True, slots=True)
class _DiagnosticSpec:
    family: TeacherDiagnosticFamily
    headline: str
    explanation: str
    guidance: str
    preferred_actions: tuple[str, ...]


def _evidence_state(item: ScoreFormReviewItem) -> tuple[EvidenceStatus, str]:
    if item.source_scan_id and item.retained_source_path:
        return (
            "retained",
            "The original scan is safely retained in the PDS workspace.",
        )
    if item.source_scan_id or item.retained_source_path:
        return (
            "uncertain",
            "ScoreForm cannot confirm complete retained-source provenance for this item.",
        )
    return (
        "not_retained",
        "This failure occurred before ScoreForm can confirm that the source was retained.",
    )


def _available_recommendations(
    preferred: tuple[str, ...],
    allowed_actions: tuple[str, ...],
) -> tuple[str, ...]:
    if (
        not isinstance(allowed_actions, tuple)
        or len(allowed_actions) != len(set(allowed_actions))
        or any(action not in RESOLUTION_ACTIONS for action in allowed_actions)
    ):
        raise ValueError("allowed_actions must be unique supported review actions.")
    allowed = set(allowed_actions)
    return tuple(action for action in preferred if action in allowed)


def _context_ints(item: ScoreFormReviewItem, key: str) -> tuple[int, ...]:
    details = item.details
    if details is None:
        return ()
    raw = details.context.get(key)
    if not isinstance(raw, (tuple, list)):
        return ()
    values = tuple(
        value
        for value in raw
        if isinstance(value, int) and not isinstance(value, bool) and value >= 1
    )
    return values if len(values) == len(raw) else ()


def _missing_pages_spec(item: ScoreFormReviewItem) -> _DiagnosticSpec:
    missing = _context_ints(item, "missing_logical_pages")
    expected = _context_ints(item, "expected_logical_pages")
    if missing:
        page_word = "page" if len(missing) == 1 else "pages"
        listed = ", ".join(str(value) for value in missing)
        if expected:
            explanation = (
                f"This issued response set is incomplete. Required {page_word} "
                f"{listed} of {len(expected)} were not found in the retained scan."
            )
        else:
            explanation = (
                f"This issued response set is incomplete. Required {page_word} "
                f"{listed} were not found in the retained scan."
            )
    else:
        explanation = (
            "ScoreForm recognized part of an issued response set, but not all "
            "required pages were available to assemble a complete attempt."
        )
    return _DiagnosticSpec(
        "incomplete_attempt",
        "A required answer-sheet page is missing",
        explanation,
        "Locate and rescan the missing physical page or pages. Do not force an "
        "incomplete response set into results.",
        ("rescan_needed", "defer"),
    )


def _spec_for(item: ScoreFormReviewItem) -> _DiagnosticSpec:
    core = item.failure_category
    detail = item.scoreform_failure_category

    if core == "source_missing":
        return _DiagnosticSpec(
            "source",
            "The selected scan file is missing",
            "ScoreForm could not open the selected source because the file is no "
            "longer available at the supplied location.",
            "Return to Process Scans and choose the correct file, or restore the "
            "source before retrying.",
            ("defer",),
        )
    if core in {"source_unreadable", "source_type_unsupported"}:
        return _DiagnosticSpec(
            "source",
            "The selected scan could not be read",
            "ScoreForm could not use the selected file as a supported scan source.",
            "Choose a readable supported scan file. If this came from a scanner, "
            "create a fresh scan before retrying.",
            ("rescan_needed", "defer"),
        )
    if core == "source_retention_failed":
        return _DiagnosticSpec(
            "source",
            "The scan could not be retained safely",
            "Core could not create the authoritative retained-source evidence, so "
            "ScoreForm stopped before treating the paper as safely retained.",
            "Keep the original file. Resolve the workspace or storage problem before "
            "retrying, and do not assume PDS preserved this source.",
            ("defer",),
        )

    if detail == "registration_marks_missing":
        return _DiagnosticSpec(
            "registration",
            "The page could not be aligned reliably",
            "ScoreForm could not reliably locate all four required registration "
            "marks, so this page was not scored.",
            "Rescan the complete page flat and reasonably upright, with all four "
            "corner registration marks visible and without cropping.",
            ("rescan_needed", "manual_entry", "manual_marks", "defer"),
        )
    if detail == "omr_processing_failed":
        return _DiagnosticSpec(
            "registration",
            "Automatic mark reading could not finish",
            "ScoreForm could not complete reliable OMR processing for this page.",
            "Rescan the full page clearly. If repeated scans fail and verified "
            "identity is available, use an allowed manual fallback or defer.",
            ("rescan_needed", "manual_entry", "manual_marks", "defer"),
        )
    if detail in _PERSISTENCE_DETAIL_CATEGORIES:
        return _DiagnosticSpec(
            "persistence",
            "Diagnostic or result evidence could not be saved",
            "ScoreForm reached a persistence step that did not complete safely.",
            "Keep the retained evidence and inspect technical details before retrying. "
            "Do not assume a missing result or review artifact was written.",
            ("defer",),
        )

    if core == "payload_missing":
        return _DiagnosticSpec(
            "qr",
            "No usable routing code was found",
            "ScoreForm could not detect a usable PDS2 QR code on this page.",
            "Rescan the complete generated page with the QR area clear and readable. "
            "Use explicit route recovery only when the paper identity can be "
            "verified safely.",
            ("rescan_needed", "route_selected", "route_corrected", "cannot_route", "defer"),
        )
    if core == "payload_unreadable":
        return _DiagnosticSpec(
            "qr",
            "The routing code could not be read",
            "A routing-code read was attempted, but ScoreForm could not obtain usable "
            "decoded text.",
            "Rescan the complete generated page clearly. If the original paper is "
            "damaged, use only an allowed verified recovery path.",
            ("rescan_needed", "route_selected", "route_corrected", "cannot_route", "defer"),
        )
    if core in _QR_INVALID_CATEGORIES:
        return _DiagnosticSpec(
            "qr",
            "The routing code is not a valid supported PDS2 identity",
            "ScoreForm read routing data, but it could not be accepted as a valid "
            "supported PDS2 locator.",
            "Check that this is the original generated ScoreForm page. Rescan if the "
            "code may have been read incorrectly; otherwise use explicit verified "
            "route recovery or defer.",
            ("rescan_needed", "route_selected", "route_corrected", "cannot_route", "defer"),
        )

    if core == "route_ambiguous":
        return _DiagnosticSpec(
            "ambiguity",
            "The routing code matches more than one possible route",
            "Core could not resolve this paper to one exact authoritative route.",
            "Do not guess. Select or correct an existing route only when the paper "
            "identity can be verified; otherwise defer or mark it unsafe to route.",
            ("route_selected", "route_corrected", "cannot_route", "defer"),
        )
    if core in _ROUTE_CATEGORIES:
        return _DiagnosticSpec(
            "route",
            "The paper's registered route cannot be used",
            "The routing code was read, but Core could not resolve it to one usable "
            "current route.",
            "Inspect the paper's verified identity. Correct or select an existing "
            "route only when safe; otherwise defer or mark the paper unsafe to route.",
            ("route_selected", "route_corrected", "cannot_route", "defer"),
        )
    if core in _SYSTEM_CATEGORIES:
        return _DiagnosticSpec(
            "system",
            "The installed module environment cannot process this route",
            "The paper was routed far enough to identify a module compatibility or "
            "availability problem. Rescanning the same paper will not fix it.",
            "Repair or update the installed PDS module environment, then retry from "
            "the retained source. Defer the item until that environment is healthy.",
            ("defer", "cannot_route"),
        )

    if detail == "missing_pages":
        return _missing_pages_spec(item)
    if detail in {"duplicate_page", "duplicate_route", "conflicting_duplicate"}:
        conflict = detail == "conflicting_duplicate"
        return _DiagnosticSpec(
            "duplicate",
            (
                "Conflicting copies of the same answer-sheet page were found"
                if conflict
                else "A duplicate answer-sheet page was found"
            ),
            (
                "ScoreForm found repeated physical-page evidence that contradicts "
                "itself, so it cannot assemble the attempt safely."
                if conflict
                else "ScoreForm found repeated evidence for a physical page and "
                "will not silently decide which copy should count."
            ),
            (
                "Inspect the physical pages and retained evidence. Dismiss a "
                "duplicate only when the existing review action permits it and the "
                "duplicate is genuinely harmless; otherwise rescan or defer."
            ),
            ("dismissed_duplicate", "rescan_needed", "defer"),
        )
    if detail in {
        "inconsistent_issuance",
        "unexpected_page",
        "invalid_page_order",
        "invalid_question_coverage",
    }:
        return _DiagnosticSpec(
            "mixed_identity",
            "The scanned pages do not form one consistent issued response set",
            "Authoritative page membership, issuance, order, or question coverage "
            "does not agree well enough to create a complete attempt.",
            "Separate the physical papers and rescan the intended issuance. Do not "
            "regroup pages by filename, scan order, or current assignment context.",
            ("mixed_assignment", "rescan_needed", "defer"),
        )

    if detail in _TARGET_DETAIL_CATEGORIES or core in _TARGET_CATEGORIES:
        return _DiagnosticSpec(
            "target",
            "The routed paper does not match a usable current ScoreForm target",
            "ScoreForm could not safely reconcile the routed page with its current "
            "authoritative assignment, issuance, or page identity.",
            "Inspect the verified target and technical details. Do not fabricate "
            "identity or force this page into results; defer or use an explicit safe "
            "route action where available.",
            ("route_selected", "route_corrected", "cannot_route", "defer"),
        )

    if core == "page_conflict":
        return _DiagnosticSpec(
            "mixed_identity",
            "The page set contains conflicting attempt evidence",
            "ScoreForm found page-level evidence that cannot be assembled into one "
            "safe complete attempt.",
            "Inspect the retained pages and technical classification, then rescan, "
            "resolve the permitted conflict explicitly, or defer.",
            ("rescan_needed", "mixed_assignment", "dismissed_duplicate", "defer"),
        )
    if core == "evidence_write_failed":
        return _DiagnosticSpec(
            "persistence",
            "ScoreForm could not save required evidence",
            "A processing step reached an evidence-write boundary that did not "
            "complete safely.",
            "Keep the original or retained source and inspect technical details "
            "before retrying. Do not assume the missing artifact was saved.",
            ("defer",),
        )

    return _DiagnosticSpec(
        "processing",
        "ScoreForm could not complete this scan item safely",
        "Processing stopped because the current evidence could not be accepted as a "
        "complete safe ScoreForm outcome.",
        "Review the technical classification and retained evidence. Rescan when the "
        "paper may be the cause; otherwise defer for follow-up.",
        ("rescan_needed", "cannot_route", "defer"),
    )


def project_teacher_scan_diagnostic(
    item: ScoreFormReviewItem,
    *,
    allowed_actions: tuple[str, ...],
) -> TeacherScanDiagnostic:
    """Project one validated review item into bounded teacher recovery guidance."""

    spec = _spec_for(item)
    evidence_status, evidence_message = _evidence_state(item)
    details = item.details
    diagnostic_artifacts_available = bool(
        details is not None and details.diagnostic_paths
    )
    return TeacherScanDiagnostic(
        family=spec.family,
        headline=spec.headline,
        explanation=spec.explanation,
        evidence_status=evidence_status,
        evidence_message=evidence_message,
        guidance=spec.guidance,
        recommended_actions=_available_recommendations(
            spec.preferred_actions,
            allowed_actions,
        ),
        diagnostic_artifacts_available=diagnostic_artifacts_available,
    )
