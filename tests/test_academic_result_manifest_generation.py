from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import pytest

from scoreform.academic_result_manifest import manifest_to_canonical_json_bytes
from scoreform.academic_result_manifest_generation import (
    ScoreFormManifestGenerationIntegrityError,
    ScoreFormManifestGenerationNotFoundError,
    build_academic_result_manifest,
    generate_academic_result_manifest,
    load_academic_result_manifest_generation_context,
)
from scoreform.assignment import AssignmentJsonBytesError, assignment_from_json_bytes
from scoreform.page_scoring import ScoredAnswer
from scoreform.results import (
    ScoreFormRoutedResult,
    export_scoreform_result_models,
    routed_results_history_from_csv_bytes,
    routed_results_v2_headers,
)
from scoreform.work_paths import scoreform_work_paths


def _managed_assignment(tmp_path, *, title="Unit Quiz"):
    paths = scoreform_work_paths(tmp_path, "class1", "quiz1")
    paths.work_root.mkdir(parents=True)
    assignment = {
        "assignment_id": "quiz1",
        "title": title,
        "question_count": 2,
        "choices": ["A", "B", "C", "D"],
        "layout_id": "standard_15q_abcd_v1",
        "answer_key": {"1": "A", "2": "B"},
        "standards": {"1": [], "2": []},
    }
    paths.assignment_path.write_text(json.dumps(assignment), encoding="utf-8")
    result = ScoreFormRoutedResult(
        result_origin="plain_paper_manual",
        class_id="class1",
        assignment_id="quiz1",
        student_id="student2",
        last_name="Synthetic",
        first_name="Learner",
        period="2",
        page_display="manual",
        score=1,
        total_points=2,
        answers=(ScoredAnswer(1, "A", True), ScoredAnswer(2, "BLANK", False)),
        source_file="plain_paper_manual_entry",
    )
    assert export_scoreform_result_models((result,), workspace_root=tmp_path).succeeded
    return paths


def test_exact_native_bytes_are_hashed_and_mapped_without_private_fields(tmp_path):
    paths = _managed_assignment(tmp_path)
    context = load_academic_result_manifest_generation_context(
        tmp_path, paths.work_ref
    )
    manifest = build_academic_result_manifest(
        context,
        record_set_revision=1,
        generated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    assert manifest.source_snapshot.assignment.sha256 == hashlib.sha256(
        paths.assignment_path.read_bytes()
    ).hexdigest()
    assert manifest.source_snapshot.results_history.sha256 == hashlib.sha256(
        paths.results_path.read_bytes()
    ).hexdigest()
    assert manifest.assignment.assignment_id == "quiz1"
    assert manifest.assignment.total_points == 2
    assert manifest.assignment.questions[0].standard_ids == ()
    attempt = manifest.students[0].attempts[0]
    assert attempt.points_earned == 1
    assert attempt.responses[1].response_state == "blank"
    assert attempt.responses[1].selected_answer is None
    assert attempt.provenance.__class__.__name__ == "PlainPaperManualProvenance"
    rendered = json.dumps(json.loads(manifest_to_canonical_json_bytes(manifest)))
    assert "Synthetic" not in rendered
    assert "Learner" not in rendered
    assert "answer_key" not in rendered


def test_missing_results_is_not_created_to_permit_generation(tmp_path):
    paths = scoreform_work_paths(tmp_path, "class1", "quiz1")
    paths.work_root.mkdir(parents=True)
    paths.assignment_path.write_text(
        json.dumps(
            {
                "assignment_id": "quiz1",
                "title": "Quiz",
                "question_count": 1,
                "choices": ["A", "B", "C", "D"],
                "layout_id": "standard_15q_abcd_v1",
                "answer_key": {"1": "A"},
                "standards": {"1": []},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ScoreFormManifestGenerationNotFoundError):
        generate_academic_result_manifest(tmp_path, "class1", "quiz1")
    assert not paths.results_path.exists()


def test_assignment_parser_rejects_duplicate_keys_nonfinite_and_nonbytes():
    with pytest.raises(AssignmentJsonBytesError):
        assignment_from_json_bytes(b'{"assignment_id":"a","assignment_id":"b"}')
    with pytest.raises(AssignmentJsonBytesError):
        assignment_from_json_bytes(b'{"value":NaN}')
    with pytest.raises(AssignmentJsonBytesError):
        assignment_from_json_bytes("{}")


def test_result_byte_parser_rejects_nonbytes_and_invalid_utf8():
    with pytest.raises(Exception):
        routed_results_history_from_csv_bytes("")
    with pytest.raises(Exception):
        routed_results_history_from_csv_bytes(b"\xff")


def test_duplicate_attempt_identity_is_rejected(tmp_path):
    paths = _managed_assignment(tmp_path)
    lines = paths.results_path.read_text(encoding="utf-8").splitlines()
    paths.results_path.write_text("\n".join([lines[0], lines[1], lines[1]]) + "\n", encoding="utf-8")
    with pytest.raises(ScoreFormManifestGenerationIntegrityError):
        load_academic_result_manifest_generation_context(tmp_path, paths.work_ref)


def test_header_only_schema_v2_history_builds_empty_students(tmp_path):
    paths = scoreform_work_paths(tmp_path, "class1", "quiz1")
    paths.work_root.mkdir(parents=True)
    paths.assignment_path.write_text(
        json.dumps(
            {
                "assignment_id": "quiz1",
                "title": "Quiz",
                "question_count": 1,
                "choices": ["A", "B", "C", "D"],
                "layout_id": "standard_15q_abcd_v1",
                "answer_key": {"1": "A"},
                "standards": {"1": []},
            }
        ),
        encoding="utf-8",
    )
    paths.results_path.write_text(
        ",".join(routed_results_v2_headers(1)) + "\n", encoding="utf-8"
    )
    context = load_academic_result_manifest_generation_context(tmp_path, paths.work_ref)
    assert context.students == ()


def test_historical_correctness_is_not_rescored_against_answer_key(tmp_path):
    paths = _managed_assignment(tmp_path)
    assignment = json.loads(paths.assignment_path.read_text(encoding="utf-8"))
    assignment["answer_key"]["1"] = "D"
    paths.assignment_path.write_text(json.dumps(assignment), encoding="utf-8")
    context = load_academic_result_manifest_generation_context(tmp_path, paths.work_ref)
    attempt = context.students[0].attempts[0]
    assert attempt.responses[0].selected_answer == "A"
    assert attempt.responses[0].correct is True
    assert attempt.points_earned == 1


def test_pds2_retained_evidence_and_scan_review_provenance(tmp_path):
    paths = scoreform_work_paths(tmp_path, "class1", "quiz1")
    paths.work_root.mkdir(parents=True)
    paths.assignment_path.write_text(
        json.dumps(
            {
                "assignment_id": "quiz1",
                "title": "Quiz",
                "question_count": 1,
                "choices": ["A", "B", "C", "D"],
                "layout_id": "standard_15q_abcd_v1",
                "answer_key": {"1": "A"},
                "standards": {"1": []},
            }
        ),
        encoding="utf-8",
    )
    retained = tmp_path / "scans" / "source" / "2026-01-01" / "scan.png"
    retained.parent.mkdir(parents=True)
    retained.write_bytes(b"synthetic retained bytes")
    digest = hashlib.sha256(retained.read_bytes()).hexdigest()
    pds2 = ScoreFormRoutedResult(
        result_origin="pds2_scan",
        class_id="class1",
        assignment_id="quiz1",
        student_id="student1",
        last_name="Synthetic",
        first_name="One",
        period="1",
        page_display="1",
        score=1,
        total_points=1,
        answers=(ScoredAnswer(1, "A", True),),
        issuance_id="iss_" + "1" * 32,
        generation_id="gen_" + "2" * 32,
        artifact_id="art_" + "3" * 32,
        page_ids=("pg_" + "4" * 32,),
        route_ids=("rt_" + "5" * 32,),
        logical_pages=(1,),
        source_file="scan.png",
        source_scan_id="scan1",
        source_page_numbers=(1,),
        retained_source_relative_path="scans/source/2026-01-01/scan.png",
        source_sha256=digest,
    )
    review = ScoreFormRoutedResult(
        result_origin="scan_review_manual",
        class_id="class1",
        assignment_id="quiz1",
        student_id="student2",
        last_name="Synthetic",
        first_name="Two",
        period="1",
        page_display="review",
        score=0,
        total_points=1,
        answers=(ScoredAnswer(1, "AMBIGUOUS", False),),
        source_file="scan_review_manual:failure1",
    )
    assert export_scoreform_result_models((pds2, review), workspace_root=tmp_path).succeeded
    context = load_academic_result_manifest_generation_context(tmp_path, paths.work_ref)
    first = context.students[0].attempts[0]
    second = context.students[1].attempts[0]
    assert first.provenance.source_sha256 == digest
    assert first.provenance.retained_source_path == "scans/source/2026-01-01/scan.png"
    assert second.provenance.review_reference.failure_id == "failure1"
    retained.write_bytes(b"changed")
    with pytest.raises(ScoreFormManifestGenerationIntegrityError):
        load_academic_result_manifest_generation_context(tmp_path, paths.work_ref)
