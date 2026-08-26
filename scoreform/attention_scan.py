"""Adapt current ScoreForm scan-review state into bounded attention facts."""

from __future__ import annotations

from dataclasses import dataclass

from pds_core.routing_models import ModuleWorkRef

from scoreform.scan_review_resolution import (
    RESOLUTION_ACTIONS,
    ScoreFormReviewItem,
)
from scoreform.scan_teacher_diagnostics import project_teacher_scan_diagnostic


@dataclass(frozen=True, slots=True)
class ScoreFormScanAttentionFact:
    """Privacy-minimal current attention fact for one open review item."""

    code: str
    class_id: str | None = None
    work_ref: ModuleWorkRef | None = None

    def __post_init__(self) -> None:
        if self.code not in {
            "scoreform_incomplete_attempt",
            "scoreform_scan_review",
        }:
            raise ValueError("Unsupported ScoreForm scan attention code.")
        if self.work_ref is not None:
            if self.work_ref.module_id != "scoreform":
                raise ValueError("scan attention work_ref must belong to ScoreForm.")
            if (
                self.class_id is not None
                and self.work_ref.class_id != self.class_id
            ):
                raise ValueError(
                    "scan attention class_id and work_ref.class_id disagree."
                )


def project_scan_attention_fact(
    item: ScoreFormReviewItem,
    /,
) -> ScoreFormScanAttentionFact:
    """Reuse #190's public diagnostic family to classify one open review item."""

    diagnostic = project_teacher_scan_diagnostic(
        item,
        allowed_actions=RESOLUTION_ACTIONS,
    )
    code = (
        "scoreform_incomplete_attempt"
        if diagnostic.family == "incomplete_attempt"
        else "scoreform_scan_review"
    )

    class_id: str | None = None
    work_ref: ModuleWorkRef | None = None
    identity = item.identity
    if identity.source in {"validated_target", "validated_locator"}:
        class_id = identity.class_id
        if class_id is not None and identity.assignment_id is not None:
            work_ref = ModuleWorkRef(
                module_id="scoreform",
                class_id=class_id,
                work_id=identity.assignment_id,
            )

    return ScoreFormScanAttentionFact(
        code=code,
        class_id=class_id,
        work_ref=work_ref,
    )


__all__ = [
    "ScoreFormScanAttentionFact",
    "project_scan_attention_fact",
]
