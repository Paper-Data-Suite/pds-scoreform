"""Consumer-neutral reader for ScoreForm Academic Result Manifest v1."""

from __future__ import annotations

from typing import Literal, TypeAlias, overload

from pds_core.identifiers import IdentifierValidationError, validate_identifier

from scoreform.academic_result_manifest import (
    AcademicResultManifest,
    AssignmentSourceSnapshot,
    Attempt,
    Question,
    Response,
    ResultsHistorySourceSnapshot,
    ScoreFormAcademicResultManifestDecodeError,
    ScoreFormAcademicResultManifestValidationError,
    StudentResults,
    manifest_from_json_bytes,
    manifest_to_canonical_json_bytes,
    validate_manifest,
)

AcademicResultSourceName: TypeAlias = Literal["assignment", "results_history"]
AcademicResultSourceSnapshot: TypeAlias = (
    AssignmentSourceSnapshot | ResultsHistorySourceSnapshot
)


class ScoreFormAcademicResultReaderError(Exception):
    """Base failure for public ScoreForm manifest reading and lookup."""


class ScoreFormAcademicResultReaderValidationError(
    ScoreFormAcademicResultReaderError, ValueError
):
    """Reader input violates the public consumer-neutral contract."""


class ScoreFormAcademicResultReaderDecodeError(
    ScoreFormAcademicResultReaderValidationError
):
    """Immutable bytes are not an exact valid ScoreForm academic-result manifest."""


class ScoreFormAcademicResultReaderNotFoundError(
    ScoreFormAcademicResultReaderError, LookupError
):
    """An exact validated lookup is absent from the supplied manifest."""


def _safe_student_id(value: object) -> str:
    if not isinstance(value, str):
        raise ScoreFormAcademicResultReaderValidationError(
            "student_id must be a safe identifier."
        )
    try:
        return validate_identifier(value, "student_id")
    except IdentifierValidationError as error:
        raise ScoreFormAcademicResultReaderValidationError(
            "student_id must be a safe identifier."
        ) from error


def _positive_integer(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ScoreFormAcademicResultReaderValidationError(
            f"{field_name} must be a positive integer."
        )
    return value


def read_academic_result_manifest(value: bytes) -> AcademicResultManifest:
    """Decode, validate, and require exact canonical ScoreForm manifest bytes."""
    if type(value) is not bytes:
        raise ScoreFormAcademicResultReaderValidationError(
            "Academic-result manifest input must be immutable bytes."
        )
    try:
        manifest = manifest_from_json_bytes(value)
    except ScoreFormAcademicResultManifestDecodeError as error:
        raise ScoreFormAcademicResultReaderDecodeError(
            "Academic-result manifest bytes are invalid."
        ) from error
    try:
        canonical = manifest_to_canonical_json_bytes(manifest)
    except ScoreFormAcademicResultManifestValidationError as error:
        raise ScoreFormAcademicResultReaderValidationError(
            "Academic-result manifest could not be validated canonically."
        ) from error
    if canonical != value:
        raise ScoreFormAcademicResultReaderValidationError(
            "Academic-result manifest bytes are not canonical."
        )
    return manifest


def validate_academic_result_manifest(
    manifest: AcademicResultManifest,
) -> AcademicResultManifest:
    """Validate one existing immutable manifest model without I/O."""
    try:
        return validate_manifest(manifest)
    except ScoreFormAcademicResultManifestValidationError as error:
        raise ScoreFormAcademicResultReaderValidationError(
            "Academic-result manifest model is invalid."
        ) from error


@overload
def lookup_academic_result_source(
    manifest: AcademicResultManifest,
    source: Literal["assignment"],
) -> AssignmentSourceSnapshot: ...


@overload
def lookup_academic_result_source(
    manifest: AcademicResultManifest,
    source: Literal["results_history"],
) -> ResultsHistorySourceSnapshot: ...


def lookup_academic_result_source(
    manifest: AcademicResultManifest,
    source: AcademicResultSourceName,
) -> AcademicResultSourceSnapshot:
    """Return one exact source snapshot embedded in the manifest."""
    checked = validate_academic_result_manifest(manifest)
    if source == "assignment":
        return checked.source_snapshot.assignment
    if source == "results_history":
        return checked.source_snapshot.results_history
    raise ScoreFormAcademicResultReaderValidationError(
        "source must be assignment or results_history."
    )


def lookup_academic_result_student(
    manifest: AcademicResultManifest,
    student_id: str,
) -> StudentResults:
    """Return one exact represented student without fabricating absence state."""
    checked = validate_academic_result_manifest(manifest)
    target = _safe_student_id(student_id)
    for student in checked.students:
        if student.student_id == target:
            return student
    raise ScoreFormAcademicResultReaderNotFoundError(
        "Requested student is not represented in this manifest."
    )


def lookup_academic_result_attempt(
    manifest: AcademicResultManifest,
    student_id: str,
    attempt_number: int,
) -> Attempt:
    """Return one exact native attempt; never choose a fallback attempt."""
    student = lookup_academic_result_student(manifest, student_id)
    target = _positive_integer(attempt_number, "attempt_number")
    for attempt in student.attempts:
        if attempt.attempt_number == target:
            return attempt
    raise ScoreFormAcademicResultReaderNotFoundError(
        "Requested attempt is not represented for this student."
    )


def lookup_academic_result_question(
    manifest: AcademicResultManifest,
    question_number: int,
) -> Question:
    """Return one exact assignment question and its native alignment metadata."""
    checked = validate_academic_result_manifest(manifest)
    target = _positive_integer(question_number, "question_number")
    for question in checked.assignment.questions:
        if question.question_number == target:
            return question
    raise ScoreFormAcademicResultReaderNotFoundError(
        "Requested question is not represented in this manifest."
    )


def lookup_academic_result_response(
    manifest: AcademicResultManifest,
    student_id: str,
    attempt_number: int,
    question_number: int,
) -> Response:
    """Return one exact native response within one exact student attempt."""
    attempt = lookup_academic_result_attempt(manifest, student_id, attempt_number)
    target = _positive_integer(question_number, "question_number")
    for response in attempt.responses:
        if response.question_number == target:
            return response
    raise ScoreFormAcademicResultReaderNotFoundError(
        "Requested response is not represented in this attempt."
    )


__all__ = (
    "AcademicResultManifest",
    "AcademicResultSourceName",
    "AcademicResultSourceSnapshot",
    "AssignmentSourceSnapshot",
    "Attempt",
    "Question",
    "Response",
    "ResultsHistorySourceSnapshot",
    "ScoreFormAcademicResultReaderDecodeError",
    "ScoreFormAcademicResultReaderError",
    "ScoreFormAcademicResultReaderNotFoundError",
    "ScoreFormAcademicResultReaderValidationError",
    "StudentResults",
    "lookup_academic_result_attempt",
    "lookup_academic_result_question",
    "lookup_academic_result_response",
    "lookup_academic_result_source",
    "lookup_academic_result_student",
    "read_academic_result_manifest",
    "validate_academic_result_manifest",
)
