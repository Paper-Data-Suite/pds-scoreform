"""Issue #225 Slice 13: guarded direct teacher recovery interface.

No default mutation. Explicit --apply plus a literal confirmation is required.
The original Source/Core routes, results, and decisions remain authoritative.
"""

from __future__ import annotations

import argparse

from pds_core.pds2 import parse_pds2_payload, serialize_pds2_payload

from scoreform import workspace
from scoreform.qr_scan_recovery_workflow import (
    ScoreFormRecoveryRouteSelection,
    ScoreFormRecoveryWorkflowError,
    execute_approved_scoreform_recovery_workflow,
    preview_scoreform_recovery_workflow,
)


class ScoreFormRecoveryInterfaceError(ValueError):
    """A teacher-facing request cannot be parsed as explicit route intent."""


def parse_recovery_page_spec(
    value: str, *, allow_route_correction: bool = False
) -> ScoreFormRecoveryRouteSelection:
    """Parse failure-id=canonical-PDS2 or failure-id=@recorded; no QR guesses."""
    if type(value) is not str or "=" not in value:
        raise ScoreFormRecoveryInterfaceError(
            "Each --page must be FAILURE_ID=CANONICAL_PDS2 or FAILURE_ID=@recorded."
        )
    failure_id, separator, choice = value.partition("=")
    if not separator or not failure_id or failure_id != failure_id.strip() or not choice:
        raise ScoreFormRecoveryInterfaceError("Page selection has an invalid failure ID or route.")
    if choice == "@recorded":
        if allow_route_correction:
            raise ScoreFormRecoveryInterfaceError("Recorded-route reuse cannot request correction.")
        return ScoreFormRecoveryRouteSelection(failure_id, use_recorded_route=True)
    try:
        locator = parse_pds2_payload(choice)
        if serialize_pds2_payload(locator) != choice or locator.module_id != "scoreform":
            raise ValueError("Not a canonical ScoreForm route payload")
        return ScoreFormRecoveryRouteSelection(
            failure_id, route_locator=locator,
            allow_route_correction=allow_route_correction,
        )
    except (TypeError, ValueError) as error:
        raise ScoreFormRecoveryInterfaceError(
            "The selected page must use an exact canonical ScoreForm PDS2 route payload."
        ) from error


def render_recovery_preview(preview) -> None:
    """Make the identity, number of pages, and uncommitted state visible."""
    print("ScoreForm retained-page recovery preview (READ ONLY)")
    print(f"Issuance: {preview.issuance_id}")
    print(f"Source scan: {preview.source_scan_id}")
    for page in preview.prepared_pages:
        print(f"Failure: {page.failure_id}")
        print(f"  Student: {page.student_id}  Class: {page.class_id}")
        print(f"  Assignment: {page.assignment_id}")
        print(f"  Logical page: {page.logical_page}/{page.total_pages}")
        print(f"  Original scan page: {page.source_page_number}")
        print(f"  Retained source: {page.retained_source.retained_source_relative_path}")
        print(f"  Registered route: {page.route_locator.route_id}")
        print(f"  Route origin: {page.route_origin}")
        print(
            "  Decision: " + (
                "Record teacher route decision"
                if page.failure_id in preview.route_decisions_needed
                else "Reuse existing teacher route decision"
            )
        )
    print("No result or resolution has been written by this preview.")
    print("Recovery saves a result only when every issuance page is available.")


def render_recovery_outcome(outcome) -> None:
    print(f"Recovery status: {outcome.status}")
    print(outcome.reason)
    if outcome.missing_logical_pages:
        print(
            "Missing logical pages: "
            + ", ".join(str(value) for value in outcome.missing_logical_pages)
        )
    if outcome.recorded_route_failure_ids:
        print("Route decisions recorded: " + ", ".join(outcome.recorded_route_failure_ids))
    if outcome.persisted is not None:
        print(f"Result path: {outcome.persisted.output_path}")
        print(f"Attempt number: {outcome.persisted.attempt_number}")
    elif outcome.completion and outcome.verified:
        first = outcome.completion[0]
        print(f"Result path: {first.output_path}")
        print(f"Attempt number: {first.attempt_number}")
    if not outcome.verified:
        print("Recovery is not verified complete; no complete result is claimed.")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="scoreform recover-scan-review")
    parser.add_argument(
        "--page", action="append", required=True, metavar="FAILURE_ID=ROUTE",
        help="Repeat for all failed pages in one issuance; use @recorded to reuse a decision",
    )
    parser.add_argument(
        "--correct-failure", action="append", default=[], metavar="FAILURE_ID",
        help="Explicitly permit correction for the matching --page",
    )
    parser.add_argument("--apply", action="store_true", help="Execute after reviewing the preview")
    parser.add_argument(
        "--confirm", metavar="RECOVER", help="Required with --apply: type exactly RECOVER"
    )
    return parser


def run_recover_scan_review(args: list[str]) -> int:
    """CLI preview by default; explicit double-confirmation for mutations."""
    try:
        options = _parser().parse_args(args)
    except SystemExit as error:
        return int(error.code or 0)
    if options.confirm is not None and not options.apply:
        print("Error: --confirm is only valid with --apply.")
        return 1
    if options.apply and options.confirm != "RECOVER":
        print("Error: --apply requires --confirm RECOVER.")
        return 1
    try:
        corrected = set(options.correct_failure)
        if len(corrected) != len(options.correct_failure):
            raise ScoreFormRecoveryInterfaceError("Correction failure IDs must not repeat.")
        selections = tuple(
            parse_recovery_page_spec(
                page, allow_route_correction=page.partition("=")[0] in corrected
            ) for page in options.page
        )
        ids = {value.failure_id for value in selections}
        if not corrected.issubset(ids):
            raise ScoreFormRecoveryInterfaceError(
                "Each --correct-failure must match a supplied --page failure ID."
            )
        root = workspace.get_scoreform_workspace_root()
        preview = preview_scoreform_recovery_workflow(root, selections)
        render_recovery_preview(preview)
        if not options.apply:
            print("To execute, repeat the same command with --apply --confirm RECOVER.")
            return 0
        outcome = execute_approved_scoreform_recovery_workflow(
            root, preview, teacher_confirmed=True
        )
        render_recovery_outcome(outcome)
        return 0 if outcome.verified else 2
    except (ScoreFormRecoveryInterfaceError, ScoreFormRecoveryWorkflowError, OSError, ValueError) as error:
        print(f"Error: {error}")
        print("Existing route decisions and results may remain durable; inspect before retrying.")
        return 1


__all__ = [
    "ScoreFormRecoveryInterfaceError",
    "parse_recovery_page_spec",
    "render_recovery_outcome",
    "render_recovery_preview",
    "run_recover_scan_review",
]
