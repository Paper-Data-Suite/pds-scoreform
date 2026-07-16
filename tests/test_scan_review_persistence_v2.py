"""Structured conversion/write isolation and persistence model invariants."""

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from pds_core.module_dispatch import (
    ModuleContractCompatibilityError,
    RouteDispatchSuccess,
)
from pds_core.routing_models import (
    ModuleRecordRef,
    ModuleWorkRef,
    RouteLocator,
    RouteRegistration,
    RoutingModelError,
)
from pds_core.scan_failure_metadata import (
    RoutingFailureMetadata,
    RoutingFailureMetadataWriteError,
    load_routing_failure_metadata,
    routing_failure_metadata_to_dict,
    write_routing_failure_metadata,
)
from pds_core.scan_retention import SourceRetentionError

import scoreform.scan_review_persistence as persistence
from scoreform.module_errors import (
    ScoreFormQrMissingError,
    ScoreFormQrUnreadableError,
    ScoreFormRegistryError,
    ScoreFormScanPreflightError,
    ScoreFormSourceMissingError,
    ScoreFormSourceTypeUnsupportedError,
)
from scoreform.pds2_scan_dispatch import Pds2ScanPageOutcome
from scoreform.scan_review_details import scoreform_failure_details
from scoreform.scan_review_models import (
    ScoreFormFailurePersistenceBatch,
    ScoreFormFailurePersistenceError,
    ScoreFormPersistedFailure,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _metadata(failure_id: str, page: int | None = None):
    return RoutingFailureMetadata(
        schema_version="2",
        failure_id=failure_id,
        scope="page" if page else "scan",
        stage="review",
        created_at=NOW.isoformat(),
        failure_category="processing_error",
        failure_message="Review failure.",
        source_filename="scan.pdf",
        source_scan_id=None,
        source_sha256=None,
        retained_source_path=None,
        review_copy_path=None,
        source_page_number=page,
        detected_payload=None,
        route_locator=None,
        target=None,
        module_details=scoreform_failure_details(
            origin="attempt_assembly", category="invalid_result_identity"
        ),
    )


def test_conversion_failure_does_not_suppress_later_occurrence(
    tmp_path, monkeypatch
) -> None:
    def fail(_failure_id):
        raise ValueError("bad\nconversion")

    occurrences = (
        persistence._Occurrence("first", "page_decode", 1, fail),
        persistence._Occurrence(
            "second",
            "attempt_assembly",
            None,
            lambda failure_id: _metadata(failure_id),
        ),
    )
    monkeypatch.setattr(
        persistence, "_occurrences", lambda *args, **kwargs: occurrences
    )

    result = persistence.persist_routed_scoring_failures(
        object(), "scan.pdf", tmp_path, now=NOW
    )

    assert len(result.persisted) == 1
    assert result.persisted[0].occurrence_key == "second"
    assert result.failures[0].persistence_stage == "conversion"
    assert "\n" not in result.failures[0].reason


def test_write_failure_does_not_suppress_later_occurrence(
    tmp_path, monkeypatch
) -> None:
    occurrences = tuple(
        persistence._Occurrence(
            key,
            "attempt_assembly",
            None,
            lambda failure_id: _metadata(failure_id),
        )
        for key in ("first", "second")
    )
    monkeypatch.setattr(
        persistence, "_occurrences", lambda *args, **kwargs: occurrences
    )
    real_write = persistence.write_routing_failure_metadata
    calls = 0

    def write(root, metadata):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RoutingFailureMetadataWriteError("permission denied")
        return real_write(root, metadata)

    monkeypatch.setattr(persistence, "write_routing_failure_metadata", write)
    result = persistence.persist_routed_scoring_failures(
        object(), "scan.pdf", tmp_path, now=NOW
    )
    assert [item.occurrence_key for item in result.persisted] == ["second"]
    assert result.failures[0].persistence_stage == "write"


def test_collision_exhaustion_is_typed(tmp_path, monkeypatch) -> None:
    failure_id = "failure_20260101T000000000000Z_deadbeefdeadbeef"
    write_routing_failure_metadata(tmp_path, _metadata(failure_id))
    occurrence = persistence._Occurrence(
        "only",
        "attempt_assembly",
        None,
        lambda generated_id: _metadata(generated_id),
    )
    monkeypatch.setattr(
        persistence, "_occurrences", lambda *args, **kwargs: (occurrence,)
    )
    monkeypatch.setattr(persistence, "_identifier", lambda *_args: failure_id)

    result = persistence.persist_routed_scoring_failures(
        object(), "scan.pdf", tmp_path, now=NOW
    )
    assert result.persisted == ()
    assert result.failures[0].persistence_stage == "collision_exhausted"


def test_exact_core_shape_and_strict_reload(tmp_path, monkeypatch) -> None:
    occurrence = persistence._Occurrence(
        "only",
        "attempt_assembly",
        None,
        lambda failure_id: _metadata(failure_id),
    )
    monkeypatch.setattr(
        persistence, "_occurrences", lambda *args, **kwargs: (occurrence,)
    )
    result = persistence.persist_routed_scoring_failures(
        object(), "scan.pdf", tmp_path, now=NOW
    )
    persisted = result.persisted[0]
    assert len(routing_failure_metadata_to_dict(persisted.metadata)) == 17
    assert (
        load_routing_failure_metadata(tmp_path, persisted.failure_id)
        == persisted.metadata
    )
    assert persisted.metadata_path.read_bytes().endswith(b"\n")


def test_persistence_models_require_canonical_paths_and_occurrence_uniqueness(
    tmp_path,
) -> None:
    metadata = _metadata("failure1")
    path = tmp_path / "scans" / "review" / "failure1.json"
    item = ScoreFormPersistedFailure(
        "occurrence1",
        "failure1",
        metadata,
        path,
        "scans/review/failure1.json",
        "attempt_assembly",
        None,
    )
    error = ScoreFormFailurePersistenceError(
        "occurrence2",
        "attempt_assembly",
        None,
        "write",
        "Write failed.",
        OSError("failed"),
    )
    assert ScoreFormFailurePersistenceBatch((item,), (error,)).complete is False
    with pytest.raises(ValueError, match="cannot be persisted and failed"):
        ScoreFormFailurePersistenceBatch(
            (item,),
            (
                ScoreFormFailurePersistenceError(
                    "occurrence1",
                    "attempt_assembly",
                    None,
                    "write",
                    "Write failed.",
                    OSError("failed"),
                ),
            ),
        )
    with pytest.raises(ValueError, match="canonical"):
        ScoreFormPersistedFailure(
            "occurrence1",
            "failure1",
            metadata,
            Path("failure1.json"),
            "elsewhere/failure1.json",
            "attempt_assembly",
            None,
        )


@pytest.mark.parametrize(
    "error, expected",
    [
        (ScoreFormSourceMissingError("missing"), ("intake", "source_missing")),
        (
            ScoreFormSourceTypeUnsupportedError("type"),
            ("intake", "source_type_unsupported"),
        ),
        (SourceRetentionError("retention"), ("retention", "source_retention_failed")),
        (
            ScoreFormRegistryError("registry infrastructure"),
            ("module_resolution", "processing_error"),
        ),
    ],
)
def test_typed_file_mapping(error, expected) -> None:
    assert persistence._file_mapping(error) == expected


def test_missing_qr_and_detector_failure_map_differently() -> None:
    missing = Pds2ScanPageOutcome(
        1, failure_stage="qr_detection", error=ScoreFormQrMissingError("missing")
    )
    unreadable = Pds2ScanPageOutcome(
        2,
        failure_stage="qr_detection",
        error=ScoreFormQrUnreadableError("detector failed"),
    )
    assert persistence._page_core_mapping(missing) == ("payload", "payload_missing")
    assert persistence._page_core_mapping(unreadable) == (
        "payload",
        "payload_unreadable",
    )


def test_registry_profile_incompatibility_requires_typed_cause() -> None:
    compatibility = ModuleContractCompatibilityError("contract mismatch")
    registry = ScoreFormRegistryError("registry failed")
    registry.__cause__ = compatibility
    assert persistence._file_mapping(registry) == (
        "module_resolution",
        "module_profile_incompatible",
    )
    assert persistence._file_mapping(ScoreFormScanPreflightError("bad file")) == (
        "intake",
        "source_unreadable",
    )


@pytest.mark.parametrize(
    "raw,error,expected",
    [
        ("PDS1|old", ValueError("schema"), "payload_schema_unsupported"),
        ("PDS2|" + "x" * 5000, ValueError("large"), "payload_too_large"),
        ("PDS2|bad", RoutingModelError("identifier"), "identifier_invalid"),
        ("PDS2|bad", ValueError("payload"), "payload_invalid"),
    ],
)
def test_payload_mapping_categories(raw, error, expected) -> None:
    page = Pds2ScanPageOutcome(
        1,
        raw_payload_text=raw,
        failure_stage="payload_parsing",
        error=error,
    )
    assert persistence._page_core_mapping(page) == ("payload", expected)


@pytest.mark.parametrize(
    "failure_stage,error,expected",
    [
        ("source_page_loading", OSError("page"), ("decoding", "source_unreadable")),
        ("request_construction", ValueError("request"), ("route_resolution", "processing_error")),
        ("request_construction", RoutingModelError("identifier"), ("route_resolution", "identifier_invalid")),
        ("core_outcome_validation", ValueError("outcome"), ("module_validation", "target_incompatible")),
        ("scoreform_result_validation", ValueError("result"), ("module_handling", "processing_error")),
    ],
)
def test_page_application_stage_mappings(failure_stage, error, expected) -> None:
    page = Pds2ScanPageOutcome(1, failure_stage=failure_stage, error=error)
    assert persistence._page_core_mapping(page) == expected


@pytest.mark.parametrize(
    "category, expected",
    [
        ("missing_pages", ("review", "page_conflict")),
        ("duplicate_page", ("review", "page_conflict")),
        ("duplicate_route", ("review", "page_conflict")),
        ("conflicting_duplicate", ("review", "page_conflict")),
        ("invalid_page_order", ("review", "page_conflict")),
        ("invalid_question_coverage", ("review", "page_conflict")),
        ("unexpected_page", ("review", "target_incompatible")),
        ("inconsistent_issuance", ("review", "target_incompatible")),
        ("invalid_result_identity", ("review", "target_incompatible")),
    ],
)
def test_every_assembly_category_mapping(category, expected) -> None:
    assert persistence._assembly_mapping(category) == expected


@pytest.mark.parametrize(
    "stage,expected",
    [
        ("integrity", ("review", "processing_error")),
        ("preflight", ("evidence", "evidence_write_failed")),
        ("staging", ("evidence", "evidence_write_failed")),
        ("replacement", ("evidence", "evidence_write_failed")),
        ("not_attempted", ("evidence", "evidence_write_failed")),
    ],
)
def test_every_export_stage_mapping(stage, expected) -> None:
    assert persistence._export_mapping(stage) == expected


def test_external_output_context_is_basename_only(tmp_path) -> None:
    context = persistence._safe_output_context(
        Path("C:/private/teacher/results.csv"), tmp_path
    )
    assert context == {
        "output_kind": "external_explicit",
        "output_path": {"marker": "external", "basename": "results.csv"},
    }


def test_page_diagnostic_paths_are_made_workspace_relative(tmp_path) -> None:
    diagnostic = tmp_path / "local_outputs" / "qr_failures" / "page.png"
    page = Pds2ScanPageOutcome(
        1,
        failure_stage="qr_detection",
        error=ScoreFormQrMissingError("missing"),
        diagnostic_paths=(str(diagnostic),),
    )
    details = persistence._page_details(
        page,
        "page_decode",
        "qr_detection",
        page.error,
        tmp_path,
    )
    assert details["scoreform"]["diagnostic_paths"] == [
        "local_outputs/qr_failures/page.png"
    ]


@pytest.mark.parametrize("contradiction", ["request", "resolution", "registration", "target"])
def test_valid_page_locator_survives_contradictory_later_identity(
    contradiction,
) -> None:
    locator = RouteLocator(
        "PDS2",
        ModuleWorkRef("scoreform", "class1", "quiz1"),
        "rt_10000000000000000000000000000000",
    )
    other = RouteLocator(
        "PDS2",
        ModuleWorkRef("scoreform", "class1", "quiz1"),
        "rt_20000000000000000000000000000000",
    )
    registration_locator = other if contradiction == "registration" else locator
    target = ModuleRecordRef(
        "scoreform",
        "answer_sheet_page",
        "pg_10000000000000000000000000000000",
        "1",
    )
    registration = RouteRegistration(
        "1",
        registration_locator,
        target,
        "2026-01-01T00:00:00+00:00",
        "active",
        "test",
        {},
    )
    if contradiction == "target":
        object.__setattr__(
            registration,
            "target",
            ModuleRecordRef(
                "other",
                "answer_sheet_page",
                "pg_10000000000000000000000000000000",
                "1",
            ),
        )
    request = SimpleNamespace(locator=locator, source_page_number=1)
    outcome_request = (
        SimpleNamespace(locator=other, source_page_number=1)
        if contradiction == "request"
        else request
    )
    resolution = SimpleNamespace(
        locator=other if contradiction == "resolution" else locator,
        registration=registration,
    )
    outcome = RouteDispatchSuccess(
        outcome_request,
        SimpleNamespace(module_id="scoreform"),
        resolution,
        object(),
    )
    page = Pds2ScanPageOutcome(
        1,
        raw_payload_text="PDS2|synthetic",
        locator=locator,
        dispatch_request=request,
        dispatch_outcome=outcome,
        failure_stage="core_outcome_validation",
        error=ValueError("contradiction"),
    )
    retained, trusted_target = persistence._validated_occurrence_identity(page)
    assert retained == locator
    assert trusted_target is None
