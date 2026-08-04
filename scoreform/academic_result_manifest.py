"""Pure ScoreForm Academic Result Manifest v1 contract.

This module intentionally performs no workspace discovery or I/O.  It owns only
immutable values, exact conversion, canonical JSON, and whole-value validation.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Literal, NoReturn, TypeAlias, cast

from pds_core.identifiers import validate_identifier

from scoreform.config import MAX_ASSIGNMENT_QUESTION_COUNT
from scoreform.layouts import require_layout

RECORD_TYPE = "scoreform_academic_result_manifest"
CONTRACT_VERSION = "scoreform_academic_result_manifest_v1"
PRODUCER_MODULE_ID = "scoreform"
ROUTED_RESULTS_SCHEMA_VERSION = "2"
ASSIGNMENT_SOURCE_PATH = "assignment.json"
RESULTS_HISTORY_SOURCE_PATH = "results.csv"

ACADEMIC_RESULT_MANIFEST_RECORD_TYPE = RECORD_TYPE
ACADEMIC_RESULT_MANIFEST_CONTRACT_VERSION = CONTRACT_VERSION

RESULT_ORIGINS = frozenset(
    {"pds2_scan", "plain_paper_manual", "scan_review_manual"}
)
RESPONSE_STATES = frozenset({"selected", "blank", "ambiguous"})

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ISO_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)
_RETAINED_EXTENSIONS = frozenset({".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"})
_TOP_LEVEL_KEYS = frozenset(
    {
        "record_type",
        "contract_version",
        "producer_module_id",
        "generated_at",
        "record_set",
        "work",
        "source_snapshot",
        "assignment",
        "students",
    }
)


class ScoreFormAcademicResultManifestError(Exception):
    """Base error for the public manifest contract."""


class ScoreFormAcademicResultManifestValidationError(
    ScoreFormAcademicResultManifestError
):
    """The supplied manifest value violates the v1 contract."""


class ScoreFormAcademicResultManifestDecodeError(
    ScoreFormAcademicResultManifestValidationError
):
    """Manifest JSON cannot be decoded without violating the v1 contract."""


ManifestValidationError = ScoreFormAcademicResultManifestValidationError
ManifestDecodeError = ScoreFormAcademicResultManifestDecodeError


def _fail(message: str) -> NoReturn:
    raise ScoreFormAcademicResultManifestValidationError(message)


def _tuple(value: object, field: str) -> tuple[Any, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        _fail(f"{field} must be an array.")
    return tuple(value)


def _json_array(value: object, field: str) -> tuple[Any, ...]:
    if not isinstance(value, list):
        _fail(f"{field} must be a JSON array.")
    return tuple(value)


def _exact_mapping(value: object, keys: frozenset[str], field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{field} must be an object.")
    actual = frozenset(value.keys())
    if any(not isinstance(key, str) for key in value) or actual != keys:
        missing = sorted(keys - actual)
        unknown_count = len(actual - keys)
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if unknown_count:
            details.append(f"{unknown_count} unknown field(s)")
        _fail(f"{field} has an invalid key set ({'; '.join(details)}).")
    return value


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str):
        _fail(f"{field} must be a safe identifier.")
    try:
        return cast(str, validate_identifier(value, field))
    except Exception as error:
        raise ScoreFormAcademicResultManifestValidationError(
            f"{field} must be a safe identifier."
        ) from error


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        _fail(f"{field} must be a positive integer.")
    return value


def _nonnegative_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        _fail(f"{field} must be a nonnegative integer.")
    return value


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        _fail(f"{field} must be a Boolean.")
    return value


def _display_text(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or any(
            unicodedata.category(character) in {"Cc", "Cf", "Cs", "Zl", "Zp"}
            for character in value
        )
    ):
        _fail(f"{field} must be nonempty, trimmed, and control-free.")
    return value


def _digest(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        _fail(f"{field} must be a lowercase SHA-256 digest.")
    return value


def _aware_datetime(value: object, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        _fail(f"{field} must be a timezone-aware datetime.")
    try:
        offset = value.utcoffset()
    except Exception as error:
        raise ScoreFormAcademicResultManifestValidationError(
            f"{field} must be a valid timezone-aware datetime."
        ) from error
    if offset is None:
        _fail(f"{field} must be a timezone-aware datetime.")
    return value


def _timestamp_from_json(value: object, field: str) -> datetime:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or _ISO_TIMESTAMP.fullmatch(value) is None
    ):
        _fail(f"{field} must be a timezone-aware ISO 8601 timestamp.")
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except (TypeError, ValueError) as error:
        raise ScoreFormAcademicResultManifestValidationError(
            f"{field} must be a timezone-aware ISO 8601 timestamp."
        ) from error
    return _aware_datetime(parsed, field)


def _timestamp_to_json(value: datetime) -> str:
    try:
        normalized = _aware_datetime(value, "timestamp").astimezone(timezone.utc)
    except ScoreFormAcademicResultManifestValidationError:
        raise
    except Exception as error:
        raise ScoreFormAcademicResultManifestValidationError(
            "timestamp cannot be normalized to UTC."
        ) from error
    return normalized.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _canonical_retained_path(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        _fail(f"{field} must be a canonical workspace-relative retained path.")
    windows = PureWindowsPath(value)
    posix = PurePosixPath(value)
    parts = tuple(value.split("/"))
    if (
        "\\" in value
        or windows.is_absolute()
        or bool(windows.drive)
        or posix.is_absolute()
        or any(part in {"", ".", ".."} for part in parts)
        or len(parts) != 4
        or parts[:2] != ("scans", "source")
    ):
        _fail(f"{field} must use scans/source/YYYY-MM-DD/<filename>.")
    try:
        parsed_date = datetime.strptime(parts[2], "%Y-%m-%d").date()
    except ValueError as error:
        raise ScoreFormAcademicResultManifestValidationError(
            f"{field} must use scans/source/YYYY-MM-DD/<filename>."
        ) from error
    if parsed_date.isoformat() != parts[2]:
        _fail(f"{field} must use a canonical date.")
    if any(
        unicodedata.category(character) in {"Cc", "Cf", "Cs", "Zl", "Zp"}
        for character in parts[3]
    ):
        _fail(f"{field} filename must be control-free.")
    if PurePosixPath(parts[3]).suffix.lower() not in _RETAINED_EXTENSIONS:
        _fail(f"{field} filename must use a supported retained-source extension.")
    return value


@dataclass(frozen=True, slots=True)
class RecordSet:
    record_set_id: str
    revision: int

    def __post_init__(self) -> None:
        _identifier(self.record_set_id, "record_set.record_set_id")
        _positive_int(self.revision, "record_set.revision")


@dataclass(frozen=True, slots=True)
class WorkReference:
    module_id: str
    class_id: str
    work_id: str

    def __post_init__(self) -> None:
        if self.module_id != PRODUCER_MODULE_ID:
            _fail("work.module_id must be scoreform.")
        _identifier(self.class_id, "work.class_id")
        _identifier(self.work_id, "work.work_id")


@dataclass(frozen=True, slots=True)
class AssignmentSourceSnapshot:
    relative_path: str
    sha256: str
    contract_version: None = None

    def __post_init__(self) -> None:
        if self.relative_path != ASSIGNMENT_SOURCE_PATH:
            _fail("source_snapshot.assignment.relative_path must be assignment.json.")
        _digest(self.sha256, "source_snapshot.assignment.sha256")
        if self.contract_version is not None:
            _fail("source_snapshot.assignment.contract_version must be null.")


@dataclass(frozen=True, slots=True)
class ResultsHistorySourceSnapshot:
    relative_path: str
    sha256: str
    result_schema_version: str

    def __post_init__(self) -> None:
        if self.relative_path != RESULTS_HISTORY_SOURCE_PATH:
            _fail("source_snapshot.results_history.relative_path must be results.csv.")
        _digest(self.sha256, "source_snapshot.results_history.sha256")
        if self.result_schema_version != ROUTED_RESULTS_SCHEMA_VERSION:
            _fail("source_snapshot.results_history.result_schema_version must be 2.")


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    assignment: AssignmentSourceSnapshot
    results_history: ResultsHistorySourceSnapshot

    def __post_init__(self) -> None:
        if not isinstance(self.assignment, AssignmentSourceSnapshot) or not isinstance(
            self.results_history, ResultsHistorySourceSnapshot
        ):
            _fail("source_snapshot contains the wrong model type.")


@dataclass(frozen=True, slots=True)
class Question:
    question_number: int
    points_possible: int
    standard_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "standard_ids", _tuple(self.standard_ids, "question.standard_ids"))
        _positive_int(self.question_number, "question.question_number")
        if self.points_possible != 1 or isinstance(self.points_possible, bool):
            _fail("question.points_possible must be exactly 1.")
        for standard_id in self.standard_ids:
            _identifier(standard_id, "question.standard_ids item")
        if len(set(self.standard_ids)) != len(self.standard_ids):
            _fail("question.standard_ids must not contain duplicates.")


@dataclass(frozen=True, slots=True)
class AssignmentSnapshot:
    assignment_id: str
    title: str
    question_count: int
    layout_id: str
    choices: tuple[str, ...]
    total_points: int
    standards_profile_id: str | None
    questions: tuple[Question, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "choices", _tuple(self.choices, "assignment.choices"))
        object.__setattr__(self, "questions", _tuple(self.questions, "assignment.questions"))
        _identifier(self.assignment_id, "assignment.assignment_id")
        _display_text(self.title, "assignment.title")
        question_count = _positive_int(self.question_count, "assignment.question_count")
        if question_count > MAX_ASSIGNMENT_QUESTION_COUNT:
            _fail("assignment.question_count exceeds ScoreForm's supported maximum.")
        try:
            layout = require_layout(self.layout_id)
        except Exception as error:
            raise ScoreFormAcademicResultManifestValidationError(
                "assignment.layout_id is not a supported ScoreForm layout."
            ) from error
        if self.choices != layout.choices:
            _fail("assignment.choices must exactly match its layout.")
        if self.total_points != question_count or isinstance(self.total_points, bool):
            _fail("assignment.total_points must equal assignment.question_count.")
        if self.standards_profile_id is not None:
            _identifier(self.standards_profile_id, "assignment.standards_profile_id")
        if any(not isinstance(question, Question) for question in self.questions):
            _fail("assignment.questions contains the wrong model type.")
        expected = tuple(range(1, question_count + 1))
        if tuple(question.question_number for question in self.questions) != expected:
            _fail("assignment.questions must cover every question exactly once in order.")
        has_standards = any(question.standard_ids for question in self.questions)
        if has_standards and self.standards_profile_id is None:
            _fail("assignment.standards_profile_id is required when standards are attached.")


@dataclass(frozen=True, slots=True)
class Response:
    question_number: int
    response_state: Literal["selected", "blank", "ambiguous"]
    selected_answer: str | None
    correct: bool

    def __post_init__(self) -> None:
        _positive_int(self.question_number, "response.question_number")
        if self.response_state not in RESPONSE_STATES:
            _fail("response.response_state is unsupported.")
        _boolean(self.correct, "response.correct")
        if self.response_state == "selected":
            if not isinstance(self.selected_answer, str):
                _fail("A selected response requires selected_answer.")
        elif self.selected_answer is not None:
            _fail("Blank and ambiguous responses must have null selected_answer.")
        if self.response_state != "selected" and self.correct:
            _fail("Blank and ambiguous responses cannot be correct.")


@dataclass(frozen=True, slots=True)
class Pds2ScanProvenance:
    issuance_id: str
    generation_id: str
    artifact_id: str
    page_ids: tuple[str, ...]
    route_ids: tuple[str, ...]
    logical_pages: tuple[int, ...]
    source_scan_id: str
    source_page_numbers: tuple[int, ...]
    retained_source_path: str
    source_sha256: str

    def __post_init__(self) -> None:
        for field in ("page_ids", "route_ids", "logical_pages", "source_page_numbers"):
            object.__setattr__(self, field, _tuple(getattr(self, field), f"provenance.{field}"))
        for field in ("issuance_id", "generation_id", "artifact_id", "source_scan_id"):
            _identifier(getattr(self, field), f"provenance.{field}")
        for field in ("page_ids", "route_ids"):
            values = getattr(self, field)
            for value in values:
                _identifier(value, f"provenance.{field} item")
            if len(set(values)) != len(values):
                _fail(f"provenance.{field} must not contain duplicates.")
        length = len(self.page_ids)
        if length < 1 or not (
            length == len(self.route_ids) == len(self.logical_pages) == len(self.source_page_numbers)
        ):
            _fail("PDS2 provenance arrays must be nonempty and aligned.")
        if self.logical_pages != tuple(range(1, length + 1)):
            _fail("provenance.logical_pages must be complete, unique, and ordered.")
        for number in self.source_page_numbers:
            _positive_int(number, "provenance.source_page_numbers item")
        if len(set(self.source_page_numbers)) != len(self.source_page_numbers):
            _fail("provenance.source_page_numbers must not contain duplicates.")
        _canonical_retained_path(self.retained_source_path, "provenance.retained_source_path")
        _digest(self.source_sha256, "provenance.source_sha256")


@dataclass(frozen=True, slots=True)
class PlainPaperManualProvenance:
    """The explicit absence of fabricated scan provenance."""


@dataclass(frozen=True, slots=True)
class ReviewReference:
    failure_id: str

    def __post_init__(self) -> None:
        _identifier(self.failure_id, "review_reference.failure_id")


@dataclass(frozen=True, slots=True)
class ScanReviewManualProvenance:
    review_reference: ReviewReference

    def __post_init__(self) -> None:
        if not isinstance(self.review_reference, ReviewReference):
            _fail("provenance.review_reference has the wrong model type.")


ScanReviewReference = ReviewReference


AttemptProvenance: TypeAlias = (
    Pds2ScanProvenance | PlainPaperManualProvenance | ScanReviewManualProvenance
)


@dataclass(frozen=True, slots=True)
class Attempt:
    attempt_number: int
    result_origin: Literal["pds2_scan", "plain_paper_manual", "scan_review_manual"]
    recorded_at: datetime
    points_earned: int
    points_possible: int
    responses: tuple[Response, ...]
    provenance: AttemptProvenance

    def __post_init__(self) -> None:
        object.__setattr__(self, "responses", _tuple(self.responses, "attempt.responses"))
        _positive_int(self.attempt_number, "attempt.attempt_number")
        if self.result_origin not in RESULT_ORIGINS:
            _fail("attempt.result_origin is unsupported.")
        _aware_datetime(self.recorded_at, "attempt.recorded_at")
        earned = _nonnegative_int(self.points_earned, "attempt.points_earned")
        possible = _positive_int(self.points_possible, "attempt.points_possible")
        if earned > possible:
            _fail("attempt.points_earned exceeds attempt.points_possible.")
        if any(not isinstance(response, Response) for response in self.responses):
            _fail("attempt.responses contains the wrong model type.")
        expected_type = {
            "pds2_scan": Pds2ScanProvenance,
            "plain_paper_manual": PlainPaperManualProvenance,
            "scan_review_manual": ScanReviewManualProvenance,
        }[self.result_origin]
        if not isinstance(self.provenance, expected_type):
            _fail("attempt result_origin and provenance disagree.")


@dataclass(frozen=True, slots=True)
class StudentResults:
    student_id: str
    attempts: tuple[Attempt, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "attempts", _tuple(self.attempts, "student.attempts"))
        _identifier(self.student_id, "student.student_id")
        if any(not isinstance(attempt, Attempt) for attempt in self.attempts):
            _fail("student.attempts contains the wrong model type.")
        numbers = tuple(attempt.attempt_number for attempt in self.attempts)
        if not numbers:
            _fail("student.attempts must not be empty.")
        if numbers != tuple(sorted(numbers)) or len(set(numbers)) != len(numbers):
            _fail("student.attempts must have unique attempt numbers in order.")


@dataclass(frozen=True, slots=True)
class AcademicResultManifest:
    record_type: str
    contract_version: str
    producer_module_id: str
    generated_at: datetime
    record_set: RecordSet
    work: WorkReference
    source_snapshot: SourceSnapshot
    assignment: AssignmentSnapshot
    students: tuple[StudentResults, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "students", _tuple(self.students, "students"))
        validate_manifest(self)


ScoreFormAcademicResultManifest = AcademicResultManifest


def validate_manifest(manifest: AcademicResultManifest) -> AcademicResultManifest:
    """Validate all local and cross-model invariants and return *manifest*."""
    if not isinstance(manifest, AcademicResultManifest):
        _fail("Wrong academic-result manifest model type.")
    if manifest.record_type != RECORD_TYPE:
        _fail(f"record_type must be {RECORD_TYPE}.")
    if manifest.contract_version != CONTRACT_VERSION:
        _fail(f"contract_version must be {CONTRACT_VERSION}.")
    if manifest.producer_module_id != PRODUCER_MODULE_ID:
        _fail("producer_module_id must be scoreform.")
    _aware_datetime(manifest.generated_at, "generated_at")
    models = (
        (manifest.record_set, RecordSet, "record_set"),
        (manifest.work, WorkReference, "work"),
        (manifest.source_snapshot, SourceSnapshot, "source_snapshot"),
        (manifest.assignment, AssignmentSnapshot, "assignment"),
    )
    for value, expected, field in models:
        if not isinstance(value, expected):
            _fail(f"{field} has the wrong model type.")
    if manifest.work.module_id != manifest.producer_module_id:
        _fail("work.module_id and producer_module_id disagree.")
    if manifest.work.work_id != manifest.assignment.assignment_id:
        _fail("work.work_id and assignment.assignment_id disagree.")
    if any(not isinstance(student, StudentResults) for student in manifest.students):
        _fail("students contains the wrong model type.")
    student_ids = tuple(student.student_id for student in manifest.students)
    if student_ids != tuple(sorted(student_ids)) or len(set(student_ids)) != len(student_ids):
        _fail("students must have unique student_id values in order.")
    expected_questions = tuple(range(1, manifest.assignment.question_count + 1))
    valid_choices = frozenset(manifest.assignment.choices)
    for student in manifest.students:
        for attempt in student.attempts:
            if attempt.points_possible != manifest.assignment.total_points:
                _fail("attempt.points_possible and assignment.total_points disagree.")
            numbers = tuple(response.question_number for response in attempt.responses)
            if numbers != expected_questions:
                _fail("attempt.responses must cover every assignment question once in order.")
            for response in attempt.responses:
                if response.response_state == "selected" and response.selected_answer not in valid_choices:
                    _fail("response.selected_answer is not an assignment choice.")
            if attempt.points_earned != sum(response.correct for response in attempt.responses):
                _fail("attempt.points_earned and response correctness disagree.")
    return manifest


def _question_to_mapping(value: Question) -> dict[str, Any]:
    return {"question_number": value.question_number, "points_possible": value.points_possible, "standard_ids": list(value.standard_ids)}


def _response_to_mapping(value: Response) -> dict[str, Any]:
    return {"question_number": value.question_number, "response_state": value.response_state, "selected_answer": value.selected_answer, "correct": value.correct}


def _provenance_to_mapping(value: AttemptProvenance) -> dict[str, Any]:
    if isinstance(value, Pds2ScanProvenance):
        return {
            "issuance_id": value.issuance_id, "generation_id": value.generation_id,
            "artifact_id": value.artifact_id, "page_ids": list(value.page_ids),
            "route_ids": list(value.route_ids), "logical_pages": list(value.logical_pages),
            "source_scan_id": value.source_scan_id,
            "source_page_numbers": list(value.source_page_numbers),
            "retained_source_path": value.retained_source_path, "source_sha256": value.source_sha256,
        }
    if isinstance(value, PlainPaperManualProvenance):
        return {}
    if isinstance(value, ScanReviewManualProvenance):
        reference = value.review_reference
        return {"review_reference": {"failure_id": reference.failure_id}}
    _fail("attempt.provenance has the wrong model type.")


def manifest_to_mapping(manifest: AcademicResultManifest) -> dict[str, Any]:
    """Return a fresh exact JSON-native mapping for *manifest*."""
    validate_manifest(manifest)
    assignment = manifest.assignment
    return {
        "record_type": manifest.record_type,
        "contract_version": manifest.contract_version,
        "producer_module_id": manifest.producer_module_id,
        "generated_at": _timestamp_to_json(manifest.generated_at),
        "record_set": {"record_set_id": manifest.record_set.record_set_id, "revision": manifest.record_set.revision},
        "work": {"module_id": manifest.work.module_id, "class_id": manifest.work.class_id, "work_id": manifest.work.work_id},
        "source_snapshot": {
            "assignment": {"relative_path": manifest.source_snapshot.assignment.relative_path, "sha256": manifest.source_snapshot.assignment.sha256, "contract_version": None},
            "results_history": {"relative_path": manifest.source_snapshot.results_history.relative_path, "sha256": manifest.source_snapshot.results_history.sha256, "result_schema_version": manifest.source_snapshot.results_history.result_schema_version},
        },
        "assignment": {
            "assignment_id": assignment.assignment_id, "title": assignment.title,
            "question_count": assignment.question_count, "layout_id": assignment.layout_id,
            "choices": list(assignment.choices), "total_points": assignment.total_points,
            "standards_profile_id": assignment.standards_profile_id,
            "questions": [_question_to_mapping(question) for question in assignment.questions],
        },
        "students": [
            {"student_id": student.student_id, "attempts": [
                {"attempt_number": attempt.attempt_number, "result_origin": attempt.result_origin,
                 "recorded_at": _timestamp_to_json(attempt.recorded_at),
                 "points_earned": attempt.points_earned, "points_possible": attempt.points_possible,
                 "responses": [_response_to_mapping(response) for response in attempt.responses],
                 "provenance": _provenance_to_mapping(attempt.provenance)}
                for attempt in student.attempts]}
            for student in manifest.students
        ],
    }


def _question_from_mapping(value: object, index: int) -> Question:
    data = _exact_mapping(value, frozenset({"question_number", "points_possible", "standard_ids"}), f"assignment.questions[{index}]")
    standards = _json_array(data["standard_ids"], f"assignment.questions[{index}].standard_ids")
    return Question(data["question_number"], data["points_possible"], cast(tuple[str, ...], standards))


def _response_from_mapping(value: object, field: str) -> Response:
    data = _exact_mapping(value, frozenset({"question_number", "response_state", "selected_answer", "correct"}), field)
    return Response(data["question_number"], data["response_state"], data["selected_answer"], data["correct"])


def _provenance_from_mapping(value: object, origin: str, field: str) -> AttemptProvenance:
    if origin == "pds2_scan":
        keys = frozenset({"issuance_id", "generation_id", "artifact_id", "page_ids", "route_ids", "logical_pages", "source_scan_id", "source_page_numbers", "retained_source_path", "source_sha256"})
        data = _exact_mapping(value, keys, field)
        return Pds2ScanProvenance(
            data["issuance_id"], data["generation_id"], data["artifact_id"],
            cast(tuple[str, ...], _json_array(data["page_ids"], f"{field}.page_ids")),
            cast(tuple[str, ...], _json_array(data["route_ids"], f"{field}.route_ids")),
            cast(tuple[int, ...], _json_array(data["logical_pages"], f"{field}.logical_pages")),
            data["source_scan_id"],
            cast(tuple[int, ...], _json_array(data["source_page_numbers"], f"{field}.source_page_numbers")),
            data["retained_source_path"], data["source_sha256"],
        )
    if origin == "plain_paper_manual":
        _exact_mapping(value, frozenset(), field)
        return PlainPaperManualProvenance()
    if origin == "scan_review_manual":
        data = _exact_mapping(value, frozenset({"review_reference"}), field)
        reference = _exact_mapping(data["review_reference"], frozenset({"failure_id"}), f"{field}.review_reference")
        return ScanReviewManualProvenance(ReviewReference(reference["failure_id"]))
    _fail("attempt.result_origin is unsupported.")


def manifest_from_mapping(value: object) -> AcademicResultManifest:
    """Decode an exact JSON-native mapping into an immutable manifest."""
    try:
        data = _exact_mapping(value, _TOP_LEVEL_KEYS, "manifest")
        record_set_data = _exact_mapping(data["record_set"], frozenset({"record_set_id", "revision"}), "record_set")
        work_data = _exact_mapping(data["work"], frozenset({"module_id", "class_id", "work_id"}), "work")
        source_data = _exact_mapping(data["source_snapshot"], frozenset({"assignment", "results_history"}), "source_snapshot")
        assignment_source = _exact_mapping(source_data["assignment"], frozenset({"relative_path", "sha256", "contract_version"}), "source_snapshot.assignment")
        results_source = _exact_mapping(source_data["results_history"], frozenset({"relative_path", "sha256", "result_schema_version"}), "source_snapshot.results_history")
        assignment_data = _exact_mapping(data["assignment"], frozenset({"assignment_id", "title", "question_count", "layout_id", "choices", "total_points", "standards_profile_id", "questions"}), "assignment")
        question_values = _json_array(assignment_data["questions"], "assignment.questions")
        student_values = _json_array(data["students"], "students")
        students = []
        for student_index, student_value in enumerate(student_values):
            student_data = _exact_mapping(student_value, frozenset({"student_id", "attempts"}), f"students[{student_index}]")
            attempt_values = _json_array(student_data["attempts"], f"students[{student_index}].attempts")
            attempts = []
            for attempt_index, attempt_value in enumerate(attempt_values):
                field = f"students[{student_index}].attempts[{attempt_index}]"
                attempt_data = _exact_mapping(attempt_value, frozenset({"attempt_number", "result_origin", "recorded_at", "points_earned", "points_possible", "responses", "provenance"}), field)
                response_values = _json_array(attempt_data["responses"], f"{field}.responses")
                origin = attempt_data["result_origin"]
                attempts.append(Attempt(
                    attempt_data["attempt_number"], origin,
                    _timestamp_from_json(attempt_data["recorded_at"], f"{field}.recorded_at"),
                    attempt_data["points_earned"], attempt_data["points_possible"],
                    tuple(_response_from_mapping(item, f"{field}.responses[{index}]") for index, item in enumerate(response_values)),
                    _provenance_from_mapping(attempt_data["provenance"], origin, f"{field}.provenance"),
                ))
            students.append(StudentResults(student_data["student_id"], tuple(attempts)))
        return AcademicResultManifest(
            data["record_type"], data["contract_version"], data["producer_module_id"],
            _timestamp_from_json(data["generated_at"], "generated_at"),
            RecordSet(record_set_data["record_set_id"], record_set_data["revision"]),
            WorkReference(work_data["module_id"], work_data["class_id"], work_data["work_id"]),
            SourceSnapshot(
                AssignmentSourceSnapshot(assignment_source["relative_path"], assignment_source["sha256"], assignment_source["contract_version"]),
                ResultsHistorySourceSnapshot(results_source["relative_path"], results_source["sha256"], results_source["result_schema_version"]),
            ),
            AssignmentSnapshot(
                assignment_data["assignment_id"], assignment_data["title"], assignment_data["question_count"], assignment_data["layout_id"],
                cast(tuple[str, ...], _json_array(assignment_data["choices"], "assignment.choices")), assignment_data["total_points"], assignment_data["standards_profile_id"],
                tuple(_question_from_mapping(item, index) for index, item in enumerate(question_values)),
            ),
            tuple(students),
        )
    except ScoreFormAcademicResultManifestValidationError:
        raise
    except Exception as error:
        raise ScoreFormAcademicResultManifestValidationError(
            "Manifest mapping contains an invalid typed value."
        ) from error


def manifest_to_canonical_json_bytes(manifest: AcademicResultManifest) -> bytes:
    """Serialize *manifest* as deterministic UTF-8 JSON with one final newline."""
    try:
        text = json.dumps(
            manifest_to_mapping(manifest), ensure_ascii=False, sort_keys=True,
            indent=2, allow_nan=False, separators=(",", ": "),
        )
    except ScoreFormAcademicResultManifestValidationError:
        raise
    except Exception as error:
        raise ScoreFormAcademicResultManifestValidationError(
            "Manifest cannot be represented as canonical JSON."
        ) from error
    return (text + "\n").encode("utf-8")


def _duplicate_guard(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ScoreFormAcademicResultManifestDecodeError(
                "Manifest JSON contains a duplicate object key."
            )
        result[key] = value
    return result


def _reject_constant(value: str) -> NoReturn:
    raise ScoreFormAcademicResultManifestDecodeError(
        "Manifest JSON contains a nonfinite number."
    )


def manifest_from_json_bytes(value: object) -> AcademicResultManifest:
    """Strictly decode UTF-8 manifest JSON bytes without filesystem access."""
    if not isinstance(value, bytes):
        raise ScoreFormAcademicResultManifestDecodeError(
            "Manifest JSON input must be bytes."
        )
    try:
        text = value.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ScoreFormAcademicResultManifestDecodeError(
            "Manifest JSON must be valid UTF-8."
        ) from error
    try:
        decoded = json.loads(
            text, object_pairs_hook=_duplicate_guard, parse_constant=_reject_constant
        )
    except ScoreFormAcademicResultManifestDecodeError:
        raise
    except (ValueError, RecursionError) as error:
        raise ScoreFormAcademicResultManifestDecodeError(
            "Manifest JSON is malformed."
        ) from error
    try:
        return manifest_from_mapping(decoded)
    except ScoreFormAcademicResultManifestValidationError as error:
        raise ScoreFormAcademicResultManifestDecodeError(str(error)) from error


# Explicit public aliases using the contract noun make consumer code self-documenting.
academic_result_manifest_to_mapping = manifest_to_mapping
academic_result_manifest_from_mapping = manifest_from_mapping
academic_result_manifest_to_canonical_json_bytes = manifest_to_canonical_json_bytes
academic_result_manifest_from_json_bytes = manifest_from_json_bytes
manifest_to_json_bytes = manifest_to_canonical_json_bytes
manifest_from_canonical_json_bytes = manifest_from_json_bytes


__all__ = [
    "ACADEMIC_RESULT_MANIFEST_CONTRACT_VERSION", "ACADEMIC_RESULT_MANIFEST_RECORD_TYPE",
    "ASSIGNMENT_SOURCE_PATH", "CONTRACT_VERSION", "PRODUCER_MODULE_ID",
    "RECORD_TYPE", "RESULTS_HISTORY_SOURCE_PATH", "ROUTED_RESULTS_SCHEMA_VERSION",
    "AcademicResultManifest", "AssignmentSnapshot", "AssignmentSourceSnapshot",
    "Attempt", "ManifestDecodeError", "ManifestValidationError",
    "Pds2ScanProvenance", "PlainPaperManualProvenance", "Question", "RecordSet",
    "Response", "ResultsHistorySourceSnapshot", "ReviewReference",
    "ScanReviewManualProvenance", "ScanReviewReference", "ScoreFormAcademicResultManifest",
    "ScoreFormAcademicResultManifestDecodeError", "ScoreFormAcademicResultManifestError",
    "ScoreFormAcademicResultManifestValidationError", "SourceSnapshot", "StudentResults",
    "WorkReference", "academic_result_manifest_from_json_bytes",
    "academic_result_manifest_from_mapping", "academic_result_manifest_to_canonical_json_bytes",
    "academic_result_manifest_to_mapping", "manifest_from_json_bytes",
    "manifest_from_canonical_json_bytes", "manifest_from_mapping",
    "manifest_to_canonical_json_bytes", "manifest_to_json_bytes", "manifest_to_mapping",
    "validate_manifest",
]
