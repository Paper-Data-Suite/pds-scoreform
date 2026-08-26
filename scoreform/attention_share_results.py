"""Adapt ScoreForm Share Results readiness into bounded attention facts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from pds_core.routing_models import ModuleWorkRef

from scoreform.guided_share_results import (
    ShareResultsNextStep,
    ShareResultsReadiness,
)

_SHARE_ATTENTION_CODES: Final[dict[ShareResultsNextStep, str]] = {
    ShareResultsNextStep.REGISTER: "scoreform_results_registration_pending",
    ShareResultsNextStep.GENERATE_MANIFEST: "scoreform_results_manifest_pending",
    ShareResultsNextStep.PUBLISH_FIRST: "scoreform_results_publication_pending",
    ShareResultsNextStep.SUPERSEDE: "scoreform_results_supersession_pending",
    ShareResultsNextStep.WITHDRAWN_HEAD_REQUIRES_EXACT_RECOVERY: (
        "scoreform_results_publication_recovery"
    ),
    ShareResultsNextStep.REPAIR_REQUIRED: "scoreform_results_state_attention",
}


@dataclass(frozen=True, slots=True)
class ScoreFormShareAttentionFact:
    """One assignment-level Share Results attention fact."""

    code: str
    work_ref: ModuleWorkRef

    def __post_init__(self) -> None:
        if self.code not in set(_SHARE_ATTENTION_CODES.values()):
            raise ValueError("Unsupported ScoreForm Share Results attention code.")
        if self.work_ref.module_id != "scoreform":
            raise ValueError("Share Results attention work_ref must belong to ScoreForm.")


def project_share_results_attention(
    readiness: ShareResultsReadiness,
    /,
) -> ScoreFormShareAttentionFact | None:
    """Project one authoritative #191 planner state into shared attention."""

    if not isinstance(readiness, ShareResultsReadiness):
        raise TypeError("readiness must be a ShareResultsReadiness.")

    code = _SHARE_ATTENTION_CODES.get(readiness.next_step)
    if code is None:
        if readiness.next_step in {
            ShareResultsNextStep.NOT_READY,
            ShareResultsNextStep.ALREADY_CURRENT,
        }:
            return None
        raise ValueError("Unsupported Share Results next step.")

    return ScoreFormShareAttentionFact(
        code=code,
        work_ref=readiness.work,
    )


__all__ = [
    "ScoreFormShareAttentionFact",
    "project_share_results_attention",
]
