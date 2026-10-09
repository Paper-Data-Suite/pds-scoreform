"""Issue #225 Slice 12: teacher-confirmed retained-page recovery coordination.

The preview is read-only. Execution requires an exact approved preview,
rechecks current authority, records a route decision only when the teacher's
choice is not already the latest recorded decision, then dispatches via Core.
Only a complete issuance may reach the existing schema-v2 writer. A Core route
resolution records a decision, NEVER a completed result or a successful score.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pds_core.module_profiles import ModuleRegistry
from pds_core.pds2 import serialize_pds2_payload
from pds_core.routing_models import ModuleRecordRef, RouteLocator

from scoreform.pds2_scan_dispatch import Pds2ScanDispatchResult
from scoreform.qr_scan_recovery_assembly import (
    ScoreFormRecoveryAssemblyPlan,
    prepare_scoreform_recovery_assembly,
)
from scoreform.qr_scan_recovery_completion import (
    ScoreFormRecoveryCompletion,
    confirm_scoreform_recovery_completion,
    inspect_scoreform_recovery_completion,
)
from scoreform.qr_scan_recovery_dispatch import (
    DispatchedScoreFormScanRecovery,
    dispatch_prepared_scoreform_scan_recovery,
)
from scoreform.qr_scan_recovery_persistence import (
    PersistedScoreFormRecovery,
    persist_scoreform_recovery_attempt,
)
from scoreform.qr_scan_recovery_preflight import (
    PreparedScoreFormScanRecovery,
    prepare_scoreform_scan_recovery,
)
from scoreform.scan_review_resolution import (
    ScoreFormReviewItem,
    discover_scan_review_items,
    resolve_scan_review_item,
)

WorkflowStage = Literal["preflight", "route_decision", "dispatch", "assembly", "persistence", "completion"]
WorkflowStatus = Literal["verified_complete", "already_complete", "needs_pages", "review_required"]
_ROUTE_ACTIONS = frozenset({"route_selected", "route_corrected"})


class ScoreFormRecoveryWorkflowError(RuntimeError):
    """Recovery stopped at a known stage; prior durable effects may remain."""

    def __init__(
        self,
        stage: WorkflowStage,
        message: str,
        *,
        failure_id: str | None = None,
        persisted: PersistedScoreFormRecovery | None = None,
    ) -> None:
        super().__init__(f"Recovery stopped ({stage}): {message}")
        self.stage = stage
        self.failure_id = failure_id
        self.persisted = persisted


@dataclass(frozen=True, slots=True)
class ScoreFormRecoveryRouteSelection:
    """One explicit route choice or deliberate reuse of a recorded choice."""

    failure_id: str
    route_locator: RouteLocator | None = None
    target: ModuleRecordRef | None = None
    use_recorded_route: bool = False
    allow_route_correction: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.failure_id, str) or not self.failure_id:
            raise ValueError("Route selection requires a failure ID.")
        if type(self.use_recorded_route) is not bool or type(self.allow_route_correction) is not bool:
            raise TypeError("Route selection flags must be Boolean.")
        if self.use_recorded_route:
            if self.route_locator is not None or self.target is not None or self.allow_route_correction:
                raise ValueError("Recorded selection cannot include an explicit route or correction.")
        elif not isinstance(self.route_locator, RouteLocator):
            raise ValueError("An explicit registered route is required.")
        if self.target is not None and not isinstance(self.target, ModuleRecordRef):
            raise TypeError("Route target must be a Core ModuleRecordRef.")


@dataclass(frozen=True, slots=True)
class ScoreFormRecoveryWorkflowPreview:
    """Read-only teacher preview; never itself a write authorization."""

    selections: tuple[ScoreFormRecoveryRouteSelection, ...]
    prepared_pages: tuple[PreparedScoreFormScanRecovery, ...]
    issuance_id: str
    source_scan_id: str
    source_page_numbers: tuple[int, ...]
    route_decisions_needed: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ScoreFormRecoveryWorkflowOutcome:
    """Report actual outcome; a selected route never implies a saved score."""

    status: WorkflowStatus
    reason: str
    failure_ids: tuple[str, ...]
    recorded_route_failure_ids: tuple[str, ...] = ()
    missing_logical_pages: tuple[int, ...] = ()
    assembly: ScoreFormRecoveryAssemblyPlan | None = None
    persisted: PersistedScoreFormRecovery | None = None
    completion: tuple[ScoreFormRecoveryCompletion, ...] = ()

    @property
    def verified(self) -> bool:
        return self.status in {"verified_complete", "already_complete"} and all(
            item.verified for item in self.completion
        ) and bool(self.completion)


def _root(value: str | Path) -> Path:
    try:
        root = Path(value).resolve(strict=True)
        if not root.is_dir():
            raise ValueError("Workspace is not a directory.")
        return root
    except (TypeError, ValueError, OSError, RuntimeError) as error:
        raise ScoreFormRecoveryWorkflowError("preflight", "Invalid recovery workspace.") from error


def _prepare_one(
    root: Path, selection: ScoreFormRecoveryRouteSelection
) -> PreparedScoreFormScanRecovery:
    return prepare_scoreform_scan_recovery(
        root,
        selection.failure_id,
        route_locator=selection.route_locator,
        target=selection.target,
        use_recorded_route=selection.use_recorded_route,
        allow_route_correction=selection.allow_route_correction,
    )


def _latest_items(root: Path) -> dict[str, ScoreFormReviewItem]:
    return {
        item.failure_id: item
        for item in discover_scan_review_items(root, include_resolved=True).items
    }


def _recorded_matches(
    item: ScoreFormReviewItem, prepared: PreparedScoreFormScanRecovery
) -> bool:
    """Never infer consent from QR hints or from merely resolved metadata."""
    return (
        item.latest_resolution_action in _ROUTE_ACTIONS
        and item.latest_resolution is not None
        and item.latest_resolution.resolution_status == "resolved"
        and item.latest_resolution.route_locator == prepared.route_locator
        and item.latest_resolution.target == prepared.target
    )


def preview_scoreform_recovery_workflow(
    workspace_root: str | Path,
    selections: tuple[ScoreFormRecoveryRouteSelection, ...],
) -> ScoreFormRecoveryWorkflowPreview:
    """Read-only preflight for one issued attempt from one retained source.

    A recent manual resolution or different teacher-selected route cannot be
    silently replaced. Changing an earlier selection requires the explicit
    correction flag, and deferral must be deliberately replaced by an explicit
    selection rather than by a recorded-route reuse.
    """
    if type(selections) is not tuple or not selections or any(
        type(value) is not ScoreFormRecoveryRouteSelection for value in selections
    ):
        raise ScoreFormRecoveryWorkflowError("preflight", "At least one exact route selection is required.")
    ids = tuple(value.failure_id for value in selections)
    if len(ids) != len(set(ids)):
        raise ScoreFormRecoveryWorkflowError("preflight", "Duplicate recovery failure IDs are not allowed.")
    root = _root(workspace_root)
    try:
        prepared = tuple(_prepare_one(root, value) for value in selections)
        first = prepared[0]
        if any(
            item.retained_source != first.retained_source
            or item.issuance_id != first.issuance_id
            or item.class_id != first.class_id
            or item.assignment_id != first.assignment_id
            or item.student_id != first.student_id
            for item in prepared
        ):
            raise ValueError("All pages must share the same issuance, student, and retained source.")
        pages = tuple(item.source_page_number for item in prepared)
        if len(pages) != len(set(pages)):
            raise ValueError("One physical page cannot have multiple recovery selections.")
        items = _latest_items(root)
        needed: list[str] = []
        for selection, page in zip(selections, prepared, strict=True):
            item = items[page.failure_id]
            if _recorded_matches(item, page):
                continue
            last = item.latest_resolution_action
            if selection.use_recorded_route:
                raise ValueError("Recorded route is no longer the current teacher decision.")
            if last not in {None, "defer", *_ROUTE_ACTIONS}:
                raise ValueError("A different final teacher decision requires manual reconciliation.")
            if last in _ROUTE_ACTIONS and not selection.allow_route_correction:
                raise ValueError("Changing a historical teacher route requires explicit correction.")
            needed.append(page.failure_id)
        return ScoreFormRecoveryWorkflowPreview(
            selections, prepared, first.issuance_id, first.retained_source.source_scan_id,
            tuple(sorted(pages)), tuple(needed),
        )
    except Exception as error:
        raise ScoreFormRecoveryWorkflowError(
            "preflight", "A selected route or original scan is no longer eligible."
        ) from error


def execute_approved_scoreform_recovery_workflow(
    workspace_root: str | Path,
    approved: ScoreFormRecoveryWorkflowPreview,
    *,
    teacher_confirmed: bool,
    original_batch: Pds2ScanDispatchResult | None = None,
    registry: ModuleRegistry | None = None,
) -> ScoreFormRecoveryWorkflowOutcome:
    """Execute a current, explicitly teacher-confirmed recovery selection.

    Existing Core route decisions are reused without appending duplicates.
    Newly selected routes are written by the existing scan-review resolver,
    not by a fabricated completion event. If a later stage fails, route
    decisions (and possibly a saved score) remain durable; retry from preview.
    """
    if type(approved) is not ScoreFormRecoveryWorkflowPreview:
        raise ScoreFormRecoveryWorkflowError("preflight", "An exact read-only teacher preview is required.")
    if teacher_confirmed is not True:
        raise ScoreFormRecoveryWorkflowError("preflight", "Explicit teacher confirmation is required.")
    root = _root(workspace_root)
    current = preview_scoreform_recovery_workflow(root, approved.selections)
    if current != approved:
        raise ScoreFormRecoveryWorkflowError("preflight", "Teacher preview is stale; review route choices again.")
    ids = tuple(item.failure_id for item in approved.prepared_pages)
    recorded_now: list[str] = []
    selected_pages: list[PreparedScoreFormScanRecovery] = []
    for page in approved.prepared_pages:
        try:
            items = _latest_items(root)
            item = items[page.failure_id]
            if not _recorded_matches(item, page):
                if page.failure_id not in approved.route_decisions_needed:
                    raise ValueError("A previously recorded route changed during execution.")
                # A historically changed route is a correction even when the
                # physical page's QR originally yielded no route at all.
                change = page.route_correction_confirmed or item.latest_resolution_action in _ROUTE_ACTIONS
                action = "route_corrected" if change else "route_selected"
                resolve_scan_review_item(
                    root,
                    page.failure_id,
                    action,
                    route_payload=serialize_pds2_payload(page.route_locator),
                )
                recorded_now.append(page.failure_id)
            confirmed = prepare_scoreform_scan_recovery(
                root, page.failure_id, use_recorded_route=True
            )
            if (
                confirmed.route_locator != page.route_locator
                or confirmed.target != page.target
                or confirmed.issuance_id != page.issuance_id
                or confirmed.retained_source != page.retained_source
                or confirmed.source_page_number != page.source_page_number
            ):
                raise ValueError("The recorded teacher route does not match the approved page.")
            selected_pages.append(confirmed)
        except Exception as error:
            raise ScoreFormRecoveryWorkflowError(
                "route_decision",
                "Cannot verify or record the approved teacher route. Prior decisions may remain saved.",
                failure_id=page.failure_id,
            ) from error

    # A restart may already have both a valid route decision and saved result.
    # In that case, do not perform optical scoring or rewrite the result.
    try:
        completion = tuple(inspect_scoreform_recovery_completion(root, fid) for fid in ids)
    except Exception as error:
        raise ScoreFormRecoveryWorkflowError("completion", "Cannot inspect saved recovery state.") from error
    if all(item.verified for item in completion):
        if len({(item.issuance_id, item.attempt_number, item.output_path) for item in completion}) != 1:
            raise ScoreFormRecoveryWorkflowError("completion", "Recovered pages disagree about saved attempt.")
        return ScoreFormRecoveryWorkflowOutcome(
            "already_complete", "Registered teacher routes and saved attempt are already verified.",
            ids, tuple(recorded_now), completion=completion,
        )
    if any(item.status == "review_required" for item in completion):
        return ScoreFormRecoveryWorkflowOutcome(
            "review_required", "Existing recovery history requires teacher reconciliation.",
            ids, tuple(recorded_now), completion=completion,
        )
    if any(item.status == "route_selection_needed" for item in completion):
        raise ScoreFormRecoveryWorkflowError("route_decision", "A recorded route decision is still missing.")

    scored: list[DispatchedScoreFormScanRecovery] = []
    for prepared in selected_pages:
        try:
            scored.append(
                dispatch_prepared_scoreform_scan_recovery(
                    root, prepared, registry=registry
                )
            )
        except Exception as error:
            raise ScoreFormRecoveryWorkflowError(
                "dispatch", "Cannot dispatch an original retained page through Core.",
                failure_id=prepared.failure_id,
            ) from error
    try:
        assembly = prepare_scoreform_recovery_assembly(
            root, tuple(scored), original_batch=original_batch
        )
    except Exception as error:
        raise ScoreFormRecoveryWorkflowError("assembly", "Current scored pages cannot be assembled.") from error
    if assembly.status in {"needs_pages", "review_required"}:
        return ScoreFormRecoveryWorkflowOutcome(
            assembly.status,
            assembly.reason,
            ids,
            tuple(recorded_now),
            missing_logical_pages=assembly.missing_logical_pages,
            assembly=assembly,
        )

    try:
        persisted = persist_scoreform_recovery_attempt(
            root, assembly, tuple(scored), original_batch=original_batch
        )
    except Exception as error:
        raise ScoreFormRecoveryWorkflowError(
            "persistence", "The result was not conclusively persisted; inspect results before retrying."
        ) from error
    try:
        completion = confirm_scoreform_recovery_completion(
            root, persisted, tuple(scored), original_batch=original_batch
        )
    except Exception as error:
        raise ScoreFormRecoveryWorkflowError(
            "completion", "A saved score exists but completion proof failed.",
            persisted=persisted,
        ) from error
    if not all(item.verified for item in completion):
        return ScoreFormRecoveryWorkflowOutcome(
            "review_required", "Score saved; at least one failed page lacks final completion proof.",
            ids, tuple(recorded_now), assembly=assembly, persisted=persisted,
            completion=completion,
        )
    return ScoreFormRecoveryWorkflowOutcome(
        "verified_complete", "Teacher route decisions and complete result are durably verified.",
        ids, tuple(recorded_now), assembly=assembly, persisted=persisted,
        completion=completion,
    )


__all__ = [
    "ScoreFormRecoveryRouteSelection",
    "ScoreFormRecoveryWorkflowError",
    "ScoreFormRecoveryWorkflowOutcome",
    "ScoreFormRecoveryWorkflowPreview",
    "execute_approved_scoreform_recovery_workflow",
    "preview_scoreform_recovery_workflow",
]
