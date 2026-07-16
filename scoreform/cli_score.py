"""Scoring command orchestration for retained PDS2 and manual workflows."""

import os
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
)
from scoreform.results import export_scoreform_attempts, export_to_csv
from scoreform.scan_filing import (
    file_original_scan_after_success,
    print_scan_filing_result,
)
from scoreform.scan_filing_settings import get_scan_filing_mode
from scoreform.scoring import (
    ManualScoringSummary,
    process_file,
    process_file_qr_aware,
)


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
        output_file is None and batch.status == "full_success" and export is not None
        and not export.failures and dispatch.other_module_success_count == 0
        and dispatch.scoreform_page_score_count == dispatch.total_source_pages
        and len({
            (item.routed_result.class_id, item.routed_result.assignment_id)
            for item in assembly.completed_attempts
        }) == 1
        and bool(export.appended_attempts or export.already_present_attempts)
    )


def _run_routed_scoring(input_file, *, workspace_root: Path, output_file=None):
    dispatch = process_file_qr_aware(input_file, workspace_root=workspace_root)
    if not isinstance(dispatch, Pds2ScanDispatchResult):
        print("Error: PDS2 scan processing returned an invalid batch result.")
        return 1
    print(format_pds2_dispatch_summary(dispatch))
    assembly = assemble_scoreform_attempts(dispatch, workspace_root=workspace_root)
    export = None
    if assembly.completed_attempts:
        export = export_scoreform_attempts(
            assembly, workspace_root=workspace_root,
            explicit_output_file=Path(output_file) if output_file is not None else None,
        )
    batch = ScoreFormRoutedScoringBatch(dispatch, assembly, export)
    print(format_routed_scoring_summary(batch))

    if _eligible_for_scan_filing(batch, output_file):
        result = file_original_scan_after_success(
            [item.routed_result for item in assembly.completed_attempts], input_file,
            mode=get_scan_filing_mode(workspace_root), workspace_root=workspace_root,
        )
        print_scan_filing_result(result)
    return batch.exit_code()


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
    print("Using legacy/manual scoring mode...")
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
