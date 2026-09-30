"""Immutable report snapshots and zero-write export preparation for Issue #217."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from scoreform.results import ScoreFormRoutedResultHistoryRow
from scoreform.results_analysis import (
    ClassResultsAnalysis,
    ResultsAnalysisError,
    StudentAttemptAnalysis,
    analyze_class_results,
    analyze_student_attempt,
    select_student_attempts,
)

RESULTS_ANALYSIS_REPORT_SCHEMA = "scoreform_results_analysis_v1"
REPORT_CONFIRMATION_TOKEN = "GENERATE"

ReportScope = Literal["class_analysis", "student_detail"]
ReportFormat = Literal["csv", "json", "pdf"]

_REPORT_FORMATS = frozenset({"csv", "json", "pdf"})

REPORT_BASIS_STATEMENT = (
    "ScoreForm Results Analysis reports descriptive assessment data. "
    "Standards summaries reflect question alignment and response correctness "
    "and are not proficiency or Grade determinations."
)
CLASS_ATTEMPT_BASIS_STATEMENT = (
    "Class aggregates use each student's most recent scored attempt for display. "
    "ScoreForm does not determine which attempt counts toward a Grade."
)
STANDARDS_BASIS_STATEMENT = (
    "Standards summaries use the assignment's current question alignment."
)


class ResultsReportingError(ValueError):
    """Raised when a report snapshot or export plan cannot be prepared safely."""


@dataclass(frozen=True, slots=True)
class AssignmentReportSnapshot:
    """Immutable assignment context needed to interpret a results report."""

    assignment_id: str
    title: str
    question_count: int
    choices: tuple[str, ...]
    answer_key: tuple[str, ...]
    standards_profile_id: str | None
    standards_by_question: tuple[tuple[str, ...], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.assignment_id, str) or not self.assignment_id:
            raise ValueError("assignment_id must be a nonempty string.")
        if not isinstance(self.title, str) or not self.title:
            raise ValueError("title must be a nonempty string.")
        if (
            isinstance(self.question_count, bool)
            or not isinstance(self.question_count, int)
            or self.question_count < 1
        ):
            raise ValueError("question_count must be a positive integer.")
        if (
            not isinstance(self.choices, tuple)
            or not self.choices
            or any(not isinstance(choice, str) or not choice for choice in self.choices)
            or len(set(self.choices)) != len(self.choices)
        ):
            raise ValueError("choices must be unique nonempty strings.")
        if (
            not isinstance(self.answer_key, tuple)
            or len(self.answer_key) != self.question_count
            or any(answer not in self.choices for answer in self.answer_key)
        ):
            raise ValueError("answer_key must cover the assignment exactly.")
        if self.standards_profile_id is not None and (
            not isinstance(self.standards_profile_id, str)
            or not self.standards_profile_id
        ):
            raise ValueError(
                "standards_profile_id must be a nonempty string when present."
            )
        if (
            not isinstance(self.standards_by_question, tuple)
            or len(self.standards_by_question) != self.question_count
        ):
            raise ValueError(
                "standards_by_question must cover the assignment exactly."
            )
        for standards in self.standards_by_question:
            if not isinstance(standards, tuple) or any(
                not isinstance(standard_id, str) or not standard_id
                for standard_id in standards
            ):
                raise ValueError(
                    "standards_by_question must contain tuples of Standard IDs."
                )
            if len(set(standards)) != len(standards):
                raise ValueError(
                    "standards_by_question must not repeat Standard IDs."
                )


@dataclass(frozen=True, slots=True)
class ResultsReportSnapshot:
    """One immutable in-memory source of truth for every report renderer."""

    schema_version: str
    generated_at: str
    scope: ReportScope
    class_id: str
    assignment: AssignmentReportSnapshot
    class_analysis: ClassResultsAnalysis | None
    student_detail: StudentAttemptAnalysis | None
    include_individual_response_rows: bool
    basis_statements: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != RESULTS_ANALYSIS_REPORT_SCHEMA:
            raise ValueError("Unsupported results-analysis report schema.")
        _validate_generated_timestamp(self.generated_at)
        if self.scope not in {"class_analysis", "student_detail"}:
            raise ValueError("Unsupported report scope.")
        if not isinstance(self.class_id, str) or not self.class_id:
            raise ValueError("class_id must be a nonempty string.")
        if not isinstance(self.assignment, AssignmentReportSnapshot):
            raise TypeError("assignment must be an AssignmentReportSnapshot.")
        if not isinstance(self.include_individual_response_rows, bool):
            raise TypeError("include_individual_response_rows must be Boolean.")
        if not isinstance(self.basis_statements, tuple) or any(
            not isinstance(statement, str) or not statement
            for statement in self.basis_statements
        ):
            raise TypeError("basis_statements must contain nonempty strings.")

        if self.scope == "class_analysis":
            if not isinstance(self.class_analysis, ClassResultsAnalysis):
                raise TypeError(
                    "class_analysis scope requires a ClassResultsAnalysis model."
                )
            if self.student_detail is not None:
                raise ValueError(
                    "class_analysis scope must not contain student_detail."
                )
            if self.include_individual_response_rows:
                raise ValueError(
                    "class_analysis reports must not default to individual response rows."
                )
            if self.class_analysis.class_id != self.class_id:
                raise ValueError("Class analysis identity does not match snapshot.")
            if (
                self.class_analysis.assignment_id
                != self.assignment.assignment_id
            ):
                raise ValueError(
                    "Class analysis assignment does not match snapshot."
                )
        else:
            if not isinstance(self.student_detail, StudentAttemptAnalysis):
                raise TypeError(
                    "student_detail scope requires a StudentAttemptAnalysis model."
                )
            if self.class_analysis is not None:
                raise ValueError(
                    "student_detail scope must not contain class_analysis."
                )
            if not self.include_individual_response_rows:
                raise ValueError(
                    "student_detail reports must include the selected response rows."
                )
            if self.student_detail.class_id != self.class_id:
                raise ValueError("Student detail class does not match snapshot.")
            if (
                self.student_detail.assignment_id
                != self.assignment.assignment_id
            ):
                raise ValueError(
                    "Student detail assignment does not match snapshot."
                )


@dataclass(frozen=True, slots=True)
class ResultsReportPlan:
    """Teacher-reviewed report intent before any renderer writes an artifact."""

    snapshot: ResultsReportSnapshot
    output_format: ReportFormat

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot, ResultsReportSnapshot):
            raise TypeError("snapshot must be a ResultsReportSnapshot.")
        if self.output_format not in _REPORT_FORMATS:
            raise ValueError("Unsupported report format.")


@dataclass(frozen=True, slots=True)
class ConfirmedResultsReportPlan:
    """Explicitly confirmed immutable report intent; still performs no writes."""

    plan: ResultsReportPlan

    def __post_init__(self) -> None:
        if not isinstance(self.plan, ResultsReportPlan):
            raise TypeError("plan must be a ResultsReportPlan.")


def _validate_generated_timestamp(value: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ResultsReportingError(
            "generated_at must be canonical UTC ISO 8601 ending in Z."
        )
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise ResultsReportingError(
            "generated_at must be canonical UTC ISO 8601 ending in Z."
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ResultsReportingError("generated_at must be timezone-aware.")
    if _canonical_generated_at(parsed) != value:
        raise ResultsReportingError("generated_at is not canonical.")
    return value


def _canonical_generated_at(value: datetime) -> str:
    if not isinstance(value, datetime):
        raise ResultsReportingError("generated_at must be a datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ResultsReportingError("generated_at must be timezone-aware.")
    utc = value.astimezone(timezone.utc)
    return utc.isoformat(timespec="seconds").replace("+00:00", "Z")


def _question_number(value: object, *, question_count: int, label: str) -> int:
    if isinstance(value, bool):
        raise ResultsReportingError(f"{label} contains an invalid question number.")
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and value.isdigit() and str(int(value)) == value:
        number = int(value)
    else:
        raise ResultsReportingError(f"{label} contains an invalid question number.")
    if not 1 <= number <= question_count:
        raise ResultsReportingError(
            f"{label} contains an out-of-range question number."
        )
    return number


def _question_mapping(
    value: object,
    *,
    question_count: int,
    label: str,
) -> dict[int, object]:
    if not isinstance(value, Mapping):
        raise ResultsReportingError(f"{label} must be a question mapping.")
    normalized: dict[int, object] = {}
    for raw_question, item in value.items():
        number = _question_number(
            raw_question,
            question_count=question_count,
            label=label,
        )
        if number in normalized:
            raise ResultsReportingError(
                f"{label} contains duplicate normalized question {number}."
            )
        normalized[number] = item
    return normalized


def snapshot_assignment_for_report(
    assignment: Mapping[str, object],
) -> AssignmentReportSnapshot:
    """Copy current managed-assignment interpretation data into immutable tuples."""
    if not isinstance(assignment, Mapping):
        raise ResultsReportingError("assignment must be a validated mapping.")

    assignment_id = assignment.get("assignment_id")
    title = assignment.get("title")
    question_count = assignment.get("question_count")
    choices = assignment.get("choices")

    if not isinstance(assignment_id, str) or not assignment_id:
        raise ResultsReportingError("assignment_id must be a nonempty string.")
    if not isinstance(title, str) or not title:
        raise ResultsReportingError("assignment title must be a nonempty string.")
    if (
        isinstance(question_count, bool)
        or not isinstance(question_count, int)
        or question_count < 1
    ):
        raise ResultsReportingError("question_count must be a positive integer.")
    if (
        not isinstance(choices, (list, tuple))
        or not choices
        or any(not isinstance(choice, str) or not choice for choice in choices)
        or len(set(choices)) != len(choices)
    ):
        raise ResultsReportingError("choices must be unique nonempty strings.")
    choice_tuple = tuple(choices)

    answer_mapping = _question_mapping(
        assignment.get("answer_key"),
        question_count=question_count,
        label="answer_key",
    )
    if set(answer_mapping) != set(range(1, question_count + 1)):
        raise ResultsReportingError(
            "answer_key must cover every assignment question."
        )
    answer_key: list[str] = []
    for number in range(1, question_count + 1):
        answer = answer_mapping[number]
        if not isinstance(answer, str) or answer not in choice_tuple:
            raise ResultsReportingError(
                f"answer_key for question {number} is incompatible with choices."
            )
        answer_key.append(answer)

    standards_mapping = _question_mapping(
        assignment.get("standards", {}),
        question_count=question_count,
        label="standards",
    )
    standards_by_question: list[tuple[str, ...]] = []
    for number in range(1, question_count + 1):
        raw = standards_mapping.get(number, ())
        if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
            raise ResultsReportingError(
                f"standards for question {number} must be a sequence."
            )
        standards = tuple(raw)
        if any(
            not isinstance(standard_id, str) or not standard_id
            for standard_id in standards
        ):
            raise ResultsReportingError(
                f"standards for question {number} contain invalid IDs."
            )
        if len(set(standards)) != len(standards):
            raise ResultsReportingError(
                f"standards for question {number} contain duplicate IDs."
            )
        standards_by_question.append(standards)

    profile_id = assignment.get("standards_profile_id")
    if profile_id is not None and (
        not isinstance(profile_id, str) or not profile_id
    ):
        raise ResultsReportingError(
            "standards_profile_id must be a nonempty string when present."
        )

    return AssignmentReportSnapshot(
        assignment_id=assignment_id,
        title=title,
        question_count=question_count,
        choices=choice_tuple,
        answer_key=tuple(answer_key),
        standards_profile_id=profile_id,
        standards_by_question=tuple(standards_by_question),
    )


def prepare_class_analysis_snapshot(
    rows: Sequence[ScoreFormRoutedResultHistoryRow],
    assignment: Mapping[str, object],
    *,
    class_id: str,
    generated_at: datetime,
) -> ResultsReportSnapshot:
    """Freeze one class-analysis report snapshot without writing any files."""
    assignment_snapshot = snapshot_assignment_for_report(assignment)
    try:
        analysis = analyze_class_results(rows, assignment, class_id=class_id)
    except ResultsAnalysisError as error:
        raise ResultsReportingError(str(error)) from error

    return ResultsReportSnapshot(
        schema_version=RESULTS_ANALYSIS_REPORT_SCHEMA,
        generated_at=_canonical_generated_at(generated_at),
        scope="class_analysis",
        class_id=class_id,
        assignment=assignment_snapshot,
        class_analysis=analysis,
        student_detail=None,
        include_individual_response_rows=False,
        basis_statements=(
            REPORT_BASIS_STATEMENT,
            CLASS_ATTEMPT_BASIS_STATEMENT,
            STANDARDS_BASIS_STATEMENT,
        ),
    )


def prepare_student_detail_snapshot(
    rows: Sequence[ScoreFormRoutedResultHistoryRow],
    assignment: Mapping[str, object],
    *,
    class_id: str,
    student_id: str,
    attempt_number: int,
    generated_at: datetime,
) -> ResultsReportSnapshot:
    """Freeze one exact student-attempt report snapshot without writing files."""
    if not isinstance(student_id, str) or not student_id:
        raise ResultsReportingError("student_id must be a nonempty string.")
    if (
        isinstance(attempt_number, bool)
        or not isinstance(attempt_number, int)
        or attempt_number < 1
    ):
        raise ResultsReportingError("attempt_number must be a positive integer.")

    assignment_snapshot = snapshot_assignment_for_report(assignment)
    try:
        attempts = select_student_attempts(rows, student_id)
    except ResultsAnalysisError as error:
        raise ResultsReportingError(str(error)) from error
    matching = tuple(
        row for row in attempts if row.attempt_number == attempt_number
    )
    if len(matching) != 1:
        raise ResultsReportingError(
            "Selected student attempt must resolve to exactly one preserved row."
        )

    try:
        detail = analyze_student_attempt(
            matching[0],
            assignment,
            class_id=class_id,
            attempt_count=len(attempts),
        )
    except ResultsAnalysisError as error:
        raise ResultsReportingError(str(error)) from error

    return ResultsReportSnapshot(
        schema_version=RESULTS_ANALYSIS_REPORT_SCHEMA,
        generated_at=_canonical_generated_at(generated_at),
        scope="student_detail",
        class_id=class_id,
        assignment=assignment_snapshot,
        class_analysis=None,
        student_detail=detail,
        include_individual_response_rows=True,
        basis_statements=(
            REPORT_BASIS_STATEMENT,
            STANDARDS_BASIS_STATEMENT,
        ),
    )


def prepare_results_report_snapshot(
    rows: Sequence[ScoreFormRoutedResultHistoryRow],
    assignment: Mapping[str, object],
    *,
    class_id: str,
    scope: ReportScope,
    generated_at: datetime,
    student_id: str | None = None,
    attempt_number: int | None = None,
) -> ResultsReportSnapshot:
    """Prepare exactly one explicit report scope from canonical in-memory inputs."""
    if scope == "class_analysis":
        if student_id is not None or attempt_number is not None:
            raise ResultsReportingError(
                "Class Analysis scope does not accept student attempt selection."
            )
        return prepare_class_analysis_snapshot(
            rows,
            assignment,
            class_id=class_id,
            generated_at=generated_at,
        )
    if scope == "student_detail":
        if student_id is None or attempt_number is None:
            raise ResultsReportingError(
                "Student Detail scope requires student_id and attempt_number."
            )
        return prepare_student_detail_snapshot(
            rows,
            assignment,
            class_id=class_id,
            student_id=student_id,
            attempt_number=attempt_number,
            generated_at=generated_at,
        )
    raise ResultsReportingError("Unsupported report scope.")


def prepare_results_report_plan(
    snapshot: ResultsReportSnapshot,
    *,
    output_format: ReportFormat,
) -> ResultsReportPlan:
    """Attach an explicit output format without performing any filesystem work."""
    if output_format not in _REPORT_FORMATS:
        raise ResultsReportingError("Unsupported report format.")
    return ResultsReportPlan(snapshot=snapshot, output_format=output_format)


def format_results_report_preview(plan: ResultsReportPlan) -> str:
    """Return teacher-facing scope confirmation text without writing anything."""
    if not isinstance(plan, ResultsReportPlan):
        raise ResultsReportingError("plan must be a ResultsReportPlan.")

    snapshot = plan.snapshot
    assignment = snapshot.assignment
    lines = [
        "Export Results Report",
        "",
        f"Class: {snapshot.class_id}",
        f"Assignment: {assignment.assignment_id} - {assignment.title}",
    ]

    if snapshot.scope == "class_analysis":
        assert snapshot.class_analysis is not None
        lines.extend(
            [
                "Scope: Class Analysis",
                f"Attempt basis: {snapshot.class_analysis.attempt_basis}",
                (
                    "Students represented: "
                    f"{snapshot.class_analysis.students_represented}"
                ),
                "Includes individual response rows: No",
            ]
        )
    else:
        assert snapshot.student_detail is not None
        detail = snapshot.student_detail
        lines.extend(
            [
                "Scope: Student Detail",
                f"Student: {detail.name or '(name unavailable)'} ({detail.student_id})",
                f"Attempt: {detail.attempt_number} of {detail.attempt_count}",
                "Includes student identity: Yes",
                "Includes individual response rows: Yes",
            ]
        )

    lines.extend(
        [
            f"Format: {plan.output_format.upper()}",
            f"Generated timestamp: {snapshot.generated_at}",
            "",
            f"Type {REPORT_CONFIRMATION_TOKEN} to create the report.",
        ]
    )
    return "\n".join(lines)


def confirm_results_report_plan(
    plan: ResultsReportPlan,
    confirmation: str,
) -> ConfirmedResultsReportPlan | None:
    """Return a confirmed immutable plan only for the exact teacher token."""
    if not isinstance(plan, ResultsReportPlan):
        raise ResultsReportingError("plan must be a ResultsReportPlan.")
    if not isinstance(confirmation, str):
        raise ResultsReportingError("confirmation must be a string.")
    if confirmation != REPORT_CONFIRMATION_TOKEN:
        return None
    return ConfirmedResultsReportPlan(plan)
