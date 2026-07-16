"""Strict versioned ScoreForm detail contracts embedded in Core metadata."""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import MappingProxyType
from typing import Final, TypeAlias, cast

from pds_core.identifiers import validate_identifier

from scoreform.answer_sheet_records import validate_issuance_id, validate_page_id
from scoreform.answer_sheet_routes import validate_route_id

DETAILS_SCHEMA_VERSION: Final[str] = "1"
MESSAGE_LIMIT: Final[int] = 512
FAILURE_ORIGINS: Final[frozenset[str]] = frozenset(
    {
        "scan_intake",
        "page_decode",
        "core_dispatch",
        "scoreform_handling",
        "invalid_page_observation",
        "attempt_assembly",
        "result_export",
    }
)
TEACHER_ACTIONS: Final[frozenset[str]] = frozenset(
    {
        "route_selected",
        "route_corrected",
        "manual_entry",
        "manual_marks",
        "rescan_needed",
        "cannot_route",
        "mixed_assignment",
        "evidence_filed",
        "dismissed_duplicate",
        "other",
        "defer",
    }
)
IDENTITY_SOURCES: Final[frozenset[str]] = frozenset(
    {"teacher_verified", "validated_target", "validated_locator", "none"}
)

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]

_FAILURE_KEYS = frozenset(
    {
        "details_schema_version",
        "record_kind",
        "failure_origin",
        "scoreform_category",
        "diagnostic_paths",
        "diagnostic_errors",
        "context",
    }
)
_RESOLUTION_KEYS = frozenset(
    {
        "details_schema_version",
        "record_kind",
        "resolution_origin",
        "teacher_action",
        "identity_source",
        "identity",
        "result",
        "evidence",
    }
)
_IDENTITY_KEYS = frozenset(
    {
        "class_id",
        "assignment_id",
        "student_id",
        "route_id",
        "page_id",
        "issuance_id",
        "logical_page",
        "total_pages",
    }
)
_RESULT_KEYS = frozenset(
    {
        "result_origin",
        "result_output_path",
        "attempt_number",
        "score",
        "total",
        "already_present",
    }
)
_EVIDENCE_KEYS = frozenset({"source_path", "filed_path", "status_tag", "sha256"})
_SHA256 = re.compile(r"[0-9a-f]{64}")
_EVIDENCE_ACTIONS = frozenset({"manual_entry", "manual_marks", "evidence_filed"})
_EVIDENCE_STATUS_BY_ACTION = {
    "manual_entry": frozenset({"manual_entry"}),
    "manual_marks": frozenset({"manual_marks"}),
    "evidence_filed": frozenset({"already_filed"}),
}


class ScoreFormDetailsError(ValueError):
    """A ScoreForm-owned details object violates its exact contract."""


def sanitize_single_line(
    value: object, *, fallback: str, limit: int = MESSAGE_LIMIT
) -> str:
    """Return bounded, trimmed, single-line, control-escaped display text."""
    if not isinstance(fallback, str) or not fallback.strip():
        raise ValueError("fallback must be a nonempty string.")
    if not isinstance(value, str):
        value = fallback
    escaped: list[str] = []
    for character in value:
        category = unicodedata.category(character)
        if character in {"\r", "\n"} or category in {"Cc", "Zl", "Zp"}:
            escaped.append(f"\\u{ord(character):04x}")
        else:
            escaped.append(character)
    result = "".join(escaped).strip()
    if not result:
        result = fallback.strip()
    if len(result) > limit:
        result = result[: max(1, limit - 1)].rstrip() + "…"
    return result


def sanitized_exception(error: Exception) -> dict[str, str]:
    if not isinstance(error, Exception):
        raise TypeError("error must be an Exception.")
    return {
        "error_type": sanitize_single_line(
            type(error).__name__, fallback="Exception", limit=128
        ),
        "error_message": sanitize_single_line(
            str(error), fallback="ScoreForm operation failed."
        ),
    }


def unsupported_value(value: object) -> dict[str, str]:
    """Represent a non-JSON observation without invoking its display hooks."""
    return {
        "value_type": sanitize_single_line(
            type(value).__name__, fallback="object", limit=128
        ),
        "display": "<unsupported non-JSON value>",
    }


def isolated_json_value(value: object, *, depth: int = 0) -> JsonValue:
    """Deeply isolate JSON-native data; deliberately bound unsupported values."""
    if depth > 32:
        raise ScoreFormDetailsError("JSON context nesting exceeds 32 levels.")
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ScoreFormDetailsError("JSON context numbers must be finite.")
        return value
    if isinstance(value, str):
        return sanitize_single_line(value, fallback="<empty>", limit=2048)
    if isinstance(value, Mapping):
        result: dict[str, JsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key:
                raise ScoreFormDetailsError(
                    "JSON context keys must be nonempty strings."
                )
            safe_key = sanitize_single_line(key, fallback="field", limit=128)
            if safe_key in result:
                raise ScoreFormDetailsError("JSON context keys must remain unique.")
            result[safe_key] = isolated_json_value(item, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        return [isolated_json_value(item, depth=depth + 1) for item in value]
    return cast(JsonValue, unsupported_value(value))


def _deep_freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _deep_freeze(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_deep_freeze(item) for item in value)
    return value


def _json_copy(value: object) -> JsonValue:
    if isinstance(value, Mapping):
        return {str(key): _json_copy(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_json_copy(item) for item in value]
    return cast(JsonScalar, value)


def _safe_path(value: object, field_name: str) -> str:
    if isinstance(value, Path) or not isinstance(value, str):
        raise ScoreFormDetailsError(f"{field_name} must be a string path.")
    path = sanitize_single_line(value, fallback="invalid", limit=1024)
    windows = PureWindowsPath(path)
    posix = PurePosixPath(path)
    parts = path.replace("\\", "/").split("/")
    if (
        windows.is_absolute()
        or windows.drive
        or windows.root
        or posix.is_absolute()
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise ScoreFormDetailsError(
            f"{field_name} must be workspace-relative and safe."
        )
    return path.replace("\\", "/")


def _diagnostic_paths(values: object) -> tuple[str, ...]:
    if not isinstance(values, (tuple, list)):
        raise ScoreFormDetailsError("diagnostic_paths must be a sequence.")
    paths = tuple(_safe_path(value, "diagnostic_paths") for value in values)
    if len(paths) != len(set(paths)):
        raise ScoreFormDetailsError("diagnostic_paths must be unique.")
    if paths != tuple(sorted(paths)):
        raise ScoreFormDetailsError("diagnostic_paths must use deterministic ordering.")
    return paths


def _diagnostic_errors(values: object) -> tuple[Mapping[str, str], ...]:
    if not isinstance(values, (tuple, list)):
        raise ScoreFormDetailsError("diagnostic_errors must be a sequence.")
    result = []
    for value in values:
        if not isinstance(value, Mapping) or frozenset(value) != {
            "error_type",
            "error_message",
        }:
            raise ScoreFormDetailsError(
                "diagnostic error records have an invalid shape."
            )
        result.append(
            MappingProxyType({
                "error_type": sanitize_single_line(
                    value["error_type"], fallback="Exception", limit=128
                ),
                "error_message": sanitize_single_line(
                    value["error_message"], fallback="Diagnostic operation failed."
                ),
            })
        )
    return tuple(result)


@dataclass(frozen=True, slots=True)
class ScoreFormFailureDetails:
    failure_origin: str
    scoreform_category: str
    diagnostic_paths: tuple[str, ...]
    diagnostic_errors: tuple[Mapping[str, str], ...]
    context: Mapping[str, object]

    def __post_init__(self) -> None:
        if self.failure_origin not in FAILURE_ORIGINS:
            raise ScoreFormDetailsError("failure_origin is unsupported.")
        category = sanitize_single_line(
            self.scoreform_category, fallback="unknown", limit=128
        )
        if (
            category != self.scoreform_category
            or not category.replace("_", "").isalnum()
        ):
            raise ScoreFormDetailsError("scoreform_category is invalid.")
        paths = _diagnostic_paths(self.diagnostic_paths)
        errors = _diagnostic_errors(self.diagnostic_errors)
        context = isolated_json_value(self.context)
        if not isinstance(context, dict):
            raise ScoreFormDetailsError("context must be a mapping.")
        object.__setattr__(self, "diagnostic_paths", paths)
        object.__setattr__(self, "diagnostic_errors", errors)
        object.__setattr__(self, "context", _deep_freeze(context))

    def to_module_details(self) -> dict[str, JsonValue]:
        return {
            "scoreform": {
                "details_schema_version": DETAILS_SCHEMA_VERSION,
                "record_kind": "failure",
                "failure_origin": self.failure_origin,
                "scoreform_category": self.scoreform_category,
                "diagnostic_paths": [*self.diagnostic_paths],
                "diagnostic_errors": [dict(item) for item in self.diagnostic_errors],
                "context": _json_copy(self.context),
            }
        }


def _exact_nested(
    value: object, keys: frozenset[str], kind: str
) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or frozenset(value) != {"scoreform"}:
        raise ScoreFormDetailsError("module_details must contain exactly scoreform.")
    nested = value["scoreform"]
    if not isinstance(nested, Mapping) or frozenset(nested) != keys:
        raise ScoreFormDetailsError(
            f"ScoreForm {kind} details have an invalid key set."
        )
    if nested["details_schema_version"] != DETAILS_SCHEMA_VERSION:
        raise ScoreFormDetailsError("ScoreForm details schema version is unsupported.")
    if nested["record_kind"] != kind:
        raise ScoreFormDetailsError("ScoreForm details record_kind is invalid.")
    return nested


def _required_string(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ScoreFormDetailsError(f"{label} must be a string.")
    return value


def scoreform_failure_details(
    *,
    origin: str,
    category: str,
    diagnostic_paths: Sequence[str] = (),
    diagnostic_errors: Sequence[Mapping[str, str] | Exception] = (),
    context: Mapping[str, object] | None = None,
) -> dict[str, JsonValue]:
    errors = tuple(
        sanitized_exception(value) if isinstance(value, Exception) else dict(value)
        for value in diagnostic_errors
    )
    return ScoreFormFailureDetails(
        origin,
        category,
        tuple(sorted(diagnostic_paths)),
        errors,
        {} if context is None else context,
    ).to_module_details()


def validate_scoreform_failure_details(value: object) -> ScoreFormFailureDetails:
    nested = _exact_nested(value, _FAILURE_KEYS, "failure")
    context = nested["context"]
    if not isinstance(context, Mapping):
        raise ScoreFormDetailsError("failure context must be a mapping.")
    if not isinstance(nested["diagnostic_paths"], list):
        raise ScoreFormDetailsError("diagnostic_paths must be an array.")
    if not isinstance(nested["diagnostic_errors"], list):
        raise ScoreFormDetailsError("diagnostic_errors must be an array.")
    return ScoreFormFailureDetails(
        _required_string(nested["failure_origin"], "failure_origin"),
        _required_string(nested["scoreform_category"], "scoreform_category"),
        tuple(nested["diagnostic_paths"]),
        tuple(nested["diagnostic_errors"]),
        context,
    )


def _validated_optional_mapping(
    value: object, allowed: frozenset[str], label: str
) -> dict[str, JsonValue] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or not frozenset(value).issubset(allowed):
        raise ScoreFormDetailsError(f"{label} has unsupported fields.")
    isolated = isolated_json_value(value)
    assert isinstance(isolated, dict)
    for key in ("source_path", "filed_path", "result_output_path"):
        if key in isolated:
            isolated[key] = _safe_path(isolated[key], f"{label}.{key}")
    return isolated


@dataclass(frozen=True, slots=True)
class ScoreFormResolutionDetails:
    teacher_action: str
    identity_source: str
    identity: Mapping[str, object]
    result: Mapping[str, object] | None
    evidence: Mapping[str, object] | None

    def __post_init__(self) -> None:
        if self.teacher_action not in TEACHER_ACTIONS:
            raise ScoreFormDetailsError("teacher_action is unsupported.")
        if self.identity_source not in IDENTITY_SOURCES:
            raise ScoreFormDetailsError("identity_source is unsupported.")
        identity = _validated_optional_mapping(
            self.identity, _IDENTITY_KEYS, "identity"
        )
        result = _validated_optional_mapping(self.result, _RESULT_KEYS, "result")
        evidence = _validated_optional_mapping(
            self.evidence, _EVIDENCE_KEYS, "evidence"
        )
        assert identity is not None
        for key in ("class_id", "assignment_id", "student_id"):
            if key in identity:
                try:
                    validate_identifier(identity[key], key)  # type: ignore[arg-type]
                except Exception as error:
                    raise ScoreFormDetailsError(
                        f"identity.{key} is invalid."
                    ) from error
        validators = {
            "route_id": validate_route_id,
            "page_id": validate_page_id,
            "issuance_id": validate_issuance_id,
        }
        for key, validator in validators.items():
            if key in identity:
                try:
                    validator(identity[key])  # type: ignore[arg-type]
                except Exception as error:
                    raise ScoreFormDetailsError(
                        f"identity.{key} is invalid."
                    ) from error
        for key in ("logical_page", "total_pages"):
            if key in identity:
                number = identity[key]
                if (
                    isinstance(number, bool)
                    or not isinstance(number, int)
                    or number < 1
                ):
                    raise ScoreFormDetailsError(f"identity.{key} must be positive.")
        identity_keys = frozenset(identity)
        if self.identity_source == "none":
            if identity:
                raise ScoreFormDetailsError("identity must be empty when identity_source is none.")
        elif self.identity_source == "validated_locator":
            required = {"class_id", "assignment_id", "route_id"}
            if identity_keys != required:
                raise ScoreFormDetailsError(
                    "validated_locator identity must contain exactly class_id, assignment_id, and route_id."
                )
        elif self.identity_source == "validated_target":
            if identity_keys != _IDENTITY_KEYS:
                raise ScoreFormDetailsError(
                    "validated_target identity must contain the complete authoritative target."
                )
            if cast(int, identity["logical_page"]) > cast(int, identity["total_pages"]):
                raise ScoreFormDetailsError("identity.logical_page cannot exceed total_pages.")
        elif self.identity_source == "teacher_verified":
            allowed_shapes = {
                "manual_entry": (
                    frozenset({"class_id", "assignment_id", "student_id"}),
                ),
                "manual_marks": (
                    frozenset({"class_id", "assignment_id"}),
                    frozenset({"class_id", "assignment_id", "student_id"}),
                ),
            }
            if identity_keys not in allowed_shapes.get(self.teacher_action, ()):
                raise ScoreFormDetailsError(
                    "teacher_verified identity has an invalid shape for the selected action."
                )
        if self.teacher_action in {"route_selected", "route_corrected"}:
            if self.identity_source != "validated_target":
                raise ScoreFormDetailsError(
                    "Route actions require validated_target identity."
                )
        elif self.teacher_action in {"manual_entry", "manual_marks"}:
            if self.identity_source != "teacher_verified":
                raise ScoreFormDetailsError(
                    "Manual actions require teacher_verified identity."
                )
        elif self.identity_source != "none":
            raise ScoreFormDetailsError(
                "The selected action does not consume resolution identity."
            )
        if result is not None:
            if frozenset(result) != _RESULT_KEYS:
                raise ScoreFormDetailsError("result must contain its exact field set.")
            if self.teacher_action != "manual_entry":
                raise ScoreFormDetailsError("Only manual_entry may carry a result.")
            if result["result_origin"] != "scan_review_manual":
                raise ScoreFormDetailsError("result.result_origin is invalid.")
            for key in ("attempt_number", "total"):
                number = result[key]
                if isinstance(number, bool) or not isinstance(number, int) or number < 1:
                    raise ScoreFormDetailsError(f"result.{key} must be positive.")
            score = result["score"]
            if isinstance(score, bool) or not isinstance(score, int) or score < 0:
                raise ScoreFormDetailsError("result.score must be nonnegative.")
            if cast(int, score) > cast(int, result["total"]):
                raise ScoreFormDetailsError("result.score cannot exceed total.")
            if not isinstance(result["already_present"], bool):
                raise ScoreFormDetailsError("result.already_present must be Boolean.")
            class_id = identity.get("class_id")
            assignment_id = identity.get("assignment_id")
            expected = (
                f"classes/{class_id}/modules/scoreform/work/"
                f"{assignment_id}/results.csv"
            )
            if result["result_output_path"] != expected:
                raise ScoreFormDetailsError(
                    "result_output_path must be the identity's canonical managed results path."
                )
        if evidence is not None:
            if frozenset(evidence) != _EVIDENCE_KEYS or not evidence:
                raise ScoreFormDetailsError("evidence must contain its exact nonempty field set.")
            if self.teacher_action not in _EVIDENCE_ACTIONS:
                raise ScoreFormDetailsError("The selected action does not permit evidence.")
            status = evidence["status_tag"]
            if status not in _EVIDENCE_STATUS_BY_ACTION[self.teacher_action]:
                raise ScoreFormDetailsError("evidence.status_tag is invalid for the action.")
            digest = evidence["sha256"]
            if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
                raise ScoreFormDetailsError("evidence.sha256 must be a full hexadecimal SHA-256.")
            if self.teacher_action == "evidence_filed":
                if evidence["source_path"] != evidence["filed_path"]:
                    raise ScoreFormDetailsError(
                        "evidence_filed source_path and filed_path must agree."
                    )
            else:
                class_id = identity.get("class_id")
                assignment_id = identity.get("assignment_id")
                prefix = (
                    f"classes/{class_id}/modules/scoreform/work/"
                    f"{assignment_id}/scans/"
                )
                if not cast(str, evidence["filed_path"]).startswith(prefix):
                    raise ScoreFormDetailsError(
                        "Copied evidence must be filed in the selected managed assignment."
                    )
        object.__setattr__(self, "identity", _deep_freeze(identity))
        object.__setattr__(
            self, "result", None if result is None else _deep_freeze(result)
        )
        object.__setattr__(
            self, "evidence", None if evidence is None else _deep_freeze(evidence)
        )

    def to_module_details(self) -> dict[str, JsonValue]:
        return {
            "scoreform": {
                "details_schema_version": DETAILS_SCHEMA_VERSION,
                "record_kind": "resolution",
                "resolution_origin": "scoreform_scan_review",
                "teacher_action": self.teacher_action,
                "identity_source": self.identity_source,
                "identity": _json_copy(self.identity),
                "result": (
                    None
                    if self.result is None
                    else _json_copy(self.result)
                ),
                "evidence": (
                    None
                    if self.evidence is None
                    else _json_copy(self.evidence)
                ),
            }
        }


def scoreform_resolution_details(
    *,
    teacher_action: str,
    identity_source: str,
    identity: Mapping[str, object] | None = None,
    result: Mapping[str, object] | None = None,
    evidence: Mapping[str, object] | None = None,
) -> dict[str, JsonValue]:
    return ScoreFormResolutionDetails(
        teacher_action,
        identity_source,
        {} if identity is None else identity,
        result,
        evidence,
    ).to_module_details()


def validate_scoreform_resolution_details(value: object) -> ScoreFormResolutionDetails:
    nested = _exact_nested(value, _RESOLUTION_KEYS, "resolution")
    if nested["resolution_origin"] != "scoreform_scan_review":
        raise ScoreFormDetailsError("resolution_origin is invalid.")
    identity = nested["identity"]
    if not isinstance(identity, Mapping):
        raise ScoreFormDetailsError("resolution identity must be a mapping.")
    result_value = nested["result"]
    evidence_value = nested["evidence"]
    if result_value is not None and not isinstance(result_value, Mapping):
        raise ScoreFormDetailsError("resolution result must be a mapping or null.")
    if evidence_value is not None and not isinstance(evidence_value, Mapping):
        raise ScoreFormDetailsError("resolution evidence must be a mapping or null.")
    return ScoreFormResolutionDetails(
        _required_string(nested["teacher_action"], "teacher_action"),
        _required_string(nested["identity_source"], "identity_source"),
        identity,
        result_value,
        evidence_value,
    )


def scoreform_details(
    value: object,
) -> ScoreFormFailureDetails | ScoreFormResolutionDetails | None:
    """Return one fully validated ScoreForm contract, never a permissive mapping."""
    try:
        if not isinstance(value, Mapping) or not isinstance(
            value.get("scoreform"), Mapping
        ):
            return None
        kind = value["scoreform"].get("record_kind")
        if kind == "failure":
            return validate_scoreform_failure_details(value)
        if kind == "resolution":
            return validate_scoreform_resolution_details(value)
    except ScoreFormDetailsError:
        return None
    return None
