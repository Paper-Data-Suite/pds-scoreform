import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pds_core.scan_failure_metadata import (
    RoutingFailureMetadata,
    write_routing_failure_metadata,
)

from scoreform import scoring
from scoreform.scan_review_resolution import (
    SCOREFORM_FAILURE_CATEGORY_MAP,
    ScanReviewError,
    discover_scan_review_items,
    preserve_qr_batch_failures_for_review,
    resolve_scan_review_item,
)

NOW = datetime(2026, 7, 11, 15, 45, 12, tzinfo=timezone.utc)


def _failure(root: Path, failure_id="failure_test", **overrides):
    values = {
        "schema_version": "1",
        "failure_id": failure_id,
        "scope": "page",
        "stage": "scoreform_qr_review",
        "created_at": NOW.isoformat(),
        "failure_category": "payload_missing",
        "failure_message": "missing QR code",
        "source_filename": "packet.pdf",
        "module_details": {
            "scoreform_failure_category": "missing_qr",
            "scoreform_failure_reason": "missing QR code",
        },
        "module": "scoreform",
        "source_scan_id": None,
        "source_sha256": None,
        "retained_source_path": "scans/source/2026-07-11/packet.pdf",
        "review_copy_path": None,
        "source_page_number": 2,
        "detected_payload": None,
        "payload_page_number": None,
        "class_id": None,
        "assignment_id": None,
        "student_id": None,
    }
    values.update(overrides)
    path = root / values["retained_source_path"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"paper truth")
    return write_routing_failure_metadata(root, RoutingFailureMetadata(**values))


def _workspace_assignment(root: Path):
    assignment_dir = root / "classes/english9_p2/assignments/quiz"
    assignment_dir.mkdir(parents=True)
    (assignment_dir / "assignment.json").write_text(
        json.dumps(
            {
                "assignment_id": "quiz",
                "title": "Quiz",
                "question_count": 2,
                "choices": ["A", "B", "C", "D"],
                "answer_key": {"1": "A", "2": "C"},
                "standards": {"1": [], "2": []},
            }
        ),
        encoding="utf-8",
    )
    roster = root / "classes/english9_p2/roster.csv"
    roster.write_text(
        "class_id,student_id,last_name,first_name,period\n"
        "english9_p2,1001,Doe,Jane,2\n",
        encoding="utf-8",
    )
    return assignment_dir


def test_preserve_qr_failures_maps_categories_and_provenance(tmp_path):
    retained = type(
        "Retained",
        (),
        {
            "source_filename": "packet.pdf",
            "source_scan_id": "scan_packet",
            "source_sha256": "a" * 64,
            "retained_source_relative_path": "scans/source/2026-07-11/packet.pdf",
        },
    )()
    summary = scoring.QRBatchSummary()
    summary.failures.extend(
        [
            scoring.QRBatchFailure(1, "missing_qr", "missing QR code"),
            scoring.QRBatchFailure(
                2,
                "assignment_lookup_failed",
                "assignment file not found",
                "english9_p2",
                "quiz",
                "1001",
            ),
        ]
    )
    results = scoring.QRBatchResults(summary=summary, retained_source=retained)

    paths = preserve_qr_batch_failures_for_review(
        results, "packet.pdf", tmp_path, now=NOW
    )

    assert len(paths) == 2
    records = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    assert records[0]["failure_category"] == SCOREFORM_FAILURE_CATEGORY_MAP["missing_qr"]
    assert records[0]["retained_source_path"].startswith("scans/source/")
    assert records[1]["class_id"] == "english9_p2"
    assert records[1]["module_details"]["scoreform_failure_category"] == "assignment_lookup_failed"


def test_discovery_hides_resolved_keeps_deferred_and_ignores_other_modules(tmp_path):
    _failure(tmp_path, "failure_one")
    _failure(tmp_path, "failure_two")
    _failure(
        tmp_path,
        "failure_other",
        stage="quillan_scan_review",
        module="quillan",
    )
    (tmp_path / "scans/review/bad.json").write_text("{", encoding="utf-8")

    resolve_scan_review_item(tmp_path, "failure_one", "cannot_route", now=NOW)
    resolve_scan_review_item(tmp_path, "failure_two", "defer", now=NOW)

    default = discover_scan_review_items(tmp_path)
    included = discover_scan_review_items(tmp_path, include_resolved=True)
    assert [item.failure_id for item in default.items] == ["failure_two"]
    assert default.items[0].status == "deferred"
    assert {item.failure_id for item in included.items} == {
        "failure_one",
        "failure_two",
    }
    assert default.warning_count == 1


@pytest.mark.parametrize(
    "action",
    [
        "manual_marks",
        "rescan_needed",
        "cannot_route",
        "mixed_assignment",
        "evidence_filed",
        "dismissed_duplicate",
        "other",
        "defer",
    ],
)
def test_resolution_actions_write_immutable_core_records(tmp_path, action):
    failure_path = _failure(tmp_path)
    original = failure_path.read_bytes()
    kwargs = {}
    if action == "evidence_filed":
        kwargs["evidence_path"] = "scans/source/2026-07-11/packet.pdf"
    if action == "other":
        kwargs["message"] = "Teacher verified a safe alternate outcome."

    result = resolve_scan_review_item(tmp_path, "failure_test", action, now=NOW, **kwargs)

    assert result.resolution_metadata_path.exists()
    record = json.loads(result.resolution_metadata_path.read_text(encoding="utf-8"))
    assert record["module"] == "scoreform"
    assert record["module_details"]["teacher_selected_action"] == action
    assert record["resolution_status"] == (
        "deferred" if action == "defer" else "resolved"
    )
    assert failure_path.read_bytes() == original
    assert (tmp_path / "scans/source/2026-07-11/packet.pdf").exists()


def test_manual_entry_writes_existing_results_contract_and_tagged_evidence(tmp_path):
    assignment_dir = _workspace_assignment(tmp_path)
    _failure(tmp_path)

    result = resolve_scan_review_item(
        tmp_path,
        "failure_test",
        "manual_entry",
        class_id="english9_p2",
        assignment_id="quiz",
        student_id="1001",
        answers={1: "A", 2: "B"},
        now=NOW,
    )

    assert result.result_written
    with (assignment_dir / "results.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
        headers = handle.seek(0) or next(csv.reader(handle))
    assert rows[0]["Score"] == "1"
    assert rows[0]["Total"] == "2"
    assert "_manual_entry.pdf" in rows[0]["source_file"]
    assert "score_source" not in headers
    assert "manual_entry" not in headers
    evidence = tmp_path / rows[0]["source_file"]
    assert evidence.exists()
    assert (tmp_path / "scans/source/2026-07-11/packet.pdf").exists()
    resolution = json.loads(result.resolution_metadata_path.read_text(encoding="utf-8"))
    assert resolution["module_details"]["manual_entry_score"] == 1


def test_manual_entry_rejects_missing_identity_without_writing(tmp_path):
    _failure(tmp_path)
    with pytest.raises(ScanReviewError, match="requires validated"):
        resolve_scan_review_item(
            tmp_path,
            "failure_test",
            "manual_entry",
            answers={1: "A"},
            now=NOW,
        )
    assert not list((tmp_path / "scans/review/resolutions").glob("*.json"))


def test_other_requires_message_and_evidence_path_rejects_traversal(tmp_path):
    _failure(tmp_path)
    with pytest.raises(ScanReviewError, match="requires a non-empty message"):
        resolve_scan_review_item(tmp_path, "failure_test", "other", now=NOW)
    with pytest.raises(ScanReviewError, match="unsafe traversal"):
        resolve_scan_review_item(
            tmp_path,
            "failure_test",
            "evidence_filed",
            evidence_path="../outside.pdf",
            now=NOW,
        )
