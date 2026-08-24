"""Independent Core-v2 conversion and persistence of routed-scoring failures."""

from __future__ import annotations

import os
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from pds_core.module_dispatch import (
    ModuleContractCompatibilityError,
    RouteDispatchFailure,
    RouteDispatchSuccess,
)
from pds_core.pds2 import PDS2_MAX_PAYLOAD_BYTES
from pds_core.routing_models import (
    ModuleRecordRef,
    RouteLocator,
    RoutingModelError,
    validate_module_record_ref,
    validate_route_locator,
    validate_route_registration,
)
from pds_core.scan_failure_metadata import (
    ROUTING_FAILURE_SCHEMA_VERSION,
    RoutingFailureMetadata,
    RoutingFailureMetadataError,
    RoutingFailureMetadataWriteError,
    routing_failure_metadata_from_dispatch_failure,
    routing_failure_metadata_path,
    validate_routing_failure_metadata,
    write_routing_failure_metadata,
)
from pds_core.scan_retention import SourceRetentionError

from scoreform.attempt_assembly import ScoreFormRoutedScoringBatch
from scoreform.module_errors import (
    ScoreFormAssignmentCompatibilityError,
    ScoreFormIssuanceAuthorizationError,
    ScoreFormPageScoringError,
    ScoreFormQrDiagnosticWriteError,
    ScoreFormQrMissingError,
    ScoreFormRegistrationValidationError,
    ScoreFormRegistryError,
    ScoreFormRetainedPageError,
    ScoreFormRouteContextError,
    ScoreFormScanPreflightError,
    ScoreFormSourceMissingError,
    ScoreFormSourceTypeUnsupportedError,
    ScoreFormTargetIntegrityError,
)
from scoreform.pds2_scan_dispatch import Pds2ScanPageOutcome
from scoreform.scan_review_details import (
    isolated_json_value,
    sanitize_single_line,
    sanitized_exception,
    scoreform_failure_details,
)
from scoreform.scan_review_models import (
    ScoreFormFailurePersistenceBatch,
    ScoreFormFailurePersistenceError,
    ScoreFormPersistedFailure,
)

_MAX_ID_ATTEMPTS = 8


@dataclass(frozen=True, slots=True)
class _Occurrence:
    occurrence_key: str
    origin: str
    source_page_number: int | None
    convert: Callable[[str], RoutingFailureMetadata]


def operation_timestamp(now: datetime | None = None) -> datetime:
    value = datetime.now(timezone.utc) if now is None else now
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError("Review persistence timestamps must be timezone-aware.")
    return value.astimezone(timezone.utc)


def _identifier(prefix: str, timestamp: datetime) -> str:
    return f"{prefix}_{timestamp.strftime('%Y%m%dT%H%M%S%fZ')}_{secrets.token_hex(8)}"


def _filename(source_file: str | Path) -> str:
    try:
        name = Path(os.fspath(source_file)).name
    except (TypeError, ValueError):
        name = ""
    return sanitize_single_line(name, fallback="scan", limit=255)


def _message(error_or_text: object, fallback: str) -> str:
    raw = (
        str(error_or_text) if isinstance(error_or_text, (Exception, str)) else fallback
    )
    return sanitize_single_line(raw, fallback=fallback)


def _provenance(batch: ScoreFormRoutedScoringBatch, source_file: str | Path):
    retained = batch.dispatch_result.retained_source
    if retained is None:
        return (_filename(source_file), None, None, None)
    return (
        retained.source_filename,
        retained.source_scan_id,
        retained.source_sha256,
        retained.retained_source_relative_path,
    )


def _metadata(
    *,
    failure_id: str,
    created_at: str,
    scope: str,
    stage: str,
    category: str,
    message: object,
    provenance: tuple[str, str | None, str | None, str | None],
    page: int | None,
    payload: str | None,
    locator: RouteLocator | None,
    target: ModuleRecordRef | None,
    details: Mapping[str, object],
) -> RoutingFailureMetadata:
    filename, scan_id, sha256, retained_path = provenance
    return RoutingFailureMetadata(
        schema_version=ROUTING_FAILURE_SCHEMA_VERSION,
        failure_id=failure_id,
        scope=scope,
        stage=stage,
        created_at=created_at,
        failure_category=category,
        failure_message=_message(message, "ScoreForm routed scoring failed."),
        source_filename=filename,
        source_scan_id=scan_id,
        source_sha256=sha256,
        retained_source_path=retained_path,
        review_copy_path=None,
        source_page_number=page,
        detected_payload=payload,
        route_locator=locator,
        target=target,
        module_details=details,
    )


def _cause_chain(error: Exception):
    seen: set[int] = set()
    current: BaseException | None = error
    while isinstance(current, Exception) and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def _scoreform_dispatch_category(error: Exception) -> str:
    """Return stable ScoreForm-owned classification through Core error wrapping."""
    for item in _cause_chain(error):
        if isinstance(item, ScoreFormPageScoringError):
            return item.diagnostic_code
        if isinstance(item, ScoreFormAssignmentCompatibilityError):
            return "assignment_incompatible"
        if isinstance(item, ScoreFormIssuanceAuthorizationError):
            return "issuance_not_authorized"
        if isinstance(item, ScoreFormTargetIntegrityError):
            return "target_integrity"
        if isinstance(item, ScoreFormRetainedPageError):
            return "retained_page_invalid"
        if isinstance(item, ScoreFormRouteContextError):
            return "route_context_invalid"
        if isinstance(item, ScoreFormRegistrationValidationError):
            return "registration_invalid"
    return "route_dispatch"


def _file_mapping(error: Exception) -> tuple[str, str]:
    if isinstance(error, ScoreFormSourceMissingError):
        return "intake", "source_missing"
    if isinstance(error, ScoreFormSourceTypeUnsupportedError):
        return "intake", "source_type_unsupported"
    if isinstance(error, ScoreFormScanPreflightError):
        return "intake", "source_unreadable"
    if isinstance(error, SourceRetentionError):
        return "retention", "source_retention_failed"
    if isinstance(error, ScoreFormRegistryError):
        if any(
            isinstance(item, ModuleContractCompatibilityError)
            for item in _cause_chain(error)
        ):
            return "module_resolution", "module_profile_incompatible"
        return "module_resolution", "processing_error"
    return "module_handling", "processing_error"


def _payload_category(page: Pds2ScanPageOutcome) -> str:
    raw = page.raw_payload_text
    if raw is not None:
        encoded = raw.encode("utf-8")
        if len(encoded) > PDS2_MAX_PAYLOAD_BYTES:
            return "payload_too_large"
        if raw.split("|", 1)[0] != "PDS2":
            return "payload_schema_unsupported"
    if page.error is not None and any(
        isinstance(item, RoutingModelError) for item in _cause_chain(page.error)
    ):
        return "identifier_invalid"
    return "payload_invalid"


def _validated_occurrence_identity(
    page: Pds2ScanPageOutcome,
) -> tuple[RouteLocator | None, ModuleRecordRef | None]:
    try:
        locator = validate_route_locator(page.locator)
    except Exception:
        return None, None
    request = page.dispatch_request
    if request is None:
        return locator, None
    try:
        request_locator = validate_route_locator(request.locator)
        if request_locator != locator:
            return locator, None
    except Exception:
        return locator, None
    outcome = page.dispatch_outcome
    if not isinstance(outcome, RouteDispatchSuccess):
        return locator, None
    try:
        outcome_request_locator = validate_route_locator(outcome.request.locator)
        resolution_locator = validate_route_locator(outcome.resolution.locator)
        registration = validate_route_registration(outcome.resolution.registration)
        target = validate_module_record_ref(registration.target)
        if (
            outcome_request_locator != locator
            or resolution_locator != locator
            or registration.locator != locator
            or target.module_id != locator.module_id
            or outcome.profile.module_id != locator.module_id
        ):
            return locator, None
    except Exception:
        return locator, None
    return locator, target


def _page_core_mapping(page: Pds2ScanPageOutcome) -> tuple[str, str]:
    error = page.error
    stage = page.failure_stage
    if stage == "source_page_loading":
        return "decoding", "source_unreadable"
    if stage == "qr_detection":
        if isinstance(error, ScoreFormQrMissingError):
            return "payload", "payload_missing"
        return "payload", "payload_unreadable"
    if stage == "payload_parsing":
        return "payload", _payload_category(page)
    if stage == "request_construction":
        if isinstance(error, RoutingModelError):
            return "route_resolution", "identifier_invalid"
        return "route_resolution", "processing_error"
    if isinstance(error, ScoreFormQrDiagnosticWriteError):
        return "evidence", "evidence_write_failed"
    if stage == "core_outcome_validation":
        return "module_validation", "target_incompatible"
    if stage == "scoreform_result_validation":
        return "module_handling", "processing_error"
    return "module_handling", "processing_error"


def _page_details(
    page: Pds2ScanPageOutcome,
    origin: str,
    category: str,
    error: Exception,
    workspace_root: Path | None = None,
):
    def locator_value(value: object):
        try:
            locator = validate_route_locator(value)
        except Exception:
            return isolated_json_value(value)
        return {
            "schema": locator.schema,
            "module_id": locator.module_id,
            "class_id": locator.class_id,
            "work_id": locator.work_id,
            "route_id": locator.route_id,
        }

    def target_value(value: object):
        try:
            target = validate_module_record_ref(value)
        except Exception:
            return isolated_json_value(value)
        return {"module_id": target.module_id, "record_id": target.record_id}

    outcome = page.dispatch_outcome
    resolution = outcome.resolution if isinstance(outcome, RouteDispatchSuccess) else None
    registration = None if resolution is None else resolution.registration
    context = {
        "decode_method": page.decode_method,
        "page_locator": locator_value(page.locator),
        "request_locator": locator_value(
            None if page.dispatch_request is None else page.dispatch_request.locator
        ),
        "resolution_locator": locator_value(
            None if resolution is None else resolution.locator
        ),
        "registration_locator": locator_value(
            None if registration is None else registration.locator
        ),
        "registration_target": target_value(
            None if registration is None else registration.target
        ),
        "profile_module_id": (
            outcome.profile.module_id
            if isinstance(outcome, RouteDispatchSuccess)
            and isinstance(outcome.profile.module_id, str)
            else None
        ),
    }
    diagnostic_paths = []
    for value in page.diagnostic_paths:
        path = Path(value)
        if path.is_absolute():
            if workspace_root is None:
                continue
            try:
                value = path.resolve(strict=False).relative_to(
                    workspace_root
                ).as_posix()
            except (OSError, RuntimeError, ValueError):
                continue
        diagnostic_paths.append(value)
    return scoreform_failure_details(
        origin=origin,
        category=category,
        diagnostic_paths=tuple(diagnostic_paths),
        diagnostic_errors=(*page.diagnostic_errors, error),
        context=context,
    )


def _page_metadata(page, provenance, failure_id, created_at, workspace_root=None):
    outcome = page.dispatch_outcome
    if isinstance(outcome, RouteDispatchFailure):
        details = {}
        if outcome.request.locator.module_id == "scoreform":
            details = _page_details(
                page,
                "core_dispatch",
                _scoreform_dispatch_category(outcome.error),
                outcome.error,
                workspace_root,
            )
        metadata = routing_failure_metadata_from_dispatch_failure(
            outcome,
            failure_id=failure_id,
            created_at=created_at,
            detected_payload=page.raw_payload_text,
            target=None,
            module_details=details,
        )
        # Core owns category/stage/message; sanitize only its human-facing message.
        return RoutingFailureMetadata(
            schema_version=metadata.schema_version,
            failure_id=metadata.failure_id,
            scope=metadata.scope,
            stage=metadata.stage,
            created_at=metadata.created_at,
            failure_category=metadata.failure_category,
            failure_message=_message(
                metadata.failure_message, "Core route dispatch failed."
            ),
            source_filename=metadata.source_filename,
            source_scan_id=metadata.source_scan_id,
            source_sha256=metadata.source_sha256,
            retained_source_path=metadata.retained_source_path,
            review_copy_path=metadata.review_copy_path,
            source_page_number=metadata.source_page_number,
            detected_payload=metadata.detected_payload,
            route_locator=metadata.route_locator,
            target=metadata.target,
            module_details=metadata.module_details,
        )
    error = page.error
    if not isinstance(error, Exception):
        raise ValueError("A reviewable page occurrence requires an error.")
    core_stage, core_category = _page_core_mapping(page)
    origin = (
        "page_decode"
        if page.failure_stage
        in {"source_page_loading", "qr_detection", "payload_parsing"}
        else "scoreform_handling"
    )
    details_category = (
        _payload_category(page)
        if page.failure_stage == "payload_parsing"
        else page.failure_stage or "page_failure"
    )
    locator, target = _validated_occurrence_identity(page)
    return _metadata(
        failure_id=failure_id,
        created_at=created_at,
        scope="page",
        stage=core_stage,
        category=core_category,
        message=error,
        provenance=provenance,
        page=page.source_page_number,
        payload=page.raw_payload_text,
        locator=locator,
        target=target,
        details=_page_details(
            page,
            origin,
            details_category,
            error,
            workspace_root,
        ),
    )


def _assembly_mapping(category: str) -> tuple[str, str]:
    if category in {
        "missing_pages",
        "duplicate_page",
        "duplicate_route",
        "conflicting_duplicate",
        "invalid_page_order",
        "invalid_question_coverage",
    }:
        return "review", "page_conflict"
    if category in {
        "unexpected_page",
        "inconsistent_issuance",
        "invalid_result_identity",
    }:
        return "review", "target_incompatible"
    return "review", "processing_error"


def _export_mapping(stage: str) -> tuple[str, str]:
    if stage == "integrity":
        return "review", "processing_error"
    return "evidence", "evidence_write_failed"


def _safe_output_context(path: Path, root: Path | None) -> dict[str, object]:
    try:
        if root is not None:
            relative = path.resolve(strict=False).relative_to(root).as_posix()
            return {"output_kind": "workspace_relative", "output_path": relative}
    except (OSError, RuntimeError, ValueError):
        pass
    return {
        "output_kind": "external_explicit",
        "output_path": {"marker": "external", "basename": _filename(path)},
    }


def _occurrences(
    batch: ScoreFormRoutedScoringBatch,
    source_file: str | Path,
    *,
    workspace_root: Path | None,
    created_at: str,
) -> tuple[_Occurrence, ...]:
    provenance = _provenance(batch, source_file)
    occurrences: list[_Occurrence] = []
    dispatch = batch.dispatch_result
    if dispatch.file_error is not None:
        error = dispatch.file_error

        def convert_file(failure_id: str, error=error):
            stage, category = _file_mapping(error)
            return _metadata(
                failure_id=failure_id,
                created_at=created_at,
                scope="scan",
                stage=stage,
                category=category,
                message=error,
                provenance=provenance,
                page=None,
                payload=None,
                locator=None,
                target=None,
                details=scoreform_failure_details(
                    origin="scan_intake",
                    category=type(error).__name__.lower(),
                    diagnostic_errors=(error,),
                    context={},
                ),
            )

        occurrences.append(
            _Occurrence("scan_intake:0", "scan_intake", None, convert_file)
        )
    for page in dispatch.pages:
        if page.failure_stage is not None or isinstance(
            page.dispatch_outcome, RouteDispatchFailure
        ):

            def convert_page(failure_id: str, page=page):
                return _page_metadata(
                    page, provenance, failure_id, created_at, workspace_root
                )

            occurrences.append(
                _Occurrence(
                    f"page:{page.source_page_number}",
                    "core_dispatch"
                    if isinstance(page.dispatch_outcome, RouteDispatchFailure)
                    else (
                        "page_decode"
                        if page.failure_stage
                        in {"source_page_loading", "qr_detection", "payload_parsing"}
                        else "scoreform_handling"
                    ),
                    page.source_page_number,
                    convert_page,
                )
            )
    pages = {page.source_page_number: page for page in dispatch.pages}
    for index, invalid in enumerate(batch.assembly_result.invalid_observations, 1):

        def convert_invalid(failure_id: str, invalid=invalid):
            wrapper = pages.get(invalid.source_page_number)
            locator, target = (
                (None, None)
                if wrapper is None
                else _validated_occurrence_identity(wrapper)
            )
            raw = {
                name: isolated_json_value(getattr(invalid, name))
                for name in (
                    "raw_route_id",
                    "raw_page_id",
                    "raw_issuance_id",
                    "raw_generation_id",
                    "raw_artifact_id",
                    "raw_class_id",
                    "raw_assignment_id",
                    "raw_student_id",
                    "raw_source_scan_id",
                    "raw_retained_source_relative_path",
                    "raw_source_sha256",
                )
            }
            return _metadata(
                failure_id=failure_id,
                created_at=created_at,
                scope="page",
                stage="module_validation",
                category="target_incompatible",
                message=invalid.error,
                provenance=provenance,
                page=invalid.source_page_number,
                payload=(None if wrapper is None else wrapper.raw_payload_text),
                locator=locator,
                target=target,
                details=scoreform_failure_details(
                    origin="invalid_page_observation",
                    category="invalid_result_identity",
                    diagnostic_paths=invalid.diagnostic_paths,
                    diagnostic_errors=(invalid.error,),
                    context={
                        **raw,
                        "source_page_number": invalid.source_page_number,
                        "validated_wrapper_route_id": invalid.route_id,
                    },
                ),
            )

        occurrences.append(
            _Occurrence(
                f"invalid_observation:{invalid.source_page_number}:{index}",
                "invalid_page_observation",
                invalid.source_page_number,
                convert_invalid,
            )
        )
    for index, failure in enumerate(batch.assembly_result.failures, 1):

        def convert_assembly(failure_id: str, failure=failure):
            stage, category = _assembly_mapping(failure.category)
            context = {
                name: getattr(failure, name)
                for name in (
                    "category",
                    "class_id",
                    "assignment_id",
                    "student_id",
                    "issuance_id",
                    "generation_id",
                    "artifact_id",
                    "expected_page_ids",
                    "observed_page_ids",
                    "observed_route_ids",
                    "expected_logical_pages",
                    "observed_logical_pages",
                    "missing_page_ids",
                    "missing_logical_pages",
                    "duplicate_page_ids",
                    "duplicate_route_ids",
                    "conflicting_page_ids",
                    "source_page_numbers",
                )
            }
            context["assembly_category"] = context.pop("category")
            return _metadata(
                failure_id=failure_id,
                created_at=created_at,
                scope="scan",
                stage=stage,
                category=category,
                message=failure.reason,
                provenance=provenance,
                page=None,
                payload=None,
                locator=None,
                target=None,
                details=scoreform_failure_details(
                    origin="attempt_assembly",
                    category=failure.category,
                    diagnostic_paths=failure.diagnostic_paths,
                    diagnostic_errors=(failure.error,),
                    context=context,
                ),
            )

        occurrences.append(
            _Occurrence(
                f"assembly:{index}:{failure.category}:{failure.issuance_id}",
                "attempt_assembly",
                None,
                convert_assembly,
            )
        )
    if batch.export_result is not None:
        for index, export_failure in enumerate(batch.export_result.failures, 1):

            def convert_export(failure_id: str, failure=export_failure):
                stage, category = _export_mapping(failure.stage)
                output = _safe_output_context(failure.output_path, workspace_root)
                cleanup = []
                for item in failure.cleanup_failures:
                    cleanup.append(
                        {
                            "temporary_path": _safe_output_context(
                                item.temporary_path, workspace_root
                            ),
                            "target_path": _safe_output_context(
                                item.target_path, workspace_root
                            ),
                            **sanitized_exception(item.error),
                        }
                    )
                return _metadata(
                    failure_id=failure_id,
                    created_at=created_at,
                    scope="scan",
                    stage=stage,
                    category=category,
                    message=failure.reason,
                    provenance=provenance,
                    page=None,
                    payload=None,
                    locator=None,
                    target=None,
                    details=scoreform_failure_details(
                        origin="result_export",
                        category=failure.stage,
                        diagnostic_errors=(failure.error,),
                        context={
                            "export_stage": failure.stage,
                            "class_id": failure.class_id,
                            "assignment_id": failure.assignment_id,
                            **output,
                            "affected_targets": failure.affected_targets,
                            "affected_attempts": [],
                            "cleanup_failures": cleanup,
                        },
                    ),
                )

            occurrences.append(
                _Occurrence(
                    f"export:{index}:{export_failure.stage}:"
                    f"{export_failure.class_id}:{export_failure.assignment_id}",
                    "result_export",
                    None,
                    convert_export,
                )
            )
    return tuple(occurrences)


def routing_failures_from_scoring_batch(
    batch: ScoreFormRoutedScoringBatch,
    source_file: str | Path,
    *,
    workspace_root: str | Path | None = None,
    now: datetime | None = None,
) -> tuple[tuple[str, int | None, RoutingFailureMetadata], ...]:
    if not isinstance(batch, ScoreFormRoutedScoringBatch):
        raise TypeError("batch must be a ScoreFormRoutedScoringBatch.")
    timestamp = operation_timestamp(now)
    root = (
        None if workspace_root is None else Path(workspace_root).resolve(strict=False)
    )
    return tuple(
        (
            item.origin,
            item.source_page_number,
            item.convert(_identifier("failure", timestamp)),
        )
        for item in _occurrences(
            batch, source_file, workspace_root=root, created_at=timestamp.isoformat()
        )
    )


def _is_collision(error: RoutingFailureMetadataWriteError) -> bool:
    return isinstance(error.__cause__, FileExistsError)


def persist_routed_scoring_failures(
    batch: ScoreFormRoutedScoringBatch,
    source_file: str | Path,
    workspace_root: str | Path,
    *,
    now: datetime | None = None,
) -> ScoreFormFailurePersistenceBatch:
    root = Path(workspace_root).resolve(strict=True)
    timestamp = operation_timestamp(now)
    occurrences = _occurrences(
        batch, source_file, workspace_root=root, created_at=timestamp.isoformat()
    )
    persisted: list[ScoreFormPersistedFailure] = []
    failures: list[ScoreFormFailurePersistenceError] = []
    for occurrence in occurrences:
        completed = False
        for attempt in range(_MAX_ID_ATTEMPTS):
            failure_id = _identifier("failure", timestamp)
            try:
                metadata = occurrence.convert(failure_id)
            except Exception as error:
                failures.append(
                    ScoreFormFailurePersistenceError(
                        occurrence.occurrence_key,
                        occurrence.origin,
                        occurrence.source_page_number,
                        "conversion",
                        _message(error, "Failure conversion failed."),
                        error,
                    )
                )
                completed = True
                break
            try:
                validate_routing_failure_metadata(metadata)
            except (RoutingFailureMetadataError, ValueError, TypeError) as error:
                failures.append(
                    ScoreFormFailurePersistenceError(
                        occurrence.occurrence_key,
                        occurrence.origin,
                        occurrence.source_page_number,
                        "validation",
                        _message(error, "Failure validation failed."),
                        error,
                    )
                )
                completed = True
                break
            path = routing_failure_metadata_path(root, failure_id)
            if path.exists() or path.is_symlink():
                if attempt + 1 == _MAX_ID_ATTEMPTS:
                    collision_error = FileExistsError(path)
                    failures.append(
                        ScoreFormFailurePersistenceError(
                            occurrence.occurrence_key,
                            occurrence.origin,
                            occurrence.source_page_number,
                            "collision_exhausted",
                            "Failure ID collision retry limit was exhausted.",
                            collision_error,
                        )
                    )
                    completed = True
                continue
            try:
                path = write_routing_failure_metadata(root, metadata)
            except RoutingFailureMetadataWriteError as error:
                if _is_collision(error):
                    if attempt + 1 == _MAX_ID_ATTEMPTS:
                        failures.append(
                            ScoreFormFailurePersistenceError(
                                occurrence.occurrence_key,
                                occurrence.origin,
                                occurrence.source_page_number,
                                "collision_exhausted",
                                "Failure ID collision retry limit was exhausted.",
                                error,
                            )
                        )
                        completed = True
                    continue
                failures.append(
                    ScoreFormFailurePersistenceError(
                        occurrence.occurrence_key,
                        occurrence.origin,
                        occurrence.source_page_number,
                        "write",
                        _message(error, "Failure metadata write failed."),
                        error,
                    )
                )
                completed = True
                break
            persisted.append(
                ScoreFormPersistedFailure(
                    occurrence.occurrence_key,
                    metadata.failure_id,
                    metadata,
                    path,
                    path.relative_to(root).as_posix(),
                    occurrence.origin,
                    occurrence.source_page_number,
                )
            )
            completed = True
            break
        if not completed:
            raise AssertionError(
                "persistence occurrence did not reach a terminal state"
            )
    return ScoreFormFailurePersistenceBatch(tuple(persisted), tuple(failures))


def format_failure_persistence_summary(batch: ScoreFormFailurePersistenceBatch) -> str:
    lines = [
        "ScoreForm scan review persistence",
        f"Review failures saved: {len(batch.persisted)}",
        f"Review failures not saved: {len(batch.failures)}",
    ]
    lines.extend(
        f"Review persistence failure [{item.origin}/{item.persistence_stage}]: {item.reason}"
        for item in batch.failures
    )
    return "\n".join(lines)
