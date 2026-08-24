"""Structured teacher-facing scan diagnostic coverage for issue #190."""

from __future__ import annotations

from types import MappingProxyType, SimpleNamespace

import pytest

from scoreform.module_errors import ScoreFormPageScoringError
from scoreform.scan_review_persistence import _scoreform_dispatch_category
from scoreform.scan_teacher_diagnostics import project_teacher_scan_diagnostic


def _item(
    *,
    core_category: str,
    detail_category: str | None = None,
    source_scan_id: str | None = "scan_20260824",
    retained_source_path: str | None = "scans/source/2026-08-24/scan.pdf",
    context: dict[str, object] | None = None,
    diagnostic_paths: tuple[str, ...] = (),
    failure_message: str = "Low-level diagnostic prose.",
):
    details = None
    if detail_category is not None:
        details = SimpleNamespace(
            scoreform_category=detail_category,
            context=MappingProxyType({} if context is None else context),
            diagnostic_paths=diagnostic_paths,
        )
    return SimpleNamespace(
        failure_category=core_category,
        scoreform_failure_category=detail_category,
        source_scan_id=source_scan_id,
        retained_source_path=retained_source_path,
        details=details,
        failure_message=failure_message,
    )


def test_registration_diagnostic_uses_structured_category_not_message_text() -> None:
    registration = project_teacher_scan_diagnostic(
        _item(
            core_category="processing_error",
            detail_category="registration_marks_missing",
            diagnostic_paths=("classes/class1/modules/scoreform/work/quiz/debug/page.png",),
            failure_message="opaque",
        ),
        allowed_actions=("rescan_needed", "manual_entry", "defer"),
    )
    assert registration.family == "registration"
    assert registration.headline == "The page could not be aligned reliably"
    assert registration.evidence_status == "retained"
    assert registration.recommended_actions == (
        "rescan_needed",
        "manual_entry",
        "defer",
    )
    assert registration.diagnostic_artifacts_available

    misleading_prose = project_teacher_scan_diagnostic(
        _item(
            core_category="processing_error",
            detail_category="route_dispatch",
            failure_message="Could not detect four registration marks.",
        ),
        allowed_actions=("rescan_needed", "defer"),
    )
    assert misleading_prose.family == "processing"


def test_missing_pages_explains_physical_membership_without_page_ids() -> None:
    diagnostic = project_teacher_scan_diagnostic(
        _item(
            core_category="page_conflict",
            detail_category="missing_pages",
            context={
                "expected_logical_pages": (1, 2, 3),
                "missing_logical_pages": (2,),
                "missing_page_ids": ("pg_secret",),
            },
        ),
        allowed_actions=("rescan_needed", "defer"),
    )

    assert diagnostic.family == "incomplete_attempt"
    assert "page 2 of 3" in diagnostic.explanation
    assert "pg_secret" not in diagnostic.explanation
    assert diagnostic.recommended_actions == ("rescan_needed", "defer")


@pytest.mark.parametrize(
    ("core_category", "expected_family"),
    [
        ("payload_missing", "qr"),
        ("payload_unreadable", "qr"),
        ("payload_invalid", "qr"),
        ("route_unknown", "route"),
        ("route_inactive", "route"),
        ("route_ambiguous", "ambiguity"),
        ("module_profile_incompatible", "system"),
        ("target_incompatible", "target"),
        ("evidence_write_failed", "persistence"),
    ],
)
def test_core_failure_families_are_stable(
    core_category: str,
    expected_family: str,
) -> None:
    diagnostic = project_teacher_scan_diagnostic(
        _item(core_category=core_category),
        allowed_actions=(
            "route_selected",
            "route_corrected",
            "rescan_needed",
            "cannot_route",
            "defer",
        ),
    )
    assert diagnostic.family == expected_family
    assert set(diagnostic.recommended_actions).issubset(
        {
            "route_selected",
            "route_corrected",
            "rescan_needed",
            "cannot_route",
            "defer",
        }
    )


@pytest.mark.parametrize(
    ("detail_category", "expected_family"),
    [
        ("duplicate_page", "duplicate"),
        ("duplicate_route", "duplicate"),
        ("conflicting_duplicate", "duplicate"),
        ("inconsistent_issuance", "mixed_identity"),
        ("unexpected_page", "mixed_identity"),
        ("invalid_result_identity", "target"),
        ("assignment_incompatible", "target"),
        ("issuance_not_authorized", "target"),
    ],
)
def test_scoreform_detail_families_are_stable(
    detail_category: str,
    expected_family: str,
) -> None:
    diagnostic = project_teacher_scan_diagnostic(
        _item(
            core_category="page_conflict",
            detail_category=detail_category,
        ),
        allowed_actions=(
            "dismissed_duplicate",
            "rescan_needed",
            "mixed_assignment",
            "route_selected",
            "cannot_route",
            "defer",
        ),
    )
    assert diagnostic.family == expected_family


def test_retention_status_does_not_infer_from_filename_or_message() -> None:
    not_retained = project_teacher_scan_diagnostic(
        _item(
            core_category="source_missing",
            detail_category="scoreformsourcemissingerror",
            source_scan_id=None,
            retained_source_path=None,
            failure_message="saved retained scan.pdf",
        ),
        allowed_actions=("defer",),
    )
    assert not_retained.evidence_status == "not_retained"
    assert "before ScoreForm can confirm" in not_retained.evidence_message

    uncertain = project_teacher_scan_diagnostic(
        _item(
            core_category="processing_error",
            source_scan_id="scan_only",
            retained_source_path=None,
        ),
        allowed_actions=("defer",),
    )
    assert uncertain.evidence_status == "uncertain"


def test_recommended_actions_can_never_exceed_actual_allowed_actions() -> None:
    diagnostic = project_teacher_scan_diagnostic(
        _item(
            core_category="processing_error",
            detail_category="registration_marks_missing",
        ),
        allowed_actions=("defer",),
    )
    assert diagnostic.recommended_actions == ("defer",)

    with pytest.raises(ValueError, match="allowed_actions"):
        project_teacher_scan_diagnostic(
            _item(core_category="processing_error"),
            allowed_actions=("invented_action",),
        )


def test_page_scoring_diagnostic_code_survives_wrapped_exception_chain() -> None:
    cause = ScoreFormPageScoringError(
        "human wording may change",
        diagnostic_code="registration_marks_missing",
    )
    try:
        raise RuntimeError("Core wrapper") from cause
    except RuntimeError as wrapped:
        assert _scoreform_dispatch_category(wrapped) == "registration_marks_missing"


def test_page_scoring_diagnostic_code_is_closed_and_backward_compatible() -> None:
    legacy = ScoreFormPageScoringError("legacy caller")
    assert legacy.diagnostic_code == "page_scoring_error"

    with pytest.raises(ValueError, match="diagnostic_code"):
        ScoreFormPageScoringError("bad", diagnostic_code="message_contains_magic")
