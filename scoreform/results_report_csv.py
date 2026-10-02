"""Deterministic CSV report-set renderer for ScoreForm Issue #217."""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Sequence

from scoreform.results_analysis import (
    PerformanceSummary,
    StandardPerformance,
    StudentAttemptAnalysis,
)
from scoreform.results_report_artifacts import (
    RenderedReportArtifact,
    RenderedResultsReport,
)
from scoreform.results_reporting import (
    ConfirmedResultsReportPlan,
    ResultsReportingError,
)
from scoreform.results_standard_display import ResultsStandardsProjection

CSV_MEDIA_TYPE = "text/csv; charset=utf-8"

CLASS_CSV_FILENAMES = (
    "report_metadata.csv",
    "assignment_overview.csv",
    "question_analysis.csv",
    "response_distribution.csv",
    "standards_analysis.csv",
    "unaligned_analysis.csv",
)

STUDENT_CSV_FILENAMES = (
    "report_metadata.csv",
    "assignment_overview.csv",
    "student_responses.csv",
    "standards_analysis.csv",
    "unaligned_analysis.csv",
)


def _csv_bytes(
    header: Sequence[str],
    rows: Iterable[Sequence[object]],
) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue().encode("utf-8")


def _percent(value: int | None) -> str:
    return "" if value is None else str(value)


def _bool(value: bool) -> str:
    return "true" if value else "false"


def _joined(values: Sequence[object]) -> str:
    return "|".join(str(value) for value in values)


def _response_state(selected_answer: str) -> tuple[str, str]:
    if selected_answer == "BLANK":
        return "BLANK", ""
    if selected_answer == "AMBIGUOUS":
        return "AMBIGUOUS", ""
    return "SELECTED", selected_answer


def _metadata_rows(plan: ConfirmedResultsReportPlan) -> tuple[tuple[str, str], ...]:
    snapshot = plan.plan.snapshot
    assignment = snapshot.assignment
    rows: list[tuple[str, str]] = [
        ("schema_version", snapshot.schema_version),
        ("generated_at", snapshot.generated_at),
        ("scope", snapshot.scope),
        ("class_id", snapshot.class_id),
        ("assignment_id", assignment.assignment_id),
        ("assignment_title", assignment.title),
        ("standards_profile_id", assignment.standards_profile_id or ""),
        (
            "include_individual_response_rows",
            _bool(snapshot.include_individual_response_rows),
        ),
        ("standards_basis", "current assignment alignment"),
    ]

    if snapshot.scope == "class_analysis":
        analysis = snapshot.class_analysis
        assert analysis is not None
        rows.extend(
            [
                ("attempt_basis", analysis.attempt_basis),
                ("students_represented", str(analysis.students_represented)),
            ]
        )
    else:
        detail = snapshot.student_detail
        assert detail is not None
        rows.extend(
            [
                ("student_id", detail.student_id),
                ("attempt_number", str(detail.attempt_number)),
                ("attempt_count", str(detail.attempt_count)),
                ("recorded_at", detail.recorded_at),
            ]
        )

    return tuple(rows)


def _overview_rows(
    students: Sequence[StudentAttemptAnalysis],
) -> tuple[tuple[object, ...], ...]:
    return tuple(
        (
            student.student_id,
            student.name,
            student.attempt_number,
            student.recorded_at,
            student.score,
            student.total_points,
            student.attempt_count,
        )
        for student in students
    )


def _standards_rows(
    standards: Sequence[StandardPerformance],
    standard_display: ResultsStandardsProjection,
) -> tuple[tuple[object, ...], ...]:
    return tuple(
        (
            standard.standard_id,
            standard_display.label_for(standard.standard_id),
            standard.correct,
            standard.responses,
            _percent(standard.percent_correct),
            _joined(standard.question_numbers),
        )
        for standard in standards
    )


def _unaligned_rows(
    unaligned: PerformanceSummary,
) -> tuple[tuple[object, ...], ...]:
    return (
        (
            unaligned.correct,
            unaligned.responses,
            _percent(unaligned.percent_correct),
            _joined(unaligned.question_numbers),
        ),
    )


def _artifact(filename: str, content: bytes) -> RenderedReportArtifact:
    return RenderedReportArtifact(
        filename=filename,
        media_type=CSV_MEDIA_TYPE,
        content=content,
    )


def render_results_report_csv(
    confirmed: ConfirmedResultsReportPlan,
) -> RenderedResultsReport:
    """Render one confirmed report plan into a deterministic in-memory CSV set."""
    if not isinstance(confirmed, ConfirmedResultsReportPlan):
        raise ResultsReportingError(
            "CSV rendering requires a ConfirmedResultsReportPlan."
        )
    if confirmed.plan.output_format != "csv":
        raise ResultsReportingError("Confirmed report format is not CSV.")

    snapshot = confirmed.plan.snapshot
    artifacts: list[RenderedReportArtifact] = [
        _artifact(
            "report_metadata.csv",
            _csv_bytes(("field", "value"), _metadata_rows(confirmed)),
        )
    ]

    if snapshot.scope == "class_analysis":
        analysis = snapshot.class_analysis
        assert analysis is not None

        artifacts.append(
            _artifact(
                "assignment_overview.csv",
                _csv_bytes(
                    (
                        "student_id",
                        "name",
                        "attempt_number",
                        "recorded_at",
                        "score",
                        "total_points",
                        "attempt_count",
                    ),
                    _overview_rows(analysis.students),
                ),
            )
        )
        artifacts.append(
            _artifact(
                "question_analysis.csv",
                _csv_bytes(
                    (
                        "question_number",
                        "correct",
                        "incorrect",
                        "blank",
                        "ambiguous",
                        "total",
                        "percent_correct",
                    ),
                    (
                        (
                            question.question_number,
                            question.correct,
                            question.incorrect,
                            question.blank,
                            question.ambiguous,
                            question.total,
                            _percent(question.percent_correct),
                        )
                        for question in analysis.questions
                    ),
                ),
            )
        )
        artifacts.append(
            _artifact(
                "response_distribution.csv",
                _csv_bytes(
                    (
                        "question_number",
                        "response",
                        "count",
                        "is_keyed_answer",
                    ),
                    (
                        (
                            question.question_number,
                            response.response,
                            response.count,
                            _bool(response.is_keyed_answer),
                        )
                        for question in analysis.questions
                        for response in question.response_distribution
                    ),
                ),
            )
        )
        artifacts.append(
            _artifact(
                "standards_analysis.csv",
                _csv_bytes(
                    (
                        "standard_id",
                        "display_label",
                        "correct",
                        "responses",
                        "percent_correct",
                        "question_numbers",
                    ),
                    _standards_rows(
                        analysis.standards,
                        snapshot.standards_projection,
                    ),
                ),
            )
        )
        artifacts.append(
            _artifact(
                "unaligned_analysis.csv",
                _csv_bytes(
                    (
                        "correct",
                        "responses",
                        "percent_correct",
                        "question_numbers",
                    ),
                    _unaligned_rows(analysis.unaligned),
                ),
            )
        )

        filenames = tuple(artifact.filename for artifact in artifacts)
        if filenames != CLASS_CSV_FILENAMES:
            raise ResultsReportingError(
                "Class CSV renderer produced an unexpected artifact set."
            )
    else:
        detail = snapshot.student_detail
        assert detail is not None

        artifacts.append(
            _artifact(
                "assignment_overview.csv",
                _csv_bytes(
                    (
                        "student_id",
                        "name",
                        "attempt_number",
                        "recorded_at",
                        "score",
                        "total_points",
                        "attempt_count",
                    ),
                    _overview_rows((detail,)),
                ),
            )
        )
        artifacts.append(
            _artifact(
                "student_responses.csv",
                _csv_bytes(
                    (
                        "student_id",
                        "name",
                        "attempt_number",
                        "question_number",
                        "response_state",
                        "selected_answer",
                        "correct",
                        "key",
                        "standard_ids",
                    ),
                    (
                        (
                            detail.student_id,
                            detail.name,
                            detail.attempt_number,
                            question.question_number,
                            _response_state(question.selected_answer)[0],
                            _response_state(question.selected_answer)[1],
                            _bool(question.correct),
                            question.keyed_answer,
                            _joined(question.standard_ids),
                        )
                        for question in detail.questions
                    ),
                ),
            )
        )
        artifacts.append(
            _artifact(
                "standards_analysis.csv",
                _csv_bytes(
                    (
                        "standard_id",
                        "display_label",
                        "correct",
                        "responses",
                        "percent_correct",
                        "question_numbers",
                    ),
                    _standards_rows(
                        detail.standards,
                        snapshot.standards_projection,
                    ),
                ),
            )
        )
        artifacts.append(
            _artifact(
                "unaligned_analysis.csv",
                _csv_bytes(
                    (
                        "correct",
                        "responses",
                        "percent_correct",
                        "question_numbers",
                    ),
                    _unaligned_rows(detail.unaligned),
                ),
            )
        )

        filenames = tuple(artifact.filename for artifact in artifacts)
        if filenames != STUDENT_CSV_FILENAMES:
            raise ResultsReportingError(
                "Student CSV renderer produced an unexpected artifact set."
            )

    return RenderedResultsReport(
        output_format="csv",
        scope=snapshot.scope,
        artifacts=tuple(artifacts),
    )
