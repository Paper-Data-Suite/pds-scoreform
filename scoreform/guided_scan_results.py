"""Teacher-facing post-scan projections for the guided ScoreForm workflow."""

from __future__ import annotations

import ntpath
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pds_core.identifiers import validate_identifier

from scoreform.cli_score import RoutedScoringOperationResult
from scoreform.results import ScoreFormAttemptExportBatch

GuidedScanOutcome = Literal[
    "complete",
    "partial",
    "needs_review",
    "no_scoreform_result",
    "failed_safely",
]


def safe_scan_source_filename(source_file: str | Path) -> str:
    """Return a basename only, independent of the host path convention."""

    raw = str(source_file).strip().rstrip("/\\")
    return ntpath.basename(raw) or "scan"


@dataclass(frozen=True, slots=True)
class GuidedScanResultTarget:
    """One exact durable ScoreForm assignment target, without student payload."""

    class_id: str
    assignment_id: str
    appended_attempts: int = 0
    already_present_attempts: int = 0

    def __post_init__(self) -> None:
        validate_identifier(self.class_id, "class_id")
        validate_identifier(self.assignment_id, "assignment_id")
        for name in ("appended_attempts", "already_present_attempts"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a nonnegative integer.")
        if self.durable_attempts < 1:
            raise ValueError("A guided result target requires a durable attempt.")

    @property
    def durable_attempts(self) -> int:
        return self.appended_attempts + self.already_present_attempts


@dataclass(frozen=True, slots=True)
class GuidedScanSummary:
    """Privacy-minimized teacher projection of one structured scoring operation."""

    source_filename: str
    retention_succeeded: bool
    source_scan_id: str | None
    source_pages_processed: int
    completed_attempts: int
    attempts_appended: int
    attempts_already_present: int
    export_failures: int
    review_items_persisted: int
    review_persistence_failures: int
    foreign_success_pages: int
    targets: tuple[GuidedScanResultTarget, ...]
    scoring_status: str
    outcome: GuidedScanOutcome

    def __post_init__(self) -> None:
        if (
            not isinstance(self.source_filename, str)
            or not self.source_filename
            or ntpath.basename(self.source_filename) != self.source_filename
            or "/" in self.source_filename
            or "\\" in self.source_filename
        ):
            raise ValueError("source_filename must be a filename only.")
        if not isinstance(self.retention_succeeded, bool):
            raise TypeError("retention_succeeded must be Boolean.")
        if self.retention_succeeded:
            if not isinstance(self.source_scan_id, str) or not self.source_scan_id:
                raise ValueError("Successful retention requires source_scan_id.")
            validate_identifier(self.source_scan_id, "source_scan_id")
        elif self.source_scan_id is not None:
            raise ValueError("Failed retention cannot carry source_scan_id.")
        for name in (
            "source_pages_processed",
            "completed_attempts",
            "attempts_appended",
            "attempts_already_present",
            "export_failures",
            "review_items_persisted",
            "review_persistence_failures",
            "foreign_success_pages",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a nonnegative integer.")
        if not isinstance(self.targets, tuple) or any(
            not isinstance(target, GuidedScanResultTarget) for target in self.targets
        ):
            raise TypeError("targets must be an immutable guided-target tuple.")
        identities = tuple(
            (target.class_id, target.assignment_id) for target in self.targets
        )
        if identities != tuple(sorted(set(identities), key=_target_sort_key)):
            raise ValueError("targets must be unique and deterministically ordered.")
        if sum(target.appended_attempts for target in self.targets) != (
            self.attempts_appended
        ):
            raise ValueError("Target appended counts must match summary.")
        if sum(target.already_present_attempts for target in self.targets) != (
            self.attempts_already_present
        ):
            raise ValueError("Target already-present counts must match summary.")
        if not isinstance(self.scoring_status, str) or not self.scoring_status:
            raise ValueError("scoring_status must be nonempty.")
        if self.outcome not in {
            "complete",
            "partial",
            "needs_review",
            "no_scoreform_result",
            "failed_safely",
        }:
            raise ValueError("outcome is unsupported.")

    @property
    def durable_attempts(self) -> int:
        return self.attempts_appended + self.attempts_already_present


def _target_sort_key(identity: tuple[str, str]) -> tuple[str, str, str, str]:
    class_id, assignment_id = identity
    return (
        class_id.casefold(),
        class_id,
        assignment_id.casefold(),
        assignment_id,
    )


def derive_durable_result_targets(
    export_result: ScoreFormAttemptExportBatch | None,
) -> tuple[GuidedScanResultTarget, ...]:
    """Project only confirmed export outcomes into exact assignment targets."""

    if export_result is None:
        return ()

    grouped: dict[tuple[str, str], list[int]] = {}
    for item in export_result.appended_attempts:
        result = item.result
        key = (result.class_id, result.assignment_id)
        counts = grouped.setdefault(key, [0, 0])
        counts[0] += 1
    for item in export_result.already_present_attempts:
        result = item.result
        key = (result.class_id, result.assignment_id)
        counts = grouped.setdefault(key, [0, 0])
        counts[1] += 1

    return tuple(
        GuidedScanResultTarget(
            class_id=class_id,
            assignment_id=assignment_id,
            appended_attempts=grouped[(class_id, assignment_id)][0],
            already_present_attempts=grouped[(class_id, assignment_id)][1],
        )
        for class_id, assignment_id in sorted(grouped, key=_target_sort_key)
    )


def _guided_outcome(
    *,
    scoring_status: str,
    durable_attempts: int,
    review_items_persisted: int,
    review_persistence_failures: int,
    export_failures: int,
    foreign_success_pages: int,
) -> GuidedScanOutcome:
    if durable_attempts:
        if (
            scoring_status == "full_success"
            and review_items_persisted == 0
            and review_persistence_failures == 0
            and export_failures == 0
        ):
            return "complete"
        return "partial"

    if review_items_persisted:
        return "needs_review"

    if (
        scoring_status == "dispatch_only_success"
        or foreign_success_pages > 0
    ) and review_persistence_failures == 0:
        return "no_scoreform_result"

    return "failed_safely"


def build_guided_scan_summary(
    operation: RoutedScoringOperationResult,
    source_file: str | Path,
) -> GuidedScanSummary:
    """Build a bounded teacher projection without re-running scoring or discovery."""

    source_filename = safe_scan_source_filename(source_file)
    if operation.operation_error is not None:
        return GuidedScanSummary(
            source_filename=source_filename,
            retention_succeeded=False,
            source_scan_id=None,
            source_pages_processed=0,
            completed_attempts=0,
            attempts_appended=0,
            attempts_already_present=0,
            export_failures=0,
            review_items_persisted=0,
            review_persistence_failures=0,
            foreign_success_pages=0,
            targets=(),
            scoring_status="operation_failure",
            outcome="failed_safely",
        )

    assert operation.batch is not None
    assert operation.review is not None
    batch = operation.batch
    dispatch = batch.dispatch_result
    assembly = batch.assembly_result
    export_result = batch.export_result
    retained = dispatch.retained_source

    targets = derive_durable_result_targets(export_result)
    appended = 0 if export_result is None else len(export_result.appended_attempts)
    already = (
        0 if export_result is None else len(export_result.already_present_attempts)
    )
    export_failures = 0 if export_result is None else len(export_result.failures)
    review_persisted = len(operation.review.persisted)
    review_failures = len(operation.review.failures)
    foreign_success = dispatch.other_module_success_count
    scoring_status = batch.status

    return GuidedScanSummary(
        source_filename=(
            source_filename if retained is None else retained.source_filename
        ),
        retention_succeeded=retained is not None,
        source_scan_id=None if retained is None else retained.source_scan_id,
        source_pages_processed=dispatch.total_source_pages,
        completed_attempts=len(assembly.completed_attempts),
        attempts_appended=appended,
        attempts_already_present=already,
        export_failures=export_failures,
        review_items_persisted=review_persisted,
        review_persistence_failures=review_failures,
        foreign_success_pages=foreign_success,
        targets=targets,
        scoring_status=scoring_status,
        outcome=_guided_outcome(
            scoring_status=scoring_status,
            durable_attempts=appended + already,
            review_items_persisted=review_persisted,
            review_persistence_failures=review_failures,
            export_failures=export_failures,
            foreign_success_pages=foreign_success,
        ),
    )


def format_guided_scan_summary(summary: GuidedScanSummary) -> str:
    """Render a compact teacher summary without student, route, or path detail."""

    outcome_labels = {
        "complete": "Complete",
        "partial": "Partial — results recorded and/or follow-up is needed",
        "needs_review": "Needs review",
        "no_scoreform_result": "No ScoreForm result",
        "failed_safely": "Failed safely",
    }
    lines = [
        "Scan processing summary",
        f"Source: {summary.source_filename}",
        f"Outcome: {outcome_labels[summary.outcome]}",
        f"Retained by Core: {'yes' if summary.retention_succeeded else 'no'}",
        f"Source pages processed: {summary.source_pages_processed}",
        f"Complete ScoreForm attempts: {summary.completed_attempts}",
        f"Attempts recorded: {summary.attempts_appended}",
        f"Attempts already recorded: {summary.attempts_already_present}",
        f"Review items queued: {summary.review_items_persisted}",
    ]
    if summary.review_persistence_failures:
        lines.append(
            "Review persistence failures: "
            f"{summary.review_persistence_failures}"
        )
    if summary.export_failures:
        lines.append(f"Result export failures: {summary.export_failures}")
    if summary.foreign_success_pages:
        lines.append(
            f"Other installed modules handled: {summary.foreign_success_pages} page(s)"
        )
    if summary.targets:
        lines.append("ScoreForm result targets:")
        for target in summary.targets:
            lines.append(
                f"- {target.class_id} / {target.assignment_id} "
                f"({target.appended_attempts} new, "
                f"{target.already_present_attempts} already recorded)"
            )
    return "\n".join(lines)
