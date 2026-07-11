"""Scoring command orchestration for the ScoreForm CLI."""

import os

from scoreform import workspace
from scoreform.assignment import load_answer_key
from scoreform.config import LOCAL_RESULTS_CSV
from scoreform.results import export_routed_results, export_to_csv
from scoreform.scan_filing import (
    file_original_scan_after_success,
    file_original_scan_copy,
    print_scan_filing_result,
    skipped_scan_filing_for_batch_outcome,
)
from scoreform.scan_filing_settings import inspect_scan_filing_settings
from scoreform.scan_review_resolution import preserve_qr_batch_failures_for_review
from scoreform.scoring import (
    ManualScoringSummary,
    get_qr_batch_summary,
    print_qr_batch_summary,
    process_file,
    process_file_qr_aware,
    save_qr_batch_summary,
    update_qr_batch_result_write_status,
)


def _get_manual_scoring_summary(results_data):
    summary = getattr(results_data, "summary", None)
    if isinstance(summary, ManualScoringSummary):
        return summary

    scored = len(results_data) if results_data else 0
    return ManualScoringSummary(
        pages_processed=scored,
        pages_scored=scored,
    )


def _print_manual_scoring_summary(summary):
    print(summary.format())


def _preserve_review_failures(results_data, input_file, workspace_root):
    paths = preserve_qr_batch_failures_for_review(
        results_data,
        input_file,
        workspace_root,
    )
    if paths:
        print(f"Preserved {len(paths)} scan review item(s) under scans/review/.")


def run_score(args):
    if len(args) < 1:
        print("Usage:")
        print("  scoreform score <input_file>")
        print("      QR-aware scoring with routed results.")
        print("  scoreform score <input_file> <output_csv>")
        print("      QR-aware scoring with explicit output CSV.")
        print("  scoreform score <input_file> <answer_key_json>")
        print("      Legacy/manual scoring with default output:")
        print("      <PDS workspace root>/local_outputs/results/results.csv")
        print("  scoreform score <input_file> <output_csv> <answer_key_json>")
        print("      Legacy/manual scoring with explicit output CSV.")
        return 1

    workspace_root = workspace.get_scoreform_workspace_root()
    default_results_csv = os.fspath(workspace_root / LOCAL_RESULTS_CSV)
    input_file = args[0]
    use_qr_aware = False
    output_file = default_results_csv
    answer_key_file = "answer_key.json"
    explicit_output_csv = False

    if len(args) == 1:
        use_qr_aware = True
    elif len(args) == 2:
        arg2 = args[1]
        if arg2.lower().endswith(".json"):
            answer_key_file = arg2
            use_qr_aware = False
        else:
            output_file = arg2
            explicit_output_csv = True
            use_qr_aware = True
    else:
        output_file = args[1]
        answer_key_file = args[2]
        use_qr_aware = False

    if use_qr_aware:
        print("Using QR-aware scoring mode...")
        results_data = process_file_qr_aware(
            input_file,
            workspace_root=workspace_root,
        )
    else:
        print("Using legacy/manual scoring mode...")
        key = load_answer_key(answer_key_file)
        if key is None:
            return 1
        results_data = process_file(input_file, key)

    if not results_data:
        if use_qr_aware:
            summary = get_qr_batch_summary(results_data)
            _preserve_review_failures(results_data, input_file, workspace_root)
            print_qr_batch_summary(summary)
            save_qr_batch_summary(
                summary,
                input_file,
                workspace_root=workspace_root,
            )
            return summary.exit_code() if summary is not None else 1
        _print_manual_scoring_summary(_get_manual_scoring_summary(results_data))
        return 1

    if use_qr_aware and not explicit_output_csv:
        export_success = export_routed_results(
            results_data,
            workspace_root=workspace_root,
        )
    else:
        export_success = export_to_csv(
            results_data,
            output_file,
            workspace_root=workspace_root,
        )

    if not export_success:
        if use_qr_aware:
            update_qr_batch_result_write_status(
                results_data,
                export_success,
                output_file if explicit_output_csv else None,
                workspace_root=workspace_root,
            )
            summary = get_qr_batch_summary(results_data)
            _preserve_review_failures(results_data, input_file, workspace_root)
            print_qr_batch_summary(summary)
            save_qr_batch_summary(
                summary,
                input_file,
                workspace_root=workspace_root,
            )
            return summary.exit_code() if summary is not None else 1
        print("Error: Failed to export results.")
        _print_manual_scoring_summary(_get_manual_scoring_summary(results_data))
        return 1

    if use_qr_aware:
        update_qr_batch_result_write_status(
            results_data,
            export_success,
            output_file if explicit_output_csv else None,
            workspace_root=workspace_root,
        )
        summary = get_qr_batch_summary(results_data)
        _preserve_review_failures(results_data, input_file, workspace_root)
        if not explicit_output_csv:
            if summary is not None and summary.outcome() == "full_success":
                filing_settings = inspect_scan_filing_settings(workspace_root)
                if filing_settings.warning:
                    print(f"Warning: {filing_settings.warning}")
                    print("Effective scan filing mode: copy")
                if filing_settings.effective_mode == "copy":
                    filing_result = file_original_scan_copy(
                        results_data,
                        input_file,
                        workspace_root=workspace_root,
                    )
                else:
                    filing_result = file_original_scan_after_success(
                        results_data,
                        input_file,
                        mode=filing_settings.effective_mode,
                        workspace_root=workspace_root,
                    )
            else:
                outcome = summary.outcome() if summary is not None else None
                filing_result = skipped_scan_filing_for_batch_outcome(outcome)
            print_scan_filing_result(filing_result)
        print_qr_batch_summary(summary)
        save_qr_batch_summary(
            summary,
            input_file,
            workspace_root=workspace_root,
        )
        return summary.exit_code() if summary is not None else 0

    manual_summary = _get_manual_scoring_summary(results_data)
    if manual_summary.failures or manual_summary.pages_processed > 1:
        _print_manual_scoring_summary(manual_summary)

    return 0
