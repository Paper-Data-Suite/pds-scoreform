"""Pure v1 models for ScoreForm answer-sheet issuance and physical pages."""

from __future__ import annotations

import math
import re
import secrets
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Final, TypeAlias

from pds_core.identifiers import IdentifierValidationError, validate_identifier
from pds_core.routing_models import ModuleRecordRef

from scoreform.layouts import require_layout
from scoreform.paging import page_count_for_question_count, question_range_for_page
from scoreform.pds_contract import (
    ANSWER_SHEET_PAGE_CONTRACT_VERSION,
    ANSWER_SHEET_PAGE_RECORD_KIND,
    SCOREFORM_MODULE_ID,
)

ANSWER_SHEET_ISSUANCE_SCHEMA_VERSION: Final[str] = "1"
ANSWER_SHEET_OUTPUT_KINDS: Final[frozenset[str]] = frozenset(
    {"individual_pdf", "class_packet_pdf"}
)
ANSWER_SHEET_GENERATION_REASONS: Final[frozenset[str]] = frozenset(
    {"initial", "additional_copy", "regeneration"}
)
ANSWER_SHEET_LIFECYCLE_STATUSES: Final[frozenset[str]] = frozenset(
    {"prepared", "issued", "cancelled", "superseded", "invalidated"}
)
ANSWER_SHEET_TERMINAL_STATUSES: Final[frozenset[str]] = frozenset(
    {"cancelled", "superseded", "invalidated"}
)
ANSWER_SHEET_LIFECYCLE_TRANSITIONS: Final[frozenset[tuple[str, str]]] = frozenset(
    {
        ("prepared", "issued"),
        ("prepared", "cancelled"),
        ("prepared", "invalidated"),
        ("issued", "superseded"),
        ("issued", "invalidated"),
    }
)

_ID_PATTERNS: Final[dict[str, re.Pattern[str]]] = {
    "generation_id": re.compile(r"^gen_[0-9a-f]{32}$"),
    "artifact_id": re.compile(r"^art_[0-9a-f]{32}$"),
    "issuance_id": re.compile(r"^iss_[0-9a-f]{32}$"),
    "page_id": re.compile(r"^pg_[0-9a-f]{32}$"),
}

JsonMapping: TypeAlias = Mapping[str, object]
Clock: TypeAlias = Callable[[], datetime | str]
IdGenerator: TypeAlias = Callable[[], str]


class AnswerSheetRecordError(ValueError):
    """Raised when an answer-sheet model violates the v1 contract."""


class AnswerSheetLifecycleError(AnswerSheetRecordError):
    """Raised when an issuance lifecycle transition is invalid."""


def _generate_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(16)}"


def generate_generation_id() -> str:
    return _generate_id("gen")


def generate_artifact_id() -> str:
    return _generate_id("art")


def generate_issuance_id() -> str:
    return _generate_id("iss")


def generate_page_id() -> str:
    return _generate_id("pg")


def _validate_record_id(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not _ID_PATTERNS[field_name].fullmatch(value):
        prefix = _ID_PATTERNS[field_name].pattern.split("_")[0].lstrip("^")
        raise AnswerSheetRecordError(
            f"{field_name} must be {prefix}_ followed by 32 lowercase hexadecimal characters."
        )
    try:
        validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise AnswerSheetRecordError(f"{field_name} is not a safe identifier.") from error
    return value


def validate_generation_id(value: object) -> str:
    return _validate_record_id(value, "generation_id")


def validate_artifact_id(value: object) -> str:
    return _validate_record_id(value, "artifact_id")


def validate_issuance_id(value: object) -> str:
    return _validate_record_id(value, "issuance_id")


def validate_page_id(value: object) -> str:
    return _validate_record_id(value, "page_id")


def _safe_identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise AnswerSheetRecordError(f"{field_name} must be a string.")
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise AnswerSheetRecordError(f"{field_name} is not a safe identifier.") from error


def _string(value: object, field_name: str, *, nonempty: bool = True) -> str:
    if not isinstance(value, str) or (nonempty and not value):
        qualifier = "a non-empty" if nonempty else "a"
        raise AnswerSheetRecordError(f"{field_name} must be {qualifier} string.")
    return value


def _normalized_string(value: object, field_name: str) -> str:
    text = _string(value, field_name).strip()
    if not text:
        raise AnswerSheetRecordError(f"{field_name} must be non-empty after trimming.")
    return text


def _integer(value: object, field_name: str, *, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise AnswerSheetRecordError(
            f"{field_name} must be an integer greater than or equal to {minimum}."
        )
    return value


def _require_layout(layout_id: object, field_name: str = "layout_id"):
    try:
        return require_layout(layout_id)
    except ValueError as error:
        raise AnswerSheetRecordError(f"Invalid {field_name}: {error}") from error


def _expected_page_count(question_count: int, layout) -> int:
    try:
        return page_count_for_question_count(question_count, layout)
    except ValueError as error:
        raise AnswerSheetRecordError(str(error)) from error


def _timestamp(value: object, field_name: str) -> str:
    text = _string(value, field_name)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise AnswerSheetRecordError(f"{field_name} must be an ISO 8601 timestamp.") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AnswerSheetRecordError(f"{field_name} must include a timezone offset.")
    if not math.isfinite(parsed.timestamp()):
        raise AnswerSheetRecordError(f"{field_name} must be finite.")
    return text


def _clock_timestamp(clock: Clock | None) -> str:
    value: datetime | str = (
        datetime.now(timezone.utc) if clock is None else clock()
    )
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise AnswerSheetRecordError("clock must return a timezone-aware datetime.")
        value = value.isoformat()
    return _timestamp(value, "timestamp")


def _exact_mapping(value: object, keys: frozenset[str], label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise AnswerSheetRecordError(f"{label} must be an object.")
    if any(not isinstance(key, str) for key in value):
        raise AnswerSheetRecordError(f"{label} keys must be strings.")
    actual = frozenset(value)
    if actual != keys:
        missing = sorted(keys - actual)
        unknown = sorted(actual - keys)
        details = []
        if missing:
            details.append(f"missing keys: {', '.join(missing)}")
        if unknown:
            details.append(f"unknown keys: {', '.join(unknown)}")
        raise AnswerSheetRecordError(f"Invalid {label} shape ({'; '.join(details)}).")
    return value


@dataclass(frozen=True, slots=True)
class AnswerSheetGenerationContext:
    output_kind: str
    reason: str
    predecessor_issuance_id: str | None


@dataclass(frozen=True, slots=True)
class AnswerSheetAssignmentSnapshot:
    title: str
    question_count: int
    layout_id: str
    choices: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AnswerSheetStudentSnapshot:
    last_name: str
    first_name: str
    period: str


@dataclass(frozen=True, slots=True)
class AnswerSheetLifecycle:
    status: str
    revision: int
    created_at: str
    updated_at: str
    issued_at: str | None
    ended_at: str | None
    reason: str | None
    replacement_issuance_id: str | None


@dataclass(frozen=True, slots=True)
class AnswerSheetIssuance:
    schema_version: str
    issuance_id: str
    generation_id: str
    artifact_id: str
    class_id: str
    assignment_id: str
    student_id: str
    generation_context: AnswerSheetGenerationContext
    assignment_snapshot: AnswerSheetAssignmentSnapshot
    student_snapshot: AnswerSheetStudentSnapshot
    page_count: int
    page_ids: tuple[str, ...]
    lifecycle: AnswerSheetLifecycle


@dataclass(frozen=True, slots=True)
class AnswerSheetPage:
    schema_version: str
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
    assignment_question_count: int
    layout_id: str
    created_at: str


@dataclass(frozen=True, slots=True)
class AnswerSheetRecordSet:
    issuance: AnswerSheetIssuance
    pages: tuple[AnswerSheetPage, ...]


def validate_generation_context(value: AnswerSheetGenerationContext) -> AnswerSheetGenerationContext:
    if not isinstance(value, AnswerSheetGenerationContext):
        raise AnswerSheetRecordError("generation_context has the wrong model type.")
    if value.output_kind not in ANSWER_SHEET_OUTPUT_KINDS:
        raise AnswerSheetRecordError("generation_context.output_kind is unsupported.")
    if value.reason not in ANSWER_SHEET_GENERATION_REASONS:
        raise AnswerSheetRecordError("generation_context.reason is unsupported.")
    predecessor = value.predecessor_issuance_id
    if value.reason == "regeneration":
        validate_issuance_id(predecessor)
    elif predecessor is not None:
        raise AnswerSheetRecordError(
            "Only regeneration may name predecessor_issuance_id."
        )
    return value


def validate_assignment_snapshot(value: AnswerSheetAssignmentSnapshot) -> AnswerSheetAssignmentSnapshot:
    if not isinstance(value, AnswerSheetAssignmentSnapshot):
        raise AnswerSheetRecordError("assignment_snapshot has the wrong model type.")
    _string(value.title, "assignment_snapshot.title")
    _integer(value.question_count, "assignment_snapshot.question_count")
    layout = _require_layout(value.layout_id, "assignment_snapshot.layout_id")
    if not isinstance(value.choices, tuple) or value.choices != layout.choices:
        raise AnswerSheetRecordError("assignment_snapshot.choices must match its layout.")
    return value


def validate_student_snapshot(value: AnswerSheetStudentSnapshot) -> AnswerSheetStudentSnapshot:
    if not isinstance(value, AnswerSheetStudentSnapshot):
        raise AnswerSheetRecordError("student_snapshot has the wrong model type.")
    _string(value.last_name, "student_snapshot.last_name")
    _string(value.first_name, "student_snapshot.first_name")
    _string(value.period, "student_snapshot.period")
    return value


def validate_lifecycle(value: AnswerSheetLifecycle) -> AnswerSheetLifecycle:
    if not isinstance(value, AnswerSheetLifecycle):
        raise AnswerSheetRecordError("lifecycle has the wrong model type.")
    if value.status not in ANSWER_SHEET_LIFECYCLE_STATUSES:
        raise AnswerSheetRecordError("lifecycle.status is unsupported.")
    _integer(value.revision, "lifecycle.revision")
    created = _timestamp(value.created_at, "lifecycle.created_at")
    updated = _timestamp(value.updated_at, "lifecycle.updated_at")
    if datetime.fromisoformat(updated) < datetime.fromisoformat(created):
        raise AnswerSheetRecordError("lifecycle.updated_at precedes created_at.")
    for field_name in ("issued_at", "ended_at"):
        field = getattr(value, field_name)
        if field is not None:
            _timestamp(field, f"lifecycle.{field_name}")
            parsed_field = datetime.fromisoformat(field)
            if not (
                datetime.fromisoformat(created)
                <= parsed_field
                <= datetime.fromisoformat(updated)
            ):
                raise AnswerSheetRecordError(
                    f"lifecycle.{field_name} must fall between created_at and updated_at."
                )
    if value.status == "prepared":
        if value.revision != 1 or created != updated:
            raise AnswerSheetRecordError("A prepared lifecycle starts at revision 1 with equal timestamps.")
    elif value.revision < 2:
        raise AnswerSheetRecordError("A transitioned lifecycle must have revision 2 or later.")
    if value.status in {"prepared", "cancelled"} and value.issued_at is not None:
        raise AnswerSheetRecordError(f"{value.status} lifecycle must not have issued_at.")
    if value.status in {"issued", "superseded"} and value.issued_at is None:
        raise AnswerSheetRecordError(f"{value.status} lifecycle requires issued_at.")
    if value.status in ANSWER_SHEET_TERMINAL_STATUSES:
        if value.ended_at is None or not isinstance(value.reason, str) or not value.reason.strip():
            raise AnswerSheetRecordError("Terminal lifecycle requires ended_at and a non-empty reason.")
    elif value.ended_at is not None or value.reason is not None:
        raise AnswerSheetRecordError("Non-terminal lifecycle must not have ended_at or reason.")
    if value.status == "superseded":
        validate_issuance_id(value.replacement_issuance_id)
    elif value.replacement_issuance_id is not None:
        raise AnswerSheetRecordError("replacement_issuance_id is allowed only for superseded.")
    return value


def validate_answer_sheet_issuance(value: AnswerSheetIssuance) -> AnswerSheetIssuance:
    if not isinstance(value, AnswerSheetIssuance):
        raise AnswerSheetRecordError("issuance has the wrong model type.")
    if value.schema_version != ANSWER_SHEET_ISSUANCE_SCHEMA_VERSION:
        raise AnswerSheetRecordError("Unsupported issuance schema_version.")
    validate_issuance_id(value.issuance_id)
    validate_generation_id(value.generation_id)
    validate_artifact_id(value.artifact_id)
    _safe_identifier(value.class_id, "class_id")
    _safe_identifier(value.assignment_id, "assignment_id")
    _safe_identifier(value.student_id, "student_id")
    validate_generation_context(value.generation_context)
    if value.generation_context.predecessor_issuance_id == value.issuance_id:
        raise AnswerSheetRecordError("An issuance cannot be its own predecessor.")
    validate_assignment_snapshot(value.assignment_snapshot)
    validate_student_snapshot(value.student_snapshot)
    _integer(value.page_count, "page_count")
    if not isinstance(value.page_ids, tuple):
        raise AnswerSheetRecordError("page_ids must be a tuple.")
    for page_id in value.page_ids:
        validate_page_id(page_id)
    if len(value.page_ids) != value.page_count:
        raise AnswerSheetRecordError("page_ids length must equal page_count.")
    if len(set(value.page_ids)) != len(value.page_ids):
        raise AnswerSheetRecordError("page_ids must be unique.")
    layout = _require_layout(value.assignment_snapshot.layout_id)
    expected = _expected_page_count(
        value.assignment_snapshot.question_count, layout
    )
    if value.page_count != expected:
        raise AnswerSheetRecordError("page_count does not match assignment structure.")
    validate_lifecycle(value.lifecycle)
    if (
        value.lifecycle.replacement_issuance_id == value.issuance_id
    ):
        raise AnswerSheetRecordError("An issuance cannot replace itself.")
    return value


def validate_answer_sheet_page(value: AnswerSheetPage) -> AnswerSheetPage:
    if not isinstance(value, AnswerSheetPage):
        raise AnswerSheetRecordError("page has the wrong model type.")
    if value.schema_version != ANSWER_SHEET_PAGE_CONTRACT_VERSION:
        raise AnswerSheetRecordError("Unsupported page schema_version.")
    validate_page_id(value.page_id)
    validate_issuance_id(value.issuance_id)
    validate_generation_id(value.generation_id)
    validate_artifact_id(value.artifact_id)
    _safe_identifier(value.class_id, "class_id")
    _safe_identifier(value.assignment_id, "assignment_id")
    _safe_identifier(value.student_id, "student_id")
    for field_name in (
        "logical_page", "total_pages", "question_start", "question_end",
        "assignment_question_count",
    ):
        _integer(getattr(value, field_name), field_name)
    layout = _require_layout(value.layout_id)
    expected_pages = _expected_page_count(
        value.assignment_question_count, layout
    )
    if value.total_pages != expected_pages:
        raise AnswerSheetRecordError("total_pages does not match assignment structure.")
    try:
        expected_range = question_range_for_page(
            value.logical_page, value.assignment_question_count, layout
        )
    except ValueError as error:
        raise AnswerSheetRecordError(str(error)) from error
    if (value.question_start, value.question_end) != expected_range:
        raise AnswerSheetRecordError("Page question range does not match layout math.")
    _timestamp(value.created_at, "created_at")
    return value


def validate_answer_sheet_record_set(value: AnswerSheetRecordSet) -> AnswerSheetRecordSet:
    if not isinstance(value, AnswerSheetRecordSet):
        raise AnswerSheetRecordError("record_set has the wrong model type.")
    issuance = validate_answer_sheet_issuance(value.issuance)
    if not isinstance(value.pages, tuple) or len(value.pages) != issuance.page_count:
        raise AnswerSheetRecordError("Record set page count is incomplete.")
    logical_pages: set[int] = set()
    actual_page_ids: list[str] = []
    for page in value.pages:
        validate_answer_sheet_page(page)
        actual_page_ids.append(page.page_id)
        if page.logical_page in logical_pages:
            raise AnswerSheetRecordError("Record set contains duplicate logical pages.")
        logical_pages.add(page.logical_page)
        duplicated = (
            page.issuance_id, page.generation_id, page.artifact_id, page.class_id,
            page.assignment_id, page.student_id, page.total_pages,
            page.assignment_question_count, page.layout_id,
        )
        expected = (
            issuance.issuance_id, issuance.generation_id, issuance.artifact_id,
            issuance.class_id, issuance.assignment_id, issuance.student_id,
            issuance.page_count, issuance.assignment_snapshot.question_count,
            issuance.assignment_snapshot.layout_id,
        )
        if duplicated != expected:
            raise AnswerSheetRecordError("Page identity/context does not match issuance.")
        if page.created_at != issuance.lifecycle.created_at:
            raise AnswerSheetRecordError(
                "Page creation time does not match issuance creation time."
            )
    if tuple(actual_page_ids) != issuance.page_ids:
        raise AnswerSheetRecordError("Page order does not match issuance.page_ids.")
    if tuple(page.logical_page for page in value.pages) != tuple(
        range(1, issuance.page_count + 1)
    ):
        raise AnswerSheetRecordError("Logical pages must be complete and ordered.")
    return value


def generation_context_to_mapping(value: AnswerSheetGenerationContext) -> dict[str, object]:
    validate_generation_context(value)
    return {"output_kind": value.output_kind, "reason": value.reason,
            "predecessor_issuance_id": value.predecessor_issuance_id}


def generation_context_from_mapping(value: object) -> AnswerSheetGenerationContext:
    data = _exact_mapping(value, frozenset({"output_kind", "reason", "predecessor_issuance_id"}), "generation_context")
    result = AnswerSheetGenerationContext(
        _string(data["output_kind"], "generation_context.output_kind"),
        _string(data["reason"], "generation_context.reason"),
        data["predecessor_issuance_id"] if data["predecessor_issuance_id"] is None else _string(data["predecessor_issuance_id"], "predecessor_issuance_id"),
    )
    return validate_generation_context(result)


def assignment_snapshot_to_mapping(value: AnswerSheetAssignmentSnapshot) -> dict[str, object]:
    validate_assignment_snapshot(value)
    return {"title": value.title, "question_count": value.question_count,
            "layout_id": value.layout_id, "choices": list(value.choices)}


def assignment_snapshot_from_mapping(value: object) -> AnswerSheetAssignmentSnapshot:
    data = _exact_mapping(value, frozenset({"title", "question_count", "layout_id", "choices"}), "assignment_snapshot")
    choices = data["choices"]
    if not isinstance(choices, list) or any(not isinstance(item, str) for item in choices):
        raise AnswerSheetRecordError("assignment_snapshot.choices must be a string array.")
    result = AnswerSheetAssignmentSnapshot(
        _string(data["title"], "assignment_snapshot.title"),
        _integer(data["question_count"], "assignment_snapshot.question_count"),
        _string(data["layout_id"], "assignment_snapshot.layout_id"), tuple(choices),
    )
    return validate_assignment_snapshot(result)


def student_snapshot_to_mapping(value: AnswerSheetStudentSnapshot) -> dict[str, object]:
    validate_student_snapshot(value)
    return {"last_name": value.last_name, "first_name": value.first_name, "period": value.period}


def student_snapshot_from_mapping(value: object) -> AnswerSheetStudentSnapshot:
    data = _exact_mapping(value, frozenset({"last_name", "first_name", "period"}), "student_snapshot")
    return validate_student_snapshot(AnswerSheetStudentSnapshot(
        _string(data["last_name"], "student_snapshot.last_name"),
        _string(data["first_name"], "student_snapshot.first_name"),
        _string(data["period"], "student_snapshot.period"),
    ))


def lifecycle_to_mapping(value: AnswerSheetLifecycle) -> dict[str, object]:
    validate_lifecycle(value)
    return {field: getattr(value, field) for field in (
        "status", "revision", "created_at", "updated_at", "issued_at",
        "ended_at", "reason", "replacement_issuance_id")}


def lifecycle_from_mapping(value: object) -> AnswerSheetLifecycle:
    keys = frozenset({"status", "revision", "created_at", "updated_at", "issued_at", "ended_at", "reason", "replacement_issuance_id"})
    data = _exact_mapping(value, keys, "lifecycle")
    nullable_strings = {}
    for field in ("issued_at", "ended_at", "reason", "replacement_issuance_id"):
        raw = data[field]
        nullable_strings[field] = raw if raw is None else _string(raw, f"lifecycle.{field}")
    return validate_lifecycle(AnswerSheetLifecycle(
        status=_string(data["status"], "lifecycle.status"),
        revision=_integer(data["revision"], "lifecycle.revision"),
        created_at=_string(data["created_at"], "lifecycle.created_at"),
        updated_at=_string(data["updated_at"], "lifecycle.updated_at"),
        **nullable_strings,
    ))


def answer_sheet_issuance_to_mapping(value: AnswerSheetIssuance) -> dict[str, object]:
    validate_answer_sheet_issuance(value)
    return {
        "schema_version": value.schema_version, "issuance_id": value.issuance_id,
        "generation_id": value.generation_id, "artifact_id": value.artifact_id,
        "class_id": value.class_id, "assignment_id": value.assignment_id,
        "student_id": value.student_id,
        "generation_context": generation_context_to_mapping(value.generation_context),
        "assignment_snapshot": assignment_snapshot_to_mapping(value.assignment_snapshot),
        "student_snapshot": student_snapshot_to_mapping(value.student_snapshot),
        "page_count": value.page_count, "page_ids": list(value.page_ids),
        "lifecycle": lifecycle_to_mapping(value.lifecycle),
    }


def answer_sheet_issuance_from_mapping(value: object) -> AnswerSheetIssuance:
    keys = frozenset({"schema_version", "issuance_id", "generation_id", "artifact_id", "class_id", "assignment_id", "student_id", "generation_context", "assignment_snapshot", "student_snapshot", "page_count", "page_ids", "lifecycle"})
    data = _exact_mapping(value, keys, "issuance")
    page_ids = data["page_ids"]
    if not isinstance(page_ids, list) or any(not isinstance(item, str) for item in page_ids):
        raise AnswerSheetRecordError("page_ids must be a string array.")
    return validate_answer_sheet_issuance(AnswerSheetIssuance(
        schema_version=_string(data["schema_version"], "schema_version"),
        issuance_id=_string(data["issuance_id"], "issuance_id"),
        generation_id=_string(data["generation_id"], "generation_id"),
        artifact_id=_string(data["artifact_id"], "artifact_id"),
        class_id=_string(data["class_id"], "class_id"),
        assignment_id=_string(data["assignment_id"], "assignment_id"),
        student_id=_string(data["student_id"], "student_id"),
        generation_context=generation_context_from_mapping(data["generation_context"]),
        assignment_snapshot=assignment_snapshot_from_mapping(data["assignment_snapshot"]),
        student_snapshot=student_snapshot_from_mapping(data["student_snapshot"]),
        page_count=_integer(data["page_count"], "page_count"),
        page_ids=tuple(page_ids),
        lifecycle=lifecycle_from_mapping(data["lifecycle"]),
    ))


def answer_sheet_page_to_mapping(value: AnswerSheetPage) -> dict[str, object]:
    validate_answer_sheet_page(value)
    return {field: getattr(value, field) for field in (
        "schema_version", "page_id", "issuance_id", "generation_id", "artifact_id",
        "class_id", "assignment_id", "student_id", "logical_page", "total_pages",
        "question_start", "question_end", "assignment_question_count", "layout_id",
        "created_at")}


def answer_sheet_page_from_mapping(value: object) -> AnswerSheetPage:
    keys = frozenset({"schema_version", "page_id", "issuance_id", "generation_id", "artifact_id", "class_id", "assignment_id", "student_id", "logical_page", "total_pages", "question_start", "question_end", "assignment_question_count", "layout_id", "created_at"})
    data = _exact_mapping(value, keys, "page")
    return validate_answer_sheet_page(AnswerSheetPage(
        schema_version=_string(data["schema_version"], "schema_version"),
        page_id=_string(data["page_id"], "page_id"),
        issuance_id=_string(data["issuance_id"], "issuance_id"),
        generation_id=_string(data["generation_id"], "generation_id"),
        artifact_id=_string(data["artifact_id"], "artifact_id"),
        class_id=_string(data["class_id"], "class_id"),
        assignment_id=_string(data["assignment_id"], "assignment_id"),
        student_id=_string(data["student_id"], "student_id"),
        logical_page=_integer(data["logical_page"], "logical_page"),
        total_pages=_integer(data["total_pages"], "total_pages"),
        question_start=_integer(data["question_start"], "question_start"),
        question_end=_integer(data["question_end"], "question_end"),
        assignment_question_count=_integer(
            data["assignment_question_count"], "assignment_question_count"
        ),
        layout_id=_string(data["layout_id"], "layout_id"),
        created_at=_string(data["created_at"], "created_at"),
    ))


# Short aliases are useful at strict persistence boundaries.
issuance_to_mapping = answer_sheet_issuance_to_mapping
issuance_from_mapping = answer_sheet_issuance_from_mapping
page_to_mapping = answer_sheet_page_to_mapping
page_from_mapping = answer_sheet_page_from_mapping


def build_answer_sheet_record_set(
    class_id: str,
    assignment: Mapping[str, object],
    student: Mapping[str, object],
    *,
    generation_id: str,
    artifact_id: str,
    output_kind: str,
    reason: str,
    assignment_id: str | None = None,
    predecessor_issuance_id: str | None = None,
    issuance_id: str | None = None,
    page_ids: Sequence[str] | None = None,
    issuance_id_generator: IdGenerator = generate_issuance_id,
    page_id_generator: IdGenerator = generate_page_id,
    clock: Clock | None = None,
) -> AnswerSheetRecordSet:
    """Plan one physical student copy without touching the filesystem."""
    class_id = _safe_identifier(class_id, "class_id")
    if not isinstance(assignment, Mapping):
        raise AnswerSheetRecordError("assignment must be a mapping.")
    stored_assignment_id = _safe_identifier(assignment.get("assignment_id"), "assignment_id")
    if assignment_id is not None and _safe_identifier(assignment_id, "assignment_id") != stored_assignment_id:
        raise AnswerSheetRecordError("assignment_id does not match assignment data.")
    if not isinstance(student, Mapping):
        raise AnswerSheetRecordError("student must be a mapping.")
    student_class = student.get("class_id", class_id)
    if _safe_identifier(student_class, "student.class_id") != class_id:
        raise AnswerSheetRecordError("Student class_id does not match class_id.")
    student_id = _safe_identifier(student.get("student_id"), "student_id")
    title = _normalized_string(assignment.get("title"), "assignment.title")
    question_count = _integer(assignment.get("question_count"), "assignment.question_count")
    layout_id = _string(assignment.get("layout_id"), "assignment.layout_id")
    layout = _require_layout(layout_id, "assignment.layout_id")
    choices = assignment.get("choices")
    if not isinstance(choices, (list, tuple)) or tuple(choices) != layout.choices:
        raise AnswerSheetRecordError("assignment.choices must match its layout.")
    generated_issuance_id = issuance_id_generator() if issuance_id is None else issuance_id
    generated_issuance_id = validate_issuance_id(generated_issuance_id)
    validate_generation_id(generation_id)
    validate_artifact_id(artifact_id)
    page_count = _expected_page_count(question_count, layout)
    generated_page_ids = (
        tuple(page_id_generator() for _ in range(page_count))
        if page_ids is None else tuple(page_ids)
    )
    if len(generated_page_ids) != page_count:
        raise AnswerSheetRecordError("Exactly one page ID is required per physical page.")
    for page_id in generated_page_ids:
        validate_page_id(page_id)
    if len(set(generated_page_ids)) != page_count:
        raise AnswerSheetRecordError("Generated page IDs must be unique.")
    timestamp = _clock_timestamp(clock)
    generation_context = validate_generation_context(AnswerSheetGenerationContext(
        output_kind, reason, predecessor_issuance_id
    ))
    if predecessor_issuance_id == generated_issuance_id:
        raise AnswerSheetRecordError("An issuance cannot be its own predecessor.")
    assignment_snapshot = validate_assignment_snapshot(AnswerSheetAssignmentSnapshot(
        title, question_count, layout_id, tuple(choices)
    ))
    student_snapshot = validate_student_snapshot(AnswerSheetStudentSnapshot(
        _normalized_string(student.get("last_name"), "student.last_name"),
        _normalized_string(student.get("first_name"), "student.first_name"),
        _normalized_string(student.get("period"), "student.period"),
    ))
    lifecycle = AnswerSheetLifecycle(
        "prepared", 1, timestamp, timestamp, None, None, None, None
    )
    issuance = AnswerSheetIssuance(
        ANSWER_SHEET_ISSUANCE_SCHEMA_VERSION, generated_issuance_id, generation_id,
        artifact_id, class_id, stored_assignment_id, student_id, generation_context,
        assignment_snapshot, student_snapshot, page_count, generated_page_ids, lifecycle,
    )
    pages = tuple(
        AnswerSheetPage(
            ANSWER_SHEET_PAGE_CONTRACT_VERSION, page_id, generated_issuance_id,
            generation_id, artifact_id, class_id, stored_assignment_id, student_id,
            logical_page, page_count,
            *question_range_for_page(logical_page, question_count, layout),
            question_count, layout_id, timestamp,
        )
        for logical_page, page_id in enumerate(generated_page_ids, start=1)
    )
    return validate_answer_sheet_record_set(AnswerSheetRecordSet(issuance, pages))


def transition_answer_sheet_lifecycle(
    issuance: AnswerSheetIssuance,
    new_status: str,
    *,
    timestamp: datetime | str,
    reason: str | None = None,
    replacement_issuance_id: str | None = None,
) -> AnswerSheetIssuance:
    """Construct one allowed immutable lifecycle transition."""
    validate_answer_sheet_issuance(issuance)
    if (issuance.lifecycle.status, new_status) not in ANSWER_SHEET_LIFECYCLE_TRANSITIONS:
        raise AnswerSheetLifecycleError(
            f"Transition {issuance.lifecycle.status} -> {new_status} is not allowed."
        )
    at = timestamp.isoformat() if isinstance(timestamp, datetime) else timestamp
    at = _timestamp(at, "timestamp")
    if datetime.fromisoformat(at) < datetime.fromisoformat(issuance.lifecycle.updated_at):
        raise AnswerSheetLifecycleError("Transition timestamp precedes updated_at.")
    terminal = new_status in ANSWER_SHEET_TERMINAL_STATUSES
    if terminal and (not isinstance(reason, str) or not reason.strip()):
        raise AnswerSheetLifecycleError("Terminal transitions require a non-empty reason.")
    if not terminal and reason is not None:
        raise AnswerSheetLifecycleError("issued transition must not include a reason.")
    if new_status == "superseded":
        validate_issuance_id(replacement_issuance_id)
        if replacement_issuance_id == issuance.issuance_id:
            raise AnswerSheetLifecycleError("An issuance cannot replace itself.")
    elif replacement_issuance_id is not None:
        raise AnswerSheetLifecycleError(
            "replacement_issuance_id is allowed only when superseding."
        )
    lifecycle = AnswerSheetLifecycle(
        status=new_status,
        revision=issuance.lifecycle.revision + 1,
        created_at=issuance.lifecycle.created_at,
        updated_at=at,
        issued_at=at if new_status == "issued" else issuance.lifecycle.issued_at,
        ended_at=at if terminal else None,
        reason=reason.strip() if isinstance(reason, str) else None,
        replacement_issuance_id=replacement_issuance_id,
    )
    return validate_answer_sheet_issuance(replace(issuance, lifecycle=lifecycle))


def answer_sheet_page_target(page: AnswerSheetPage | str) -> ModuleRecordRef:
    """Return the exact future Core target without creating a route or locator."""
    page_id = page.page_id if isinstance(page, AnswerSheetPage) else page
    if isinstance(page, AnswerSheetPage):
        validate_answer_sheet_page(page)
    return ModuleRecordRef(
        module_id=SCOREFORM_MODULE_ID,
        record_kind=ANSWER_SHEET_PAGE_RECORD_KIND,
        record_id=validate_page_id(page_id),
        contract_version=ANSWER_SHEET_PAGE_CONTRACT_VERSION,
    )


build_answer_sheet_page_target = answer_sheet_page_target
