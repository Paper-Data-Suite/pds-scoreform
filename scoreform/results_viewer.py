"""Read-only helpers for displaying strict schema-v2 assignment results."""

from dataclasses import dataclass
from pathlib import Path

from scoreform.module_errors import ScoreFormRoutedResultReadError
from scoreform.results import load_routed_results_history
from scoreform.results_analysis import select_recent_display_attempts
from scoreform.results_standard_display import (
    ResultsStandardsProjection,
    order_standard_items,
)

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
_STUDENT_OUTCOME_LABELS = {
    "correct": "Correct",
    "incorrect": "Incorrect",
    "blank": "Blank",
    "ambiguous": "Ambiguous",
}


def _analysis_table(headers, rows):
    if not rows:
        return ""
    widths = [
        max(len(headers[column]), *(len(record[column]) for record in rows))
        for column in range(len(headers))
    ]
    return "\n".join(
        [_format_table_row(headers, widths)]
        + [_format_table_row(record, widths) for record in rows]
    )


def _format_percent(value):
    return "—" if value is None else f"{value}%"


def _standards_in_display_order(
    standards,
    standard_display,
):
    if standard_display is None:
        return standards
    if not isinstance(standard_display, ResultsStandardsProjection):
        raise ResultsViewError(
            "standard_display must be a ResultsStandardsProjection."
        )
    return order_standard_items(standards, standard_display)


def _standard_display_label(
    standard_id,
    standard_display,
):
    if standard_display is None:
        return standard_id
    if not isinstance(standard_display, ResultsStandardsProjection):
        raise ResultsViewError(
            "standard_display must be a ResultsStandardsProjection."
        )
    return standard_display.label_for(standard_id)


def format_student_attempt_detail(analysis, *, standard_display=None):
    """Format one exact immutable Student Detail analysis for terminal display."""
    from scoreform.results_analysis import StudentAttemptAnalysis

    if not isinstance(analysis, StudentAttemptAnalysis):
        raise ResultsViewError("Student detail requires a validated analysis model.")

    lines = [
        "Student Result",
        "",
        f"Class: {analysis.class_id}",
        f"Assignment: {analysis.assignment_id}",
        f"Student: {analysis.name or '(name unavailable)'} ({analysis.student_id})",
        f"Attempt: {analysis.attempt_number} of {analysis.attempt_count}",
        f"Recorded: {analysis.recorded_at}",
        f"Overall: {analysis.score} / {analysis.total_points}",
        "",
    ]

    question_rows = []
    for question in analysis.questions:
        standards = ", ".join(question.standard_ids) if question.standard_ids else "Unaligned"
        question_rows.append(
            (
                f"Q{question.question_number}",
                question.selected_answer,
                question.keyed_answer,
                _STUDENT_OUTCOME_LABELS[question.outcome],
                standards,
            )
        )
    lines.append(
        _analysis_table(
            ("Question", "Response", "Key", "Result", "Standard(s)"),
            question_rows,
        )
    )

    lines.extend(["", "Student Standards Breakdown", ""])
    standard_rows = [
        (
            _standard_display_label(item.standard_id, standard_display),
            str(item.correct),
            str(item.responses),
            _format_percent(item.percent_correct),
        )
        for item in _standards_in_display_order(
            analysis.standards,
            standard_display,
        )
    ]
    if standard_rows:
        lines.append(
            _analysis_table(
                ("Standard", "Correct", "Asked", "Percent"),
                standard_rows,
            )
        )
    else:
        lines.append("No Standards are aligned to this assignment.")

    if analysis.unaligned.responses:
        lines.extend(
            [
                "",
                (
                    "Unaligned: "
                    f"{analysis.unaligned.correct} / {analysis.unaligned.responses} "
                    f"({_format_percent(analysis.unaligned.percent_correct)})"
                ),
            ]
        )

    lines.extend(
        [
            "",
            "Standards basis: current assignment alignment.",
            (
                "These are descriptive response counts, not proficiency or "
                "Grade determinations."
            ),
        ]
    )
    return "\n".join(lines)


def format_student_standard_detail(
    analysis,
    standard_id,
    *,
    standard_display=None,
):
    """Format contributing questions for one Standard in one selected attempt."""
    from scoreform.results_analysis import StudentAttemptAnalysis

    if not isinstance(analysis, StudentAttemptAnalysis):
        raise ResultsViewError("Standard detail requires a validated analysis model.")
    if not isinstance(standard_id, str) or not standard_id:
        raise ResultsViewError("standard_id must be a nonempty string.")

    standard = next(
        (item for item in analysis.standards if item.standard_id == standard_id),
        None,
    )
    if standard is None:
        raise ResultsViewError(
            f"Standard {standard_id!r} does not contribute to this attempt."
        )

    contributing = tuple(
        question
        for question in analysis.questions
        if standard_id in question.standard_ids
    )
    rows = [
        (
            f"Q{question.question_number}",
            question.selected_answer,
            question.keyed_answer,
            _STUDENT_OUTCOME_LABELS[question.outcome],
        )
        for question in contributing
    ]

    return "\n".join(
        [
            (
                "Standard: "
                f"{_standard_display_label(standard.standard_id, standard_display)}"
            ),
            (
                f"Correct: {standard.correct} / {standard.responses} "
                f"({_format_percent(standard.percent_correct)})"
            ),
            "Standards basis: current assignment alignment.",
            "",
            _analysis_table(
                ("Question", "Response", "Key", "Result"),
                rows,
            ),
        ]
    )
def format_question_analysis_table(analysis):
    """Format class-level question counts from one immutable analysis snapshot."""
    from scoreform.results_analysis import ClassResultsAnalysis

    if not isinstance(analysis, ClassResultsAnalysis):
        raise ResultsViewError("Question analysis requires a validated class model.")

    rows = [
        (
            f"Q{question.question_number}",
            str(question.correct),
            str(question.incorrect),
            str(question.blank),
            str(question.ambiguous),
            str(question.total),
            _format_percent(question.percent_correct),
        )
        for question in analysis.questions
    ]
    return "\n".join(
        [
            "Question Analysis",
            "",
            f"Students represented: {analysis.students_represented}",
            f"Basis: {analysis.attempt_basis}.",
            "",
            _analysis_table(
                (
                    "Question",
                    "Correct",
                    "Incorrect",
                    "Blank",
                    "Ambiguous",
                    "Total",
                    "% Correct",
                ),
                rows,
            ),
        ]
    )


def format_question_response_distribution(analysis, question_number):
    """Format one question's complete response distribution."""
    from scoreform.results_analysis import ClassResultsAnalysis

    if not isinstance(analysis, ClassResultsAnalysis):
        raise ResultsViewError(
            "Question distribution requires a validated class model."
        )
    if (
        isinstance(question_number, bool)
        or not isinstance(question_number, int)
        or not 1 <= question_number <= len(analysis.questions)
    ):
        raise ResultsViewError("question_number is outside the assignment range.")

    question = analysis.questions[question_number - 1]
    rows = [
        (
            item.response,
            str(item.count),
            "Yes" if item.is_keyed_answer else "",
        )
        for item in question.response_distribution
    ]

    return "\n".join(
        [
            f"Q{question.question_number}",
            f"Correct answer: {question.keyed_answer}",
            "",
            _analysis_table(("Response", "Count", "Key"), rows),
            "",
            (
                f"Correct: {question.correct} / {question.total} "
                f"({_format_percent(question.percent_correct)})"
            ),
            f"Basis: {analysis.attempt_basis}.",
        ]
    )


def format_class_standards_analysis(
    analysis,
    *,
    standard_display=None,
):
    """Format descriptive class-level counts by current assignment Standard."""
    from scoreform.results_analysis import ClassResultsAnalysis

    if not isinstance(analysis, ClassResultsAnalysis):
        raise ResultsViewError("Standards analysis requires a validated class model.")

    lines = [
        "Standards Analysis",
        "",
        f"Students represented: {analysis.students_represented}",
        f"Basis: {analysis.attempt_basis}.",
        f"Standards basis: {analysis.standards_basis}.",
        "",
    ]

    rows = [
        (
            str(index),
            _standard_display_label(
                standard.standard_id,
                standard_display,
            ),
            str(standard.correct),
            str(standard.responses),
            _format_percent(standard.percent_correct),
        )
        for index, standard in enumerate(
            _standards_in_display_order(
                analysis.standards,
                standard_display,
            ),
            start=1,
        )
    ]
    if rows:
        lines.append(
            _analysis_table(
                ("#", "Standard", "Correct", "Responses", "Percent"),
                rows,
            )
        )
    else:
        lines.append("No Standards are aligned to this assignment.")

    if analysis.unaligned.responses:
        lines.extend(
            [
                "",
                (
                    "Unaligned: "
                    f"{analysis.unaligned.correct} / {analysis.unaligned.responses} "
                    f"({_format_percent(analysis.unaligned.percent_correct)})"
                ),
            ]
        )

    lines.extend(
        [
            "",
            (
                "These are descriptive response counts, not proficiency or "
                "Grade determinations."
            ),
        ]
    )
    return "\n".join(lines)


def format_class_standard_detail(
    analysis,
    standard_id,
    *,
    standard_display=None,
):
    """Format exact assignment questions contributing to one class Standard."""
    from scoreform.results_analysis import ClassResultsAnalysis

    if not isinstance(analysis, ClassResultsAnalysis):
        raise ResultsViewError(
            "Class Standard detail requires a validated class model."
        )
    if not isinstance(standard_id, str) or not standard_id:
        raise ResultsViewError("standard_id must be a nonempty string.")

    standard = next(
        (item for item in analysis.standards if item.standard_id == standard_id),
        None,
    )
    if standard is None:
        raise ResultsViewError(
            f"Standard {standard_id!r} does not contribute to this analysis."
        )

    question_lookup = {item.question_number: item for item in analysis.questions}
    rows = [
        (
            f"Q{number}",
            str(question_lookup[number].correct),
            str(question_lookup[number].total),
            _format_percent(question_lookup[number].percent_correct),
        )
        for number in standard.question_numbers
    ]

    return "\n".join(
        [
            (
                "Standard: "
                f"{_standard_display_label(standard.standard_id, standard_display)}"
            ),
            (
                f"Correct responses: {standard.correct} / {standard.responses} "
                f"({_format_percent(standard.percent_correct)})"
            ),
            f"Standards basis: {analysis.standards_basis}.",
            f"Basis: {analysis.attempt_basis}.",
            "",
            _analysis_table(
                ("Question", "Correct", "Responses", "% Correct"),
                rows,
            ),
        ]
    )
