"""Bounded ScoreForm attention definitions and deterministic aggregation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

from pds_core.module_operations import (
    MAX_MODULE_OPERATION_COUNT,
    ModuleAttentionSummary,
    ModuleOperationsNotice,
    ModuleOperationsRequest,
    ModuleOwnerActionRef,
)
from pds_core.routing_models import ModuleWorkRef

from scoreform.pds_contract import SCOREFORM_MODULE_ID

PARTIAL_NOTICE_CODE: Final = "scoreform_attention_partial"
UNAVAILABLE_NOTICE_CODE: Final = "scoreform_attention_unavailable"
PARTIAL_NOTICE_SUMMARY: Final = (
    "Some ScoreForm attention sources could not be inspected safely; "
    "available summaries are partial."
)
MISSING_WORKSPACE_SUMMARY: Final = (
    "ScoreForm attention requires an explicit workspace."
)
UNSAFE_WORKSPACE_SUMMARY: Final = (
    "The supplied workspace cannot be inspected safely for ScoreForm attention."
)
UNSAFE_CLASS_SCOPE_SUMMARY: Final = (
    "The requested ScoreForm class work scope cannot be inspected safely."
)


@dataclass(frozen=True, slots=True)
class AttentionDefinition:
    code: str
    label: str
    action_id: str


ATTENTION_DEFINITIONS: Final[tuple[AttentionDefinition, ...]] = (
    AttentionDefinition("scoreform_incomplete_attempt", "Incomplete answer-sheet attempts need review", "open_scan_review"),
    AttentionDefinition("scoreform_scan_review", "Returned-paper scan review needs attention", "open_scan_review"),
    AttentionDefinition("scoreform_results_registration_pending", "Results need Academic Work registration before sharing", "open_share_results"),
    AttentionDefinition("scoreform_results_manifest_pending", "A current Academic Result manifest is needed before sharing", "open_share_results"),
    AttentionDefinition("scoreform_results_publication_pending", "Results are ready for explicit first publication", "open_share_results"),
    AttentionDefinition("scoreform_results_supersession_pending", "Newer results are ready for explicit supersession", "open_share_results"),
    AttentionDefinition("scoreform_results_publication_recovery", "Withdrawn publication state needs exact teacher review", "open_share_results"),
    AttentionDefinition("scoreform_results_state_attention", "Result publication state needs teacher inspection", "open_share_results"),
)

DEFINITION_BY_CODE: Final[dict[str, AttentionDefinition]] = {
    definition.code: definition for definition in ATTENTION_DEFINITIONS
}


class ScoreFormAttentionAggregationError(ValueError):
    pass


@dataclass(slots=True)
class _Aggregate:
    count: int = 0
    class_ids: set[str] = field(default_factory=set)
    work_refs: set[ModuleWorkRef] = field(default_factory=set)
    class_context_complete: bool = True
    work_context_complete: bool = True

    def add(self, count: int, *, class_id: str | None, work_ref: ModuleWorkRef | None) -> None:
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ScoreFormAttentionAggregationError(
                "attention count must be a nonnegative integer."
            )
        if count == 0:
            return
        if self.count > MAX_MODULE_OPERATION_COUNT - count:
            raise ScoreFormAttentionAggregationError(
                "attention count exceeds the Core shared-report bound."
            )
        self.count += count
        if class_id is None:
            self.class_context_complete = False
        else:
            self.class_ids.add(class_id)
        if work_ref is None:
            self.work_context_complete = False
        else:
            if work_ref.module_id != SCOREFORM_MODULE_ID:
                raise ScoreFormAttentionAggregationError(
                    "attention work_ref must belong to ScoreForm."
                )
            if class_id is not None and work_ref.class_id != class_id:
                raise ScoreFormAttentionAggregationError(
                    "attention class_id and work_ref.class_id disagree."
                )
            self.work_refs.add(work_ref)


class ScoreFormAttentionAccumulator:
    def __init__(self) -> None:
        self._aggregates: dict[str, _Aggregate] = {}

    def add(
        self,
        code: str,
        count: int,
        *,
        class_id: str | None = None,
        work_ref: ModuleWorkRef | None = None,
    ) -> None:
        if code not in DEFINITION_BY_CODE:
            raise ScoreFormAttentionAggregationError(
                f"Unknown ScoreForm attention code: {code}"
            )
        if count == 0:
            return
        self._aggregates.setdefault(code, _Aggregate()).add(
            count, class_id=class_id, work_ref=work_ref
        )

    def summaries(
        self, request: ModuleOperationsRequest
    ) -> tuple[ModuleAttentionSummary, ...]:
        summaries: list[ModuleAttentionSummary] = []
        for definition in ATTENTION_DEFINITIONS:
            aggregate = self._aggregates.get(definition.code)
            if aggregate is None or aggregate.count == 0:
                continue
            class_id, work_ref = _summary_context(aggregate, request)
            summaries.append(
                ModuleAttentionSummary(
                    code=definition.code,
                    label=definition.label,
                    count=aggregate.count,
                    class_id=class_id,
                    work_ref=work_ref,
                    action=ModuleOwnerActionRef(
                        module_id=SCOREFORM_MODULE_ID,
                        action_id=definition.action_id,
                    ),
                )
            )
        return tuple(summaries)


def _summary_context(
    aggregate: _Aggregate,
    request: ModuleOperationsRequest,
) -> tuple[str | None, ModuleWorkRef | None]:
    if request.class_id is not None:
        if any(value != request.class_id for value in aggregate.class_ids):
            raise ScoreFormAttentionAggregationError(
                "attention aggregate escaped the requested class scope."
            )
        if any(value.class_id != request.class_id for value in aggregate.work_refs):
            raise ScoreFormAttentionAggregationError(
                "attention work aggregate escaped the requested class scope."
            )
    class_id: str | None = None
    if request.class_id is not None:
        class_id = request.class_id
    elif aggregate.class_context_complete and len(aggregate.class_ids) == 1:
        class_id = next(iter(aggregate.class_ids))
    work_ref: ModuleWorkRef | None = None
    if aggregate.work_context_complete and len(aggregate.work_refs) == 1:
        work_ref = next(iter(aggregate.work_refs))
        if class_id is None:
            class_id = work_ref.class_id
    return class_id, work_ref


def partial_notice() -> ModuleOperationsNotice:
    return ModuleOperationsNotice(
        code=PARTIAL_NOTICE_CODE,
        summary=PARTIAL_NOTICE_SUMMARY,
    )


def unavailable_notice(summary: str) -> ModuleOperationsNotice:
    return ModuleOperationsNotice(
        code=UNAVAILABLE_NOTICE_CODE,
        summary=summary,
    )


__all__ = [
    "ATTENTION_DEFINITIONS",
    "DEFINITION_BY_CODE",
    "MISSING_WORKSPACE_SUMMARY",
    "PARTIAL_NOTICE_CODE",
    "PARTIAL_NOTICE_SUMMARY",
    "ScoreFormAttentionAccumulator",
    "ScoreFormAttentionAggregationError",
    "UNAVAILABLE_NOTICE_CODE",
    "UNSAFE_CLASS_SCOPE_SUMMARY",
    "UNSAFE_WORKSPACE_SUMMARY",
    "partial_notice",
    "unavailable_notice",
]
