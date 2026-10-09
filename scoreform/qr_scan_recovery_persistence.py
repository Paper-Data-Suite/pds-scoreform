"""Issue #225 Slice 10: guarded durable storage of one complete recovery result.

This is *not* scan-review completion. The caller supplies a teacher-confirmed
Slice 9 plan plus its original dispatched evidence; the plan alone can never
write a result. Existing ScoreForm schema-v2 history remains authoritative.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from scoreform.attempt_assembly import ScoreFormAssembledAttempt
from scoreform.pds2_scan_dispatch import Pds2ScanDispatchResult
from scoreform.qr_scan_recovery_assembly import (
    ScoreFormRecoveryAssemblyPlan,
    prepare_scoreform_recovery_assembly,
)
from scoreform.qr_scan_recovery_dispatch import DispatchedScoreFormScanRecovery
from scoreform.results import (
    ScoreFormAttemptExportBatch,
    ScoreFormRoutedResultHistoryRow,
    export_scoreform_result_models,
    load_routed_results_history,
    pds2_results_semantically_equivalent,
)
from scoreform.work_paths import scoreform_work_paths


class ScoreFormRecoveryPersistenceError(RuntimeError):
    """Write was refused, or verification failed; no completion is inferred."""


class ScoreFormRecoveryPersistenceUncertainError(ScoreFormRecoveryPersistenceError):
    """The v2 writer was invoked: check its durable result before retrying.

    A writer exception, partial reported failure, or failed post-write proof
    cannot establish whether a result row was committed. The best-effort
    inspection status is advisory, not permission to retry without rechecking.
    """

    def __init__(
        self,
        message: str,
        *,
        output_path: Path,
        row_verified: bool | None,
        attempt_number: int | None,
    ) -> None:
        super().__init__(message)
        self.output_path = output_path
        self.row_verified = row_verified
        self.attempt_number = attempt_number


@dataclass(frozen=True, slots=True)
class PersistedScoreFormRecovery:
    """Verified schema-v2 student result; NOT a resolved scan-review failure."""

    status: Literal["appended", "already_present"]
    output_path: Path
    attempt_number: int
    assembled_attempt: ScoreFormAssembledAttempt
    recovered_failure_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.status not in {"appended", "already_present"}:
            raise ValueError("Unsupported recovery persistence status.")
        if not isinstance(self.output_path, Path):
            raise TypeError("output_path must be a Path.")
        if type(self.attempt_number) is not int or self.attempt_number < 1:
            raise ValueError("attempt_number must be positive.")
        if type(self.assembled_attempt) is not ScoreFormAssembledAttempt:
            raise TypeError("Recovery requires an exact assembled attempt.")
        if (
            not isinstance(self.recovered_failure_ids, tuple)
            or not self.recovered_failure_ids
            or len(set(self.recovered_failure_ids)) != len(self.recovered_failure_ids)
        ):
            raise ValueError("Recovered failure IDs must be unique.")


def _verified_row(
    path: Path, attempt: ScoreFormAssembledAttempt
) -> ScoreFormRoutedResultHistoryRow | None:
    """Find exactly one semantically matching recorded result; reject conflicts.

    A matching result must not coexist with another recorded result for the
    same issuance, regardless of scan identity. Existing manual result rows
    for the same student must not be silently displaced.
    """
    expected = attempt.routed_result
    rows = load_routed_results_history(path)
    matches: list[ScoreFormRoutedResultHistoryRow] = []
    for row in rows:
        stored = row.result
        if stored.result_origin == "pds2_scan" and stored.issuance_id == expected.issuance_id:
            if not pds2_results_semantically_equivalent(stored, expected):
                raise ScoreFormRecoveryPersistenceError(
                    "A different result is already recorded for this issuance."
                )
            matches.append(row)
        elif (
            stored.class_id, stored.assignment_id, stored.student_id
        ) == (
            expected.class_id, expected.assignment_id, expected.student_id
        ) and stored.result_origin in {"plain_paper_manual", "scan_review_manual"}:
            raise ScoreFormRecoveryPersistenceError(
                "Existing manual student result requires teacher reconciliation."
            )
    if len(matches) > 1:
        raise ScoreFormRecoveryPersistenceError(
            "Multiple results already refer to this issuance; teacher review required."
        )
    return matches[0] if matches else None


def _inspect_after_write(
    path: Path, attempt: ScoreFormAssembledAttempt
) -> tuple[bool | None, int | None]:
    """Best-effort evidence for ambiguous writer/verification failures."""
    try:
        row = _verified_row(path, attempt)
    except Exception:
        return None, None
    return (row is not None, row.attempt_number if row is not None else None)


def _refresh(
    root: Path,
    recovered_pages: tuple[DispatchedScoreFormScanRecovery, ...],
    original_batch: Pds2ScanDispatchResult | None,
) -> ScoreFormRecoveryAssemblyPlan:
    try:
        return prepare_scoreform_recovery_assembly(
            root, recovered_pages, original_batch=original_batch
        )
    except Exception as error:
        raise ScoreFormRecoveryPersistenceError(
            "Recovery evidence no longer passes authoritative assembly; re-preview."
        ) from error


def _plan_compatible(
    approved: ScoreFormRecoveryAssemblyPlan,
    fresh: ScoreFormRecoveryAssemblyPlan,
) -> bool:
    """Allow only the idempotent ready-to-persist -> already-persisted step."""
    if approved == fresh:
        return True
    return (
        approved.status == "ready_to_persist"
        and fresh.status == "already_persisted"
        and approved.assembled_attempt == fresh.assembled_attempt
        and approved.issuance_id == fresh.issuance_id
        and approved.source_scan_id == fresh.source_scan_id
        and approved.source_page_numbers == fresh.source_page_numbers
        and approved.missing_logical_pages == fresh.missing_logical_pages
    )


def _require_expected_plan(value: object) -> ScoreFormRecoveryAssemblyPlan:
    if type(value) is not ScoreFormRecoveryAssemblyPlan:
        raise ScoreFormRecoveryPersistenceError(
            "An exact teacher-reviewed Slice 9 assembly plan is required."
        )
    if value.status not in {"ready_to_persist", "already_persisted"}:
        raise ScoreFormRecoveryPersistenceError(
            "Incomplete or conflicting recovery cannot write a student result."
        )
    if type(value.assembled_attempt) is not ScoreFormAssembledAttempt:
        raise ScoreFormRecoveryPersistenceError(
            "Recovery plan lacks a complete authoritative student attempt."
        )
    return value


def persist_scoreform_recovery_attempt(
    workspace_root: str | Path,
    approved_plan: ScoreFormRecoveryAssemblyPlan,
    recovered_pages: tuple[DispatchedScoreFormScanRecovery, ...],
    *,
    original_batch: Pds2ScanDispatchResult | None = None,
) -> PersistedScoreFormRecovery:
    """Write one confirmed complete result via ScoreForm's existing v2 writer.

    The original evidence and results history are re-evaluated before writing.
    A previously saved equivalent result is reused without calling the writer.
    A writer failure is never treated as confirmation that no row was saved.
    No Core resolution or scan-review decision is appended by this operation.
    """
    approved = _require_expected_plan(approved_plan)
    if not isinstance(recovered_pages, tuple) or not recovered_pages:
        raise ScoreFormRecoveryPersistenceError("Original recovered page evidence is required.")
    try:
        root = Path(workspace_root).resolve(strict=True)
        if not root.is_dir():
            raise ValueError("Workspace root is not a directory.")
    except (OSError, ValueError, TypeError, RuntimeError) as error:
        raise ScoreFormRecoveryPersistenceError("Invalid recovery workspace.") from error

    fresh = _refresh(root, recovered_pages, original_batch)
    if not _plan_compatible(approved, fresh):
        raise ScoreFormRecoveryPersistenceError(
            "Recovery plan changed since teacher review; prepare and confirm again."
        )
    attempt = fresh.assembled_attempt
    if attempt is None or fresh.status not in {"ready_to_persist", "already_persisted"}:
        raise ScoreFormRecoveryPersistenceError(
            "Refreshed recovery does not contain a complete student attempt."
        )
    result = attempt.routed_result
    output_path = scoreform_work_paths(root, result.class_id, result.assignment_id).results_path
    failures = tuple(item.prepared.failure_id for item in recovered_pages)
    if len(failures) != len(set(failures)):
        raise ScoreFormRecoveryPersistenceError("Repeated recovered failure identity.")
    try:
        prior = _verified_row(output_path, attempt)
    except Exception as error:
        raise ScoreFormRecoveryPersistenceError(
            "Existing result history could not be verified; no write attempted."
        ) from error
    if fresh.status == "already_persisted":
        if prior is None or fresh.prior_attempt_number != prior.attempt_number:
            raise ScoreFormRecoveryPersistenceError(
                "Previously reported result does not match authoritative history."
            )
        return PersistedScoreFormRecovery(
            "already_present", output_path, prior.attempt_number, attempt, failures
        )
    if prior is not None:
        raise ScoreFormRecoveryPersistenceError(
            "A stored attempt appeared without a matching refreshed history plan."
        )

    # Do not manufacture an assembly batch or manipulate a CSV row. The writer
    # owns schema-v2 idempotency, validation, staging, and replacement.
    try:
        exported = export_scoreform_result_models((result,), workspace_root=root)
        if type(exported) is not ScoreFormAttemptExportBatch:
            raise ScoreFormRecoveryPersistenceError("The v2 writer returned the wrong result model.")
        if exported.failures:
            raise ScoreFormRecoveryPersistenceError(
                "The v2 writer did not complete cleanly; inspect the result before retrying."
            )
        confirmations = (*exported.appended_attempts, *exported.already_present_attempts)
        if len(confirmations) != 1:
            raise ScoreFormRecoveryPersistenceError(
                "The v2 writer did not confirm exactly one attempt."
            )
        confirmed = confirmations[0]
        if (
            confirmed.output_path != output_path
            or not pds2_results_semantically_equivalent(confirmed.result, result)
        ):
            raise ScoreFormRecoveryPersistenceError(
                "Writer-confirmed attempt is inconsistent with recovery."
            )
        written_status: Literal["appended", "already_present"] = (
            "appended" if exported.appended_attempts else "already_present"
        )
    except Exception as error:
        exists, attempt_number = _inspect_after_write(output_path, attempt)
        raise ScoreFormRecoveryPersistenceUncertainError(
            "Result export failed or has an unverified outcome. Reopen recovery "
            "and inspect managed history before retrying; do not mark review complete.",
            output_path=output_path, row_verified=exists, attempt_number=attempt_number,
        ) from error

    try:
        recorded = _verified_row(output_path, attempt)
        if recorded is None or recorded.attempt_number != confirmed.attempt_number:
            raise ScoreFormRecoveryPersistenceError(
                "The persisted result row does not match the writer confirmation."
            )
        after = _refresh(root, recovered_pages, original_batch)
        if (
            after.status != "already_persisted"
            or after.assembled_attempt != attempt
            or after.prior_attempt_number != recorded.attempt_number
        ):
            raise ScoreFormRecoveryPersistenceError(
                "Post-write recovery revalidation could not confirm the complete attempt."
            )
    except Exception as error:
        exists, attempt_number = _inspect_after_write(output_path, attempt)
        raise ScoreFormRecoveryPersistenceUncertainError(
            "The writer returned success but post-write verification failed. "
            "Inspect managed results and retry only after fresh recovery review.",
            output_path=output_path, row_verified=exists, attempt_number=attempt_number,
        ) from error

    return PersistedScoreFormRecovery(
        written_status, output_path, recorded.attempt_number, attempt, failures
    )


__all__ = [
    "PersistedScoreFormRecovery",
    "ScoreFormRecoveryPersistenceError",
    "ScoreFormRecoveryPersistenceUncertainError",
    "persist_scoreform_recovery_attempt",
]
