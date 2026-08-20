"""Strict workspace-local assessment setup presets for ScoreForm."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pds_core.academic_work_registration_storage import (
    AcademicWorkRegistrationStorageError,
    list_academic_work_registration_revisions,
)
from pds_core.class_metadata import (
    ClassMetadataError,
    class_metadata_path,
    load_class_metadata_for_class,
)
from pds_core.classes import load_class_roster
from pds_core.identifiers import IdentifierValidationError, validate_identifier
from pds_core.publication_storage import (
    PublicationStorageError,
    list_publication_records,
)
from pds_core.rosters import RosterError
from pds_core.routing_models import ModuleWorkRef
from pds_core.standards import StandardsLibrary

from scoreform.assignment import (
    AssignmentStandardsAlignmentError,
    validate_assignment_data,
    validate_assignment_standard_alignments,
)
from scoreform.assignment_copying import (
    AssignmentCopyError,
    AssignmentCopyNotFoundError,
    AssignmentCopySource,
    load_assignment_copy_source,
)
from scoreform.work_paths import scoreform_work_paths

PRESET_SCHEMA_VERSION = 1
PRESET_MODULE = "scoreform"
PRESET_RECORD_TYPE = "assignment_setup_preset"
PRESET_COLLECTION_RELATIVE = Path("modules") / PRESET_MODULE / "presets"

_REQUIRED_PRESET_FIELDS = frozenset(
    {
        "schema_version",
        "module",
        "record_type",
        "preset_id",
        "label",
        "question_count",
        "choices",
        "layout_id",
        "answer_key",
        "standards",
    }
)
_OPTIONAL_PRESET_FIELDS = frozenset({"standards_profile_id"})
_ALLOWED_PRESET_FIELDS = _REQUIRED_PRESET_FIELDS | _OPTIONAL_PRESET_FIELDS

PresetMutationKind = Literal["create", "update", "delete"]


class AssignmentPresetError(Exception):
    """Base error for ScoreForm assignment setup presets."""


class AssignmentPresetValidationError(AssignmentPresetError, ValueError):
    """Raised when a preset record or path violates the preset contract."""


class AssignmentPresetNotFoundError(AssignmentPresetError):
    """Raised when one exact canonical preset does not exist."""


class AssignmentPresetConflictError(AssignmentPresetError):
    """Raised when reviewed preset state is stale or a destination collides."""


class AssignmentPresetWriteError(AssignmentPresetError):
    """Raised when a guarded preset mutation cannot be persisted safely."""


@dataclass(frozen=True, slots=True)
class AssignmentPresetSnapshot:
    """Exact canonical preset bytes and their normalized v1 record."""

    preset_id: str
    path: Path
    preset_bytes: bytes
    preset_sha256: str
    preset: dict[str, object]


@dataclass(frozen=True, slots=True)
class AssignmentPresetDiscoveryIssue:
    """One invalid direct child found while discovering the preset collection."""

    path: Path
    message: str


@dataclass(frozen=True, slots=True)
class AssignmentPresetDiscovery:
    """Deterministic valid presets plus bounded invalid-entry diagnostics."""

    presets: tuple[AssignmentPresetSnapshot, ...]
    issues: tuple[AssignmentPresetDiscoveryIssue, ...]


@dataclass(frozen=True, slots=True)
class AssignmentPresetMutationPlan:
    """Immutable reviewed mutation intent; planning itself never writes."""

    operation: PresetMutationKind
    preset_id: str
    path: Path
    candidate: dict[str, object] | None
    candidate_bytes: bytes | None
    candidate_sha256: str | None
    current_bytes: bytes | None
    current_sha256: str | None


@dataclass(frozen=True, slots=True)
class AssignmentPresetFromAssignmentPlan:
    """Reviewed assignment snapshot plus create-only preset mutation plan."""

    source: AssignmentCopySource
    mutation: AssignmentPresetMutationPlan


@dataclass(frozen=True, slots=True)
class AssignmentPresetRosterSummary:
    """Privacy-minimal current Core class context for preset application."""

    class_id: str
    student_count: int
    periods: tuple[str, ...]
    school_year: str | None
    metadata_warning: str | None


@dataclass(frozen=True, slots=True)
class AssignmentPresetApplicationTarget:
    """One exact class-qualified destination in a non-mutating application plan."""

    work: ModuleWorkRef
    work_root: Path
    assignment_path: Path
    roster: AssignmentPresetRosterSummary


@dataclass(frozen=True, slots=True)
class AssignmentPresetApplicationPlan:
    """Reviewed preset snapshot and independent staged assignment destinations."""

    preset: AssignmentPresetSnapshot
    candidate: dict[str, object]
    candidate_sha256: str
    targets: tuple[AssignmentPresetApplicationTarget, ...]


def assignment_preset_collection_dir(workspace_root: str | Path) -> Path:
    """Return the ScoreForm-owned workspace-level preset collection."""

    return Path(workspace_root) / PRESET_COLLECTION_RELATIVE


def assignment_preset_path(
    workspace_root: str | Path,
    preset_id: str,
) -> Path:
    """Return one exact canonical preset path without touching the filesystem."""

    validated_id = _validate_preset_id(preset_id)
    return assignment_preset_collection_dir(workspace_root) / f"{validated_id}.json"


def _validate_preset_id(value: object) -> str:
    if not isinstance(value, str):
        raise AssignmentPresetValidationError("preset_id must be a string.")
    try:
        return validate_identifier(value, "preset_id")
    except IdentifierValidationError as error:
        raise AssignmentPresetValidationError(str(error)) from error


def _duplicate_guard(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise AssignmentPresetValidationError(
                f"Preset JSON contains duplicate object key {key!r}."
            )
        result[key] = value
    return result


def _reject_nonfinite_constant(value: str) -> None:
    raise AssignmentPresetValidationError(
        f"Preset JSON contains nonfinite numeric constant {value!r}."
    )


def assignment_preset_from_json_bytes(
    data: bytes,
    *,
    standards_library: StandardsLibrary | None = None,
    require_current_standards: bool = False,
) -> dict[str, object]:
    """Strictly parse and normalize exact preset JSON bytes."""

    if not isinstance(data, bytes):
        raise AssignmentPresetValidationError("Preset JSON input must be bytes.")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise AssignmentPresetValidationError(
            "Preset JSON must be valid UTF-8."
        ) from error

    try:
        decoded = json.loads(
            text,
            object_pairs_hook=_duplicate_guard,
            parse_constant=_reject_nonfinite_constant,
        )
    except AssignmentPresetValidationError:
        raise
    except (ValueError, RecursionError) as error:
        raise AssignmentPresetValidationError("Preset JSON is malformed.") from error

    if not isinstance(decoded, dict):
        raise AssignmentPresetValidationError(
            "Preset JSON must contain one object."
        )
    return validate_assignment_preset_data(
        decoded,
        standards_library=standards_library,
        require_current_standards=require_current_standards,
    )


def validate_assignment_preset_data(
    data: Mapping[str, object],
    *,
    standards_library: StandardsLibrary | None = None,
    require_current_standards: bool = False,
) -> dict[str, object]:
    """Validate and normalize one v1 preset mapping."""

    if not isinstance(data, Mapping):
        raise AssignmentPresetValidationError("Preset data must be a mapping.")

    keys = set(data)
    missing = sorted(_REQUIRED_PRESET_FIELDS - keys)
    unknown = sorted(keys - _ALLOWED_PRESET_FIELDS)
    if missing:
        raise AssignmentPresetValidationError(
            "Preset is missing required field(s): " + ", ".join(missing)
        )
    if unknown:
        raise AssignmentPresetValidationError(
            "Preset contains unknown top-level field(s): " + ", ".join(unknown)
        )

    schema_version = data.get("schema_version")
    if (
        isinstance(schema_version, bool)
        or not isinstance(schema_version, int)
        or schema_version != PRESET_SCHEMA_VERSION
    ):
        raise AssignmentPresetValidationError(
            f"schema_version must equal {PRESET_SCHEMA_VERSION}."
        )
    if data.get("module") != PRESET_MODULE:
        raise AssignmentPresetValidationError(
            f"module must equal {PRESET_MODULE!r}."
        )
    if data.get("record_type") != PRESET_RECORD_TYPE:
        raise AssignmentPresetValidationError(
            f"record_type must equal {PRESET_RECORD_TYPE!r}."
        )

    preset_id = _validate_preset_id(data.get("preset_id"))

    label = data.get("label")
    if not isinstance(label, str) or not label.strip():
        raise AssignmentPresetValidationError(
            "label must be a non-empty string."
        )
    normalized_label = label.strip()

    validation_assignment: dict[str, object] = {
        "assignment_id": "preset_validation",
        "title": normalized_label,
        "question_count": data.get("question_count"),
        "choices": data.get("choices"),
        "layout_id": data.get("layout_id"),
        "answer_key": data.get("answer_key"),
        "standards": data.get("standards"),
    }
    if "standards_profile_id" in data:
        validation_assignment["standards_profile_id"] = data.get(
            "standards_profile_id"
        )

    diagnostics = io.StringIO()
    with contextlib.redirect_stdout(diagnostics):
        normalized_assignment = validate_assignment_data(validation_assignment)
    if normalized_assignment is None:
        detail = diagnostics.getvalue().strip()
        raise AssignmentPresetValidationError(
            detail or "Preset assignment configuration is invalid."
        )

    if _preset_requires_standards_library(normalized_assignment):
        if standards_library is None and require_current_standards:
            raise AssignmentPresetValidationError(
                "A current PDS Core standards library is required for this preset."
            )
        if standards_library is not None:
            try:
                validate_assignment_standard_alignments(
                    normalized_assignment,
                    standards_library,
                )
            except AssignmentStandardsAlignmentError as error:
                raise AssignmentPresetValidationError(
                    f"Preset standards configuration is not currently valid: {error}"
                ) from error

    question_count = normalized_assignment.get("question_count")
    choices = normalized_assignment.get("choices")
    layout_id = normalized_assignment.get("layout_id")
    answer_key = normalized_assignment.get("answer_key")
    standards = normalized_assignment.get("standards")
    if (
        isinstance(question_count, bool)
        or not isinstance(question_count, int)
        or not isinstance(choices, list)
        or any(not isinstance(choice, str) for choice in choices)
        or not isinstance(layout_id, str)
        or not isinstance(answer_key, dict)
        or not isinstance(standards, dict)
    ):
        raise AssignmentPresetValidationError(
            "Validated preset configuration was not normalized as expected."
        )

    normalized_key: dict[str, str] = {}
    normalized_standards: dict[str, list[str]] = {}
    for question_number in range(1, question_count + 1):
        answer = answer_key.get(question_number)
        if not isinstance(answer, str):
            raise AssignmentPresetValidationError(
                f"Validated preset is missing answer key question {question_number}."
            )
        normalized_key[str(question_number)] = answer

        values = standards.get(str(question_number), [])
        if not isinstance(values, list) or any(
            not isinstance(value, str) for value in values
        ):
            raise AssignmentPresetValidationError(
                f"Validated preset standards for question {question_number} "
                "are not normalized strings."
            )
        normalized_standards[str(question_number)] = list(values)

    normalized: dict[str, object] = {
        "schema_version": PRESET_SCHEMA_VERSION,
        "module": PRESET_MODULE,
        "record_type": PRESET_RECORD_TYPE,
        "preset_id": preset_id,
        "label": normalized_label,
        "question_count": question_count,
        "choices": list(choices),
        "layout_id": layout_id,
        "answer_key": normalized_key,
        "standards": normalized_standards,
    }

    standards_profile_id = normalized_assignment.get("standards_profile_id")
    if standards_profile_id is not None:
        if not isinstance(standards_profile_id, str):
            raise AssignmentPresetValidationError(
                "Validated standards_profile_id is not a string."
            )
        normalized["standards_profile_id"] = standards_profile_id

    return normalized


def build_assignment_preset(
    *,
    preset_id: str,
    label: str,
    question_count: int,
    choices: list[str] | tuple[str, ...],
    layout_id: str,
    answer_key: Mapping[int | str, str],
    standards: Mapping[int | str, list[str] | tuple[str, ...]] | None = None,
    standards_profile_id: str | None = None,
    standards_library: StandardsLibrary | None = None,
) -> dict[str, object]:
    """Build an independent normalized preset from permitted setup fields."""

    candidate: dict[str, object] = {
        "schema_version": PRESET_SCHEMA_VERSION,
        "module": PRESET_MODULE,
        "record_type": PRESET_RECORD_TYPE,
        "preset_id": preset_id,
        "label": label,
        "question_count": question_count,
        "choices": list(choices),
        "layout_id": layout_id,
        "answer_key": dict(answer_key),
        "standards": (
            {}
            if standards is None
            else {str(key): list(values) for key, values in standards.items()}
        ),
    }
    if standards_profile_id is not None:
        candidate["standards_profile_id"] = standards_profile_id

    return validate_assignment_preset_data(
        candidate,
        standards_library=standards_library,
        require_current_standards=True,
    )


def serialize_assignment_preset(preset: Mapping[str, object]) -> bytes:
    """Serialize one already-normalized preset deterministically."""

    normalized = validate_assignment_preset_data(preset)
    try:
        text = json.dumps(
            normalized,
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise AssignmentPresetValidationError(
            f"Preset cannot be serialized as deterministic JSON: {error}"
        ) from error
    return (text + "\n").encode("utf-8")


def load_assignment_preset(
    workspace_root: str | Path,
    preset_id: str,
    *,
    standards_library: StandardsLibrary | None = None,
    require_current_standards: bool = False,
) -> AssignmentPresetSnapshot:
    """Load one exact canonical regular preset file without following links."""

    path = assignment_preset_path(workspace_root, preset_id)
    _preflight_collection_chain(
        workspace_root,
        require_collection=True,
    )
    if path.is_symlink():
        raise AssignmentPresetValidationError(
            f"Preset file must not be a symbolic link: {path}"
        )
    if not _lexists(path) or not path.is_file():
        raise AssignmentPresetNotFoundError(
            f"Preset does not exist: {path}"
        )

    try:
        preset_bytes = path.read_bytes()
    except OSError as error:
        raise AssignmentPresetValidationError(
            f"Could not read preset {preset_id!r}: {error}"
        ) from error

    preset = assignment_preset_from_json_bytes(
        preset_bytes,
        standards_library=standards_library,
        require_current_standards=require_current_standards,
    )
    if preset.get("preset_id") != preset_id:
        raise AssignmentPresetValidationError(
            "Preset identity does not match its canonical filename."
        )
    return AssignmentPresetSnapshot(
        preset_id=preset_id,
        path=path,
        preset_bytes=preset_bytes,
        preset_sha256=hashlib.sha256(preset_bytes).hexdigest(),
        preset=preset,
    )


def discover_assignment_presets(
    workspace_root: str | Path,
    *,
    standards_library: StandardsLibrary | None = None,
    require_current_standards: bool = False,
) -> AssignmentPresetDiscovery:
    """Discover canonical direct-child presets without letting one bad file abort."""

    collection = assignment_preset_collection_dir(workspace_root)
    if not _lexists(collection):
        return AssignmentPresetDiscovery(presets=(), issues=())

    try:
        _preflight_collection_chain(workspace_root, require_collection=True)
    except AssignmentPresetError as error:
        return AssignmentPresetDiscovery(
            presets=(),
            issues=(AssignmentPresetDiscoveryIssue(collection, str(error)),),
        )

    try:
        entries = sorted(collection.iterdir(), key=lambda path: path.name)
    except OSError as error:
        return AssignmentPresetDiscovery(
            presets=(),
            issues=(
                AssignmentPresetDiscoveryIssue(
                    collection,
                    f"Could not list preset collection: {error}",
                ),
            ),
        )

    presets: list[AssignmentPresetSnapshot] = []
    issues: list[AssignmentPresetDiscoveryIssue] = []
    for entry in entries:
        if entry.is_symlink():
            issues.append(
                AssignmentPresetDiscoveryIssue(
                    entry,
                    "Preset collection entry is a symbolic link.",
                )
            )
            continue
        if not entry.is_file():
            issues.append(
                AssignmentPresetDiscoveryIssue(
                    entry,
                    "Preset collection entry is not a regular file.",
                )
            )
            continue
        if entry.suffix != ".json":
            issues.append(
                AssignmentPresetDiscoveryIssue(
                    entry,
                    "Preset collection entry does not use the .json extension.",
                )
            )
            continue

        preset_id = entry.stem
        try:
            _validate_preset_id(preset_id)
            snapshot = load_assignment_preset(
                workspace_root,
                preset_id,
                standards_library=standards_library,
                require_current_standards=require_current_standards,
            )
        except AssignmentPresetError as error:
            issues.append(AssignmentPresetDiscoveryIssue(entry, str(error)))
            continue
        presets.append(snapshot)

    return AssignmentPresetDiscovery(
        presets=tuple(presets),
        issues=tuple(issues),
    )


def build_assignment_preset_from_source(
    source: AssignmentCopySource,
    *,
    preset_id: str,
    label: str | None = None,
    standards_library: StandardsLibrary | None = None,
) -> dict[str, object]:
    """Project one exact assignment snapshot onto the preset allowlist."""

    if not isinstance(source, AssignmentCopySource):
        raise AssignmentPresetValidationError(
            "source must be an exact AssignmentCopySource snapshot."
        )

    definition = source.definition
    effective_label = definition.title if label is None else label
    return build_assignment_preset(
        preset_id=preset_id,
        label=effective_label,
        question_count=definition.question_count,
        choices=definition.choices,
        layout_id=definition.layout_id,
        answer_key=dict(definition.answer_key),
        standards={
            str(question_number): list(standard_ids)
            for question_number, standard_ids in definition.standards
        },
        standards_profile_id=definition.standards_profile_id,
        standards_library=standards_library,
    )


def plan_create_assignment_preset_from_assignment(
    workspace_root: str | Path,
    *,
    source_class_id: str,
    source_assignment_id: str,
    preset_id: str,
    label: str | None = None,
    standards_library: StandardsLibrary | None = None,
) -> AssignmentPresetFromAssignmentPlan:
    """Plan a create-only preset projected from one canonical assignment."""

    try:
        source = load_assignment_copy_source(
            workspace_root,
            source_class_id,
            source_assignment_id,
            standards_library=standards_library,
        )
    except AssignmentCopyNotFoundError as error:
        raise AssignmentPresetNotFoundError(
            f"Source assignment is unavailable: {error}"
        ) from error
    except AssignmentCopyError as error:
        raise AssignmentPresetValidationError(
            f"Source assignment is not eligible for a preset: {error}"
        ) from error

    preset = build_assignment_preset_from_source(
        source,
        preset_id=preset_id,
        label=label,
        standards_library=standards_library,
    )
    mutation = plan_create_assignment_preset(
        workspace_root,
        preset,
        standards_library=standards_library,
    )
    return AssignmentPresetFromAssignmentPlan(
        source=source,
        mutation=mutation,
    )


def commit_assignment_preset_from_assignment(
    workspace_root: str | Path,
    plan: AssignmentPresetFromAssignmentPlan,
    *,
    standards_library: StandardsLibrary | None = None,
) -> AssignmentPresetSnapshot:
    """Revalidate the reviewed source, then create its independent preset."""

    if not isinstance(plan, AssignmentPresetFromAssignmentPlan):
        raise AssignmentPresetValidationError(
            "plan must be an AssignmentPresetFromAssignmentPlan."
        )

    try:
        current = load_assignment_copy_source(
            workspace_root,
            plan.source.work.class_id,
            plan.source.work.work_id,
            standards_library=standards_library,
        )
    except AssignmentCopyError as error:
        raise AssignmentPresetConflictError(
            "Source assignment changed or became unsafe after preview: "
            f"{error}"
        ) from error

    if (
        current.work != plan.source.work
        or current.work_root != plan.source.work_root
        or current.assignment_path != plan.source.assignment_path
        or current.assignment_bytes != plan.source.assignment_bytes
        or current.assignment_sha256 != plan.source.assignment_sha256
    ):
        raise AssignmentPresetConflictError(
            "Source assignment changed after preview; build a new preset plan."
        )

    result = commit_assignment_preset_mutation(
        workspace_root,
        plan.mutation,
        standards_library=standards_library,
    )
    if result is None:
        raise AssignmentPresetWriteError(
            "Preset creation unexpectedly returned no persisted snapshot."
        )
    return result


def build_assignment_from_preset(
    preset: Mapping[str, object],
    *,
    target_assignment_id: str,
    title: str,
    standards_library: StandardsLibrary | None = None,
) -> dict[str, object]:
    """Build one independent normal assignment from reviewed preset values."""

    normalized_preset = validate_assignment_preset_data(
        preset,
        standards_library=standards_library,
        require_current_standards=True,
    )
    choices = normalized_preset.get("choices")
    answer_key = normalized_preset.get("answer_key")
    standards = normalized_preset.get("standards")
    if (
        not isinstance(choices, list)
        or any(not isinstance(choice, str) for choice in choices)
        or not isinstance(answer_key, dict)
        or not isinstance(standards, dict)
    ):
        raise AssignmentPresetValidationError(
            "Validated preset configuration was not normalized as expected."
        )

    normalized_answer_key: dict[str, str] = {}
    for question_number, answer in answer_key.items():
        if not isinstance(question_number, str) or not isinstance(answer, str):
            raise AssignmentPresetValidationError(
                "Validated preset answer key was not normalized as expected."
            )
        normalized_answer_key[question_number] = answer

    normalized_standards: dict[str, list[str]] = {}
    for question_number, standard_ids in standards.items():
        if (
            not isinstance(question_number, str)
            or not isinstance(standard_ids, list)
            or any(not isinstance(standard_id, str) for standard_id in standard_ids)
        ):
            raise AssignmentPresetValidationError(
                "Validated preset standards were not normalized as expected."
            )
        normalized_standards[question_number] = list(standard_ids)

    candidate: dict[str, object] = {
        "assignment_id": target_assignment_id,
        "title": title,
        "question_count": normalized_preset["question_count"],
        "choices": list(choices),
        "layout_id": normalized_preset["layout_id"],
        "answer_key": normalized_answer_key,
        "standards": normalized_standards,
    }
    standards_profile_id = normalized_preset.get("standards_profile_id")
    if standards_profile_id is not None:
        candidate["standards_profile_id"] = standards_profile_id

    diagnostics = io.StringIO()
    with contextlib.redirect_stdout(diagnostics):
        normalized_assignment = validate_assignment_data(candidate)
    if normalized_assignment is None:
        detail = diagnostics.getvalue().strip()
        raise AssignmentPresetValidationError(
            detail or "Preset-derived assignment configuration is invalid."
        )

    if standards_library is not None:
        try:
            validate_assignment_standard_alignments(
                normalized_assignment,
                standards_library,
            )
        except AssignmentStandardsAlignmentError as error:
            raise AssignmentPresetValidationError(
                f"Preset-derived standards configuration is not currently valid: {error}"
            ) from error
    return normalized_assignment


def plan_assignment_preset_application(
    workspace_root: str | Path,
    *,
    preset_id: str,
    target_class_ids: tuple[str, ...] | list[str],
    target_assignment_id: str,
    title: str,
    standards_library: StandardsLibrary | None = None,
) -> AssignmentPresetApplicationPlan:
    """Plan fresh class-qualified assignments from one exact preset without writes."""

    if isinstance(target_class_ids, (str, bytes)) or not target_class_ids:
        raise AssignmentPresetValidationError(
            "Select at least one target class."
        )

    preset = load_assignment_preset(
        workspace_root,
        preset_id,
        standards_library=standards_library,
        require_current_standards=True,
    )
    candidate = build_assignment_from_preset(
        preset.preset,
        target_assignment_id=target_assignment_id,
        title=title,
        standards_library=standards_library,
    )

    targets: list[AssignmentPresetApplicationTarget] = []
    seen_class_ids: set[str] = set()
    for class_id in target_class_ids:
        if not isinstance(class_id, str) or not class_id.strip():
            raise AssignmentPresetValidationError(
                "Target class IDs must be non-empty strings."
            )
        if class_id in seen_class_ids:
            raise AssignmentPresetValidationError(
                f"Target class '{class_id}' was selected more than once."
            )
        seen_class_ids.add(class_id)

        try:
            paths = scoreform_work_paths(
                workspace_root,
                class_id,
                target_assignment_id,
            )
        except (TypeError, ValueError) as error:
            raise AssignmentPresetValidationError(str(error)) from error

        roster = _preset_application_roster_summary(workspace_root, class_id)
        target = AssignmentPresetApplicationTarget(
            work=paths.work_ref,
            work_root=paths.work_root,
            assignment_path=paths.assignment_path,
            roster=roster,
        )
        _preflight_preset_application_target(workspace_root, target)
        targets.append(target)

    return AssignmentPresetApplicationPlan(
        preset=preset,
        candidate=candidate,
        candidate_sha256=_assignment_candidate_sha256(candidate),
        targets=tuple(targets),
    )


def _assignment_candidate_sha256(candidate: Mapping[str, object]) -> str:
    try:
        payload = json.dumps(
            candidate,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise AssignmentPresetValidationError(
            f"Preset-derived assignment is not deterministic JSON data: {error}"
        ) from error
    return hashlib.sha256(payload).hexdigest()


def _preset_application_roster_summary(
    workspace_root: str | Path,
    class_id: str,
) -> AssignmentPresetRosterSummary:
    try:
        roster = load_class_roster(workspace_root, class_id)
    except RosterError as error:
        raise AssignmentPresetNotFoundError(
            f"Target class '{class_id}' does not have a valid Core roster: {error}"
        ) from error

    periods = tuple(sorted({student.period for student in roster.students}))
    school_year: str | None = None
    metadata_warning: str | None = None
    metadata_path = class_metadata_path(workspace_root, class_id)

    if metadata_path.is_symlink():
        metadata_warning = "Class metadata path is a symbolic link and was not read."
    elif metadata_path.is_file():
        try:
            metadata = load_class_metadata_for_class(workspace_root, class_id)
        except ClassMetadataError as error:
            metadata_warning = str(error)
        else:
            school_year = metadata.school_year

    return AssignmentPresetRosterSummary(
        class_id=class_id,
        student_count=len(roster.students),
        periods=periods,
        school_year=school_year,
        metadata_warning=metadata_warning,
    )


def _preflight_preset_application_target(
    workspace_root: str | Path,
    target: AssignmentPresetApplicationTarget,
) -> None:
    for entry in _workspace_descendant_chain(
        workspace_root,
        target.work_root.parent,
    ):
        if not _lexists(entry):
            continue
        if entry.is_symlink():
            raise AssignmentPresetConflictError(
                f"Target path chain contains a symbolic link: {entry}"
            )
        if not entry.is_dir():
            raise AssignmentPresetConflictError(
                f"Target path chain contains a non-directory entry: {entry}"
            )

    if _lexists(target.work_root):
        raise AssignmentPresetConflictError(
            f"Target ScoreForm work root already exists: {target.work_root}"
        )

    try:
        registration_revisions = list_academic_work_registration_revisions(
            workspace_root,
            target.work,
        )
    except AcademicWorkRegistrationStorageError as error:
        raise AssignmentPresetConflictError(
            "Could not prove the target Academic Work Registration state is clean: "
            f"{error}"
        ) from error
    if registration_revisions:
        raise AssignmentPresetConflictError(
            "Target work identity already has Core Academic Work Registration history."
        )

    try:
        publications = list_publication_records(workspace_root)
    except PublicationStorageError as error:
        raise AssignmentPresetConflictError(
            "Could not prove the target publication state is clean: "
            f"{error}"
        ) from error
    if any(publication.work == target.work for publication in publications):
        raise AssignmentPresetConflictError(
            "Target work identity already has Core Publication Record history."
        )


def plan_create_assignment_preset(
    workspace_root: str | Path,
    preset: Mapping[str, object],
    *,
    standards_library: StandardsLibrary | None = None,
) -> AssignmentPresetMutationPlan:
    """Plan create-only preset persistence without creating any directories."""

    normalized = validate_assignment_preset_data(
        preset,
        standards_library=standards_library,
        require_current_standards=True,
    )
    preset_id = _preset_id_from_normalized(normalized)
    path = assignment_preset_path(workspace_root, preset_id)
    _preflight_collection_chain(workspace_root, require_collection=False)
    if _lexists(path):
        raise AssignmentPresetConflictError(
            f"Preset already exists: {path}"
        )
    candidate_bytes = serialize_assignment_preset(normalized)
    return AssignmentPresetMutationPlan(
        operation="create",
        preset_id=preset_id,
        path=path,
        candidate=normalized,
        candidate_bytes=candidate_bytes,
        candidate_sha256=hashlib.sha256(candidate_bytes).hexdigest(),
        current_bytes=None,
        current_sha256=None,
    )


def plan_update_assignment_preset(
    workspace_root: str | Path,
    preset_id: str,
    replacement: Mapping[str, object],
    *,
    standards_library: StandardsLibrary | None = None,
) -> AssignmentPresetMutationPlan:
    """Plan guarded replacement of one exact current preset."""

    current = load_assignment_preset(
        workspace_root,
        preset_id,
        standards_library=standards_library,
        require_current_standards=False,
    )
    normalized = validate_assignment_preset_data(
        replacement,
        standards_library=standards_library,
        require_current_standards=True,
    )
    if normalized.get("preset_id") != preset_id:
        raise AssignmentPresetValidationError(
            "Updated preset_id must match the selected preset identity."
        )
    candidate_bytes = serialize_assignment_preset(normalized)
    return AssignmentPresetMutationPlan(
        operation="update",
        preset_id=preset_id,
        path=current.path,
        candidate=normalized,
        candidate_bytes=candidate_bytes,
        candidate_sha256=hashlib.sha256(candidate_bytes).hexdigest(),
        current_bytes=current.preset_bytes,
        current_sha256=current.preset_sha256,
    )


def plan_delete_assignment_preset(
    workspace_root: str | Path,
    preset_id: str,
) -> AssignmentPresetMutationPlan:
    """Plan deletion of one exact reviewed preset snapshot."""

    current = load_assignment_preset(workspace_root, preset_id)
    return AssignmentPresetMutationPlan(
        operation="delete",
        preset_id=preset_id,
        path=current.path,
        candidate=None,
        candidate_bytes=None,
        candidate_sha256=None,
        current_bytes=current.preset_bytes,
        current_sha256=current.preset_sha256,
    )


def commit_assignment_preset_mutation(
    workspace_root: str | Path,
    plan: AssignmentPresetMutationPlan,
    *,
    standards_library: StandardsLibrary | None = None,
) -> AssignmentPresetSnapshot | None:
    """Commit one reviewed preset mutation after full stale-state revalidation."""

    if not isinstance(plan, AssignmentPresetMutationPlan):
        raise AssignmentPresetValidationError(
            "plan must be an AssignmentPresetMutationPlan."
        )
    expected_path = assignment_preset_path(workspace_root, plan.preset_id)
    if expected_path != plan.path:
        raise AssignmentPresetConflictError(
            "Preset mutation plan does not match this workspace."
        )

    if plan.operation == "create":
        return _commit_create(
            workspace_root,
            plan,
            standards_library=standards_library,
        )
    if plan.operation == "update":
        return _commit_update(
            workspace_root,
            plan,
            standards_library=standards_library,
        )
    if plan.operation == "delete":
        _commit_delete(workspace_root, plan)
        return None
    raise AssignmentPresetValidationError(
        f"Unsupported preset mutation operation: {plan.operation!r}"
    )


def _commit_create(
    workspace_root: str | Path,
    plan: AssignmentPresetMutationPlan,
    *,
    standards_library: StandardsLibrary | None,
) -> AssignmentPresetSnapshot:
    candidate, candidate_bytes = _revalidate_candidate(
        plan,
        standards_library=standards_library,
    )
    _preflight_collection_chain(workspace_root, require_collection=False)
    if _lexists(plan.path):
        raise AssignmentPresetConflictError(
            "Preset destination appeared after preview; build a new plan."
        )

    _ensure_collection_directory(workspace_root)
    _preflight_collection_chain(workspace_root, require_collection=True)
    if _lexists(plan.path):
        raise AssignmentPresetConflictError(
            "Preset destination appeared after preview; build a new plan."
        )

    wrote_file = False
    try:
        with plan.path.open("xb") as output:
            output.write(candidate_bytes)
            output.flush()
            os.fsync(output.fileno())
        wrote_file = True
        snapshot = load_assignment_preset(
            workspace_root,
            plan.preset_id,
            standards_library=standards_library,
            require_current_standards=True,
        )
        if snapshot.preset != candidate:
            raise AssignmentPresetWriteError(
                "Persisted preset does not match the reviewed candidate."
            )
        return snapshot
    except FileExistsError as error:
        raise AssignmentPresetConflictError(
            "Preset destination appeared during creation; nothing was overwritten."
        ) from error
    except AssignmentPresetError:
        if wrote_file:
            _remove_our_exact_file(plan.path, candidate_bytes)
        raise
    except OSError as error:
        if wrote_file:
            _remove_our_exact_file(plan.path, candidate_bytes)
        raise AssignmentPresetWriteError(
            f"Could not create preset safely: {error}"
        ) from error


def _commit_update(
    workspace_root: str | Path,
    plan: AssignmentPresetMutationPlan,
    *,
    standards_library: StandardsLibrary | None,
) -> AssignmentPresetSnapshot:
    candidate, candidate_bytes = _revalidate_candidate(
        plan,
        standards_library=standards_library,
    )
    _revalidate_current_snapshot(workspace_root, plan)

    temporary_path: Path | None = None
    try:
        descriptor, raw_path = tempfile.mkstemp(
            dir=plan.path.parent,
            prefix=f".{plan.path.name}.",
            suffix=".tmp",
        )
        temporary_path = Path(raw_path)
        with os.fdopen(descriptor, "wb") as output:
            output.write(candidate_bytes)
            output.flush()
            os.fsync(output.fileno())

        _revalidate_current_snapshot(workspace_root, plan)
        os.replace(temporary_path, plan.path)
        temporary_path = None

        snapshot = load_assignment_preset(
            workspace_root,
            plan.preset_id,
            standards_library=standards_library,
            require_current_standards=True,
        )
        if snapshot.preset != candidate:
            raise AssignmentPresetWriteError(
                "Persisted preset does not match the reviewed replacement."
            )
        return snapshot
    except AssignmentPresetError:
        raise
    except OSError as error:
        raise AssignmentPresetWriteError(
            f"Could not update preset safely: {error}"
        ) from error
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


def _commit_delete(
    workspace_root: str | Path,
    plan: AssignmentPresetMutationPlan,
) -> None:
    _revalidate_current_snapshot(workspace_root, plan)
    try:
        plan.path.unlink()
    except OSError as error:
        raise AssignmentPresetWriteError(
            f"Could not delete preset safely: {error}"
        ) from error


def _revalidate_candidate(
    plan: AssignmentPresetMutationPlan,
    *,
    standards_library: StandardsLibrary | None,
) -> tuple[dict[str, object], bytes]:
    if (
        plan.candidate is None
        or plan.candidate_bytes is None
        or plan.candidate_sha256 is None
    ):
        raise AssignmentPresetConflictError(
            "Preset mutation plan is missing its reviewed candidate."
        )

    normalized = validate_assignment_preset_data(
        plan.candidate,
        standards_library=standards_library,
        require_current_standards=True,
    )
    candidate_bytes = serialize_assignment_preset(normalized)
    digest = hashlib.sha256(candidate_bytes).hexdigest()
    if (
        normalized != plan.candidate
        or candidate_bytes != plan.candidate_bytes
        or digest != plan.candidate_sha256
    ):
        raise AssignmentPresetConflictError(
            "Preset candidate changed after preview; build a new plan."
        )
    return normalized, candidate_bytes


def _revalidate_current_snapshot(
    workspace_root: str | Path,
    plan: AssignmentPresetMutationPlan,
) -> None:
    if plan.current_bytes is None or plan.current_sha256 is None:
        raise AssignmentPresetConflictError(
            "Preset mutation plan is missing its reviewed current snapshot."
        )
    current = load_assignment_preset(workspace_root, plan.preset_id)
    if (
        current.preset_bytes != plan.current_bytes
        or current.preset_sha256 != plan.current_sha256
    ):
        raise AssignmentPresetConflictError(
            "Preset changed after preview; build a new plan."
        )


def _preset_id_from_normalized(preset: Mapping[str, object]) -> str:
    preset_id = preset.get("preset_id")
    if not isinstance(preset_id, str):
        raise AssignmentPresetValidationError(
            "Normalized preset_id is not a string."
        )
    return preset_id


def _preset_requires_standards_library(
    assignment: Mapping[str, object],
) -> bool:
    if assignment.get("standards_profile_id") is not None:
        return True
    standards = assignment.get("standards")
    return isinstance(standards, Mapping) and any(
        bool(values) for values in standards.values()
    )


def _lexists(path: Path) -> bool:
    return os.path.lexists(os.fspath(path))


def _workspace_descendant_chain(
    workspace_root: str | Path,
    descendant: Path,
) -> tuple[Path, ...]:
    root = Path(os.path.abspath(os.fspath(workspace_root)))
    target = Path(os.path.abspath(os.fspath(descendant)))
    try:
        relative = target.relative_to(root)
    except ValueError as error:
        raise AssignmentPresetValidationError(
            f"Preset path escapes the workspace: {descendant}"
        ) from error

    current = root
    chain: list[Path] = []
    for component in relative.parts:
        current = current / component
        chain.append(current)
    return tuple(chain)


def _preflight_collection_chain(
    workspace_root: str | Path,
    *,
    require_collection: bool,
) -> None:
    collection = assignment_preset_collection_dir(workspace_root)
    chain = _workspace_descendant_chain(workspace_root, collection)
    for entry in chain:
        if not _lexists(entry):
            if require_collection:
                raise AssignmentPresetNotFoundError(
                    f"Preset collection path does not exist: {entry}"
                )
            continue
        if entry.is_symlink():
            raise AssignmentPresetValidationError(
                f"Preset path chain contains a symbolic link: {entry}"
            )
        if not entry.is_dir():
            raise AssignmentPresetValidationError(
                f"Preset path chain contains a non-directory entry: {entry}"
            )


def _ensure_collection_directory(workspace_root: str | Path) -> Path:
    collection = assignment_preset_collection_dir(workspace_root)
    current = Path(os.path.abspath(os.fspath(workspace_root)))
    for component in PRESET_COLLECTION_RELATIVE.parts:
        current = current / component
        if _lexists(current):
            if current.is_symlink() or not current.is_dir():
                raise AssignmentPresetConflictError(
                    f"Preset collection path is unsafe: {current}"
                )
            continue
        try:
            current.mkdir()
        except FileExistsError:
            if current.is_symlink() or not current.is_dir():
                raise AssignmentPresetConflictError(
                    f"Preset collection path became unsafe: {current}"
                )
        except OSError as error:
            raise AssignmentPresetWriteError(
                f"Could not create preset collection directory {current}: {error}"
            ) from error
    return collection


def _remove_our_exact_file(path: Path, expected_bytes: bytes) -> None:
    try:
        if path.is_symlink() or not path.is_file():
            return
        if path.read_bytes() != expected_bytes:
            return
        path.unlink()
    except OSError:
        pass

class AssignmentPresetApplicationWriteError(AssignmentPresetWriteError):
    """Raised when one preset-derived target cannot be persisted safely."""

    def __init__(
        self,
        message: str,
        *,
        residue_paths: tuple[Path, ...] = (),
    ) -> None:
        super().__init__(message)
        self.residue_paths = residue_paths


@dataclass(frozen=True, slots=True)
class AssignmentPresetApplicationCreatedTarget:
    """One preset-derived target assignment durably created and verified."""

    work: ModuleWorkRef
    assignment_path: Path


@dataclass(frozen=True, slots=True)
class AssignmentPresetApplicationTargetFailure:
    """Truthful runtime failure state for one attempted target."""

    target: AssignmentPresetApplicationTarget
    message: str
    residue_paths: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class AssignmentPresetApplicationResult:
    """Preset application result preserving earlier durable successes."""

    preset: AssignmentPresetSnapshot
    candidate: dict[str, object]
    created: tuple[AssignmentPresetApplicationCreatedTarget, ...]
    failures: tuple[AssignmentPresetApplicationTargetFailure, ...]
    not_attempted: tuple[AssignmentPresetApplicationTarget, ...]

    @property
    def complete(self) -> bool:
        return not self.failures and not self.not_attempted


def commit_assignment_preset_application(
    workspace_root: str | Path,
    plan: AssignmentPresetApplicationPlan,
    *,
    standards_library: StandardsLibrary | None = None,
) -> AssignmentPresetApplicationResult:
    """Revalidate the full plan, then create targets sequentially without overwrite."""

    _revalidate_assignment_preset_application_plan(
        workspace_root,
        plan,
        standards_library=standards_library,
    )

    created: list[AssignmentPresetApplicationCreatedTarget] = []
    failures: list[AssignmentPresetApplicationTargetFailure] = []
    not_attempted: tuple[AssignmentPresetApplicationTarget, ...] = ()

    for index, target in enumerate(plan.targets):
        try:
            created_target = _persist_preset_application_target(
                workspace_root,
                target,
                plan.candidate,
            )
        except AssignmentPresetApplicationWriteError as error:
            failures.append(
                AssignmentPresetApplicationTargetFailure(
                    target=target,
                    message=str(error),
                    residue_paths=error.residue_paths,
                )
            )
            not_attempted = plan.targets[index + 1 :]
            break
        created.append(created_target)

    return AssignmentPresetApplicationResult(
        preset=plan.preset,
        candidate=plan.candidate,
        created=tuple(created),
        failures=tuple(failures),
        not_attempted=not_attempted,
    )


def _revalidate_assignment_preset_application_plan(
    workspace_root: str | Path,
    plan: AssignmentPresetApplicationPlan,
    *,
    standards_library: StandardsLibrary | None,
) -> None:
    if not isinstance(plan, AssignmentPresetApplicationPlan):
        raise AssignmentPresetValidationError(
            "plan must be an AssignmentPresetApplicationPlan."
        )
    if not plan.targets:
        raise AssignmentPresetValidationError(
            "Preset application plan must contain at least one target."
        )
    if _assignment_candidate_sha256(plan.candidate) != plan.candidate_sha256:
        raise AssignmentPresetConflictError(
            "Preset-derived assignment changed after preview; build a new plan."
        )

    try:
        current_preset = load_assignment_preset(
            workspace_root,
            plan.preset.preset_id,
            standards_library=standards_library,
            require_current_standards=True,
        )
    except AssignmentPresetError as error:
        raise AssignmentPresetConflictError(
            "Preset changed or became unsafe after preview: "
            f"{error}"
        ) from error

    if (
        current_preset.path != plan.preset.path
        or current_preset.preset_bytes != plan.preset.preset_bytes
        or current_preset.preset_sha256 != plan.preset.preset_sha256
        or current_preset.preset != plan.preset.preset
    ):
        raise AssignmentPresetConflictError(
            "Preset changed after preview; build a new application plan."
        )

    diagnostics = io.StringIO()
    with contextlib.redirect_stdout(diagnostics):
        normalized_candidate = validate_assignment_data(plan.candidate)
    if normalized_candidate is None:
        detail = diagnostics.getvalue().strip()
        raise AssignmentPresetConflictError(
            detail or "Preset-derived assignment is no longer valid."
        )
    if normalized_candidate != plan.candidate:
        raise AssignmentPresetConflictError(
            "Preset-derived assignment no longer matches its normalized preview."
        )

    if _preset_requires_standards_library(normalized_candidate):
        if standards_library is None:
            raise AssignmentPresetValidationError(
                "A current PDS Core standards library is required to commit "
                "this preset-derived assignment."
            )
        try:
            validate_assignment_standard_alignments(
                normalized_candidate,
                standards_library,
            )
        except AssignmentStandardsAlignmentError as error:
            raise AssignmentPresetConflictError(
                "Preset-derived standards configuration is no longer valid: "
                f"{error}"
            ) from error

    assignment_id = normalized_candidate.get("assignment_id")
    if not isinstance(assignment_id, str):
        raise AssignmentPresetConflictError(
            "Preset-derived assignment identity is no longer valid."
        )

    seen: set[ModuleWorkRef] = set()
    for target in plan.targets:
        if target.work in seen:
            raise AssignmentPresetConflictError(
                f"Duplicate target work identity in application plan: {target.work}"
            )
        seen.add(target.work)
        if target.work.work_id != assignment_id:
            raise AssignmentPresetConflictError(
                "Target work identity no longer matches the reviewed assignment ID."
            )

        current_roster = _preset_application_roster_summary(
            workspace_root,
            target.work.class_id,
        )
        if current_roster != target.roster:
            raise AssignmentPresetConflictError(
                f"Target roster/class context changed after preview for "
                f"'{target.work.class_id}'; build a new plan."
            )

        _preflight_preset_application_target(workspace_root, target)


def _ensure_preset_application_parent_directories(
    workspace_root: str | Path,
    target: AssignmentPresetApplicationTarget,
) -> list[Path]:
    created: list[Path] = []
    for entry in _workspace_descendant_chain(
        workspace_root,
        target.work_root.parent,
    ):
        if _lexists(entry):
            if entry.is_symlink() or not entry.is_dir():
                raise AssignmentPresetApplicationWriteError(
                    f"Target parent path became unsafe during commit: {entry}",
                    residue_paths=tuple(created),
                )
            continue
        try:
            entry.mkdir()
        except FileExistsError:
            if entry.is_symlink() or not entry.is_dir():
                raise AssignmentPresetApplicationWriteError(
                    f"Target parent path became unsafe during commit: {entry}",
                    residue_paths=tuple(created),
                )
        except OSError as error:
            raise AssignmentPresetApplicationWriteError(
                f"Could not create target parent directory {entry}: {error}",
                residue_paths=tuple(created),
            ) from error
        else:
            created.append(entry)
    return created


def _cleanup_empty_preset_application_directories(
    directories: tuple[Path, ...] | list[Path],
) -> tuple[Path, ...]:
    residue: list[Path] = []
    for directory in reversed(tuple(directories)):
        try:
            directory.rmdir()
        except FileNotFoundError:
            continue
        except OSError:
            residue.append(directory)
    return tuple(reversed(residue))


def _persist_preset_application_target(
    workspace_root: str | Path,
    target: AssignmentPresetApplicationTarget,
    candidate: dict[str, object],
) -> AssignmentPresetApplicationCreatedTarget:
    from scoreform.assignment import (
        AssignmentJsonBytesError,
        assignment_from_json_bytes,
    )

    created_directories: list[Path] = []
    try:
        created_directories.extend(
            _ensure_preset_application_parent_directories(
                workspace_root,
                target,
            )
        )

        try:
            target.work_root.mkdir()
        except FileExistsError as error:
            raise AssignmentPresetApplicationWriteError(
                f"Target work root appeared during commit: {target.work_root}"
            ) from error
        except OSError as error:
            raise AssignmentPresetApplicationWriteError(
                f"Could not create target work root {target.work_root}: {error}"
            ) from error
        created_directories.append(target.work_root)

        for directory in (
            target.work_root / "templates",
            target.work_root / "templates" / "individual",
            target.work_root / "scans",
            target.work_root / "debug",
        ):
            try:
                directory.mkdir()
            except OSError as error:
                raise AssignmentPresetApplicationWriteError(
                    f"Could not create target managed directory {directory}: {error}"
                ) from error
            created_directories.append(directory)

        try:
            content = (
                json.dumps(
                    candidate,
                    indent=2,
                    ensure_ascii=False,
                    allow_nan=False,
                )
                + "\n"
            ).encode("utf-8")
        except (TypeError, ValueError) as error:
            raise AssignmentPresetApplicationWriteError(
                f"Could not serialize preset-derived assignment: {error}"
            ) from error

        try:
            with target.assignment_path.open("xb") as assignment_file:
                assignment_file.write(content)
                assignment_file.flush()
                os.fsync(assignment_file.fileno())
        except FileExistsError as error:
            raise AssignmentPresetApplicationWriteError(
                f"Target assignment appeared during commit: {target.assignment_path}",
                residue_paths=(target.assignment_path,),
            ) from error
        except OSError as error:
            residue = (
                (target.assignment_path,)
                if _lexists(target.assignment_path)
                else ()
            )
            raise AssignmentPresetApplicationWriteError(
                f"Could not exclusively write target assignment "
                f"{target.assignment_path}: {error}",
                residue_paths=residue,
            ) from error

        try:
            persisted_bytes = target.assignment_path.read_bytes()
            persisted = assignment_from_json_bytes(persisted_bytes)
        except (OSError, AssignmentJsonBytesError) as error:
            raise AssignmentPresetApplicationWriteError(
                f"Could not verify target assignment {target.assignment_path}: {error}",
                residue_paths=(target.assignment_path,),
            ) from error
        if persisted != candidate:
            raise AssignmentPresetApplicationWriteError(
                "Persisted target assignment differs from the reviewed candidate: "
                f"{target.assignment_path}",
                residue_paths=(target.assignment_path,),
            )
        if persisted.get("assignment_id") != target.work.work_id:
            raise AssignmentPresetApplicationWriteError(
                "Persisted target assignment identity does not match its work path: "
                f"{target.assignment_path}",
                residue_paths=(target.assignment_path,),
            )

        return AssignmentPresetApplicationCreatedTarget(
            work=target.work,
            assignment_path=target.assignment_path,
        )
    except AssignmentPresetApplicationWriteError as error:
        cleanup_residue = _cleanup_empty_preset_application_directories(
            created_directories
        )
        combined = tuple(
            dict.fromkeys((*error.residue_paths, *cleanup_residue))
        )
        raise AssignmentPresetApplicationWriteError(
            str(error),
            residue_paths=combined,
        ) from error
    except Exception as error:
        cleanup_residue = _cleanup_empty_preset_application_directories(
            created_directories
        )
        raise AssignmentPresetApplicationWriteError(
            f"Unexpected target persistence failure for {target.work}: {error}",
            residue_paths=cleanup_residue,
        ) from error
