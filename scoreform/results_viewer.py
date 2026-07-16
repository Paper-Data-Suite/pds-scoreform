"""Read-only helpers for displaying assignment-local results."""

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

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
    """Load assignment-local results.csv rows without mutating the file."""
    path = Path(results_csv_path)
    if not path.exists():
        raise FileNotFoundError(path)
    if not path.is_file():
        raise ResultsViewError(f"Results path is not a file: {path}")

    try:
        with path.open(mode="r", newline="", encoding="utf-8") as csv_file:
            reader = csv.DictReader(csv_file, strict=True)
            if reader.fieldnames is None:
                return []

            rows = []
            for row in reader:
                if None in row or any(value is None for value in row.values()):
                    raise ResultsViewError("Results CSV contains malformed rows.")
                rows.append(dict(row))
            return rows
    except csv.Error as error:
        raise ResultsViewError(f"Results CSV is not valid CSV: {error}") from error
    except UnicodeDecodeError as error:
        raise ResultsViewError(f"Results CSV is not valid UTF-8: {error}") from error
    except OSError as error:
        raise ResultsViewError(f"Could not read results CSV: {error}") from error


def summarize_assignment_results(rows):
    """Return one display summary per student using recent-attempt display policy."""
    grouped = {}
    for index, row in enumerate(rows):
        normalized = _normalize_result_row(row)
        student_id = normalized["student_id"]
        if not student_id:
            continue
        grouped.setdefault(student_id, []).append((index, normalized))

    summaries = []
    for student_id in sorted(grouped, key=str.lower):
        attempts = grouped[student_id]
        recent = _select_recent_attempt(attempts)
        summaries.append(
            AssignmentResultSummary(
                student_id=student_id,
                name=recent["name"],
                recent=recent["recent"],
                total=recent["total"],
                attempts=len(attempts),
            )
        )
    return summaries


def format_assignment_results_table(summary_rows):
    """Format assignment result summaries as a compact read-only table."""
    if not summary_rows:
        return "No displayable result rows found."

    headers = ("Student ID", "Name", "Recent", "Total", "Attempts")
    body = [
        (
            row.student_id,
            row.name,
            row.recent,
            row.total,
            str(row.attempts),
        )
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


def _normalize_result_row(row):
    return {
        "student_id": _first_present(row, "student_id", "Student ID", "student"),
        "name": _student_name(row),
        "recent": _first_present(row, "Score", "score", "correct", "Correct"),
        "total": _first_present(
            row,
            "Total",
            "total",
            "total_points",
            "Total Points",
        ),
        "scan_timestamp": _first_present(
            row,
            "scan_timestamp",
            "Scan Timestamp",
            "timestamp",
        ),
    }


def _first_present(row, *field_names):
    for field_name in field_names:
        value = row.get(field_name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _student_name(row):
    last_name = _first_present(row, "last_name", "Last Name", "last")
    first_name = _first_present(row, "first_name", "First Name", "first")
    if last_name and first_name:
        return f"{last_name}, {first_name}"
    if last_name:
        return last_name
    if first_name:
        return first_name
    return _first_present(row, "Name", "name", "student_name")


def _select_recent_attempt(attempts):
    parseable = []
    for index, row in attempts:
        timestamp = _parse_scan_timestamp(row["scan_timestamp"])
        if timestamp is None:
            return attempts[-1][1]
        parseable.append((timestamp, index, row))

    return max(parseable, key=lambda item: (item[0], item[1]))[2]


def _parse_scan_timestamp(value):
    if not value:
        return None

    for parser in (_parse_iso_timestamp, _parse_scoreform_timestamp):
        parsed = parser(value)
        if parsed is not None:
            return parsed
    return None


def _parse_iso_timestamp(value):
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is not None:
            return parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
    except ValueError:
        return None


def _parse_scoreform_timestamp(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
