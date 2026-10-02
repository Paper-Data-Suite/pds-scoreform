"""Pure read-only descriptive analysis for strict ScoreForm result history."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from scoreform.results import ScoreFormRoutedResultHistoryRow

ATTEMPT_DISPLAY_BASIS = "most recent scored attempt per student for display"
STANDARDS_ALIGNMENT_BASIS = "current assignment alignment"
PERCENT_ROUNDING_RULE = "nearest whole percent, halves rounded up"

_SPECIAL_RESPONSES = ("BLANK", "AMBIGUOUS")
QuestionOutcome = Literal["correct", "incorrect", "blank", "ambiguous"]


class ResultsAnalysisError(ValueError):
    """Raised when validated result history and assignment inputs are incompatible."""


@dataclass(frozen=True, slots=True)
class DisplayAttemptSelection:
    """One student's most-recent display attempt plus preserved attempt count."""

    student_id: str
    row: ScoreFormRoutedResultHistoryRow
    attempt_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.student_id, str) or not self.student_id:
            raise ValueError("student_id must be a nonempty string.")
        if not isinstance(self.row, ScoreFormRoutedResultHistoryRow):
            raise TypeError("row must be a ScoreFormRoutedResultHistoryRow.")
        if self.row.result.student_id != self.student_id:
            raise ValueError("selection student_id must match the selected row.")
        if (
            isinstance(self.attempt_count, bool)
            or not isinstance(self.attempt_count, int)
            or self.attempt_count < 1
        ):
            raise ValueError("attempt_count must be a positive integer.")


@dataclass(frozen=True, slots=True)
class ResponseCount:
    response: str
    count: int
    is_keyed_answer: bool

    def __post_init__(self) -> None:
        if not isinstance(self.response, str) or not self.response:
            raise ValueError("response must be a nonempty string.")
        if isinstance(self.count, bool) or not isinstance(self.count, int) or self.count < 0:
            raise ValueError("count must be a nonnegative integer.")
        if not isinstance(self.is_keyed_answer, bool):
            raise TypeError("is_keyed_answer must be Boolean.")


@dataclass(frozen=True, slots=True)
class QuestionDetail:
    question_number: int
    selected_answer: str
    keyed_answer: str
    outcome: QuestionOutcome
    correct: bool
    standard_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            isinstance(self.question_number, bool)
            or not isinstance(self.question_number, int)
            or self.question_number < 1
        ):
            raise ValueError("question_number must be a positive integer.")
        if not isinstance(self.selected_answer, str) or not self.selected_answer:
            raise ValueError("selected_answer must be a nonempty string.")
        if not isinstance(self.keyed_answer, str) or not self.keyed_answer:
            raise ValueError("keyed_answer must be a nonempty string.")
        if self.outcome not in {"correct", "incorrect", "blank", "ambiguous"}:
            raise ValueError("outcome is unsupported.")
        if not isinstance(self.correct, bool):
            raise TypeError("correct must be Boolean.")
        if not isinstance(self.standard_ids, tuple) or any(
            not isinstance(value, str) or not value for value in self.standard_ids
        ):
            raise TypeError("standard_ids must contain nonempty strings.")
        if len(set(self.standard_ids)) != len(self.standard_ids):
            raise ValueError("standard_ids must not repeat.")
        if self.correct != (self.outcome == "correct"):
            raise ValueError("correct must agree with outcome.")


@dataclass(frozen=True, slots=True)
class PerformanceSummary:
    """Raw descriptive correct/response counts with contributing questions."""

    correct: int
    responses: int
    question_numbers: tuple[int, ...]

    def __post_init__(self) -> None:
        for name, value in (("correct", self.correct), ("responses", self.responses)):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a nonnegative integer.")
        if self.correct > self.responses:
            raise ValueError("correct must not exceed responses.")
        if not isinstance(self.question_numbers, tuple) or any(
            isinstance(number, bool)
            or not isinstance(number, int)
            or number < 1
            for number in self.question_numbers
        ):
            raise TypeError("question_numbers must contain positive integers.")
        if tuple(sorted(set(self.question_numbers))) != self.question_numbers:
            raise ValueError("question_numbers must be unique and sorted.")

    @property
    def percent_correct(self) -> int | None:
        return rounded_percent(self.correct, self.responses)


@dataclass(frozen=True, slots=True)
class StandardPerformance:
    standard_id: str
    correct: int
    responses: int
    question_numbers: tuple[int, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.standard_id, str) or not self.standard_id:
            raise ValueError("standard_id must be a nonempty string.")
        PerformanceSummary(
            self.correct,
            self.responses,
            self.question_numbers,
        )

    @property
    def percent_correct(self) -> int | None:
        return rounded_percent(self.correct, self.responses)


@dataclass(frozen=True, slots=True)
class StudentAttemptAnalysis:
    class_id: str
    assignment_id: str
    student_id: str
    last_name: str
    first_name: str
    period: str
    attempt_number: int
    attempt_count: int
    recorded_at: str
    score: int
    total_points: int
    questions: tuple[QuestionDetail, ...]
    standards: tuple[StandardPerformance, ...]
    unaligned: PerformanceSummary

    def __post_init__(self) -> None:
        for name in ("class_id", "assignment_id", "student_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must be a nonempty string.")
        for name in ("last_name", "first_name", "period", "recorded_at"):
            if not isinstance(getattr(self, name), str):
                raise TypeError(f"{name} must be a string.")
        for name, value in (
            ("attempt_number", self.attempt_number),
            ("attempt_count", self.attempt_count),
            ("total_points", self.total_points),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer.")
        if isinstance(self.score, bool) or not isinstance(self.score, int):
            raise TypeError("score must be an integer.")
        if not 0 <= self.score <= self.total_points:
            raise ValueError("score is out of range.")
        if len(self.questions) != self.total_points:
            raise ValueError("questions must cover the complete attempt.")
        if tuple(question.question_number for question in self.questions) != tuple(
            range(1, self.total_points + 1)
        ):
            raise ValueError("questions must be in exact assignment order.")
        if self.score != sum(question.correct for question in self.questions):
            raise ValueError("score must agree with question correctness.")
        if tuple(sorted(item.standard_id for item in self.standards)) != tuple(
            item.standard_id for item in self.standards
        ):
            raise ValueError("standards must use deterministic ID ordering.")

    @property
    def name(self) -> str:
        return ", ".join(
            value for value in (self.last_name, self.first_name) if value
        )


@dataclass(frozen=True, slots=True)
class QuestionAnalysis:
    question_number: int
    keyed_answer: str
    correct: int
    incorrect: int
    blank: int
    ambiguous: int
    response_distribution: tuple[ResponseCount, ...]

    def __post_init__(self) -> None:
        if (
            isinstance(self.question_number, bool)
            or not isinstance(self.question_number, int)
            or self.question_number < 1
        ):
            raise ValueError("question_number must be a positive integer.")
        if not isinstance(self.keyed_answer, str) or not self.keyed_answer:
            raise ValueError("keyed_answer must be a nonempty string.")
        for name in ("correct", "incorrect", "blank", "ambiguous"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a nonnegative integer.")
        if not isinstance(self.response_distribution, tuple):
            raise TypeError("response_distribution must be a tuple.")
        if sum(item.count for item in self.response_distribution) != self.total:
            raise ValueError("response distribution must reconcile to total.")

    @property
    def total(self) -> int:
        return self.correct + self.incorrect + self.blank + self.ambiguous

    @property
    def percent_correct(self) -> int | None:
        return rounded_percent(self.correct, self.total)


@dataclass(frozen=True, slots=True)
class ClassResultsAnalysis:
    class_id: str
    assignment_id: str
    choices: tuple[str, ...]
    attempt_basis: str
    standards_basis: str
    students: tuple[StudentAttemptAnalysis, ...]
    questions: tuple[QuestionAnalysis, ...]
    standards: tuple[StandardPerformance, ...]
    unaligned: PerformanceSummary

    def __post_init__(self) -> None:
        if not isinstance(self.class_id, str) or not self.class_id:
            raise ValueError("class_id must be a nonempty string.")
        if not isinstance(self.assignment_id, str) or not self.assignment_id:
            raise ValueError("assignment_id must be a nonempty string.")
        if not isinstance(self.choices, tuple) or not self.choices:
            raise ValueError("choices must be a nonempty tuple.")
        if self.attempt_basis != ATTEMPT_DISPLAY_BASIS:
            raise ValueError("attempt_basis does not match the display contract.")
        if self.standards_basis != STANDARDS_ALIGNMENT_BASIS:
            raise ValueError("standards_basis does not match the analysis contract.")
        if tuple(student.student_id.lower() for student in self.students) != tuple(
            sorted(student.student_id.lower() for student in self.students)
        ):
            raise ValueError("students must use deterministic student-ID ordering.")
        expected_questions = tuple(range(1, len(self.questions) + 1))
        if tuple(item.question_number for item in self.questions) != expected_questions:
            raise ValueError("questions must use exact assignment ordering.")
        if tuple(item.standard_id for item in self.standards) != tuple(
            sorted(item.standard_id for item in self.standards)
        ):
            raise ValueError("standards must use deterministic ID ordering.")

    @property
    def students_represented(self) -> int:
        return len(self.students)


@dataclass(frozen=True, slots=True)
class _AssignmentContext:
    assignment_id: str
    question_count: int
    choices: tuple[str, ...]
    answer_key: tuple[str, ...]
    standards_by_question: tuple[tuple[str, ...], ...]


def rounded_percent(correct: int, responses: int) -> int | None:
    """Return nearest whole percent using deterministic half-up rounding."""
    for name, value in (("correct", correct), ("responses", responses)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ResultsAnalysisError(f"{name} must be a nonnegative integer.")
    if correct > responses:
        raise ResultsAnalysisError("correct must not exceed responses.")
    if responses == 0:
        return None
    whole, remainder = divmod(correct * 100, responses)
    if remainder * 2 >= responses:
        whole += 1
    return whole


def _row_sort_key(row: ScoreFormRoutedResultHistoryRow) -> tuple[datetime, int]:
    return datetime.fromisoformat(row.scan_timestamp), row.attempt_number


def _require_history_rows(
    rows: Sequence[ScoreFormRoutedResultHistoryRow],
) -> tuple[ScoreFormRoutedResultHistoryRow, ...]:
    materialized = tuple(rows)
    if any(not isinstance(row, ScoreFormRoutedResultHistoryRow) for row in materialized):
        raise ResultsAnalysisError(
            "Results analysis requires rows from the strict history loader."
        )
    return materialized


def select_recent_display_attempts(
    rows: Sequence[ScoreFormRoutedResultHistoryRow],
) -> tuple[DisplayAttemptSelection, ...]:
    """Select exactly the existing overview's most-recent display row per student."""
    materialized = _require_history_rows(rows)
    grouped: dict[str, list[ScoreFormRoutedResultHistoryRow]] = {}
    for row in materialized:
        grouped.setdefault(row.result.student_id, []).append(row)

    selections: list[DisplayAttemptSelection] = []
    for student_id in sorted(grouped, key=str.lower):
        attempts = grouped[student_id]
        recent = max(attempts, key=_row_sort_key)
        selections.append(
            DisplayAttemptSelection(
                student_id=student_id,
                row=recent,
                attempt_count=len(attempts),
            )
        )
    return tuple(selections)


def select_student_attempts(
    rows: Sequence[ScoreFormRoutedResultHistoryRow],
    student_id: str,
) -> tuple[ScoreFormRoutedResultHistoryRow, ...]:
    """Return every preserved attempt for one student in chronological display order."""
    if not isinstance(student_id, str) or not student_id:
        raise ResultsAnalysisError("student_id must be a nonempty string.")
    materialized = _require_history_rows(rows)
    selected = tuple(row for row in materialized if row.result.student_id == student_id)
    return tuple(sorted(selected, key=_row_sort_key))


def _question_key(value: object, *, question_count: int, label: str) -> int:
    if isinstance(value, bool):
        raise ResultsAnalysisError(f"{label} contains an invalid question number.")
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and value.isdigit() and str(int(value)) == value:
        number = int(value)
    else:
        raise ResultsAnalysisError(f"{label} contains an invalid question number.")
    if number < 1 or number > question_count:
        raise ResultsAnalysisError(f"{label} contains an out-of-range question number.")
    return number


def _normalize_question_mapping(
    value: object,
    *,
    question_count: int,
    label: str,
) -> dict[int, object]:
    if not isinstance(value, Mapping):
        raise ResultsAnalysisError(f"{label} must be a question mapping.")
    normalized: dict[int, object] = {}
    for raw_key, item in value.items():
        number = _question_key(raw_key, question_count=question_count, label=label)
        if number in normalized:
            raise ResultsAnalysisError(
                f"{label} contains duplicate normalized question {number}."
            )
        normalized[number] = item
    return normalized


def _assignment_context(assignment: Mapping[str, object]) -> _AssignmentContext:
    if not isinstance(assignment, Mapping):
        raise ResultsAnalysisError("assignment must be a validated mapping.")

    assignment_id = assignment.get("assignment_id")
    question_count = assignment.get("question_count")
    choices = assignment.get("choices")

    if not isinstance(assignment_id, str) or not assignment_id:
        raise ResultsAnalysisError("assignment_id must be a nonempty string.")
    if (
        isinstance(question_count, bool)
        or not isinstance(question_count, int)
        or question_count < 1
    ):
        raise ResultsAnalysisError("question_count must be a positive integer.")
    if (
        not isinstance(choices, (list, tuple))
        or not choices
        or any(not isinstance(choice, str) or not choice for choice in choices)
        or len(set(choices)) != len(choices)
    ):
        raise ResultsAnalysisError("choices must be unique nonempty strings.")
    choice_tuple = tuple(choices)

    answer_values = _normalize_question_mapping(
        assignment.get("answer_key"),
        question_count=question_count,
        label="answer_key",
    )
    if set(answer_values) != set(range(1, question_count + 1)):
        raise ResultsAnalysisError("answer_key must cover every assignment question.")
    answer_key: list[str] = []
    for number in range(1, question_count + 1):
        answer = answer_values[number]
        if not isinstance(answer, str) or answer not in choice_tuple:
            raise ResultsAnalysisError(
                f"answer_key for question {number} is incompatible with choices."
            )
        answer_key.append(answer)

    raw_standards = assignment.get("standards", {})
    standard_values = _normalize_question_mapping(
        raw_standards,
        question_count=question_count,
        label="standards",
    )
    standards_by_question: list[tuple[str, ...]] = []
    for number in range(1, question_count + 1):
        raw = standard_values.get(number, ())
        if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
            raise ResultsAnalysisError(
                f"standards for question {number} must be a sequence."
            )
        standards = tuple(raw)
        if any(not isinstance(value, str) or not value for value in standards):
            raise ResultsAnalysisError(
                f"standards for question {number} contain invalid IDs."
            )
        if len(set(standards)) != len(standards):
            raise ResultsAnalysisError(
                f"standards for question {number} contain duplicate IDs."
            )
        standards_by_question.append(standards)

    return _AssignmentContext(
        assignment_id=assignment_id,
        question_count=question_count,
        choices=choice_tuple,
        answer_key=tuple(answer_key),
        standards_by_question=tuple(standards_by_question),
    )


def _question_outcome(selected_answer: str, correct: bool) -> QuestionOutcome:
    if selected_answer == "BLANK":
        if correct:
            raise ResultsAnalysisError("A BLANK response cannot be marked correct.")
        return "blank"
    if selected_answer == "AMBIGUOUS":
        if correct:
            raise ResultsAnalysisError("An AMBIGUOUS response cannot be marked correct.")
        return "ambiguous"
    return "correct" if correct else "incorrect"


def _validate_row_for_analysis(
    row: ScoreFormRoutedResultHistoryRow,
    *,
    context: _AssignmentContext,
    class_id: str,
) -> None:
    result = row.result
    if result.class_id != class_id:
        raise ResultsAnalysisError(
            "Result class identity does not match the selected class."
        )
    if result.assignment_id != context.assignment_id:
        raise ResultsAnalysisError(
            "Result assignment identity does not match the selected assignment."
        )
    if result.total_points != context.question_count:
        raise ResultsAnalysisError(
            "Result question count is incompatible with the selected assignment."
        )
    if len(result.answers) != context.question_count:
        raise ResultsAnalysisError(
            "Result answers do not cover the selected assignment."
        )
    allowed = set(context.choices) | set(_SPECIAL_RESPONSES)
    for answer in result.answers:
        if answer.selected_answer not in allowed:
            raise ResultsAnalysisError(
                f"Q{answer.question_number} response is incompatible with assignment choices."
            )
        _question_outcome(answer.selected_answer, answer.correct)


def _standards_question_map(
    context: _AssignmentContext,
) -> dict[str, tuple[int, ...]]:
    grouped: dict[str, list[int]] = {}
    for question_number, standard_ids in enumerate(
        context.standards_by_question,
        start=1,
    ):
        for standard_id in standard_ids:
            grouped.setdefault(standard_id, []).append(question_number)
    return {
        standard_id: tuple(question_numbers)
        for standard_id, question_numbers in grouped.items()
    }


def _student_analysis(
    row: ScoreFormRoutedResultHistoryRow,
    *,
    context: _AssignmentContext,
    class_id: str,
    attempt_count: int,
) -> StudentAttemptAnalysis:
    _validate_row_for_analysis(row, context=context, class_id=class_id)
    result = row.result

    questions = tuple(
        QuestionDetail(
            question_number=answer.question_number,
            selected_answer=answer.selected_answer,
            keyed_answer=context.answer_key[answer.question_number - 1],
            outcome=_question_outcome(answer.selected_answer, answer.correct),
            correct=answer.correct,
            standard_ids=context.standards_by_question[answer.question_number - 1],
        )
        for answer in result.answers
    )

    standard_questions = _standards_question_map(context)
    standards: list[StandardPerformance] = []
    for standard_id in sorted(standard_questions):
        question_numbers = standard_questions[standard_id]
        matching = tuple(
            question
            for question in questions
            if question.question_number in question_numbers
        )
        standards.append(
            StandardPerformance(
                standard_id=standard_id,
                correct=sum(question.correct for question in matching),
                responses=len(matching),
                question_numbers=question_numbers,
            )
        )

    unaligned_questions = tuple(
        question
        for question in questions
        if not question.standard_ids
    )
    unaligned = PerformanceSummary(
        correct=sum(question.correct for question in unaligned_questions),
        responses=len(unaligned_questions),
        question_numbers=tuple(
            question.question_number for question in unaligned_questions
        ),
    )

    return StudentAttemptAnalysis(
        class_id=result.class_id,
        assignment_id=result.assignment_id,
        student_id=result.student_id,
        last_name=result.last_name,
        first_name=result.first_name,
        period=result.period,
        attempt_number=row.attempt_number,
        attempt_count=attempt_count,
        recorded_at=row.scan_timestamp,
        score=result.score,
        total_points=result.total_points,
        questions=questions,
        standards=tuple(standards),
        unaligned=unaligned,
    )


def analyze_student_attempt(
    row: ScoreFormRoutedResultHistoryRow,
    assignment: Mapping[str, object],
    *,
    class_id: str,
    attempt_count: int = 1,
) -> StudentAttemptAnalysis:
    """Build the immutable descriptive model for one exact preserved attempt."""
    if not isinstance(row, ScoreFormRoutedResultHistoryRow):
        raise ResultsAnalysisError(
            "Student analysis requires a row from the strict history loader."
        )
    context = _assignment_context(assignment)
    return _student_analysis(
        row,
        context=context,
        class_id=class_id,
        attempt_count=attempt_count,
    )


def _question_analysis(
    students: tuple[StudentAttemptAnalysis, ...],
    context: _AssignmentContext,
) -> tuple[QuestionAnalysis, ...]:
    analyses: list[QuestionAnalysis] = []
    response_order = context.choices + _SPECIAL_RESPONSES

    for question_number in range(1, context.question_count + 1):
        details = tuple(
            student.questions[question_number - 1]
            for student in students
        )
        outcomes = Counter(detail.outcome for detail in details)
        responses = Counter(detail.selected_answer for detail in details)
        keyed_answer = context.answer_key[question_number - 1]
        distribution = tuple(
            ResponseCount(
                response=response,
                count=responses.get(response, 0),
                is_keyed_answer=response == keyed_answer,
            )
            for response in response_order
        )
        analyses.append(
            QuestionAnalysis(
                question_number=question_number,
                keyed_answer=keyed_answer,
                correct=outcomes.get("correct", 0),
                incorrect=outcomes.get("incorrect", 0),
                blank=outcomes.get("blank", 0),
                ambiguous=outcomes.get("ambiguous", 0),
                response_distribution=distribution,
            )
        )
    return tuple(analyses)


def _class_standards(
    students: tuple[StudentAttemptAnalysis, ...],
    context: _AssignmentContext,
) -> tuple[tuple[StandardPerformance, ...], PerformanceSummary]:
    standard_questions = _standards_question_map(context)
    standards: list[StandardPerformance] = []
    for standard_id in sorted(standard_questions):
        question_numbers = standard_questions[standard_id]
        contributing = tuple(
            student.questions[number - 1]
            for student in students
            for number in question_numbers
        )
        standards.append(
            StandardPerformance(
                standard_id=standard_id,
                correct=sum(question.correct for question in contributing),
                responses=len(contributing),
                question_numbers=question_numbers,
            )
        )

    unaligned_numbers = tuple(
        number
        for number, standard_ids in enumerate(context.standards_by_question, start=1)
        if not standard_ids
    )
    unaligned_questions = tuple(
        student.questions[number - 1]
        for student in students
        for number in unaligned_numbers
    )
    unaligned = PerformanceSummary(
        correct=sum(question.correct for question in unaligned_questions),
        responses=len(unaligned_questions),
        question_numbers=unaligned_numbers,
    )
    return tuple(standards), unaligned


def analyze_class_results(
    rows: Sequence[ScoreFormRoutedResultHistoryRow],
    assignment: Mapping[str, object],
    *,
    class_id: str,
) -> ClassResultsAnalysis:
    """Build one immutable class snapshot using the overview's display-attempt basis."""
    if not isinstance(class_id, str) or not class_id:
        raise ResultsAnalysisError("class_id must be a nonempty string.")

    context = _assignment_context(assignment)
    materialized = _require_history_rows(rows)
    for row in materialized:
        _validate_row_for_analysis(row, context=context, class_id=class_id)

    selections = select_recent_display_attempts(materialized)
    students = tuple(
        _student_analysis(
            selection.row,
            context=context,
            class_id=class_id,
            attempt_count=selection.attempt_count,
        )
        for selection in selections
    )
    questions = _question_analysis(students, context)
    standards, unaligned = _class_standards(students, context)

    return ClassResultsAnalysis(
        class_id=class_id,
        assignment_id=context.assignment_id,
        choices=context.choices,
        attempt_basis=ATTEMPT_DISPLAY_BASIS,
        standards_basis=STANDARDS_ALIGNMENT_BASIS,
        students=students,
        questions=questions,
        standards=standards,
        unaligned=unaligned,
    )
