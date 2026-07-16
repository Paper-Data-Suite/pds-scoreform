"""Active Core-v2 scan-review discovery and resolution coverage."""

import csv
import json
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from pds_core.routing_models import ModuleWorkRef, RouteLocator
from pds_core.scan_failure_metadata import (
    RoutingFailureMetadata,
    load_routing_failure_metadata,
    write_routing_failure_metadata,
)
from pds_core.scan_resolution_metadata import (
    ScanResolutionMetadataWriteError,
    create_scan_resolution_metadata,
    load_scan_resolution_metadata,
    scan_resolution_metadata_to_dict,
    write_scan_resolution_metadata,
)

import scoreform.results as result_service
import scoreform.scan_review_resolution as review_service
from scoreform.folders import setup_assignment_folder
from scoreform.scan_review_details import (
    scoreform_failure_details,
    scoreform_resolution_details,
)
from scoreform.scan_review_resolution import (
    ScanReviewError,
    ScanReviewPartialOperationError,
    ScoreFormResolutionResult,
    discover_scan_review_items,
    resolve_scan_review_item,
)
from scoreform.work_paths import scoreform_work_paths


def _failure(failure_id="failure1", scoreform_category="missing_qr"):
    return RoutingFailureMetadata(
        schema_version="2",
        failure_id=failure_id,
        scope="page",
        stage="payload_detection",
        created_at="2026-01-01T00:00:00+00:00",
        failure_category="payload_missing",
        failure_message="No QR was detected.",
        source_filename="scan.pdf",
        source_scan_id=None,
        source_sha256=None,
        retained_source_path=None,
        review_copy_path=None,
        source_page_number=1,
        detected_payload=None,
        route_locator=None,
        target=None,
        module_details=scoreform_failure_details(
            origin="page_decode", category=scoreform_category
        ),
    )


def test_v2_failure_is_discovered_and_deferred_append_only(tmp_path) -> None:
    original = _failure()
    failure_path = write_routing_failure_metadata(tmp_path, original)
    before = failure_path.read_bytes()

    found = discover_scan_review_items(tmp_path)
    assert [item.failure_id for item in found.items] == ["failure1"]
    result = resolve_scan_review_item(
        tmp_path,
        "failure1",
        "defer",
        now=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )

    assert failure_path.read_bytes() == before
    assert load_routing_failure_metadata(tmp_path, "failure1") == original
    resolution = load_scan_resolution_metadata(tmp_path, result.resolution_id)
    assert resolution.schema_version == "2"
    assert (resolution.resolution_status, resolution.resolution_action) == (
        "deferred",
        "deferred",
    )
    projected = discover_scan_review_items(tmp_path)
    assert projected.items[0].status == "deferred"
    assert len(projected.items[0].resolution_history) == 1


def test_v1_failure_is_preserved_but_rejected(tmp_path) -> None:
    review = tmp_path / "scans" / "review"
    review.mkdir(parents=True)
    path = review / "old_failure.json"
    content = '{"schema_version":"1","failure_id":"old_failure"}\n'
    path.write_text(content, encoding="utf-8")

    found = discover_scan_review_items(tmp_path)

    assert found.items == ()
    assert found.unsupported_v1_failure_count == 1
    assert path.read_text(encoding="utf-8") == content


def test_v1_resolution_is_counted_separately(tmp_path) -> None:
    directory = tmp_path / "scans" / "review" / "resolutions"
    directory.mkdir(parents=True)
    path = directory / "old_resolution.json"
    content = '{"schema_version":"1","resolution_id":"old_resolution"}\n'
    path.write_text(content, encoding="utf-8")

    found = discover_scan_review_items(tmp_path)

    assert found.unsupported_v1_failure_count == 0
    assert found.unsupported_v1_resolution_count == 1
    assert path.read_text(encoding="utf-8") == content


def _resolution(failure, resolution_id, resolved_at, action="defer"):
    deferred = action == "defer"
    return create_scan_resolution_metadata(
        failure,
        resolution_id=resolution_id,
        resolution_status="deferred" if deferred else "resolved",
        resolution_action="deferred" if deferred else "other",
        resolved_at=resolved_at,
        resolution_message="Teacher decision.",
        module_details=scoreform_resolution_details(
            teacher_action=action, identity_source="none"
        ),
    )


def test_history_orders_by_utc_instant_not_timestamp_text(tmp_path) -> None:
    failure = _failure()
    write_routing_failure_metadata(tmp_path, failure)
    later_lexically_smaller = _resolution(
        failure, "resolution_later", "2026-01-02T00:30:00+00:00"
    )
    earlier_lexically_larger = _resolution(
        failure, "resolution_earlier", "2026-01-02T01:00:00+02:00"
    )
    write_scan_resolution_metadata(tmp_path, later_lexically_smaller)
    write_scan_resolution_metadata(tmp_path, earlier_lexically_larger)

    item = discover_scan_review_items(tmp_path).items[0]
    assert [value.resolution_id for value in item.resolution_history] == [
        "resolution_earlier",
        "resolution_later",
    ]


def test_resolution_provenance_mismatch_does_not_project_status(tmp_path) -> None:
    failure = _failure()
    write_routing_failure_metadata(tmp_path, failure)
    resolution = _resolution(
        failure, "resolution_mismatch", "2026-01-02T00:00:00+00:00"
    )
    data = scan_resolution_metadata_to_dict(resolution)
    data["source_filename"] = "different.pdf"
    directory = tmp_path / "scans" / "review" / "resolutions"
    directory.mkdir(parents=True)
    path = directory / "resolution_mismatch.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    found = discover_scan_review_items(tmp_path)
    assert found.provenance_mismatch_count == 1
    assert found.items[0].status == "unresolved"
    assert path.exists()


def test_orphan_and_foreign_resolutions_are_counted_separately(tmp_path) -> None:
    linked_failure = _failure("failure_linked")
    write_routing_failure_metadata(tmp_path, linked_failure)
    foreign = create_scan_resolution_metadata(
        linked_failure,
        resolution_id="resolution_foreign",
        resolution_status="deferred",
        resolution_action="deferred",
        resolved_at="2026-01-02T00:00:00+00:00",
        resolution_message="Foreign decision.",
        module_details={},
    )
    orphan_failure = _failure("failure_not_written")
    orphan = _resolution(
        orphan_failure,
        "resolution_orphan",
        "2026-01-02T00:01:00+00:00",
    )
    write_scan_resolution_metadata(tmp_path, foreign)
    directory = tmp_path / "scans" / "review" / "resolutions"
    orphan_path = directory / "resolution_orphan.json"
    orphan_path.write_text(
        json.dumps(scan_resolution_metadata_to_dict(orphan)), encoding="utf-8"
    )

    found = discover_scan_review_items(tmp_path)

    assert found.foreign_record_count == 1
    assert found.orphan_resolution_count == 1
    assert found.items[0].status == "unresolved"


@pytest.mark.parametrize(
    "field,value",
    [
        ("class_id", "../class"),
        ("assignment_id", "bad/id"),
        ("student_id", "student\n1"),
        ("source_scan_id", "unsafe value"),
        ("stage", "Payload"),
        ("failure_category", "bad category"),
        ("status", "closed"),
        ("limit", 0),
    ],
)
def test_discovery_rejects_unsafe_filters(tmp_path, field, value) -> None:
    with pytest.raises(ScanReviewError):
        discover_scan_review_items(tmp_path, **{field: value})


def test_malformed_details_and_foreign_records_are_counted_separately(tmp_path) -> None:
    malformed = _failure("failure_malformed")
    malformed = RoutingFailureMetadata(
        schema_version=malformed.schema_version,
        failure_id=malformed.failure_id,
        scope=malformed.scope,
        stage=malformed.stage,
        created_at=malformed.created_at,
        failure_category=malformed.failure_category,
        failure_message=malformed.failure_message,
        source_filename=malformed.source_filename,
        source_scan_id=None,
        source_sha256=None,
        retained_source_path=None,
        review_copy_path=None,
        source_page_number=1,
        detected_payload=None,
        route_locator=None,
        target=None,
        module_details={"scoreform": {"details_schema_version": "1"}},
    )
    foreign = RoutingFailureMetadata(
        schema_version="2",
        failure_id="failure_foreign",
        scope="scan",
        stage="intake",
        created_at="2026-01-01T00:00:00+00:00",
        failure_category="source_unreadable",
        failure_message="Unreadable.",
        source_filename="scan.pdf",
        source_scan_id=None,
        source_sha256=None,
        retained_source_path=None,
        review_copy_path=None,
        source_page_number=None,
        detected_payload=None,
        route_locator=None,
        target=None,
        module_details={},
    )
    write_routing_failure_metadata(tmp_path, malformed)
    write_routing_failure_metadata(tmp_path, foreign)

    found = discover_scan_review_items(tmp_path)
    assert found.malformed_scoreform_details_count == 1
    assert found.foreign_record_count == 1
    assert found.items == ()


def test_review_item_binds_actual_failure_path_to_failure_id(tmp_path) -> None:
    failure = _failure()
    write_routing_failure_metadata(tmp_path, failure)
    item = discover_scan_review_items(tmp_path).items[0]
    with pytest.raises(ValueError, match="Path disagrees"):
        replace(
            item,
            failure_metadata_path=(
                tmp_path / "scans" / "review" / "different.json"
            ),
        )


@pytest.mark.parametrize(
    "value",
    [
        "results.csv",
        "classes/class1/results.csv",
        "classes/class1/modules/scoreform/work/quiz/extra/results.csv",
        "../classes/class1/modules/scoreform/work/quiz/results.csv",
        "C:/classes/class1/modules/scoreform/work/quiz/results.csv",
        "classes\\class1\\modules\\scoreform\\work\\quiz\\results.csv",
    ],
)
def test_partial_operation_requires_canonical_managed_result_path(value) -> None:
    with pytest.raises((TypeError, ValueError)):
        ScanReviewPartialOperationError(
            failure_id="failure1",
            result_output_path=value,
            attempt_number=1,
            result_appended=True,
            result_already_present=False,
            error=OSError("failed"),
        )


def test_resolution_result_binds_path_and_manual_result_flags(tmp_path) -> None:
    resolution_id = "resolution1"
    canonical_path = (
        tmp_path
        / "scans"
        / "review"
        / "resolutions"
        / f"{resolution_id}.json"
    )
    relative = f"scans/review/resolutions/{resolution_id}.json"
    with pytest.raises(ValueError, match="exactly one"):
        ScoreFormResolutionResult(
            resolution_id,
            canonical_path,
            relative,
            "failure1",
            "resolved",
            "manual_entry",
        )
    with pytest.raises(ValueError, match="exactly one"):
        ScoreFormResolutionResult(
            resolution_id,
            canonical_path,
            relative,
            "failure1",
            "resolved",
            "manual_entry",
            True,
            True,
        )
    accepted = ScoreFormResolutionResult(
        resolution_id,
        canonical_path,
        relative,
        "failure1",
        "resolved",
        "manual_entry",
        True,
        False,
    )
    assert accepted.result_written
    with pytest.raises(ValueError, match="Path disagrees"):
        replace(accepted, resolution_metadata_path=tmp_path / "wrong.json")
    with pytest.raises(ValueError, match="Only manual_entry"):
        replace(accepted, resolution_action="defer")


def test_scoreform_locator_owns_record_without_module_details(tmp_path) -> None:
    locator = RouteLocator(
        "PDS2",
        ModuleWorkRef("scoreform", "class1", "work1"),
        "rt_10000000000000000000000000000000",
    )
    failure = RoutingFailureMetadata(
        schema_version="2",
        failure_id="failure_locator",
        scope="page",
        stage="route_resolution",
        created_at="2026-01-01T00:00:00+00:00",
        failure_category="route_unknown",
        failure_message="Unknown route.",
        source_filename="scan.pdf",
        source_scan_id=None,
        source_sha256=None,
        retained_source_path=None,
        review_copy_path=None,
        source_page_number=1,
        detected_payload=None,
        route_locator=locator,
        target=None,
        module_details={},
    )
    write_routing_failure_metadata(tmp_path, failure)

    item = discover_scan_review_items(tmp_path).items[0]
    assert item.identity.source == "validated_locator"
    assert item.identity.class_id == "class1"
    assert item.identity.student_id is None


def _managed_assignment(root):
    roster = {
        "class_id": "class1",
        "students": [
            {
                "student_id": "student1",
                "last_name": "Doe",
                "first_name": "Jane",
                "period": "1",
            }
        ],
    }
    assignment = {
        "assignment_id": "quiz",
        "title": "Quiz",
        "question_count": 2,
        "choices": ["A", "B", "C", "D"],
        "answer_key": {"1": "A", "2": "B"},
        "standards": {"1": [], "2": []},
    }
    assert setup_assignment_folder(roster, assignment, workspace_root=root)


def _managed_review_targets(root):
    roster1 = {
        "class_id": "class1",
        "students": [
            {"student_id": "student1", "last_name": "One", "first_name": "A", "period": "1"},
            {"student_id": "student2", "last_name": "Two", "first_name": "B", "period": "1"},
        ],
    }
    roster2 = {
        "class_id": "class2",
        "students": [
            {"student_id": "student1", "last_name": "One", "first_name": "A", "period": "2"},
        ],
    }
    for roster, assignment_id in (
        (roster1, "quiz"),
        (roster1, "quiz2"),
        (roster2, "quiz"),
    ):
        assignment = {
            "assignment_id": assignment_id,
            "title": assignment_id,
            "question_count": 2,
            "choices": ["A", "B", "C", "D"],
            "answer_key": {"1": "A", "2": "B"},
            "standards": {"1": [], "2": []},
        }
        assert setup_assignment_folder(roster, assignment, workspace_root=root)


def test_manual_entry_partial_operation_retry_is_idempotent(
    tmp_path, monkeypatch
) -> None:
    _managed_assignment(tmp_path)
    failure = _failure()
    write_routing_failure_metadata(tmp_path, failure)
    real_write = review_service.write_scan_resolution_metadata

    def fail_resolution(*_args, **_kwargs):
        raise ScanResolutionMetadataWriteError("resolution write failed")

    monkeypatch.setattr(
        review_service, "write_scan_resolution_metadata", fail_resolution
    )
    with pytest.raises(ScanReviewPartialOperationError) as raised:
        resolve_scan_review_item(
            tmp_path,
            failure.failure_id,
            "manual_entry",
            class_id="class1",
            assignment_id="quiz",
            student_id="student1",
            answers={1: "A", 2: "blank"},
            now=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )
    partial = raised.value
    assert partial.result_appended and not partial.result_already_present
    assert "Retrying will not create another attempt" in str(partial)

    monkeypatch.setattr(review_service, "write_scan_resolution_metadata", real_write)
    retried = resolve_scan_review_item(
        tmp_path,
        failure.failure_id,
        "manual_entry",
        class_id="class1",
        assignment_id="quiz",
        student_id="student1",
        answers={1: "A", 2: "blank"},
        now=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    assert retried.result_already_present and not retried.result_written
    results_path = scoreform_work_paths(tmp_path, "class1", "quiz").results_path
    with results_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1 and rows[0]["attempt_number"] == "1"
    item = discover_scan_review_items(tmp_path, include_resolved=True).items[0]
    assert len(item.resolution_history) == 1


@pytest.mark.parametrize(
    "class_id,assignment_id,student_id,answers",
    [
        ("class1", "quiz2", "student1", {1: "A", 2: "blank"}),
        ("class2", "quiz", "student1", {1: "A", 2: "blank"}),
        ("class1", "quiz", "student2", {1: "A", 2: "blank"}),
        ("class1", "quiz", "student1", {1: "B", 2: "blank"}),
    ],
)
def test_manual_review_failure_link_is_globally_unique(
    tmp_path,
    monkeypatch,
    class_id,
    assignment_id,
    student_id,
    answers,
) -> None:
    _managed_review_targets(tmp_path)
    failure = _failure()
    write_routing_failure_metadata(tmp_path, failure)
    real_write = review_service.write_scan_resolution_metadata
    monkeypatch.setattr(
        review_service,
        "write_scan_resolution_metadata",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ScanResolutionMetadataWriteError("resolution write failed")
        ),
    )
    with pytest.raises(ScanReviewPartialOperationError):
        resolve_scan_review_item(
            tmp_path,
            failure.failure_id,
            "manual_entry",
            class_id="class1",
            assignment_id="quiz",
            student_id="student1",
            answers={1: "A", 2: "blank"},
            now=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )
    monkeypatch.setattr(review_service, "write_scan_resolution_metadata", real_write)

    with pytest.raises(ScanReviewError, match="Manual-entry result writing failed"):
        resolve_scan_review_item(
            tmp_path,
            failure.failure_id,
            "manual_entry",
            class_id=class_id,
            assignment_id=assignment_id,
            student_id=student_id,
            answers=answers,
            now=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )

    histories = tuple(tmp_path.glob("classes/*/modules/scoreform/work/*/results.csv"))
    rows = []
    for path in histories:
        with path.open(newline="", encoding="utf-8") as handle:
            rows.extend(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["attempt_number"] == "1"


def _write_one_review_result(root, failure_id="failure1"):
    failure = _failure(failure_id)
    write_routing_failure_metadata(root, failure)
    result = resolve_scan_review_item(
        root,
        failure_id,
        "manual_entry",
        class_id="class1",
        assignment_id="quiz",
        student_id="student1",
        answers={1: "A", 2: "blank"},
    )
    path = scoreform_work_paths(root, "class1", "quiz").results_path
    return failure, result, path


def test_correctly_placed_global_review_link_preserves_original_attempt(tmp_path) -> None:
    _managed_review_targets(tmp_path)
    _failure_record, _resolution, path = _write_one_review_result(tmp_path)
    links = result_service._managed_review_result_links(tmp_path)
    model, attempt, linked_path = links["scan_review_manual:failure1"][0]
    assert attempt == 1
    assert linked_path == path
    assert model.class_id == "class1" and model.assignment_id == "quiz"


@pytest.mark.parametrize(
    "destination",
    [
        ("class2", "quiz"),
        ("class1", "quiz2"),
    ],
)
def test_review_link_row_must_match_managed_history_directory(
    tmp_path, destination
) -> None:
    _managed_review_targets(tmp_path)
    _failure_record, _resolution, source = _write_one_review_result(tmp_path)
    target = scoreform_work_paths(tmp_path, *destination).results_path
    source.replace(target)
    with pytest.raises(result_service.ScoreFormRoutedResultIntegrityError):
        result_service._managed_review_result_links(tmp_path)


def test_nonreview_row_identity_must_match_managed_history_directory(tmp_path) -> None:
    _managed_review_targets(tmp_path)
    _failure_record, _resolution, source = _write_one_review_result(tmp_path)
    with source.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames
        rows = list(reader)
    assert fields is not None
    rows[0]["result_origin"] = "plain_paper_manual"
    rows[0]["source_file"] = "plain_paper_manual_entry"
    rows[0]["Page"] = "manual"
    with source.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    target = scoreform_work_paths(tmp_path, "class2", "quiz").results_path
    source.replace(target)
    with pytest.raises(result_service.ScoreFormRoutedResultIntegrityError):
        result_service._managed_review_result_links(tmp_path)


def test_global_history_requires_assignment_definition_directory_identity(
    tmp_path,
) -> None:
    _managed_review_targets(tmp_path)
    _failure_record, _resolution, _source = _write_one_review_result(tmp_path)
    definition = scoreform_work_paths(
        tmp_path, "class1", "quiz"
    ).assignment_path
    value = json.loads(definition.read_text(encoding="utf-8"))
    value["assignment_id"] = "different"
    definition.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(result_service.ScoreFormRoutedResultIntegrityError):
        result_service._managed_review_result_links(tmp_path)


@pytest.mark.parametrize("ancestor", ["modules", "scoreform", "work"])
def test_global_history_discovery_rejects_symlinked_ancestor(
    tmp_path, ancestor
) -> None:
    _managed_review_targets(tmp_path)
    _failure_record, _resolution, _path = _write_one_review_result(tmp_path)
    class_root = tmp_path / "classes" / "class1"
    nodes = {
        "modules": class_root / "modules",
        "scoreform": class_root / "modules" / "scoreform",
        "work": class_root / "modules" / "scoreform" / "work",
    }
    node = nodes[ancestor]
    target = tmp_path / f"real_{ancestor}"
    node.rename(target)
    try:
        node.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("Directory symlinks are unavailable.")
    with pytest.raises(result_service.ScoreFormRoutedResultIntegrityError):
        result_service._managed_review_result_links(tmp_path)


def test_global_history_discovery_rejects_symlinked_results_file(tmp_path) -> None:
    _managed_review_targets(tmp_path)
    _failure_record, _resolution, path = _write_one_review_result(tmp_path)
    target = tmp_path / "real_results.csv"
    path.replace(target)
    try:
        path.symlink_to(target)
    except OSError:
        pytest.skip("File symlinks are unavailable.")
    with pytest.raises(result_service.ScoreFormRoutedResultIntegrityError):
        result_service._managed_review_result_links(tmp_path)


def test_misplaced_exact_link_fails_integrity_without_second_row(
    tmp_path, monkeypatch
) -> None:
    _managed_review_targets(tmp_path)
    failure = _failure()
    write_routing_failure_metadata(tmp_path, failure)
    real_write = review_service.write_scan_resolution_metadata
    monkeypatch.setattr(
        review_service,
        "write_scan_resolution_metadata",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ScanResolutionMetadataWriteError("resolution write failed")
        ),
    )
    with pytest.raises(ScanReviewPartialOperationError):
        resolve_scan_review_item(
            tmp_path,
            failure.failure_id,
            "manual_entry",
            class_id="class1",
            assignment_id="quiz",
            student_id="student1",
            answers={1: "A", 2: "blank"},
        )
    source = scoreform_work_paths(tmp_path, "class1", "quiz").results_path
    misplaced = scoreform_work_paths(tmp_path, "class2", "quiz").results_path
    source.replace(misplaced)
    monkeypatch.setattr(review_service, "write_scan_resolution_metadata", real_write)
    with pytest.raises(ScanReviewError, match="Manual-entry result writing failed"):
        resolve_scan_review_item(
            tmp_path,
            failure.failure_id,
            "manual_entry",
            class_id="class1",
            assignment_id="quiz",
            student_id="student1",
            answers={1: "A", 2: "blank"},
        )
    assert not source.exists()
    with misplaced.open(newline="", encoding="utf-8") as handle:
        assert len(list(csv.DictReader(handle))) == 1


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"route_payload": "PDS2|x"}, "route_payload"),
        ({"answers": {1: "A"}}, "Answer data"),
        ({"class_id": "class1"}, "identity overrides"),
    ],
)
def test_nonconsuming_actions_reject_incompatible_arguments(
    tmp_path, kwargs, message
) -> None:
    failure = _failure()
    write_routing_failure_metadata(tmp_path, failure)
    with pytest.raises(ScanReviewError, match=message):
        resolve_scan_review_item(tmp_path, failure.failure_id, "defer", **kwargs)


def test_route_action_rejects_nonissued_issuance(tmp_path, monkeypatch) -> None:
    failure = _failure()
    write_routing_failure_metadata(tmp_path, failure)
    context = SimpleNamespace(
        issuance=SimpleNamespace(lifecycle=SimpleNamespace(status="prepared"))
    )
    monkeypatch.setattr(
        review_service,
        "_validated_route",
        lambda *_args: (SimpleNamespace(), SimpleNamespace(), context),
    )
    with pytest.raises(ScanReviewError, match="issued answer sheet"):
        resolve_scan_review_item(
            tmp_path,
            failure.failure_id,
            "route_selected",
            route_payload="PDS2|synthetic",
        )


def test_evidence_retry_after_resolution_failure_reuses_one_copy(
    tmp_path, monkeypatch
) -> None:
    _managed_assignment(tmp_path)
    failure = _failure()
    write_routing_failure_metadata(tmp_path, failure)
    evidence = tmp_path / "evidence.pdf"
    evidence.write_bytes(b"evidence")
    real_write = review_service.write_scan_resolution_metadata

    def fail_resolution(*_args, **_kwargs):
        raise ScanResolutionMetadataWriteError("resolution write failed")

    monkeypatch.setattr(
        review_service, "write_scan_resolution_metadata", fail_resolution
    )
    with pytest.raises(ScanReviewPartialOperationError):
        resolve_scan_review_item(
            tmp_path,
            failure.failure_id,
            "manual_entry",
            evidence_path="evidence.pdf",
            class_id="class1",
            assignment_id="quiz",
            student_id="student1",
            answers={1: "A", 2: "blank"},
        )
    scans = scoreform_work_paths(tmp_path, "class1", "quiz").scans_dir
    assert len(tuple(scans.iterdir())) == 1

    monkeypatch.setattr(review_service, "write_scan_resolution_metadata", real_write)
    retried = resolve_scan_review_item(
        tmp_path,
        failure.failure_id,
        "manual_entry",
        evidence_path="evidence.pdf",
        class_id="class1",
        assignment_id="quiz",
        student_id="student1",
        answers={1: "A", 2: "blank"},
    )
    assert retried.result_already_present
    assert len(tuple(scans.iterdir())) == 1


def test_evidence_retry_rejects_changed_source_digest(tmp_path, monkeypatch) -> None:
    _managed_assignment(tmp_path)
    failure = _failure()
    write_routing_failure_metadata(tmp_path, failure)
    evidence = tmp_path / "evidence.pdf"
    evidence.write_bytes(b"first")
    monkeypatch.setattr(
        review_service,
        "write_scan_resolution_metadata",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ScanResolutionMetadataWriteError("resolution write failed")
        ),
    )
    with pytest.raises(ScanReviewPartialOperationError):
        resolve_scan_review_item(
            tmp_path,
            failure.failure_id,
            "manual_entry",
            evidence_path="evidence.pdf",
            class_id="class1",
            assignment_id="quiz",
            student_id="student1",
            answers={1: "A", 2: "blank"},
        )
    evidence.write_bytes(b"second")
    with pytest.raises(ScanReviewPartialOperationError) as raised:
        resolve_scan_review_item(
            tmp_path,
            failure.failure_id,
            "manual_entry",
            evidence_path="evidence.pdf",
            class_id="class1",
            assignment_id="quiz",
            student_id="student1",
            answers={1: "A", 2: "blank"},
        )
    assert "Contradictory reuse" in str(raised.value.error)


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"class_id": "class1"},
        {"assignment_id": "quiz"},
    ],
)
def test_manual_marks_requires_class_and_assignment(tmp_path, kwargs) -> None:
    _managed_assignment(tmp_path)
    failure = _failure()
    write_routing_failure_metadata(tmp_path, failure)
    with pytest.raises(ScanReviewError, match="class and assignment"):
        resolve_scan_review_item(
            tmp_path, failure.failure_id, "manual_marks", **kwargs
        )


@pytest.mark.parametrize("student_id", [None, "student1"])
def test_manual_marks_persists_exact_teacher_verified_identity(
    tmp_path, student_id
) -> None:
    _managed_assignment(tmp_path)
    failure = _failure()
    write_routing_failure_metadata(tmp_path, failure)
    result = resolve_scan_review_item(
        tmp_path,
        failure.failure_id,
        "manual_marks",
        class_id="class1",
        assignment_id="quiz",
        student_id=student_id,
    )
    resolution = load_scan_resolution_metadata(tmp_path, result.resolution_id)
    details = review_service.validate_scoreform_resolution_details(
        resolution.module_details
    )
    expected = {"class_id": "class1", "assignment_id": "quiz"}
    if student_id is not None:
        expected["student_id"] = student_id
    assert details.identity_source == "teacher_verified"
    assert dict(details.identity) == expected


def test_manual_marks_rejects_student_outside_selected_roster(tmp_path) -> None:
    _managed_assignment(tmp_path)
    failure = _failure()
    write_routing_failure_metadata(tmp_path, failure)
    with pytest.raises(ScanReviewError, match="Student was not found"):
        resolve_scan_review_item(
            tmp_path,
            failure.failure_id,
            "manual_marks",
            class_id="class1",
            assignment_id="quiz",
            student_id="other_student",
        )


def test_dismissed_duplicate_is_service_gated_by_validated_category(tmp_path) -> None:
    ordinary = _failure("failure_ordinary")
    duplicate = _failure("failure_duplicate", "duplicate_page")
    write_routing_failure_metadata(tmp_path, ordinary)
    write_routing_failure_metadata(tmp_path, duplicate)
    with pytest.raises(ScanReviewError, match="duplicate failure category"):
        resolve_scan_review_item(
            tmp_path, ordinary.failure_id, "dismissed_duplicate"
        )
    result = resolve_scan_review_item(
        tmp_path, duplicate.failure_id, "dismissed_duplicate"
    )
    assert result.resolution_action == "dismissed_duplicate"


@pytest.mark.parametrize(
    "action,kwargs",
    [
        ("rescan_needed", {}),
        ("cannot_route", {}),
        ("mixed_assignment", {}),
        ("evidence_filed", {"evidence_path": "filed.pdf"}),
        ("other", {"message": "Reviewed."}),
        ("defer", {}),
    ],
)
def test_nonmanual_nonroute_actions_persist_no_identity(
    tmp_path, action, kwargs
) -> None:
    failure = _failure()
    write_routing_failure_metadata(tmp_path, failure)
    if action == "evidence_filed":
        (tmp_path / "filed.pdf").write_bytes(b"filed")
    result = resolve_scan_review_item(
        tmp_path, failure.failure_id, action, **kwargs
    )
    resolution = load_scan_resolution_metadata(tmp_path, result.resolution_id)
    details = review_service.validate_scoreform_resolution_details(
        resolution.module_details
    )
    assert details.identity_source == "none"
    assert dict(details.identity) == {}


def test_evidence_filed_rejects_source_through_symlinked_ancestor(tmp_path) -> None:
    failure = _failure()
    write_routing_failure_metadata(tmp_path, failure)
    real = tmp_path / "real"
    real.mkdir()
    (real / "filed.pdf").write_bytes(b"filed")
    link = tmp_path / "link"
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("Directory symlinks are unavailable.")
    with pytest.raises(ScanReviewError, match="symlink component"):
        resolve_scan_review_item(
            tmp_path,
            failure.failure_id,
            "evidence_filed",
            evidence_path="link/filed.pdf",
        )


def test_mixed_assignment_maps_to_core_cannot_route(tmp_path) -> None:
    failure = _failure()
    write_routing_failure_metadata(tmp_path, failure)
    result = resolve_scan_review_item(
        tmp_path,
        failure.failure_id,
        "mixed_assignment",
        now=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    resolution = load_scan_resolution_metadata(tmp_path, result.resolution_id)
    assert resolution.resolution_action == "cannot_route"


@pytest.mark.parametrize(
    "action",
    [
        "rescan_needed",
        "cannot_route",
        "defer",
        "mixed_assignment",
    ],
)
def test_no_evidence_actions_reject_evidence(tmp_path, action) -> None:
    failure = _failure()
    write_routing_failure_metadata(tmp_path, failure)
    evidence = tmp_path / "evidence.pdf"
    evidence.write_bytes(b"evidence")
    with pytest.raises(ScanReviewError, match="cannot include evidence"):
        resolve_scan_review_item(
            tmp_path,
            failure.failure_id,
            action,
            evidence_path="evidence.pdf",
            now=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )
