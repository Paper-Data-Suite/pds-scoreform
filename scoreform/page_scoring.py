"""Authoritative strict scoring for one immutable answer-sheet page."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from pds_core.identifiers import IdentifierValidationError, validate_identifier

from scoreform.answer_sheet_persistence import AnswerSheetPageContext
from scoreform.answer_sheet_records import (
    AnswerSheetRecordError,
    validate_answer_sheet_record_set,
    validate_artifact_id,
    validate_generation_id,
    validate_issuance_id,
    validate_page_id,
)
from scoreform.answer_sheet_routes import (
    AnswerSheetRouteValidationError,
    validate_route_id,
)
from scoreform.layouts import require_layout
from scoreform.module_errors import (
    ScoreFormAssignmentCompatibilityError,
    ScoreFormPageScoringError,
)
from scoreform.paging import page_count_for_question_count, question_range_for_page
from scoreform.retained_page import validate_canonical_retained_source_relative_path
from scoreform.scoring import score_image

_SPECIAL_ANSWERS = frozenset({"BLANK", "AMBIGUOUS"})
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class ScoredAnswer:
    question_number: int
    selected_answer: str
    correct: bool


@dataclass(frozen=True, slots=True)
class ScoreFormPageDispatchResult:
    route_id: str
    page_id: str
    issuance_id: str
    generation_id: str
    artifact_id: str
    class_id: str
    assignment_id: str
    student_id: str
    logical_page: int
    total_pages: int
    question_start: int
    question_end: int
    layout_id: str
    score: int
    total_points: int
    answers: tuple[ScoredAnswer, ...]
    source_scan_id: str
    source_page_number: int
    retained_source_relative_path: str
    source_sha256: str
    diagnostic_paths: tuple[str, ...]


def validate_assignment_page_compatibility(
    page_context: AnswerSheetPageContext,
    assignment: Mapping[str, object],
) -> None:
    """Require current scoring structure to match the issued physical form."""
    if not isinstance(page_context, AnswerSheetPageContext):
        raise ScoreFormAssignmentCompatibilityError(
            "page_context must be an AnswerSheetPageContext."
        )
    try:
        validate_answer_sheet_record_set(page_context.record_set)
    except AnswerSheetRecordError as error:
        raise ScoreFormAssignmentCompatibilityError(
            "Answer-sheet page and issuance context is invalid."
        ) from error
    if not isinstance(assignment, Mapping):
        raise ScoreFormAssignmentCompatibilityError(
            "Managed assignment must be a mapping."
        )
    page = page_context.page
    issuance = page_context.issuance
    required = {
        "assignment_id",
        "question_count",
        "layout_id",
        "choices",
        "answer_key",
    }
    if not required.issubset(assignment):
        raise ScoreFormAssignmentCompatibilityError(
            "Managed assignment is missing scoring-required fields."
        )
    assignment_id = assignment["assignment_id"]
    question_count = assignment["question_count"]
    layout_id = assignment["layout_id"]
    choices = assignment["choices"]
    answer_key = assignment["answer_key"]
    if assignment_id != page.assignment_id:
        raise ScoreFormAssignmentCompatibilityError(
            "Managed assignment identity does not match the routed work."
        )
    if isinstance(question_count, bool) or not isinstance(question_count, int):
        raise ScoreFormAssignmentCompatibilityError(
            "Managed assignment question_count must be an integer."
        )
    try:
        layout = require_layout(layout_id)
    except ValueError as error:
        raise ScoreFormAssignmentCompatibilityError(
            "Managed assignment layout is unsupported."
        ) from error
    if not isinstance(choices, (list, tuple)) or any(
        not isinstance(choice, str) for choice in choices
    ):
        raise ScoreFormAssignmentCompatibilityError(
            "Managed assignment choices must be a collection."
        )
    choice_tuple: tuple[str, ...] = tuple(choices)
    snapshot = issuance.assignment_snapshot
    if not (
        question_count
        == snapshot.question_count
        == page.assignment_question_count
    ):
        raise ScoreFormAssignmentCompatibilityError(
            "Managed, issued, and page question counts do not match."
        )
    if layout.layout_id != snapshot.layout_id or layout.layout_id != page.layout_id:
        raise ScoreFormAssignmentCompatibilityError(
            "Managed, issued, and page layouts do not match."
        )
    if choice_tuple != layout.choices or choice_tuple != snapshot.choices:
        raise ScoreFormAssignmentCompatibilityError(
            "Managed choices do not match the issued layout."
        )
    try:
        expected_pages = page_count_for_question_count(question_count, layout)
        expected_range = question_range_for_page(
            page.logical_page, question_count, layout
        )
    except ValueError as error:
        raise ScoreFormAssignmentCompatibilityError(
            "Physical page structure is invalid for the selected layout."
        ) from error
    if not (
        expected_pages
        == issuance.page_count
        == page.total_pages
        == len(issuance.page_ids)
    ):
        raise ScoreFormAssignmentCompatibilityError(
            "Physical page counts do not match the current assignment."
        )
    if expected_range != (page.question_start, page.question_end):
        raise ScoreFormAssignmentCompatibilityError(
            "Physical page question range does not match the current assignment."
        )
    if not isinstance(answer_key, Mapping):
        raise ScoreFormAssignmentCompatibilityError(
            "Managed assignment answer_key must be a mapping."
        )
    expected_questions = set(range(1, question_count + 1))
    if set(answer_key) != expected_questions or any(
        answer_key[number] not in layout.choices for number in expected_questions
    ):
        raise ScoreFormAssignmentCompatibilityError(
            "Managed assignment answer_key is incomplete or incompatible."
        )


def validate_page_dispatch_result(
    result: ScoreFormPageDispatchResult,
    *,
    valid_choices: tuple[str, ...],
) -> ScoreFormPageDispatchResult:
    """Validate and return one immutable strict page result."""
    if not isinstance(result, ScoreFormPageDispatchResult):
        raise ScoreFormPageScoringError(
            "Scoring service returned the wrong result model."
        )
    integer_fields = {
        "logical_page": result.logical_page,
        "total_pages": result.total_pages,
        "question_start": result.question_start,
        "question_end": result.question_end,
        "score": result.score,
        "total_points": result.total_points,
        "source_page_number": result.source_page_number,
    }
    for field_name, value in integer_fields.items():
        if isinstance(value, bool) or not isinstance(value, int):
            raise ScoreFormPageScoringError(
                f"Result {field_name} must be an integer, not a Boolean."
            )
    if result.logical_page < 1 or result.total_pages < 1:
        raise ScoreFormPageScoringError("Result page numbers must be positive.")
    if result.logical_page > result.total_pages:
        raise ScoreFormPageScoringError(
            "Result logical_page must not exceed total_pages."
        )
    if result.question_start < 1 or result.question_end < result.question_start:
        raise ScoreFormPageScoringError("Result question range is invalid.")
    if result.source_page_number < 1:
        raise ScoreFormPageScoringError(
            "Result source_page_number must be positive."
        )
    try:
        validate_route_id(result.route_id)
        validate_page_id(result.page_id)
        validate_issuance_id(result.issuance_id)
        validate_generation_id(result.generation_id)
        validate_artifact_id(result.artifact_id)
        validate_identifier(result.class_id, "class_id")
        validate_identifier(result.assignment_id, "assignment_id")
        validate_identifier(result.student_id, "student_id")
        validate_identifier(result.source_scan_id, "source_scan_id")
        layout = require_layout(result.layout_id)
    except (
        AnswerSheetRouteValidationError,
        AnswerSheetRecordError,
        IdentifierValidationError,
        TypeError,
        ValueError,
    ) as error:
        raise ScoreFormPageScoringError(
            "Result contains an invalid identity or layout."
        ) from error
    if tuple(valid_choices) != layout.choices:
        raise ScoreFormPageScoringError(
            "Result validation choices do not match its registered layout."
        )
    if not isinstance(result.source_sha256, str) or not _SHA256_PATTERN.fullmatch(
        result.source_sha256
    ):
        raise ScoreFormPageScoringError(
            "Result source_sha256 must be 64 lowercase hexadecimal characters."
        )
    try:
        validate_canonical_retained_source_relative_path(
            result.retained_source_relative_path
        )
    except (TypeError, ValueError) as error:
        raise ScoreFormPageScoringError(
            "Result retained_source_relative_path is not canonical."
        ) from error
    if not isinstance(result.answers, tuple) or any(
        not isinstance(answer, ScoredAnswer) for answer in result.answers
    ):
        raise ScoreFormPageScoringError("Result answers must be immutable models.")
    for answer in result.answers:
        if isinstance(answer.question_number, bool) or not isinstance(
            answer.question_number, int
        ):
            raise ScoreFormPageScoringError(
                "Result answer question_number must be an integer, not a Boolean."
            )
        if not isinstance(answer.selected_answer, str):
            raise ScoreFormPageScoringError(
                "Result selected answers must be strings."
            )
        if not isinstance(answer.correct, bool):
            raise ScoreFormPageScoringError(
                "Result answer correctness must be Boolean."
            )
    expected_numbers = tuple(range(result.question_start, result.question_end + 1))
    if result.total_points != len(expected_numbers):
        raise ScoreFormPageScoringError("Result total_points is inconsistent.")
    if tuple(answer.question_number for answer in result.answers) != expected_numbers:
        raise ScoreFormPageScoringError(
            "Result answers must cover the page range exactly in order."
        )
    allowed = frozenset(layout.choices) | _SPECIAL_ANSWERS
    if any(answer.selected_answer not in allowed for answer in result.answers):
        raise ScoreFormPageScoringError("Result contains an unsupported answer value.")
    if result.score < 0 or result.score > result.total_points:
        raise ScoreFormPageScoringError("Result score is outside its valid range.")
    if result.score != sum(answer.correct for answer in result.answers):
        raise ScoreFormPageScoringError("Result score is inconsistent with answers.")
    if not isinstance(result.diagnostic_paths, tuple):
        raise ScoreFormPageScoringError("Result diagnostic_paths must be immutable.")
    if any(
        not isinstance(path, str) or not path for path in result.diagnostic_paths
    ):
        raise ScoreFormPageScoringError(
            "Result diagnostic paths must be nonempty strings."
        )
    if len(set(result.diagnostic_paths)) != len(result.diagnostic_paths):
        raise ScoreFormPageScoringError("Result diagnostic paths must be unique.")
    return result


def score_authoritative_answer_sheet_page(
    image: np.ndarray,
    *,
    page_context: AnswerSheetPageContext,
    assignment: Mapping[str, object],
    route_id: str,
    source_scan_id: str,
    source_page_number: int,
    retained_source_relative_path: str,
    source_sha256: str,
    debug_dir: Path | None = None,
) -> ScoreFormPageDispatchResult:
    """Score exactly the authoritative page range using the current answer key."""
    if (
        not isinstance(image, np.ndarray)
        or image.size == 0
        or image.ndim != 3
        or image.shape[2] != 3
        or image.dtype != np.uint8
    ):
        raise ScoreFormPageScoringError(
            "image must be a nonempty uint8 OpenCV BGR array."
        )
    try:
        validate_route_id(route_id)
        validate_identifier(source_scan_id, "source_scan_id")
    except (
        AnswerSheetRouteValidationError,
        IdentifierValidationError,
        TypeError,
        ValueError,
    ) as error:
        raise ScoreFormPageScoringError(
            "Route or retained-source identity is invalid."
        ) from error
    if (
        isinstance(source_page_number, bool)
        or not isinstance(source_page_number, int)
        or source_page_number < 1
    ):
        raise ScoreFormPageScoringError(
            "source_page_number must be an integer greater than or equal to one."
        )
    if (
        not isinstance(retained_source_relative_path, str)
        or not retained_source_relative_path
        or not isinstance(source_sha256, str)
        or not _SHA256_PATTERN.fullmatch(source_sha256)
    ):
        raise ScoreFormPageScoringError("Retained-source provenance is invalid.")
    validate_assignment_page_compatibility(page_context, assignment)
    page = page_context.page
    layout = require_layout(page.layout_id)
    question_count = page.question_end - page.question_start + 1
    diagnostic_stem = (
        f"{source_scan_id}_source_{source_page_number}_{page.page_id}"
    )
    try:
        raw = score_image(
            image,
            assignment["answer_key"],
            page_num=source_page_number,
            debug_dir=None if debug_dir is None else str(debug_dir),
            question_count=question_count,
            question_start=page.question_start,
            layout=layout,
            diagnostic_stem=diagnostic_stem,
            write_diagnostics=debug_dir is not None,
            raise_on_failure=True,
        )
    except ScoreFormPageScoringError:
        raise
    except Exception as error:
        raise ScoreFormPageScoringError(
            "One-page OMR processing or diagnostic creation failed.",
            diagnostic_code="omr_processing_failed",
        ) from error
    if raw is None:
        raise ScoreFormPageScoringError(
            "Could not detect the four required registration marks.",
            diagnostic_code="registration_marks_missing",
        )
    try:
        raw_answers = raw["answers"]
        answers = tuple(
            ScoredAnswer(
                question_number=item["Q"],
                selected_answer=item["Answer"],
                correct=item["Correct"],
            )
            for item in raw_answers
        )
        diagnostics = tuple(str(path) for path in raw.get("diagnostic_paths", ()))
        result = ScoreFormPageDispatchResult(
            route_id=route_id,
            page_id=page.page_id,
            issuance_id=page.issuance_id,
            generation_id=page.generation_id,
            artifact_id=page.artifact_id,
            class_id=page.class_id,
            assignment_id=page.assignment_id,
            student_id=page.student_id,
            logical_page=page.logical_page,
            total_pages=page.total_pages,
            question_start=page.question_start,
            question_end=page.question_end,
            layout_id=page.layout_id,
            score=raw["score"],
            total_points=raw["total_points"],
            answers=answers,
            source_scan_id=source_scan_id,
            source_page_number=source_page_number,
            retained_source_relative_path=retained_source_relative_path,
            source_sha256=source_sha256,
            diagnostic_paths=diagnostics,
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ScoreFormPageScoringError(
            "OMR processing returned malformed page results.",
            diagnostic_code="malformed_page_result",
        ) from error
    return validate_page_dispatch_result(result, valid_choices=layout.choices)
