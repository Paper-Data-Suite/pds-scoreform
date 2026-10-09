"""Issue #225 Slice 13: terminal prompts over the guarded recovery coordinator."""

from __future__ import annotations

from scoreform.cli_scan_recovery import (
    parse_recovery_page_spec,
    render_recovery_outcome,
    render_recovery_preview,
)
from scoreform.qr_scan_recovery_workflow import (
    execute_approved_scoreform_recovery_workflow,
    preview_scoreform_recovery_workflow,
)


def run_teacher_scan_recovery(root, item) -> bool:
    """Return False on safe cancel; True after an explicitly applied workflow.

    No mutation occurs until exact RECOVER input after a read-only preview.
    A later failed stage may leave a teacher route decision already recorded.
    """
    print("Recover an unreadable ScoreForm QR from its original retained scan.")
    print("Use only a route you have verified against the physical answer sheet.")
    print("For a multi-page attempt, add other failed-page IDs from the same scan.")
    extra = input("Additional failure IDs (comma separated, or blank): ").strip()
    ids = (item.failure_id, *tuple(x.strip() for x in extra.split(",") if x.strip()))
    if len(set(ids)) != len(ids):
        print("Duplicate failure IDs; recovery canceled.")
        return False
    selections = []
    for failure_id in ids:
        value = input(
            f"Route for {failure_id} (exact PDS2 payload, @recorded, or B to cancel): "
        ).strip()
        if not value or value.casefold() in {"b", "c", "q"}:
            print("Recovery canceled; no new result or route decision written.")
            return False
        correct = False
        if value != "@recorded":
            correct = (
                input("Is this an explicit correction of a prior/observed route? "
                      "Type CORRECT if so, or Enter otherwise: ").strip() == "CORRECT"
            )
        selections.append(
            parse_recovery_page_spec(
                f"{failure_id}={value}", allow_route_correction=correct
            )
        )
    preview = preview_scoreform_recovery_workflow(root, tuple(selections))
    print()
    render_recovery_preview(preview)
    print("The original teacher selection and complete-result requirements will be revalidated.")
    if input("Type RECOVER to record routes and process these pages: ").strip() != "RECOVER":
        print("Recovery canceled; no new result or route decision written.")
        return False
    outcome = execute_approved_scoreform_recovery_workflow(
        root, preview, teacher_confirmed=True
    )
    print()
    render_recovery_outcome(outcome)
    return True


__all__ = ["run_teacher_scan_recovery"]
