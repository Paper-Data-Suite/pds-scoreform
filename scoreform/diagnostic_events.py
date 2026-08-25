"""Privacy-conscious ScoreForm-local diagnostic event records and storage."""

from __future__ import annotations

import json
import os
import re
import secrets
import stat
import tomllib
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Final, Literal, cast

from pds_core.identifiers import IdentifierValidationError, validate_identifier

DIAGNOSTIC_SCHEMA_VERSION: Final = "1"
DIAGNOSTIC_MODULE: Final = "scoreform"
DIAGNOSTIC_RECORD_TYPE: Final = "diagnostic_event"
DEFAULT_EVENT_RETENTION_LIMIT: Final = 500
DEFAULT_EVENT_LIST_LIMIT: Final = 50
MAX_EVENT_LIST_LIMIT: Final = 200
EVENT_DIRECTORY_PARTS: Final = ("shared", "scoreform", "diagnostics", "events")

DiagnosticComponent = Literal[
    "assignment",
    "generation",
    "scan_intake",
    "scoring",
    "scan_review",
    "results",
    "publication",
    "recovery",
    "diagnostics",
]
DiagnosticOutcome = Literal[
    "success",
    "warning",
    "failure",
    "partial_success",
    "recovered",
    "blocked",
]
DiagnosticCategory = Literal[
    "validation",
    "storage",
    "assignment",
    "generation",
    "qr",
    "routing",
    "scoring",
    "results",
    "scan_review",
    "publication",
    "recovery",
    "diagnostics",
]

_COMPONENTS: Final = frozenset(
    {
        "assignment",
        "generation",
        "scan_intake",
        "scoring",
        "scan_review",
        "results",
        "publication",
        "recovery",
        "diagnostics",
    }
)
_WORKFLOWS: Final = frozenset(
    {
        "create_assignment",
        "copy_assignment",
        "apply_assignment_preset",
        "bulk_edit_assignment",
        "generate_answer_sheets",
        "generate_multi_class_answer_sheets",
        "process_scan",
        "score_scan",
        "assemble_attempt",
        "persist_results",
        "resolve_scan_review",
        "enter_plain_paper_results",
        "register_academic_work",
        "generate_result_manifest",
        "publish_results",
        "supersede_results",
        "share_results",
        "inspect_diagnostics",
        "retain_diagnostics",
    }
)
_STAGES: Final = frozenset(
    {
        "validate_input",
        "load_context",
        "plan",
        "preflight",
        "generate",
        "decode",
        "parse",
        "dispatch",
        "score",
        "assemble",
        "write_record",
        "verify_record",
        "export",
        "reconcile",
        "catalog_rebuild",
        "post_write_verify",
        "recover",
        "retention",
    }
)
_OUTCOMES: Final = frozenset(
    {
        "success",
        "warning",
        "failure",
        "partial_success",
        "recovered",
        "blocked",
    }
)
_CATEGORIES: Final = frozenset(
    {
        "validation",
        "storage",
        "assignment",
        "generation",
        "qr",
        "routing",
        "scoring",
        "results",
        "scan_review",
        "publication",
        "recovery",
        "diagnostics",
    }
)

# Each durable code owns both its broad category and its only persisted summary.
# Callers never persist arbitrary exception or teacher-authored prose in an event.
_CODE_CONTRACTS: Final[dict[str, tuple[str, str]]] = {
    "assignment_validation_failed": (
        "assignment",
        "Assignment input failed validation.",
    ),
    "assignment_copy_conflict": (
        "assignment",
        "Assignment copy encountered an existing or changed destination.",
    ),
    "assignment_copy_stale": (
        "assignment",
        "Assignment copy source changed after review.",
    ),
    "assignment_write_partial_success": (
        "storage",
        "Assignment write may already be durable and requires inspection.",
    ),
    "assignment_copy_verified": (
        "assignment",
        "Assignment copy completed and was verified.",
    ),
    "assignment_preset_conflict": (
        "assignment",
        "Assignment preset operation encountered changed canonical state.",
    ),
    "assignment_bulk_edit_conflict": (
        "assignment",
        "Bulk assignment edit encountered changed canonical state.",
    ),
    "generation_preflight_failed": (
        "generation",
        "Answer-sheet generation failed preflight validation.",
    ),
    "generation_conflict": (
        "generation",
        "Answer-sheet generation encountered an output or state conflict.",
    ),
    "generation_partial_success": (
        "generation",
        "Answer-sheet generation completed only partially.",
    ),
    "generation_verified": (
        "generation",
        "Answer-sheet generation completed and was verified.",
    ),
    "scan_preflight_failed": (
        "validation",
        "Scan intake failed bounded source or workspace preflight.",
    ),
    "source_retention_failed": (
        "storage",
        "Scan source retention did not complete.",
    ),
    "qr_missing": (
        "qr",
        "QR detection did not find a usable locator on the retained page.",
    ),
    "qr_unreadable": (
        "qr",
        "QR image detection failed before a usable locator was obtained.",
    ),
    "payload_invalid": (
        "qr",
        "Decoded locator payload failed bounded validation.",
    ),
    "route_dispatch_failed": (
        "routing",
        "Core route dispatch did not complete for the requested page.",
    ),
    "dispatch_integration_failed": (
        "routing",
        "Returned route-dispatch state could not be integrated safely.",
    ),
    "scoreform_result_invalid": (
        "scoring",
        "Returned ScoreForm page result failed bounded validation.",
    ),
    "attempt_incomplete": (
        "scoring",
        "Attempt assembly found incomplete canonical page state.",
    ),
    "attempt_identity_conflict": (
        "scoring",
        "Attempt assembly found conflicting canonical identity state.",
    ),
    "attempt_assembly_failed": (
        "scoring",
        "Attempt assembly did not complete.",
    ),
    "result_persistence_failed": (
        "results",
        "Result persistence did not complete.",
    ),
    "result_persistence_partial_success": (
        "storage",
        "Result persistence may already be durable and requires inspection.",
    ),
    "result_persistence_verified": (
        "results",
        "Result persistence completed and was verified.",
    ),
    "scan_review_resolution_failed": (
        "scan_review",
        "Scan-review resolution did not complete.",
    ),
    "scan_review_recovered": (
        "recovery",
        "Scan-review recovery completed and was verified.",
    ),
    "registration_conflict": (
        "publication",
        "Academic Work Registration encountered a current-state conflict.",
    ),
    "registration_partial_success": (
        "publication",
        "Academic Work Registration may already be durable and requires inspection.",
    ),
    "manifest_generation_failed": (
        "publication",
        "Academic Result manifest generation did not complete.",
    ),
    "manifest_partial_success": (
        "publication",
        "Academic Result manifest generation may already be durable.",
    ),
    "manifest_revision_created": (
        "publication",
        "Academic Result manifest revision was created and verified.",
    ),
    "publication_conflict": (
        "publication",
        "Core publication encountered a current-state conflict.",
    ),
    "stale_core_head": (
        "publication",
        "Core publication head changed before the requested transition.",
    ),
    "publication_partial_success": (
        "publication",
        "Core publication may already be durable and requires inspection.",
    ),
    "catalog_reconciliation_failed": (
        "publication",
        "Core publication exists but catalog reconciliation did not verify.",
    ),
    "publication_verified": (
        "publication",
        "Core publication completed and final status was verified.",
    ),
    "supersession_verified": (
        "publication",
        "Core publication supersession completed and final status was verified.",
    ),
    "share_state_changed": (
        "publication",
        "Share Results canonical state changed after teacher authorization.",
    ),
    "diagnostic_retention_warning": (
        "diagnostics",
        "Diagnostic retention could not complete safely.",
    ),
}

_EVENT_ID_RE: Final = re.compile(r"diag_[0-9a-f]{32}\Z")
_EXCEPTION_TYPE_RE: Final = re.compile(r"[A-Za-z_][A-Za-z0-9_.]{0,127}\Z")
_VERSION_RE: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+!_-]{0,63}\Z")
_DATE_RE: Final = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")
_REPARSE_POINT_ATTRIBUTE: Final = 0x400

_REQUIRED_FIELDS: Final = frozenset(
    {
        "schema_version",
        "module",
        "record_type",
        "event_id",
        "occurred_at",
        "scoreform_version",
        "core_version",
        "component",
        "workflow",
        "stage",
        "outcome",
        "category",
        "code",
        "class_id",
        "assignment_id",
        "exception_type",
        "safe_summary",
        "path_context",
    }
)


class DiagnosticEventError(ValueError):
    """Base error for local diagnostic event operations."""


class DiagnosticEventValidationError(DiagnosticEventError):
    """One diagnostic event or request is invalid or privacy-unsafe."""


class DiagnosticEventStorageError(DiagnosticEventError):
    """Diagnostic storage is unavailable, unsafe, or uncertain."""

    def __init__(self, message: str, *, possibly_durable: bool = False) -> None:
        super().__init__(message)
        self.possibly_durable = possibly_durable


@dataclass(frozen=True, slots=True)
class DiagnosticEvent:
    schema_version: str
    module: str
    record_type: str
    event_id: str
    occurred_at: str
    scoreform_version: str
    core_version: str
    component: str
    workflow: str
    stage: str
    outcome: str
    category: str
    code: str
    class_id: str | None
    assignment_id: str | None
    exception_type: str | None
    safe_summary: str
    path_context: str | None


@dataclass(frozen=True, slots=True)
class DiagnosticEventWriteResult:
    event: DiagnosticEvent
    relative_path: str
    retention_pruned_count: int
    retention_warning: str | None


@dataclass(frozen=True, slots=True)
class DiagnosticEventAttempt:
    recorded: bool
    event_id: str | None
    warning_code: str | None


@dataclass(frozen=True, slots=True)
class DiagnosticEventListing:
    events: tuple[DiagnosticEvent, ...]
    warning_codes: tuple[str, ...]


def build_diagnostic_event(
    *,
    component: str,
    workflow: str,
    stage: str,
    outcome: str,
    code: str,
    class_id: str | None = None,
    assignment_id: str | None = None,
    exception: BaseException | None = None,
    workspace_root: str | Path | None = None,
    path: str | Path | None = None,
    occurred_at: datetime | None = None,
    event_id: str | None = None,
) -> DiagnosticEvent:
    """Build one privacy-minimal event from fixed vocabularies and safe context."""
    _require_member(component, "component", _COMPONENTS)
    _require_member(workflow, "workflow", _WORKFLOWS)
    _require_member(stage, "stage", _STAGES)
    _require_member(outcome, "outcome", _OUTCOMES)
    contract = _CODE_CONTRACTS.get(code)
    if contract is None:
        raise DiagnosticEventValidationError("code is not a supported diagnostic code.")
    category, safe_summary = contract
    _require_member(category, "category", _CATEGORIES)

    normalized_class = _optional_identifier(class_id, "class_id")
    normalized_assignment = _optional_identifier(assignment_id, "assignment_id")

    if path is not None and workspace_root is None:
        raise DiagnosticEventValidationError(
            "workspace_root is required when path context is supplied."
        )
    path_context = (
        None
        if path is None
        else sanitize_diagnostic_path(
            cast(str | Path, workspace_root),
            path,
            class_id=normalized_class,
            assignment_id=normalized_assignment,
        )
    )

    event = DiagnosticEvent(
        schema_version=DIAGNOSTIC_SCHEMA_VERSION,
        module=DIAGNOSTIC_MODULE,
        record_type=DIAGNOSTIC_RECORD_TYPE,
        event_id=event_id or _new_event_id(),
        occurred_at=_normalize_timestamp(occurred_at),
        scoreform_version=_scoreform_version(),
        core_version=_installed_core_version(),
        component=component,
        workflow=workflow,
        stage=stage,
        outcome=outcome,
        category=category,
        code=code,
        class_id=normalized_class,
        assignment_id=normalized_assignment,
        exception_type=_safe_exception_type(exception),
        safe_summary=safe_summary,
        path_context=path_context,
    )
    validate_diagnostic_event(event)
    return event


def validate_diagnostic_event(event: DiagnosticEvent) -> None:
    """Validate the exact schema-v1 event and its privacy-bounded values."""
    if not isinstance(event, DiagnosticEvent):
        raise DiagnosticEventValidationError(
            "diagnostic event must be a DiagnosticEvent."
        )
    if event.schema_version != DIAGNOSTIC_SCHEMA_VERSION:
        raise DiagnosticEventValidationError("Unsupported diagnostic schema version.")
    if event.module != DIAGNOSTIC_MODULE:
        raise DiagnosticEventValidationError("Diagnostic module must be scoreform.")
    if event.record_type != DIAGNOSTIC_RECORD_TYPE:
        raise DiagnosticEventValidationError("Invalid diagnostic record type.")
    _validate_event_id(event.event_id)
    _parse_timestamp(event.occurred_at)
    _validated_version(event.scoreform_version, "scoreform_version")
    _validated_version(event.core_version, "core_version")
    _require_member(event.component, "component", _COMPONENTS)
    _require_member(event.workflow, "workflow", _WORKFLOWS)
    _require_member(event.stage, "stage", _STAGES)
    _require_member(event.outcome, "outcome", _OUTCOMES)
    _require_member(event.category, "category", _CATEGORIES)

    contract = _CODE_CONTRACTS.get(event.code)
    if contract is None:
        raise DiagnosticEventValidationError("Unsupported diagnostic code.")
    expected_category, expected_summary = contract
    if event.category != expected_category:
        raise DiagnosticEventValidationError(
            "Diagnostic code/category combination is invalid."
        )
    if event.safe_summary != expected_summary:
        raise DiagnosticEventValidationError(
            "safe_summary must be the fixed summary owned by the diagnostic code."
        )

    _optional_identifier(event.class_id, "class_id")
    _optional_identifier(event.assignment_id, "assignment_id")
    if event.exception_type is not None:
        if (
            type(event.exception_type) is not str
            or _EXCEPTION_TYPE_RE.fullmatch(event.exception_type) is None
        ):
            raise DiagnosticEventValidationError(
                "exception_type must be a bounded exception class name."
            )
    if event.path_context is not None:
        _validate_sanitized_path_context(
            event.path_context,
            class_id=event.class_id,
            assignment_id=event.assignment_id,
        )


def diagnostic_events_dir(workspace_root: str | Path) -> Path:
    """Return the ScoreForm-local event directory without creating it."""
    root = _canonical_workspace_root(workspace_root)
    return root.joinpath(*EVENT_DIRECTORY_PARTS)


def diagnostic_event_path(
    workspace_root: str | Path,
    event_id: str,
) -> Path:
    """Return one exact event path without creating anything."""
    _validate_event_id(event_id)
    return diagnostic_events_dir(workspace_root) / f"{event_id}.json"


def sanitize_diagnostic_path(
    workspace_root: str | Path,
    path: str | Path,
    *,
    class_id: str | None = None,
    assignment_id: str | None = None,
) -> str:
    """Reduce one workspace path to an allowlisted privacy-safe context."""
    root = _canonical_workspace_root(workspace_root)
    raw = Path(path)
    if ".." in raw.parts:
        raise DiagnosticEventValidationError(
            "Diagnostic path context must not contain traversal."
        )
    candidate = raw if raw.is_absolute() else root / raw
    candidate = Path(os.path.abspath(candidate))
    try:
        relative = candidate.relative_to(root)
    except ValueError as error:
        raise DiagnosticEventValidationError(
            "Diagnostic path must remain inside the selected workspace."
        ) from error
    _preflight_existing_path_chain(root, candidate)

    parts = relative.parts
    if not parts:
        raise DiagnosticEventValidationError(
            "Workspace root itself is not a useful diagnostic path context."
        )

    normalized_class = _optional_identifier(class_id, "class_id")
    normalized_assignment = _optional_identifier(assignment_id, "assignment_id")

    if len(parts) >= 6 and parts[0] == "classes":
        path_class = _identifier(parts[1], "path class_id")
        if parts[2:5] != ("modules", "scoreform", "work"):
            raise DiagnosticEventValidationError(
                "Class path is not a ScoreForm work diagnostic context."
            )
        path_assignment = _identifier(parts[5], "path assignment_id")
        if normalized_class is not None and path_class != normalized_class:
            raise DiagnosticEventValidationError(
                "Diagnostic path class_id does not match event class_id."
            )
        if (
            normalized_assignment is not None
            and path_assignment != normalized_assignment
        ):
            raise DiagnosticEventValidationError(
                "Diagnostic path assignment_id does not match event assignment_id."
            )
        prefix = (
            f"classes/{path_class}/modules/scoreform/work/{path_assignment}"
        )
        tail = parts[6:]
        if not tail:
            return prefix
        if tail == ("assignment.json",):
            return f"{prefix}/assignment.json"
        if tail == ("results.csv",):
            return f"{prefix}/results.csv"
        if tail[0] == "answer_sheets":
            return f"{prefix}/answer_sheets/<artifact>"
        if tail[0] == "templates":
            return f"{prefix}/templates/<artifact>"
        if tail[0] == "scans":
            return f"{prefix}/scans/<source>"
        if tail[0] == "debug":
            return f"{prefix}/debug/<diagnostic>"
        if tail[0] == "exports":
            return f"{prefix}/exports/<artifact>"
        return f"{prefix}/<artifact>"

    if parts[:4] == EVENT_DIRECTORY_PARTS:
        return "shared/scoreform/diagnostics/events/<event>"
    if len(parts) >= 2 and parts[:2] == ("scans", "review"):
        return "scans/review/<failure>"
    if len(parts) >= 2 and parts[:2] == ("scans", "source"):
        return "scans/source/<source>"
    if parts[0] == "scans":
        return "scans/<source>"
    if len(parts) >= 2 and parts[:2] == ("local_outputs", "qr_failures"):
        if len(parts) >= 3 and _DATE_RE.fullmatch(parts[2]) is not None:
            return "local_outputs/qr_failures/<date>/<diagnostic>"
        return "local_outputs/qr_failures/<diagnostic>"

    raise DiagnosticEventValidationError(
        "Path does not match a supported privacy-safe diagnostic context."
    )


def record_diagnostic_event(
    workspace_root: str | Path,
    event: DiagnosticEvent,
) -> DiagnosticEventWriteResult:
    """Persist one immutable event and apply conservative bounded retention."""
    validate_diagnostic_event(event)
    root = _canonical_workspace_root(workspace_root)
    directory = _ensure_event_directory(root)
    path = directory / f"{event.event_id}.json"
    data = _serialize_event(event)
    _preflight_event_target(root, path)
    _create_exclusive_bytes(path, data, event)

    pruned_count = 0
    retention_warning: str | None = None
    try:
        pruned_count = _prune_retention(
            root,
            max_events=DEFAULT_EVENT_RETENTION_LIMIT,
        )
    except (OSError, DiagnosticEventError):
        retention_warning = "diagnostic_retention_degraded"

    return DiagnosticEventWriteResult(
        event=event,
        relative_path=path.relative_to(root).as_posix(),
        retention_pruned_count=pruned_count,
        retention_warning=retention_warning,
    )


def try_record_diagnostic_event(
    workspace_root: str | Path,
    event: DiagnosticEvent,
) -> DiagnosticEventAttempt:
    """Best-effort persistence that can never replace the primary outcome."""
    try:
        result = record_diagnostic_event(workspace_root, event)
    except DiagnosticEventStorageError as error:
        return DiagnosticEventAttempt(
            recorded=False,
            event_id=getattr(event, "event_id", None),
            warning_code=(
                "diagnostic_write_may_be_durable"
                if error.possibly_durable
                else "diagnostic_write_failed"
            ),
        )
    except (DiagnosticEventError, OSError, ValueError, TypeError):
        return DiagnosticEventAttempt(
            recorded=False,
            event_id=getattr(event, "event_id", None),
            warning_code="diagnostic_write_failed",
        )
    return DiagnosticEventAttempt(
        recorded=True,
        event_id=result.event.event_id,
        warning_code=result.retention_warning,
    )


def try_emit_diagnostic_event(
    workspace_root: str | Path,
    *,
    component: str,
    workflow: str,
    stage: str,
    outcome: str,
    code: str,
    class_id: str | None = None,
    assignment_id: str | None = None,
    exception: BaseException | None = None,
    path: str | Path | None = None,
) -> DiagnosticEventAttempt:
    """Build and persist one event without ever replacing the primary outcome."""
    try:
        event = build_diagnostic_event(
            component=component,
            workflow=workflow,
            stage=stage,
            outcome=outcome,
            code=code,
            class_id=class_id,
            assignment_id=assignment_id,
            exception=exception,
            workspace_root=workspace_root if path is not None else None,
            path=path,
        )
        return try_record_diagnostic_event(workspace_root, event)
    except Exception:
        return DiagnosticEventAttempt(
            recorded=False,
            event_id=None,
            warning_code="diagnostic_instrumentation_failed",
        )


def load_diagnostic_event(
    workspace_root: str | Path,
    event_id: str,
) -> DiagnosticEvent:
    """Load one exact immutable event without creating or repairing state."""
    _validate_event_id(event_id)
    root = _canonical_workspace_root(workspace_root)
    directory = _existing_event_directory(root)
    if directory is None:
        raise DiagnosticEventStorageError("Diagnostic event was not found.")
    path = directory / f"{event_id}.json"
    _preflight_event_target(root, path)
    if not os.path.lexists(path):
        raise DiagnosticEventStorageError("Diagnostic event was not found.")
    if _is_link_like(path) or not path.is_file():
        raise DiagnosticEventStorageError(
            "Diagnostic event path is not an ordinary file."
        )
    try:
        event = _deserialize_event(path.read_bytes())
    except (OSError, DiagnosticEventError, ValueError) as error:
        raise DiagnosticEventStorageError(
            "Diagnostic event could not be loaded safely."
        ) from error
    if event.event_id != event_id:
        raise DiagnosticEventStorageError(
            "Diagnostic event identity does not match its filename."
        )
    return event


def list_diagnostic_events(
    workspace_root: str | Path,
    *,
    limit: int = DEFAULT_EVENT_LIST_LIMIT,
) -> DiagnosticEventListing:
    """List recent valid events newest-first without creating or repairing state."""
    normalized_limit = _validate_list_limit(limit)
    root = _canonical_workspace_root(workspace_root)
    directory = _existing_event_directory(root)
    if directory is None:
        return DiagnosticEventListing(events=(), warning_codes=())

    events: list[DiagnosticEvent] = []
    warnings: list[str] = []
    try:
        entries = tuple(sorted(directory.iterdir(), key=lambda item: item.name))
    except OSError as error:
        raise DiagnosticEventStorageError(
            "Diagnostic event directory could not be inspected."
        ) from error

    for path in entries:
        if _is_link_like(path) or not path.is_file():
            warnings.append("unexpected_diagnostic_entry")
            continue
        if path.suffix != ".json" or _EVENT_ID_RE.fullmatch(path.stem) is None:
            warnings.append("unexpected_diagnostic_entry")
            continue
        try:
            event = _deserialize_event(path.read_bytes())
            if event.event_id != path.stem:
                raise DiagnosticEventValidationError(
                    "Diagnostic event ID does not match filename."
                )
        except (OSError, DiagnosticEventError, ValueError):
            warnings.append("invalid_diagnostic_event")
            continue
        events.append(event)

    events.sort(key=lambda item: (item.occurred_at, item.event_id), reverse=True)
    return DiagnosticEventListing(
        events=tuple(events[:normalized_limit]),
        warning_codes=tuple(warnings[:MAX_EVENT_LIST_LIMIT]),
    )


def _serialize_event(event: DiagnosticEvent) -> bytes:
    validate_diagnostic_event(event)
    payload = {
        "schema_version": event.schema_version,
        "module": event.module,
        "record_type": event.record_type,
        "event_id": event.event_id,
        "occurred_at": event.occurred_at,
        "scoreform_version": event.scoreform_version,
        "core_version": event.core_version,
        "component": event.component,
        "workflow": event.workflow,
        "stage": event.stage,
        "outcome": event.outcome,
        "category": event.category,
        "code": event.code,
        "class_id": event.class_id,
        "assignment_id": event.assignment_id,
        "exception_type": event.exception_type,
        "safe_summary": event.safe_summary,
        "path_context": event.path_context,
    }
    return (
        json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _deserialize_event(data: bytes) -> DiagnosticEvent:
    value = _strict_json_object(data)
    if frozenset(value) != _REQUIRED_FIELDS:
        raise DiagnosticEventValidationError(
            "Diagnostic event must contain exactly the schema-v1 fields."
        )
    event = DiagnosticEvent(
        schema_version=_json_text(value["schema_version"], "schema_version"),
        module=_json_text(value["module"], "module"),
        record_type=_json_text(value["record_type"], "record_type"),
        event_id=_json_text(value["event_id"], "event_id"),
        occurred_at=_json_text(value["occurred_at"], "occurred_at"),
        scoreform_version=_json_text(
            value["scoreform_version"], "scoreform_version"
        ),
        core_version=_json_text(value["core_version"], "core_version"),
        component=_json_text(value["component"], "component"),
        workflow=_json_text(value["workflow"], "workflow"),
        stage=_json_text(value["stage"], "stage"),
        outcome=_json_text(value["outcome"], "outcome"),
        category=_json_text(value["category"], "category"),
        code=_json_text(value["code"], "code"),
        class_id=_json_optional_text(value["class_id"], "class_id"),
        assignment_id=_json_optional_text(
            value["assignment_id"], "assignment_id"
        ),
        exception_type=_json_optional_text(
            value["exception_type"], "exception_type"
        ),
        safe_summary=_json_text(value["safe_summary"], "safe_summary"),
        path_context=_json_optional_text(value["path_context"], "path_context"),
    )
    validate_diagnostic_event(event)
    return event


def _json_text(value: object, field: str) -> str:
    if type(value) is not str:
        raise DiagnosticEventValidationError(
            f"Diagnostic event field {field!r} must be text."
        )
    return value


def _json_optional_text(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _json_text(value, field)


def _strict_json_object(data: bytes) -> dict[str, object]:
    def pairs_hook(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise DiagnosticEventValidationError(
                    "Diagnostic event contains a duplicate JSON key."
                )
            result[key] = value
        return result

    def reject_constant(_value: str) -> object:
        raise DiagnosticEventValidationError(
            "Diagnostic event contains a non-finite JSON number."
        )

    try:
        value = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=pairs_hook,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DiagnosticEventValidationError(
            "Diagnostic event is not strict UTF-8 JSON."
        ) from error
    if not isinstance(value, dict):
        raise DiagnosticEventValidationError("Diagnostic event must be a JSON object.")
    return cast(dict[str, object], value)


def _canonical_workspace_root(workspace_root: str | Path) -> Path:
    if not isinstance(workspace_root, (str, Path)):
        raise DiagnosticEventStorageError(
            "workspace_root must identify an existing directory."
        )
    path = Path(os.path.abspath(Path(workspace_root)))
    if _is_link_like(path) or not path.is_dir():
        raise DiagnosticEventStorageError(
            "workspace_root must be an existing ordinary non-link directory."
        )
    return path


def _is_link_like(path: Path) -> bool:
    try:
        info = os.lstat(path)
    except (FileNotFoundError, NotADirectoryError):
        return False
    except OSError as error:
        raise DiagnosticEventStorageError(
            "Diagnostic path safety could not be inspected."
        ) from error
    if stat.S_ISLNK(info.st_mode):
        return True
    attributes = getattr(info, "st_file_attributes", 0)
    return bool(attributes & _REPARSE_POINT_ATTRIBUTE)


def _ensure_event_directory(root: Path) -> Path:
    current = root
    for component in EVENT_DIRECTORY_PARTS:
        current = current / component
        if os.path.lexists(current):
            _require_safe_directory(current)
            continue
        try:
            current.mkdir()
        except FileExistsError:
            pass
        except OSError as error:
            raise DiagnosticEventStorageError(
                "Diagnostic event directory could not be created safely."
            ) from error
        _require_safe_directory(current)
    return current


def _existing_event_directory(root: Path) -> Path | None:
    current = root
    for component in EVENT_DIRECTORY_PARTS:
        current = current / component
        if not os.path.lexists(current):
            return None
        _require_safe_directory(current)
    return current


def _require_safe_directory(path: Path) -> None:
    if _is_link_like(path) or not path.is_dir():
        raise DiagnosticEventStorageError(
            "Diagnostic storage path must be an ordinary non-link directory."
        )


def _preflight_event_target(root: Path, target: Path) -> None:
    try:
        relative = Path(os.path.abspath(target)).relative_to(root)
    except ValueError as error:
        raise DiagnosticEventStorageError(
            "Diagnostic event path escaped the selected workspace."
        ) from error
    current = root
    _require_safe_directory(current)
    for index, part in enumerate(relative.parts):
        current = current / part
        if not os.path.lexists(current):
            continue
        if _is_link_like(current):
            raise DiagnosticEventStorageError(
                "Diagnostic storage path contains a link-like entry."
            )
        is_last = index == len(relative.parts) - 1
        if is_last:
            if not current.is_file():
                raise DiagnosticEventStorageError(
                    "Diagnostic event target is not an ordinary file."
                )
        elif not current.is_dir():
            raise DiagnosticEventStorageError(
                "Diagnostic storage parent is not an ordinary directory."
            )


def _preflight_existing_path_chain(root: Path, target: Path) -> None:
    try:
        relative = target.relative_to(root)
    except ValueError as error:
        raise DiagnosticEventValidationError(
            "Diagnostic path must remain inside the selected workspace."
        ) from error
    current = root
    if _is_link_like(current) or not current.is_dir():
        raise DiagnosticEventValidationError("Workspace path is not safe.")
    for part in relative.parts:
        current = current / part
        if not os.path.lexists(current):
            continue
        if _is_link_like(current):
            raise DiagnosticEventValidationError(
                "Diagnostic path context contains a link-like entry."
            )


def _create_exclusive_bytes(
    path: Path,
    data: bytes,
    expected: DiagnosticEvent,
) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except OSError as error:
        raise DiagnosticEventStorageError(
            "Diagnostic event could not be created exclusively."
        ) from error

    write_error: OSError | None = None
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as error:
        write_error = error
    if write_error is not None:
        raise DiagnosticEventStorageError(
            "Diagnostic event write may already be durable.",
            possibly_durable=True,
        ) from write_error

    try:
        written = path.read_bytes()
        loaded = _deserialize_event(written)
    except (OSError, DiagnosticEventError, ValueError) as error:
        raise DiagnosticEventStorageError(
            "Diagnostic event write may already be durable but could not be verified.",
            possibly_durable=True,
        ) from error
    if written != data or loaded != expected:
        raise DiagnosticEventStorageError(
            "Diagnostic event write may already be durable but verification differed.",
            possibly_durable=True,
        )


def _prune_retention(root: Path, *, max_events: int) -> int:
    if (
        isinstance(max_events, bool)
        or not isinstance(max_events, int)
        or max_events < 1
    ):
        raise DiagnosticEventValidationError(
            "Diagnostic retention limit must be a positive integer."
        )
    directory = _existing_event_directory(root)
    if directory is None:
        return 0
    candidates: list[tuple[DiagnosticEvent, Path, bytes]] = []
    for path in tuple(sorted(directory.iterdir(), key=lambda item: item.name)):
        if _is_link_like(path) or not path.is_file():
            continue
        if path.suffix != ".json" or _EVENT_ID_RE.fullmatch(path.stem) is None:
            continue
        try:
            original_bytes = path.read_bytes()
            event = _deserialize_event(original_bytes)
        except (OSError, DiagnosticEventError, ValueError):
            continue
        if event.event_id != path.stem:
            continue
        candidates.append((event, path, original_bytes))
    candidates.sort(key=lambda item: (item[0].occurred_at, item[0].event_id))
    overflow = len(candidates) - max_events
    if overflow <= 0:
        return 0
    removed = 0
    for _event, path, expected_bytes in candidates[:overflow]:
        if _is_link_like(path) or not path.is_file():
            raise DiagnosticEventStorageError(
                "Owned diagnostic event changed before retention cleanup."
            )
        try:
            if path.read_bytes() != expected_bytes:
                raise DiagnosticEventStorageError(
                    "Owned diagnostic event changed before retention cleanup."
                )
            path.unlink()
        except DiagnosticEventStorageError:
            raise
        except OSError as error:
            raise DiagnosticEventStorageError(
                "Diagnostic retention could not remove an owned old event."
            ) from error
        removed += 1
    return removed


def _validate_sanitized_path_context(
    value: str,
    *,
    class_id: str | None,
    assignment_id: str | None,
) -> None:
    if type(value) is not str or not value or len(value) > 512:
        raise DiagnosticEventValidationError(
            "path_context must be bounded canonical POSIX text."
        )
    if "\\" in value or ":" in value:
        raise DiagnosticEventValidationError(
            "path_context must not contain machine-specific path syntax."
        )
    path = Path(value)
    if path.is_absolute() or value != path.as_posix():
        raise DiagnosticEventValidationError(
            "path_context must be workspace-relative POSIX text."
        )
    if any(part in {"", ".", ".."} for part in path.parts):
        raise DiagnosticEventValidationError("path_context contains unsafe traversal.")

    parts = path.parts
    if len(parts) >= 6 and parts[0] == "classes":
        if parts[2:5] != ("modules", "scoreform", "work"):
            raise DiagnosticEventValidationError(
                "path_context is not a ScoreForm work path."
            )
        path_class = _identifier(parts[1], "path class_id")
        path_assignment = _identifier(parts[5], "path assignment_id")
        if class_id is not None and path_class != class_id:
            raise DiagnosticEventValidationError(
                "path_context class_id does not match event class_id."
            )
        if assignment_id is not None and path_assignment != assignment_id:
            raise DiagnosticEventValidationError(
                "path_context assignment_id does not match event assignment_id."
            )
        tail = parts[6:]
        allowed = {
            (),
            ("assignment.json",),
            ("results.csv",),
            ("answer_sheets", "<artifact>"),
            ("templates", "<artifact>"),
            ("scans", "<source>"),
            ("debug", "<diagnostic>"),
            ("exports", "<artifact>"),
            ("<artifact>",),
        }
        if tail not in allowed:
            raise DiagnosticEventValidationError(
                "path_context is not an approved sanitized work-path shape."
            )
        return

    if parts == ("shared", "scoreform", "diagnostics", "events", "<event>"):
        return
    if parts in {
        ("scans", "review", "<failure>"),
        ("scans", "source", "<source>"),
        ("scans", "<source>"),
        ("local_outputs", "qr_failures", "<diagnostic>"),
        ("local_outputs", "qr_failures", "<date>", "<diagnostic>"),
    }:
        return
    raise DiagnosticEventValidationError(
        "path_context is not an approved sanitized diagnostic path."
    )


def _validate_list_limit(limit: int) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise DiagnosticEventValidationError(
            "Diagnostic list limit must be an integer."
        )
    if not 1 <= limit <= MAX_EVENT_LIST_LIMIT:
        raise DiagnosticEventValidationError(
            f"Diagnostic list limit must be between 1 and {MAX_EVENT_LIST_LIMIT}."
        )
    return limit


def _new_event_id() -> str:
    return f"diag_{secrets.token_hex(16)}"


def _validate_event_id(value: object) -> str:
    if type(value) is not str or _EVENT_ID_RE.fullmatch(value) is None:
        raise DiagnosticEventValidationError(
            "event_id must be an opaque schema-v1 diagnostic identifier."
        )
    return value


def _normalize_timestamp(value: datetime | None) -> str:
    instant = datetime.now(timezone.utc) if value is None else value
    if not isinstance(instant, datetime) or instant.tzinfo is None:
        raise DiagnosticEventValidationError(
            "occurred_at must be a timezone-aware datetime."
        )
    utc = instant.astimezone(timezone.utc)
    return utc.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_timestamp(value: object) -> datetime:
    if type(value) is not str or not value.endswith("Z"):
        raise DiagnosticEventValidationError(
            "occurred_at must be canonical UTC timestamp text."
        )
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise DiagnosticEventValidationError(
            "occurred_at is not a valid timestamp."
        ) from error
    if parsed.tzinfo != timezone.utc:
        raise DiagnosticEventValidationError("occurred_at must use UTC.")
    canonical = parsed.isoformat(timespec="microseconds").replace("+00:00", "Z")
    if value != canonical:
        raise DiagnosticEventValidationError(
            "occurred_at must use canonical microsecond UTC formatting."
        )
    return parsed


def _scoreform_version() -> str:
    try:
        return _validated_version(metadata.version("scoreform"), "scoreform_version")
    except metadata.PackageNotFoundError:
        pass

    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    try:
        payload = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        project = payload.get("project")
        if isinstance(project, dict):
            value = project.get("version")
            return _validated_version(value, "scoreform_version")
    except (OSError, tomllib.TOMLDecodeError, DiagnosticEventValidationError):
        pass
    raise DiagnosticEventValidationError("ScoreForm package version is unavailable.")


def _installed_core_version() -> str:
    try:
        value = metadata.version("pds-core")
    except metadata.PackageNotFoundError as error:
        raise DiagnosticEventValidationError(
            "Installed pds-core version is unavailable."
        ) from error
    return _validated_version(value, "core_version")


def _validated_version(value: object, field: str) -> str:
    if type(value) is not str or _VERSION_RE.fullmatch(value) is None:
        raise DiagnosticEventValidationError(
            f"{field} must be bounded package-version text."
        )
    return value


def _safe_exception_type(error: BaseException | None) -> str | None:
    if error is None:
        return None
    name = type(error).__name__
    if _EXCEPTION_TYPE_RE.fullmatch(name) is None:
        return None
    return name


def _optional_identifier(value: str | None, field: str) -> str | None:
    if value is None:
        return None
    return _identifier(value, field)


def _identifier(value: object, field: str) -> str:
    if type(value) is not str:
        raise DiagnosticEventValidationError(f"{field} must be an identifier.")
    try:
        return validate_identifier(value, field)
    except (IdentifierValidationError, TypeError, ValueError) as error:
        raise DiagnosticEventValidationError(
            f"{field} must be a valid identifier."
        ) from error


def _require_member(value: object, field: str, allowed: frozenset[str]) -> str:
    if type(value) is not str or value not in allowed:
        raise DiagnosticEventValidationError(
            f"{field} is not a supported diagnostic value."
        )
    return value


__all__ = [
    "DEFAULT_EVENT_LIST_LIMIT",
    "DEFAULT_EVENT_RETENTION_LIMIT",
    "DIAGNOSTIC_MODULE",
    "DIAGNOSTIC_RECORD_TYPE",
    "DIAGNOSTIC_SCHEMA_VERSION",
    "MAX_EVENT_LIST_LIMIT",
    "DiagnosticEvent",
    "DiagnosticEventAttempt",
    "DiagnosticEventError",
    "DiagnosticEventListing",
    "DiagnosticEventStorageError",
    "DiagnosticEventValidationError",
    "DiagnosticEventWriteResult",
    "build_diagnostic_event",
    "diagnostic_event_path",
    "diagnostic_events_dir",
    "list_diagnostic_events",
    "load_diagnostic_event",
    "record_diagnostic_event",
    "sanitize_diagnostic_path",
    "try_emit_diagnostic_event",
    "try_record_diagnostic_event",
    "validate_diagnostic_event",
]
