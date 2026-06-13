from __future__ import annotations

import os
from pathlib import Path
from typing import TypedDict

from pds_core.rosters import (
    Roster as CoreRoster,
)
from pds_core.rosters import (
    RosterError,
    RosterValidationError,
)
from pds_core.rosters import (
    StudentRecord as CoreStudentRecord,
)
from pds_core.rosters import (
    load_roster as load_core_roster,
)

LegacyStudent = dict[str, str]


class LegacyRoster(TypedDict):
    """ScoreForm's existing public roster dictionary shape."""

    class_id: str
    roster_path: str
    students: list[LegacyStudent]


def _student_to_legacy_dict(student: CoreStudentRecord) -> LegacyStudent:
    """Convert one core student record to ScoreForm's legacy dictionary."""
    data = {
        "class_id": student.class_id,
        "student_id": student.student_id,
        "last_name": student.last_name,
        "first_name": student.first_name,
        "period": student.period,
    }
    data.update(student.extra_fields)
    return data


def _core_roster_to_legacy_dict(roster: CoreRoster) -> LegacyRoster:
    """Convert a validated core roster to ScoreForm's legacy dictionary."""
    roster_path = os.fspath(roster.source_path) if roster.source_path else ""
    return {
        "class_id": roster.class_id,
        "roster_path": roster_path,
        "students": [
            _student_to_legacy_dict(student) for student in roster.students
        ],
    }


def _print_roster_error(roster_path: str | Path, error: RosterError) -> None:
    """Print a core roster error using ScoreForm's established error surface."""
    if not isinstance(error, RosterValidationError):
        print(f"Error: Could not read roster file '{roster_path}': {error}")
        return

    missing_columns = sorted(
        {
            issue.column
            for issue in error.issues
            if issue.code == "missing_required_column" and issue.column
        }
    )
    if missing_columns:
        print(
            f"Error: Roster file '{roster_path}' is missing required columns: "
            f"{', '.join(missing_columns)}."
        )
        return

    issue = error.issues[0]
    if issue.code == "missing_header":
        print(f"Error: Roster file '{roster_path}' is empty or missing headers.")
    elif issue.code in {"blank_required_value", "missing_required_field"}:
        print(f"Error: Missing {issue.column} on row {issue.row_number}.")
    elif issue.code == "inconsistent_class_id":
        print(f"Error: Inconsistent class_id on row {issue.row_number}. {issue.message}")
    elif issue.code == "duplicate_student_id":
        print(
            f"Error: Duplicate student_id '{issue.value}' found on row "
            f"{issue.row_number}."
        )
    elif issue.code == "empty_roster":
        print(f"Error: Roster file '{roster_path}' contains no student rows.")
    else:
        print(f"Error: Invalid roster file '{roster_path}': {error}")


def load_roster(roster_path: str | Path) -> LegacyRoster | None:
    """Load a roster through pds-core and return ScoreForm's legacy shape."""
    if not os.path.exists(roster_path):
        print(f"Error: Roster file '{roster_path}' not found.")
        return None

    try:
        roster = load_core_roster(roster_path)
    except RosterError as error:
        _print_roster_error(roster_path, error)
        return None

    return _core_roster_to_legacy_dict(roster)
