"""Interactive Results Report export workflow for ScoreForm Issue #217."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path

from scoreform.menu_navigation import (
    parse_scoreform_navigation,
    print_invalid_navigation,
    print_scoreform_navigation_options,
)
from scoreform.results import ScoreFormRoutedResultHistoryRow
from scoreform.results_analysis import (
    ResultsAnalysisError,
    select_recent_display_attempts,
    select_student_attempts,
)
from scoreform.results_report_csv import render_results_report_csv
from scoreform.results_report_json import render_results_report_json
from scoreform.results_report_output import (
    ResultsReportOutputError,
    install_rendered_results_report,
    plan_results_report_destination,
)
from scoreform.results_report_pdf import render_results_report_pdf
from scoreform.results_reporting import (
    REPORT_CONFIRMATION_TOKEN,
    ConfirmedResultsReportPlan,
    ReportFormat,
    ReportScope,
    ResultsReportingError,
    confirm_results_report_plan,
    format_results_report_preview,
    prepare_results_report_plan,
    prepare_results_report_snapshot,
)
from scoreform.workflows import print_menu_header

InputCallback = Callable[[str], str]
UiCallback = Callable[[], None]
NowCallback = Callable[[], datetime]


def _choose_scope(
    *,
    input_fn: InputCallback,
    clear_screen_fn: UiCallback,
) -> ReportScope | None:
    while True:
        clear_screen_fn()
        print_menu_header("Export Results Report")
        print("Select report scope:")
        print("1. Class Analysis")
        print("2. Student Detail")
        print_scoreform_navigation_options()
        print()

        choice = input_fn("Select an option: ").strip()
        if parse_scoreform_navigation(choice) is not None:
            return None
        if choice == "1":
            return "class_analysis"
        if choice == "2":
            return "student_detail"
        print(f"Invalid selection: {choice}.")
        print_invalid_navigation()
        print()


def _choose_student(
    rows: Sequence[ScoreFormRoutedResultHistoryRow],
    *,
    input_fn: InputCallback,
    clear_screen_fn: UiCallback,
) -> str | None:
    recent = select_recent_display_attempts(rows)
    if not recent:
        raise ResultsReportingError(
            "No scored student attempts are available for Student Detail."
        )

    while True:
        clear_screen_fn()
        print_menu_header("Export Student Detail Report")
        print("Select student:")
        for index, selected in enumerate(recent, start=1):
            result = selected.row.result
            print(
                f"{index}. {result.student_id} - "
                f"{result.last_name}, {result.first_name}"
            )
        print_scoreform_navigation_options()
        print()

        choice = input_fn("Select student: ").strip()
        if parse_scoreform_navigation(choice) is not None:
            return None
        if choice.isdigit():
            index = int(choice)
            if 1 <= index <= len(recent):
                return recent[index - 1].row.result.student_id
        print(f"Invalid selection: {choice}.")
        print_invalid_navigation()
        print()


def _choose_attempt(
    rows: Sequence[ScoreFormRoutedResultHistoryRow],
    student_id: str,
    *,
    input_fn: InputCallback,
    clear_screen_fn: UiCallback,
) -> int | None:
    attempts = select_student_attempts(rows, student_id)
    if not attempts:
        raise ResultsReportingError(
            "No preserved attempts are available for the selected student."
        )
    if len(attempts) == 1:
        return attempts[0].attempt_number

    recent_attempt = attempts[-1].attempt_number
    while True:
        clear_screen_fn()
        print_menu_header("Export Student Detail Report")
        print(f"Student ID: {student_id}")
        print()
        print("Select preserved attempt:")
        for index, row in enumerate(attempts, start=1):
            suffix = " (Recent)" if row.attempt_number == recent_attempt else ""
            print(
                f"{index}. Attempt {row.attempt_number} - "
                f"{row.scan_timestamp}{suffix}"
            )
        print()
        print(
            f"Press Enter for the recent display attempt "
            f"(Attempt {recent_attempt})."
        )
        print_scoreform_navigation_options()
        print()

        choice = input_fn("Select attempt: ").strip()
        if not choice:
            return recent_attempt
        if parse_scoreform_navigation(choice) is not None:
            return None
        if choice.isdigit():
            index = int(choice)
            if 1 <= index <= len(attempts):
                return attempts[index - 1].attempt_number
        print(f"Invalid selection: {choice}.")
        print_invalid_navigation()
        print()


def _choose_format(
    *,
    input_fn: InputCallback,
    clear_screen_fn: UiCallback,
) -> ReportFormat | None:
    while True:
        clear_screen_fn()
        print_menu_header("Export Results Report")
        print("Select format:")
        print("1. CSV report set")
        print("2. JSON")
        print("3. PDF")
        print_scoreform_navigation_options()
        print()

        choice = input_fn("Select format: ").strip()
        if parse_scoreform_navigation(choice) is not None:
            return None
        formats: dict[str, ReportFormat] = {
            "1": "csv",
            "2": "json",
            "3": "pdf",
        }
        if choice in formats:
            return formats[choice]
        print(f"Invalid selection: {choice}.")
        print_invalid_navigation()
        print()


def _render_confirmed(confirmed: ConfirmedResultsReportPlan):
    output_format = confirmed.plan.output_format
    if output_format == "csv":
        return render_results_report_csv(confirmed)
    if output_format == "json":
        return render_results_report_json(confirmed)
    if output_format == "pdf":
        return render_results_report_pdf(confirmed)
    raise ResultsReportingError("Unsupported confirmed report format.")


def launch_results_export_menu(
    rows: Sequence[ScoreFormRoutedResultHistoryRow],
    assignment: Mapping[str, object],
    *,
    class_id: str,
    assignment_id: str,
    workspace_root: str | Path,
    input_fn: InputCallback = input,
    clear_screen_fn: UiCallback,
    now_fn: NowCallback | None = None,
) -> int:
    """Prepare, confirm, render, and create one assignment-local report."""
    clock = (
        (lambda: datetime.now(timezone.utc))
        if now_fn is None
        else now_fn
    )

    try:
        scope = _choose_scope(
            input_fn=input_fn,
            clear_screen_fn=clear_screen_fn,
        )
        if scope is None:
            return 0

        student_id: str | None = None
        attempt_number: int | None = None
        if scope == "student_detail":
            student_id = _choose_student(
                rows,
                input_fn=input_fn,
                clear_screen_fn=clear_screen_fn,
            )
            if student_id is None:
                return 0
            attempt_number = _choose_attempt(
                rows,
                student_id,
                input_fn=input_fn,
                clear_screen_fn=clear_screen_fn,
            )
            if attempt_number is None:
                return 0

        output_format = _choose_format(
            input_fn=input_fn,
            clear_screen_fn=clear_screen_fn,
        )
        if output_format is None:
            return 0

        snapshot = prepare_results_report_snapshot(
            rows,
            assignment,
            class_id=class_id,
            scope=scope,
            generated_at=clock(),
            student_id=student_id,
            attempt_number=attempt_number,
            workspace_root=workspace_root,
        )
        plan = prepare_results_report_plan(
            snapshot,
            output_format=output_format,
        )
        destination = plan_results_report_destination(
            workspace_root,
            class_id=class_id,
            assignment_id=assignment_id,
            snapshot=snapshot,
            output_format=plan.output_format,
        )

        clear_screen_fn()
        print(format_results_report_preview(plan))
        print(
            "Destination: "
            f"{destination.workspace_relative_dir.as_posix()}"
        )
        print("Existing reports are never overwritten.")
        print()

        confirmation = input_fn(
            f"Type {REPORT_CONFIRMATION_TOKEN} to create the report: "
        ).strip()
        confirmed = confirm_results_report_plan(plan, confirmation)
        if confirmed is None:
            print("Cancelled: report was not created.")
            return 0

        rendered = _render_confirmed(confirmed)
        installed = install_rendered_results_report(
            destination,
            rendered,
        )

        clear_screen_fn()
        print_menu_header("Results Report Created")
        print(
            "Report directory: "
            f"{installed.destination.workspace_relative_dir.as_posix()}"
        )
        print("Created files:")
        for path in installed.workspace_relative_files:
            print(f"- {path.as_posix()}")
        print()
        print("The report remains a local teacher-controlled artifact.")
        return 0
    except (
        ResultsAnalysisError,
        ResultsReportingError,
        ResultsReportOutputError,
    ) as error:
        print(f"Error: Could not export results report: {error}")
        return 1
