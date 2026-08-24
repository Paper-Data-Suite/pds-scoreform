"""Scoring command orchestration for retained PDS2 and manual workflows."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from scoreform import workspace
from scoreform.assignment import load_answer_key
from scoreform.attempt_assembly import (
    ScoreFormRoutedScoringBatch,
    assemble_scoreform_attempts,
    format_routed_scoring_summary,
)
from scoreform.config import LOCAL_RESULTS_CSV
from scoreform.pds2_scan_dispatch import (
    Pds2ScanDispatchResult,
    format_pds2_dispatch_summary,
    process_pds2_scan,
)
from scoreform.results import export_scoreform_attempts, export_to_csv
from scoreform.scan_filing import (
    ScanFilingResult,
    file_original_scan_after_success,
    print_scan_filing_result,
)
from scoreform.scan_filing_settings import get_scan_filing_mode
from scoreform.scan_review_models import ScoreFormFailurePersistenceBatch
from scoreform.scan_review_persistence import (
    format_failure_persistence_summary,
    persist_routed_scoring_failures,
)
from scoreform.scoring import (
    ManualScoringSummary,
    process_file,
)


@dataclass(frozen=True, slots=True)
class RoutedScoringOperationResult:
    """Structured result of one exact retained PDS2 scoring operation."""

    batch: ScoreFormRoutedScoringBatch | None
    review: ScoreFormFailurePersistenceBatch | None
    scan_filing: ScanFilingResult | None = None
    operation_error: str | None = None

    def __post_init__(self) -> None:
        if self.operation_error is not None:
            if not isinstance(self.operation_error, str) or not self.operation_error.strip():
                raise ValueError("operation_error must be a nonempty string or null.")
            if self.batch is not None or self.review is not None or self.scan_filing is not None:
                raise ValueError(
                    "A terminal routed-scoring operation error cannot carry partial models."
                )
            return

        if not isinstance(self.batch, ScoreFormRoutedScoringBatch):
            raise TypeError("A successful orchestration result requires a routed scoring batch.")
        if not isinstance(self.review, ScoreFormFailurePersistenceBatch):
            raise TypeError(
                "A successful orchestration result requires a failure-persistence batch."
            )
        if self.scan_filing is not None and not isinstance(
            self.scan_filing, ScanFilingResult
        ):
            raise TypeError("scan_filing must be a ScanFilingResult or null.")

    @property
    def exit_code(self) -> int:
        """Return the historical direct-CLI exit status for this operation."""

        if self.operation_error is not None:
            return 1
        assert self.batch is not None
        assert self.review is not None
        return 1 if self.review.failures else self.batch.exit_code()


def _get_manual_scoring_summary(results_data):
    summary = getattr(results_data, "summary", None)
    if isinstance(summary, ManualScoringSummary):
        return summary
    scored = len(results_data) if results_data else 0
    return ManualScoringSummary(pages_processed=scored, pages_scored=scored)


def _print_manual_scoring_summary(summary):
    print(summary.format())


def _eligible_for_scan_filing(batch: ScoreFormRoutedScoringBatch, output_file) -> bool:
    dispatch = batch.dispatch_result
    assembly = batch.assembly_result
    export = batch.export_result
    return (
        output_file is None
        and batch.status == "full_success"
        and export is not None
        and not export.failures
        and dispatch.other_module_success_count == 0
        and dispatch.scoreform_page_score_count == dispatch.total_source_pages
        and len(
            {
                (item.routed_result.class_id, item.routed_result.assignment_id)
                for item in assembly.completed_attempts
            }
        )
        == 1
        and bool(export.appended_attempts or export.already_present_attempts)
    )


def execute_routed_scoring_operation(
    input_file: str | Path,
    *,
    workspace_root: Path,
    output_file: str | Path | None = None,
) -> RoutedScoringOperationResult:
    """Execute retain/dispatch/assemble/export/review/file exactly once.

    This is the structured application boundary shared by the direct CLI and the
    guided teacher workflow. It deliberately performs no rendering.
    """

    dispatch = process_pds2_scan(input_file, workspace_root=workspace_root)
    if not isinstance(dispatch, Pds2ScanDispatchResult):
        return RoutedScoringOperationResult(
            batch=None,
            review=None,
            operation_error="PDS2 scan processing returned an invalid batch result.",
        )

    assembly = assemble_scoreform_attempts(dispatch, workspace_root=workspace_root)
    export = None
    if assembly.completed_attempts:
        export = export_scoreform_attempts(
            assembly,
            workspace_root=workspace_root,
            explicit_output_file=(
                Path(output_file) if output_file is not None else None
            ),
        )

    batch = ScoreFormRoutedScoringBatch(dispatch, assembly, export)
    review = persist_routed_scoring_failures(batch, input_file, workspace_root)

    scan_filing = None
    if _eligible_for_scan_filing(batch, output_file):
        scan_filing = file_original_scan_after_success(
            [item.routed_result for item in assembly.completed_attempts],
            input_file,
            mode=get_scan_filing_mode(workspace_root),
            workspace_root=workspace_root,
        )

    return RoutedScoringOperationResult(
        batch=batch,
        review=review,
        scan_filing=scan_filing,
    )


def _print_routed_scoring_operation(result: RoutedScoringOperationResult) -> None:
    """Render the historical technical CLI summaries from a structured result."""

    if result.operation_error is not None:
        print(f"Error: {result.operation_error}")
        return

    assert result.batch is not None
    assert result.review is not None
    print(format_pds2_dispatch_summary(result.batch.dispatch_result))
    print(format_routed_scoring_summary(result.batch))
    if result.review.persisted or result.review.failures:
        print(format_failure_persistence_summary(result.review))
    if result.scan_filing is not None:
        print_scan_filing_result(result.scan_filing)


def _run_routed_scoring(input_file, *, workspace_root: Path, output_file=None):
    result = execute_routed_scoring_operation(
        input_file,
        workspace_root=workspace_root,
        output_file=output_file,
    )
    _print_routed_scoring_operation(result)
    return result.exit_code


def run_score(args):
    """Dispatch retained PDS2 pages or run the distinct manual answer-key path."""
    if len(args) < 1:
        print("Usage:")
        print("  scoreform score <input_file>")
        print("      Retain, dispatch, assemble, and route complete PDS2 attempts.")
        print("  scoreform score <input_file> <output_csv>")
        print("      Write assembled PDS2 attempts to an explicit schema-v2 CSV.")
        print("  scoreform score <input_file> <answer_key_json>")
        print("      Manual scoring with default output:")
        print("      <PDS workspace root>/local_outputs/results/results.csv")
        print("  scoreform score <input_file> <output_csv> <answer_key_json>")
        print("      Manual scoring with an explicit output CSV.")
        return 1
    if len(args) > 3:
        print("Error: Too many arguments for scoreform score.")
        return 1

    input_file = args[0]
    if len(args) == 1:
        workspace_root = workspace.get_scoreform_workspace_root()
        print("Using retained PDS2 Core dispatch mode...")
        return _run_routed_scoring(input_file, workspace_root=workspace_root)

    if len(args) == 2 and not args[1].lower().endswith(".json"):
        workspace_root = workspace.get_scoreform_workspace_root()
        print("Using retained PDS2 Core dispatch mode with explicit output...")
        return _run_routed_scoring(
            input_file, workspace_root=workspace_root, output_file=args[1]
        )

    output_file = None
    answer_key_file = "answer_key.json"
    if len(args) == 2:
        answer_key_file = args[1]
    else:
        output_file = args[1]
        answer_key_file = args[2]

    workspace_root = workspace.get_scoreform_workspace_root()
    if output_file is None:
        output_file = os.fspath(workspace_root / LOCAL_RESULTS_CSV)
    print("Using explicit answer-key manual scoring mode...")
    key = load_answer_key(answer_key_file)
    if key is None:
        return 1
    results_data = process_file(input_file, key)
    if not results_data:
        _print_manual_scoring_summary(_get_manual_scoring_summary(results_data))
        return 1
    if not export_to_csv(results_data, output_file, workspace_root=workspace_root):
        print("Error: Failed to export results.")
        _print_manual_scoring_summary(_get_manual_scoring_summary(results_data))
        return 1
    manual_summary = _get_manual_scoring_summary(results_data)
    if manual_summary.failures or manual_summary.pages_processed > 1:
        _print_manual_scoring_summary(manual_summary)
    return 0
