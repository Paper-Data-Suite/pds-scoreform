"""Read-only helpers for displaying strict schema-v2 assignment results."""

from dataclasses import dataclass
from pathlib import Path

from scoreform.module_errors import ScoreFormRoutedResultReadError
from scoreform.results import load_routed_results_history
from scoreform.results_analysis import select_recent_display_attempts

MULTIPLE_ATTEMPTS_NOTE = (
    "Note: Recent shows the most recent scored attempt. Attempts shows how many "
    "scored rows exist for that student. ScoreForm does not decide which attempt "
    "counts as the grade."
)


class ResultsViewError(Exception):
    """Raised when assignment results cannot be loaded for display."""


@dataclass(frozen=True)
class AssignmentResultSummary:
    student_id: str
    name: str
    recent: str
    total: str
    attempts: int


def load_assignment_results(results_csv_path):
    """Load assignment-local results through the shared strict v2 reader."""
    path = Path(results_csv_path)
    if not path.exists():
        raise FileNotFoundError(path)
    try:
        return load_routed_results_history(path)
    except ScoreFormRoutedResultReadError as error:
        raise ResultsViewError(str(error)) from error


def summarize_assignment_results(rows):
    """Return one display summary per student using the shared display-attempt rule."""
    try:
        selections = select_recent_display_attempts(rows)
    except (TypeError, ValueError) as error:
        raise ResultsViewError(str(error)) from error

    summaries = []
    for selection in selections:
        result = selection.row.result
        name = ", ".join(part for part in (result.last_name, result.first_name) if part)
        summaries.append(
            AssignmentResultSummary(
                student_id=selection.student_id,
                name=name,
                recent=str(result.score),
                total=str(result.total_points),
                attempts=selection.attempt_count,
            )
        )
    return summaries


def format_assignment_results_table(summary_rows):
    """Format assignment result summaries as a compact read-only table."""
    if not summary_rows:
        return "No displayable result rows found."

    headers = ("Student ID", "Name", "Recent", "Total", "Attempts")
    body = [
        (row.student_id, row.name, row.recent, row.total, str(row.attempts))
        for row in summary_rows
    ]
    widths = [
        max(len(headers[column]), *(len(record[column]) for record in body))
        for column in range(len(headers))
    ]
    lines = [_format_table_row(headers, widths)]
    lines.extend(_format_table_row(record, widths) for record in body)
    if any(row.attempts > 1 for row in summary_rows):
        lines.extend(["", MULTIPLE_ATTEMPTS_NOTE])
    return "\n".join(lines)


def _format_table_row(values, widths):
    return "  ".join(
        value.ljust(width)
        for value, width in zip(values, widths, strict=True)
    ).rstrip()
