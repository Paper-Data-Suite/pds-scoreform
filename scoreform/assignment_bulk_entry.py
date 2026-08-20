"""Pure bulk answer-key and standards-alignment parsing for ScoreForm.

The functions in this module do not read files, prompt, print, or mutate a workspace.
They normalize teacher-provided text/CSV/JSON into complete assignment-definition
values and return structured diagnostics for ordinary invalid input.
"""

from __future__ import annotations

import csv
import io
import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Generic, Literal, TypeVar

from pds_core.standards import (
    StandardsLibrary,
    StandardsValidationError,
    find_standards_profile,
    validate_profile_standard_selection,
)

from scoreform.config import MAX_ASSIGNMENT_QUESTION_COUNT

BulkSource = Literal[
    "answer-key-text",
    "answer-key-csv",
    "answer-key-json",
    "alignment-text",
    "alignment-csv",
    "alignment-json",
]

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class BulkInputDiagnostic:
    """One deterministic, teacher-presentable bulk-input problem."""

    source: BulkSource
    code: str
    message: str
    row: int | None = None
    field: str | None = None
    question: int | None = None
    selector: str | None = None


@dataclass(frozen=True, slots=True)
class BulkParseResult(Generic[T]):
    """A pure parsing result containing either a complete value or diagnostics."""

    value: T | None
    diagnostics: tuple[BulkInputDiagnostic, ...] = ()

    @property
    def ok(self) -> bool:
        return self.value is not None and not self.diagnostics


@dataclass(frozen=True, slots=True)
class BulkAnswerKey:
    """One complete normalized answer key ordered by ascending question number."""

    answers: tuple[str, ...]

    @property
    def question_count(self) -> int:
        return len(self.answers)

    def as_assignment_mapping(self) -> dict[str, str]:
        return {
            str(question_number): answer
            for question_number, answer in enumerate(self.answers, start=1)
        }


@dataclass(frozen=True, slots=True)
class BulkStandardsAlignment:
    """One complete normalized question-level standards alignment."""

    standards_profile_id: str | None
    by_question: tuple[tuple[str, ...], ...]

    @property
    def question_count(self) -> int:
        return len(self.by_question)

    @property
    def has_standards(self) -> bool:
        return any(self.by_question)

    def as_assignment_mapping(self) -> dict[str, list[str]]:
        return {
            str(question_number): list(standard_ids)
            for question_number, standard_ids in enumerate(
                self.by_question,
                start=1,
            )
        }


class _StrictJsonProblem(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _duplicate_json_key(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _StrictJsonProblem(
                "duplicate_json_key",
                f"JSON contains duplicate object key {key!r}.",
            )
        result[key] = value
    return result


def _reject_nonfinite_json(value: str) -> None:
    raise _StrictJsonProblem(
        "nonfinite_json_constant",
        f"JSON contains unsupported nonfinite constant {value!r}.",
    )


def _strict_json_object(
    data: str | bytes,
    *,
    source: BulkSource,
) -> BulkParseResult[dict[str, object]]:
    if isinstance(data, bytes):
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return BulkParseResult(
                None,
                (
                    BulkInputDiagnostic(
                        source,
                        "invalid_encoding",
                        "JSON input must be valid UTF-8.",
                    ),
                ),
            )
    elif isinstance(data, str):
        text = data
    else:
        return BulkParseResult(
            None,
            (
                BulkInputDiagnostic(
                    source,
                    "invalid_input_type",
                    "JSON input must be text or bytes.",
                ),
            ),
        )

    try:
        decoded = json.loads(
            text,
            object_pairs_hook=_duplicate_json_key,
            parse_constant=_reject_nonfinite_json,
        )
    except _StrictJsonProblem as error:
        return BulkParseResult(
            None,
            (BulkInputDiagnostic(source, error.code, str(error)),),
        )
    except (ValueError, RecursionError):
        return BulkParseResult(
            None,
            (
                BulkInputDiagnostic(
                    source,
                    "malformed_json",
                    "JSON input is malformed.",
                ),
            ),
        )

    if not isinstance(decoded, dict):
        return BulkParseResult(
            None,
            (
                BulkInputDiagnostic(
                    source,
                    "wrong_json_top_level",
                    "JSON input must contain one top-level object.",
                ),
            ),
        )
    return BulkParseResult(decoded)



def _order_row_diagnostics(
    diagnostics: Iterable[BulkInputDiagnostic],
) -> tuple[BulkInputDiagnostic, ...]:
    indexed = list(enumerate(diagnostics))
    indexed.sort(
        key=lambda item: (
            item[1].row is None,
            item[1].row if item[1].row is not None else 0,
            item[0],
        )
    )
    return tuple(diagnostic for _, diagnostic in indexed)

def _question_count_diagnostic(
    question_count: object,
    source: BulkSource,
) -> BulkInputDiagnostic | None:
    if (
        isinstance(question_count, bool)
        or not isinstance(question_count, int)
        or question_count < 1
        or question_count > MAX_ASSIGNMENT_QUESTION_COUNT
    ):
        return BulkInputDiagnostic(
            source,
            "invalid_question_count",
            "question_count must be an integer between 1 and "
            f"{MAX_ASSIGNMENT_QUESTION_COUNT}.",
            field="question_count",
        )
    return None


def _normalize_choices(
    choices: Sequence[str],
    source: BulkSource,
) -> tuple[tuple[str, ...] | None, tuple[BulkInputDiagnostic, ...]]:
    if isinstance(choices, (str, bytes)) or not isinstance(choices, Sequence):
        return None, (
            BulkInputDiagnostic(
                source,
                "invalid_choices",
                "choices must be a non-empty sequence of answer strings.",
                field="choices",
            ),
        )

    normalized: list[str] = []
    seen: set[str] = set()
    for value in choices:
        if not isinstance(value, str) or not value.strip():
            return None, (
                BulkInputDiagnostic(
                    source,
                    "invalid_choices",
                    "choices must contain non-empty strings only.",
                    field="choices",
                ),
            )
        choice = value.strip().upper()
        if choice in seen:
            return None, (
                BulkInputDiagnostic(
                    source,
                    "duplicate_choice",
                    f"choices contains duplicate value {choice!r}.",
                    field="choices",
                ),
            )
        seen.add(choice)
        normalized.append(choice)

    if not normalized:
        return None, (
            BulkInputDiagnostic(
                source,
                "invalid_choices",
                "choices must contain at least one answer value.",
                field="choices",
            ),
        )
    return tuple(normalized), ()


def _validate_answer_entries(
    entries: Iterable[tuple[int, object, int | None]],
    *,
    question_count: int,
    choices: tuple[str, ...],
    source: BulkSource,
) -> BulkParseResult[BulkAnswerKey]:
    diagnostics: list[BulkInputDiagnostic] = []
    answers: dict[int, str] = {}
    seen_questions: set[int] = set()
    valid_choices = set(choices)

    for question, raw_answer, row in entries:
        if question < 1 or question > question_count:
            diagnostics.append(
                BulkInputDiagnostic(
                    source,
                    "question_out_of_range",
                    f"Question {question} is outside the valid range 1-{question_count}.",
                    row=row,
                    field="question",
                    question=question,
                )
            )
            continue
        if question in seen_questions:
            diagnostics.append(
                BulkInputDiagnostic(
                    source,
                    "duplicate_question",
                    f"Question {question} is defined more than once.",
                    row=row,
                    field="question",
                    question=question,
                )
            )
            continue
        seen_questions.add(question)

        if not isinstance(raw_answer, str) or not raw_answer.strip():
            diagnostics.append(
                BulkInputDiagnostic(
                    source,
                    "blank_answer",
                    f"Question {question} has no answer.",
                    row=row,
                    field="answer",
                    question=question,
                )
            )
            continue

        answer = raw_answer.strip().upper()
        if answer not in valid_choices:
            diagnostics.append(
                BulkInputDiagnostic(
                    source,
                    "invalid_answer",
                    f"Question {question} answer {raw_answer!r} is not one of "
                    f"{', '.join(choices)}.",
                    row=row,
                    field="answer",
                    question=question,
                )
            )
            continue
        answers[question] = answer

    missing = [
        question
        for question in range(1, question_count + 1)
        if question not in seen_questions
    ]
    for question in missing:
        diagnostics.append(
            BulkInputDiagnostic(
                source,
                "missing_question",
                f"Question {question} is missing.",
                field="question",
                question=question,
            )
        )

    if diagnostics:
        return BulkParseResult(None, tuple(diagnostics))

    return BulkParseResult(
        BulkAnswerKey(tuple(answers[question] for question in range(1, question_count + 1)))
    )


def parse_answer_key_text(
    text: str,
    *,
    question_count: int,
    choices: Sequence[str],
) -> BulkParseResult[BulkAnswerKey]:
    """Parse one complete positional answer sequence from pasted text."""

    source: BulkSource = "answer-key-text"
    count_problem = _question_count_diagnostic(question_count, source)
    normalized_choices, choice_problems = _normalize_choices(choices, source)
    preflight = tuple(
        problem
        for problem in (count_problem, *choice_problems)
        if problem is not None
    )
    if preflight:
        return BulkParseResult(None, preflight)
    assert normalized_choices is not None

    if not isinstance(text, str):
        return BulkParseResult(
            None,
            (
                BulkInputDiagnostic(
                    source,
                    "invalid_input_type",
                    "Answer-key paste input must be text.",
                ),
            ),
        )

    diagnostics: list[BulkInputDiagnostic] = []
    tokens: list[str] = []
    if "," in text:
        raw_tokens = text.split(",")
        for index, raw in enumerate(raw_tokens, start=1):
            token = raw.strip()
            if not token:
                diagnostics.append(
                    BulkInputDiagnostic(
                        source,
                        "empty_answer_token",
                        f"Answer position {index} is empty.",
                        field="answer",
                        question=index if index <= question_count else None,
                    )
                )
            tokens.append(token)
    else:
        tokens = text.split()

    if len(tokens) < question_count:
        diagnostics.append(
            BulkInputDiagnostic(
                source,
                "too_few_answers",
                f"Expected {question_count} answers but received {len(tokens)}.",
                field="answer_key",
            )
        )
    elif len(tokens) > question_count:
        diagnostics.append(
            BulkInputDiagnostic(
                source,
                "too_many_answers",
                f"Expected {question_count} answers but received {len(tokens)}.",
                field="answer_key",
            )
        )

    valid_choices = set(normalized_choices)
    normalized_answers: list[str] = []
    for index, token in enumerate(tokens, start=1):
        if not token:
            continue
        answer = token.upper()
        if answer not in valid_choices:
            diagnostics.append(
                BulkInputDiagnostic(
                    source,
                    "invalid_answer",
                    f"Answer position {index} value {token!r} is not one of "
                    f"{', '.join(normalized_choices)}.",
                    field="answer",
                    question=index if index <= question_count else None,
                )
            )
        normalized_answers.append(answer)

    if diagnostics:
        return BulkParseResult(None, tuple(diagnostics))
    return BulkParseResult(BulkAnswerKey(tuple(normalized_answers)))


def _decode_csv_input(
    data: str | bytes,
    *,
    source: BulkSource,
) -> BulkParseResult[str]:
    if isinstance(data, str):
        return BulkParseResult(data.removeprefix("\ufeff"))
    if isinstance(data, bytes):
        try:
            return BulkParseResult(data.decode("utf-8-sig"))
        except UnicodeDecodeError:
            return BulkParseResult(
                None,
                (
                    BulkInputDiagnostic(
                        source,
                        "invalid_encoding",
                        "CSV input must be valid UTF-8.",
                    ),
                ),
            )
    return BulkParseResult(
        None,
        (
            BulkInputDiagnostic(
                source,
                "invalid_input_type",
                "CSV input must be text or bytes.",
            ),
        ),
    )


def _csv_rows(
    data: str | bytes,
    *,
    source: BulkSource,
    expected_header: tuple[str, str],
) -> BulkParseResult[list[tuple[int, dict[str, str]]]]:
    decoded = _decode_csv_input(data, source=source)
    if not decoded.ok:
        return BulkParseResult(None, decoded.diagnostics)
    assert decoded.value is not None

    try:
        rows = list(csv.reader(io.StringIO(decoded.value, newline=""), strict=True))
    except csv.Error as error:
        return BulkParseResult(
            None,
            (
                BulkInputDiagnostic(
                    source,
                    "malformed_csv",
                    f"CSV input is malformed: {error}.",
                ),
            ),
        )

    while rows and not any(cell.strip() for cell in rows[-1]):
        rows.pop()
    if not rows:
        return BulkParseResult(
            None,
            (
                BulkInputDiagnostic(
                    source,
                    "missing_header",
                    "CSV input is empty and has no header row.",
                    row=1,
                ),
            ),
        )

    header = [cell.strip() for cell in rows[0]]
    diagnostics: list[BulkInputDiagnostic] = []
    duplicate_headers = sorted({name for name in header if header.count(name) > 1 and name})
    for name in duplicate_headers:
        diagnostics.append(
            BulkInputDiagnostic(
                source,
                "duplicate_header",
                f"CSV header {name!r} appears more than once.",
                row=1,
                field=name,
            )
        )
    for required in expected_header:
        if required not in header:
            diagnostics.append(
                BulkInputDiagnostic(
                    source,
                    "missing_column",
                    f"CSV is missing required column {required!r}.",
                    row=1,
                    field=required,
                )
            )
    unexpected = [name for name in header if name not in expected_header]
    for name in unexpected:
        diagnostics.append(
            BulkInputDiagnostic(
                source,
                "unexpected_column",
                f"CSV contains unexpected column {name!r}.",
                row=1,
                field=name or None,
            )
        )
    if len(header) != len(expected_header):
        if not unexpected and not duplicate_headers:
            diagnostics.append(
                BulkInputDiagnostic(
                    source,
                    "wrong_column_count",
                    f"CSV header must be exactly {','.join(expected_header)}.",
                    row=1,
                )
            )
    if diagnostics:
        return BulkParseResult(None, tuple(diagnostics))

    normalized_rows: list[tuple[int, dict[str, str]]] = []
    for row_number, row in enumerate(rows[1:], start=2):
        if not any(cell.strip() for cell in row):
            continue
        if len(row) != len(expected_header):
            diagnostics.append(
                BulkInputDiagnostic(
                    source,
                    "wrong_column_count",
                    f"CSV row {row_number} has {len(row)} columns; expected "
                    f"{len(expected_header)}.",
                    row=row_number,
                )
            )
            continue
        normalized_rows.append(
            (row_number, dict(zip(expected_header, (cell.strip() for cell in row), strict=True)))
        )

    if diagnostics:
        return BulkParseResult(None, tuple(diagnostics))
    return BulkParseResult(normalized_rows)


def _parse_question_text(
    value: str,
    *,
    question_count: int,
    source: BulkSource,
    row: int,
) -> tuple[int | None, BulkInputDiagnostic | None]:
    if not value:
        return None, BulkInputDiagnostic(
            source,
            "blank_question",
            f"CSV row {row} has no question number.",
            row=row,
            field="question",
        )
    if not value.isdigit():
        return None, BulkInputDiagnostic(
            source,
            "invalid_question",
            f"CSV row {row} question {value!r} is not an integer.",
            row=row,
            field="question",
        )
    question = int(value)
    if question < 1 or question > question_count:
        return None, BulkInputDiagnostic(
            source,
            "question_out_of_range",
            f"Question {question} is outside the valid range 1-{question_count}.",
            row=row,
            field="question",
            question=question,
        )
    return question, None


def parse_answer_key_csv(
    data: str | bytes,
    *,
    question_count: int,
    choices: Sequence[str],
) -> BulkParseResult[BulkAnswerKey]:
    """Parse strict ``question,answer`` CSV into one complete answer key."""

    source: BulkSource = "answer-key-csv"
    count_problem = _question_count_diagnostic(question_count, source)
    normalized_choices, choice_problems = _normalize_choices(choices, source)
    preflight = tuple(
        problem
        for problem in (count_problem, *choice_problems)
        if problem is not None
    )
    if preflight:
        return BulkParseResult(None, preflight)
    assert normalized_choices is not None

    rows = _csv_rows(
        data,
        source=source,
        expected_header=("question", "answer"),
    )
    if not rows.ok:
        return BulkParseResult(None, rows.diagnostics)
    assert rows.value is not None

    entries: list[tuple[int, object, int | None]] = []
    diagnostics: list[BulkInputDiagnostic] = []
    for row_number, row in rows.value:
        question, problem = _parse_question_text(
            row["question"],
            question_count=question_count,
            source=source,
            row=row_number,
        )
        if problem is not None:
            diagnostics.append(problem)
            continue
        assert question is not None
        entries.append((question, row["answer"], row_number))

    validated = _validate_answer_entries(
        entries,
        question_count=question_count,
        choices=normalized_choices,
        source=source,
    )
    if diagnostics or validated.diagnostics:
        return BulkParseResult(
            None,
            _order_row_diagnostics(tuple(diagnostics) + validated.diagnostics),
        )
    return validated


def _json_question_number(
    key: object,
    *,
    question_count: int,
    source: BulkSource,
) -> tuple[int | None, BulkInputDiagnostic | None]:
    if not isinstance(key, str) or not key.isdigit():
        return None, BulkInputDiagnostic(
            source,
            "invalid_question_key",
            f"JSON question key {key!r} must be an integer string.",
            field="question",
        )
    question = int(key)
    if question < 1 or question > question_count:
        return None, BulkInputDiagnostic(
            source,
            "question_out_of_range",
            f"Question {question} is outside the valid range 1-{question_count}.",
            field="question",
            question=question,
        )
    return question, None


def parse_answer_key_json(
    data: str | bytes,
    *,
    question_count: int,
    choices: Sequence[str],
) -> BulkParseResult[BulkAnswerKey]:
    """Parse strict JSON question-to-answer mapping into a complete answer key."""

    source: BulkSource = "answer-key-json"
    count_problem = _question_count_diagnostic(question_count, source)
    normalized_choices, choice_problems = _normalize_choices(choices, source)
    preflight = tuple(
        problem
        for problem in (count_problem, *choice_problems)
        if problem is not None
    )
    if preflight:
        return BulkParseResult(None, preflight)
    assert normalized_choices is not None

    parsed = _strict_json_object(data, source=source)
    if not parsed.ok:
        return BulkParseResult(None, parsed.diagnostics)
    assert parsed.value is not None

    entries: list[tuple[int, object, int | None]] = []
    diagnostics: list[BulkInputDiagnostic] = []
    for key, value in parsed.value.items():
        question, problem = _json_question_number(
            key,
            question_count=question_count,
            source=source,
        )
        if problem is not None:
            diagnostics.append(problem)
            continue
        assert question is not None
        entries.append((question, value, None))

    validated = _validate_answer_entries(
        entries,
        question_count=question_count,
        choices=normalized_choices,
        source=source,
    )
    if diagnostics or validated.diagnostics:
        return BulkParseResult(None, tuple(diagnostics) + validated.diagnostics)
    return validated


_SELECTOR_ATOM = re.compile(r"^(\d+)(?:\s*-\s*(\d+))?$")


def _parse_selector(
    selector: str,
    *,
    question_count: int,
    source: BulkSource,
    row: int | None,
) -> tuple[tuple[int, ...], tuple[BulkInputDiagnostic, ...]]:
    diagnostics: list[BulkInputDiagnostic] = []
    selected: list[int] = []
    if not selector.strip():
        return (), (
            BulkInputDiagnostic(
                source,
                "empty_selector",
                "Question selector is empty.",
                row=row,
                field="question",
                selector=selector,
            ),
        )

    for raw_atom in selector.split(","):
        atom = raw_atom.strip()
        match = _SELECTOR_ATOM.fullmatch(atom)
        if match is None:
            diagnostics.append(
                BulkInputDiagnostic(
                    source,
                    "malformed_selector",
                    f"Question selector atom {atom!r} is malformed.",
                    row=row,
                    field="question",
                    selector=selector,
                )
            )
            continue
        start = int(match.group(1))
        end_text = match.group(2)
        end = start if end_text is None else int(end_text)
        if start < 1 or start > question_count:
            diagnostics.append(
                BulkInputDiagnostic(
                    source,
                    "question_out_of_range",
                    f"Question {start} is outside the valid range 1-{question_count}.",
                    row=row,
                    field="question",
                    question=start,
                    selector=selector,
                )
            )
            continue
        if end < 1 or end > question_count:
            diagnostics.append(
                BulkInputDiagnostic(
                    source,
                    "question_out_of_range",
                    f"Question {end} is outside the valid range 1-{question_count}.",
                    row=row,
                    field="question",
                    question=end,
                    selector=selector,
                )
            )
            continue
        if end < start:
            diagnostics.append(
                BulkInputDiagnostic(
                    source,
                    "reversed_range",
                    f"Question range {start}-{end} is reversed.",
                    row=row,
                    field="question",
                    selector=selector,
                )
            )
            continue
        for question in range(start, end + 1):
            if question in selected:
                diagnostics.append(
                    BulkInputDiagnostic(
                        source,
                        "duplicate_question_coverage",
                        f"Question {question} is covered more than once by selector "
                        f"{selector!r}.",
                        row=row,
                        field="question",
                        question=question,
                        selector=selector,
                    )
                )
                continue
            selected.append(question)

    return tuple(selected), tuple(diagnostics)


def _standard_tokens(
    value: object,
    *,
    source: BulkSource,
    row: int | None,
    question: int | None = None,
    separator: str = ",",
    blank_means_unaligned: bool = False,
) -> tuple[tuple[str, ...], tuple[BulkInputDiagnostic, ...]]:
    if not isinstance(value, str):
        return (), (
            BulkInputDiagnostic(
                source,
                "invalid_standard_list",
                "Standards must be provided as text IDs.",
                row=row,
                field="standards",
                question=question,
            ),
        )
    text = value.strip()
    if not text:
        if blank_means_unaligned:
            return (), ()
        return (), (
            BulkInputDiagnostic(
                source,
                "blank_standard_list",
                "Standards list is blank; use '-' or 'none' for explicit unaligned coverage.",
                row=row,
                field="standards",
                question=question,
            ),
        )
    if text == "-" or text.lower() == "none":
        return (), ()

    diagnostics: list[BulkInputDiagnostic] = []
    tokens: list[str] = []
    seen: set[str] = set()
    for raw in text.split(separator):
        standard_id = raw.strip()
        if not standard_id:
            diagnostics.append(
                BulkInputDiagnostic(
                    source,
                    "blank_standard_id",
                    "Standards list contains an empty standard ID.",
                    row=row,
                    field="standards",
                    question=question,
                )
            )
            continue
        if standard_id in seen:
            diagnostics.append(
                BulkInputDiagnostic(
                    source,
                    "duplicate_standard_id",
                    f"Standard ID {standard_id!r} is repeated.",
                    row=row,
                    field="standards",
                    question=question,
                )
            )
            continue
        seen.add(standard_id)
        tokens.append(standard_id)
    return tuple(tokens), tuple(diagnostics)


def _validate_profile_and_standard_ids(
    *,
    standards_profile_id: str | None,
    standards_library: StandardsLibrary | None,
    standard_occurrences: Iterable[
        tuple[str, int | None, int | None]
    ],  # standard_id, question, row
    source: BulkSource,
) -> tuple[BulkInputDiagnostic, ...]:
    occurrences = tuple(standard_occurrences)
    if not occurrences:
        if standards_profile_id is None:
            return ()
        if standards_library is None:
            return (
                BulkInputDiagnostic(
                    source,
                    "missing_standards_library",
                    "A current PDS Core standards library is required to validate the selected profile.",
                    field="standards_profile_id",
                ),
            )
        if find_standards_profile(standards_library, standards_profile_id) is None:
            return (
                BulkInputDiagnostic(
                    source,
                    "unknown_standards_profile",
                    f"Standards profile {standards_profile_id!r} does not exist in the current Core library.",
                    field="standards_profile_id",
                ),
            )
        return ()

    if not isinstance(standards_profile_id, str) or not standards_profile_id.strip():
        return (
            BulkInputDiagnostic(
                source,
                "missing_standards_profile",
                "A standards_profile_id is required when any question is aligned.",
                field="standards_profile_id",
            ),
        )
    profile_id = standards_profile_id.strip()
    if standards_library is None:
        return (
            BulkInputDiagnostic(
                source,
                "missing_standards_library",
                "A current PDS Core standards library is required for nonempty alignment.",
                field="standards_profile_id",
            ),
        )
    if find_standards_profile(standards_library, profile_id) is None:
        return (
            BulkInputDiagnostic(
                source,
                "unknown_standards_profile",
                f"Standards profile {profile_id!r} does not exist in the current Core library.",
                field="standards_profile_id",
            ),
        )

    diagnostics: list[BulkInputDiagnostic] = []
    seen_validation: set[tuple[str, int | None, int | None]] = set()
    for standard_id, question, row in occurrences:
        occurrence = (standard_id, question, row)
        if occurrence in seen_validation:
            continue
        seen_validation.add(occurrence)
        try:
            validate_profile_standard_selection(
                standards_library,
                profile_id=profile_id,
                selected_standard_ids=(standard_id,),
            )
        except StandardsValidationError as error:
            diagnostics.append(
                BulkInputDiagnostic(
                    source,
                    "invalid_standard_id",
                    f"Standard ID {standard_id!r} is not valid for profile "
                    f"{profile_id!r}: {error}",
                    row=row,
                    field="standards",
                    question=question,
                )
            )
    return tuple(diagnostics)


def _build_alignment(
    coverage: Iterable[
        tuple[tuple[int, ...], tuple[str, ...], int | None, str | None]
    ],
    *,
    question_count: int,
    standards_profile_id: str | None,
    standards_library: StandardsLibrary | None,
    source: BulkSource,
    initial_diagnostics: Iterable[BulkInputDiagnostic] = (),
) -> BulkParseResult[BulkStandardsAlignment]:
    diagnostics = list(initial_diagnostics)
    by_question: dict[int, tuple[str, ...]] = {}
    occurrences: list[tuple[str, int | None, int | None]] = []

    for questions, standard_ids, row, selector in coverage:
        for question in questions:
            if question in by_question:
                diagnostics.append(
                    BulkInputDiagnostic(
                        source,
                        "duplicate_question_coverage",
                        f"Question {question} is covered more than once.",
                        row=row,
                        field="question",
                        question=question,
                        selector=selector,
                    )
                )
                continue
            by_question[question] = standard_ids
            occurrences.extend((standard_id, question, row) for standard_id in standard_ids)

    for question in range(1, question_count + 1):
        if question not in by_question:
            diagnostics.append(
                BulkInputDiagnostic(
                    source,
                    "missing_question_coverage",
                    f"Question {question} has no explicit alignment coverage.",
                    field="question",
                    question=question,
                )
            )

    diagnostics.extend(
        _validate_profile_and_standard_ids(
            standards_profile_id=standards_profile_id,
            standards_library=standards_library,
            standard_occurrences=occurrences,
            source=source,
        )
    )
    if diagnostics:
        return BulkParseResult(None, tuple(diagnostics))

    normalized_profile = (
        standards_profile_id.strip()
        if isinstance(standards_profile_id, str) and standards_profile_id.strip()
        else None
    )
    return BulkParseResult(
        BulkStandardsAlignment(
            standards_profile_id=normalized_profile,
            by_question=tuple(by_question[question] for question in range(1, question_count + 1)),
        )
    )


def parse_alignment_text(
    text: str,
    *,
    question_count: int,
    standards_profile_id: str | None,
    standards_library: StandardsLibrary | None,
) -> BulkParseResult[BulkStandardsAlignment]:
    """Parse complete range-aware ``selector = standard-list`` alignment text."""

    source: BulkSource = "alignment-text"
    count_problem = _question_count_diagnostic(question_count, source)
    if count_problem is not None:
        return BulkParseResult(None, (count_problem,))
    if not isinstance(text, str):
        return BulkParseResult(
            None,
            (
                BulkInputDiagnostic(
                    source,
                    "invalid_input_type",
                    "Alignment paste input must be text.",
                ),
            ),
        )

    groups: list[tuple[int, str]] = []
    line_number = 0
    for line in text.splitlines() or [text]:
        line_number += 1
        for part in line.split(";"):
            stripped = part.strip()
            if stripped:
                groups.append((line_number, stripped))

    if not groups:
        return BulkParseResult(
            None,
            (
                BulkInputDiagnostic(
                    source,
                    "empty_input",
                    "Alignment paste input is empty.",
                ),
            ),
        )

    diagnostics: list[BulkInputDiagnostic] = []
    coverage: list[tuple[tuple[int, ...], tuple[str, ...], int | None, str | None]] = []
    for row, group in groups:
        if group.count("=") != 1:
            diagnostics.append(
                BulkInputDiagnostic(
                    source,
                    "malformed_alignment_group",
                    f"Alignment group {group!r} must contain exactly one '='.",
                    row=row,
                )
            )
            continue
        selector, raw_standards = (part.strip() for part in group.split("=", 1))
        questions, selector_diagnostics = _parse_selector(
            selector,
            question_count=question_count,
            source=source,
            row=row,
        )
        standard_ids, standard_diagnostics = _standard_tokens(
            raw_standards,
            source=source,
            row=row,
        )
        diagnostics.extend(selector_diagnostics)
        diagnostics.extend(standard_diagnostics)
        coverage.append((questions, standard_ids, row, selector))

    return _build_alignment(
        coverage,
        question_count=question_count,
        standards_profile_id=standards_profile_id,
        standards_library=standards_library,
        source=source,
        initial_diagnostics=diagnostics,
    )


def parse_alignment_csv(
    data: str | bytes,
    *,
    question_count: int,
    standards_profile_id: str | None,
    standards_library: StandardsLibrary | None,
) -> BulkParseResult[BulkStandardsAlignment]:
    """Parse strict ``question,standards`` CSV into complete alignment."""

    source: BulkSource = "alignment-csv"
    count_problem = _question_count_diagnostic(question_count, source)
    if count_problem is not None:
        return BulkParseResult(None, (count_problem,))

    rows = _csv_rows(
        data,
        source=source,
        expected_header=("question", "standards"),
    )
    if not rows.ok:
        return BulkParseResult(None, rows.diagnostics)
    assert rows.value is not None

    diagnostics: list[BulkInputDiagnostic] = []
    coverage: list[tuple[tuple[int, ...], tuple[str, ...], int | None, str | None]] = []
    for row_number, row in rows.value:
        question, problem = _parse_question_text(
            row["question"],
            question_count=question_count,
            source=source,
            row=row_number,
        )
        if problem is not None:
            diagnostics.append(problem)
            continue
        assert question is not None
        standard_ids, standard_diagnostics = _standard_tokens(
            row["standards"],
            source=source,
            row=row_number,
            question=question,
            separator=";",
            blank_means_unaligned=True,
        )
        diagnostics.extend(standard_diagnostics)
        coverage.append(((question,), standard_ids, row_number, row["question"]))

    return _build_alignment(
        coverage,
        question_count=question_count,
        standards_profile_id=standards_profile_id,
        standards_library=standards_library,
        source=source,
        initial_diagnostics=diagnostics,
    )


def parse_alignment_json(
    data: str | bytes,
    *,
    question_count: int,
    standards_profile_id: str | None,
    standards_library: StandardsLibrary | None,
) -> BulkParseResult[BulkStandardsAlignment]:
    """Parse strict JSON question-to-standard-ID-array mapping."""

    source: BulkSource = "alignment-json"
    count_problem = _question_count_diagnostic(question_count, source)
    if count_problem is not None:
        return BulkParseResult(None, (count_problem,))

    parsed = _strict_json_object(data, source=source)
    if not parsed.ok:
        return BulkParseResult(None, parsed.diagnostics)
    assert parsed.value is not None

    diagnostics: list[BulkInputDiagnostic] = []
    coverage: list[tuple[tuple[int, ...], tuple[str, ...], int | None, str | None]] = []
    for key, value in parsed.value.items():
        question, problem = _json_question_number(
            key,
            question_count=question_count,
            source=source,
        )
        if problem is not None:
            diagnostics.append(problem)
            continue
        assert question is not None
        if not isinstance(value, list):
            diagnostics.append(
                BulkInputDiagnostic(
                    source,
                    "wrong_alignment_value_type",
                    f"Question {question} alignment must be a JSON array of standard IDs.",
                    field="standards",
                    question=question,
                )
            )
            continue

        standard_ids: list[str] = []
        seen: set[str] = set()
        for item in value:
            if not isinstance(item, str) or not item.strip():
                diagnostics.append(
                    BulkInputDiagnostic(
                        source,
                        "invalid_standard_id_type",
                        f"Question {question} standards must contain non-empty strings only.",
                        field="standards",
                        question=question,
                    )
                )
                continue
            standard_id = item.strip()
            if standard_id in seen:
                diagnostics.append(
                    BulkInputDiagnostic(
                        source,
                        "duplicate_standard_id",
                        f"Question {question} repeats standard ID {standard_id!r}.",
                        field="standards",
                        question=question,
                    )
                )
                continue
            seen.add(standard_id)
            standard_ids.append(standard_id)
        coverage.append(((question,), tuple(standard_ids), None, key))

    return _build_alignment(
        coverage,
        question_count=question_count,
        standards_profile_id=standards_profile_id,
        standards_library=standards_library,
        source=source,
        initial_diagnostics=diagnostics,
    )


def format_bulk_diagnostic(diagnostic: BulkInputDiagnostic) -> str:
    """Render one structured diagnostic without exposing a traceback."""

    location: list[str] = []
    if diagnostic.row is not None:
        location.append(f"row {diagnostic.row}")
    if diagnostic.question is not None:
        location.append(f"Q{diagnostic.question}")
    if diagnostic.field is not None:
        location.append(diagnostic.field)
    prefix = f"[{' / '.join(location)}] " if location else ""
    return f"{prefix}{diagnostic.message}"


__all__ = [
    "BulkAnswerKey",
    "BulkInputDiagnostic",
    "BulkParseResult",
    "BulkStandardsAlignment",
    "format_bulk_diagnostic",
    "parse_alignment_csv",
    "parse_alignment_json",
    "parse_alignment_text",
    "parse_answer_key_csv",
    "parse_answer_key_json",
    "parse_answer_key_text",
]
