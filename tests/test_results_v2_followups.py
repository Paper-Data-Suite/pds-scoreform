from __future__ import annotations

import csv
from dataclasses import replace

import pytest

from scoreform import results as results_module
from scoreform.folders import setup_assignment_folder
from scoreform.page_scoring import ScoredAnswer
from scoreform.results import (
    ScoreFormAttemptExportBatch,
    ScoreFormExportedAttempt,
    ScoreFormRoutedResult,
    ScoreFormRoutedResultReadError,
    _export_result_models,
    load_routed_results_history,
    routed_results_v2_headers,
)
from scoreform.work_paths import scoreform_work_paths


def _setup(tmp_path, *, question_count=1):
    roster = {
        "class_id": "class1",
        "students": [
            {
                "student_id": "1001",
                "last_name": "Doe",
                "first_name": "Jane",
                "period": "1",
            }
        ],
    }
    assignment = {
        "assignment_id": "quiz1",
        "title": "Quiz",
        "question_count": question_count,
        "choices": ["A", "B", "C", "D"],
        "answer_key": {str(number): "A" for number in range(1, question_count + 1)},
        "standards": {str(number): [] for number in range(1, question_count + 1)},
    }
    assert setup_assignment_folder(roster, assignment, workspace_root=tmp_path)


def _scan(*, question_count=1, hash_digit="a", issuance_digit="1", scan_id="scan1"):
    answers = tuple(
        ScoredAnswer(number, "A", True)
        for number in range(1, question_count + 1)
    )
    return ScoreFormRoutedResult(
        result_origin="pds2_scan",
        class_id="class1",
        assignment_id="quiz1",
        student_id="1001",
        last_name="Doe",
        first_name="Jane",
        period="1",
        page_display="1",
        score=question_count,
        total_points=question_count,
        answers=answers,
        issuance_id="iss_" + issuance_digit * 32,
        generation_id="gen_" + issuance_digit * 32,
        artifact_id="art_" + issuance_digit * 32,
        page_ids=("pg_" + issuance_digit * 32,),
        route_ids=("rt_" + issuance_digit * 32,),
        logical_pages=(1,),
        source_file="scan.pdf",
        source_scan_id=scan_id,
        source_page_numbers=(1,),
        retained_source_relative_path=(
            f"scans/source/2026-07-16/{scan_id}.pdf"
        ),
        source_sha256=hash_digit * 64,
    )


def _manual(origin="plain_paper_manual"):
    return ScoreFormRoutedResult(
        result_origin=origin,
        class_id="class1",
        assignment_id="quiz1",
        student_id="1001",
        last_name="Doe",
        first_name="Jane",
        period="1",
        page_display="manual" if origin == "plain_paper_manual" else "review",
        score=1,
        total_points=1,
        answers=(ScoredAnswer(1, "A", True),),
        source_file=(
            "plain_paper_manual_entry"
            if origin == "plain_paper_manual"
            else "scan_review_manual:failure1"
        ),
    )


def _results_path(tmp_path):
    return scoreform_work_paths(tmp_path, "class1", "quiz1").results_path


def _read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or ()), list(reader)


def _rewrite_legacy_order(path):
    _headers, rows = _read_csv(path)
    question_count = int(rows[0]["Total"])
    headers = list(results_module._V2_LEGACY_BASE_HEADERS)
    for number in range(1, question_count + 1):
        headers.extend((f"Q{number}", f"Q{number}_Correct"))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


@pytest.mark.parametrize("question_count", (1, 30))
def test_teacher_first_headers_have_exact_dynamic_order(question_count):
    questions = [
        item
        for number in range(1, question_count + 1)
        for item in (f"Q{number}", f"Q{number}_Correct")
    ]
    expected = [
        "class_id",
        "assignment_id",
        "student_id",
        "last_name",
        "first_name",
        "period",
        "Score",
        "Total",
        *questions,
        "Page",
        "attempt_number",
        "scan_timestamp",
        "source_file",
        "result_schema_version",
        "result_origin",
        "issuance_id",
        "generation_id",
        "artifact_id",
        "page_ids",
        "route_ids",
        "logical_pages",
        "source_scan_id",
        "source_pages",
        "retained_source_path",
        "source_sha256",
    ]

    assert routed_results_v2_headers(question_count) == expected


def test_new_teacher_order_round_trips_canonical_values(tmp_path):
    _setup(tmp_path, question_count=3)
    result = _scan(question_count=3)
    assert _export_result_models((result,), workspace_root=tmp_path).succeeded
    path = _results_path(tmp_path)
    headers, rows = _read_csv(path)

    assert headers == routed_results_v2_headers(3)
    assert rows[0]["page_ids"] == '["pg_11111111111111111111111111111111"]'
    assert rows[0]["source_pages"] == "[1]"
    assert load_routed_results_history(path)[0].result == result


def test_legacy_order_load_is_read_only_then_equivalent_export_normalizes(tmp_path):
    _setup(tmp_path)
    first = _scan()
    assert _export_result_models((first,), workspace_root=tmp_path).succeeded
    path = _results_path(tmp_path)
    _rewrite_legacy_order(path)
    before_load = path.read_bytes()

    loaded = load_routed_results_history(path)

    assert loaded[0].result == first
    assert path.read_bytes() == before_load
    retained_again = replace(
        first,
        source_file="renamed.pdf",
        source_scan_id="scan2",
        retained_source_relative_path="scans/source/2026-07-16/scan2.pdf",
    )
    batch = _export_result_models((retained_again,), workspace_root=tmp_path)
    headers, rows = _read_csv(path)
    assert not batch.appended_attempts
    assert batch.already_present_attempts[0].attempt_number == 1
    assert batch.already_present_attempts[0].result == first
    assert batch.already_present_attempts[0].result.source_file == "scan.pdf"
    assert batch.already_present_attempts[0].result.source_scan_id == "scan1"
    assert batch.already_present_attempts[0].result.retained_source_relative_path == (
        "scans/source/2026-07-16/scan1.pdf"
    )
    assert headers == routed_results_v2_headers(1)
    assert len(rows) == 1
    assert rows[0]["source_scan_id"] == "scan1"


def test_append_to_legacy_order_preserves_old_row_and_normalizes(tmp_path):
    _setup(tmp_path)
    first = _scan()
    assert _export_result_models((first,), workspace_root=tmp_path).succeeded
    path = _results_path(tmp_path)
    _rewrite_legacy_order(path)
    _headers, before_rows = _read_csv(path)

    second = replace(first, source_scan_id="scan2", source_sha256="b" * 64)
    batch = _export_result_models((second,), workspace_root=tmp_path)
    headers, after_rows = _read_csv(path)

    assert batch.appended_attempts[0].attempt_number == 2
    assert headers == routed_results_v2_headers(1)
    assert after_rows[0] == before_rows[0]
    assert after_rows[1]["attempt_number"] == "2"


def test_explicit_history_can_grow_question_width_in_teacher_order(tmp_path):
    path = tmp_path / "explicit.csv"
    first = _scan(question_count=1)
    second = _scan(
        question_count=3,
        hash_digit="b",
        issuance_digit="2",
        scan_id="scan2",
    )

    assert _export_result_models(
        (first,), workspace_root=tmp_path, explicit_output_file=path
    ).succeeded
    assert _export_result_models(
        (second,), workspace_root=tmp_path, explicit_output_file=path
    ).succeeded
    headers, rows = _read_csv(path)

    assert headers == routed_results_v2_headers(3)
    assert rows[0]["Q2"] == rows[0]["Q2_Correct"] == ""
    assert rows[1]["Q3"] == "A"


def test_legacy_normalization_staging_failure_preserves_original(
    tmp_path, monkeypatch
):
    _setup(tmp_path)
    result = _scan()
    assert _export_result_models((result,), workspace_root=tmp_path).succeeded
    path = _results_path(tmp_path)
    _rewrite_legacy_order(path)
    before = path.read_bytes()
    monkeypatch.setattr(
        results_module,
        "_stage_history",
        lambda *_args: (_ for _ in ()).throw(OSError("stage failed")),
    )

    batch = _export_result_models((result,), workspace_root=tmp_path)

    assert batch.failures[0].stage == "staging"
    assert path.read_bytes() == before
    assert not tuple(path.parent.glob("*.tmp"))


def test_arbitrary_v2_header_permutation_is_rejected(tmp_path):
    _setup(tmp_path)
    assert _export_result_models((_scan(),), workspace_root=tmp_path).succeeded
    path = _results_path(tmp_path)
    headers, rows = _read_csv(path)
    headers[0], headers[1] = headers[1], headers[0]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)

    with pytest.raises(ScoreFormRoutedResultReadError):
        load_routed_results_history(path)


def test_equivalent_historical_duplicates_use_earliest_attempt(tmp_path):
    _setup(tmp_path)
    first = _scan()
    assert _export_result_models((first,), workspace_root=tmp_path).succeeded
    path = _results_path(tmp_path)
    headers, rows = _read_csv(path)
    duplicate = dict(rows[0])
    duplicate.update(
        attempt_number="2",
        scan_timestamp="2026-07-16T15:00:00+00:00",
        source_file="renamed.pdf",
        source_scan_id="scan2",
        retained_source_path="scans/source/2026-07-16/scan2.pdf",
    )
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows((*rows, duplicate))

    assert len(load_routed_results_history(path)) == 2
    future = replace(
        first,
        source_file="third-name.pdf",
        source_scan_id="scan3",
        retained_source_relative_path="scans/source/2026-07-16/scan3.pdf",
    )
    batch = _export_result_models((future,), workspace_root=tmp_path)
    assert not batch.appended_attempts
    assert batch.already_present_attempts[0].attempt_number == 1
    assert len(_read_csv(path)[1]) == 2


def test_conflicting_historical_content_key_is_rejected(tmp_path):
    _setup(tmp_path)
    assert _export_result_models((_scan(),), workspace_root=tmp_path).succeeded
    path = _results_path(tmp_path)
    headers, rows = _read_csv(path)
    conflicting = dict(rows[0])
    conflicting.update(
        attempt_number="2",
        Score="0",
        Q1="B",
        Q1_Correct="False",
    )
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows((*rows, conflicting))

    with pytest.raises(ScoreFormRoutedResultReadError, match="source_sha256"):
        load_routed_results_history(path)
    batch = _export_result_models((_scan(scan_id="scan3"),), workspace_root=tmp_path)
    assert batch.failures[0].stage == "preflight"


def test_incoming_content_keys_collapse_or_conflict_and_issuances_stay_distinct(
    tmp_path,
):
    _setup(tmp_path)
    first = _scan()
    equivalent = replace(
        first,
        source_file="copy.pdf",
        source_scan_id="scan2",
        retained_source_relative_path="scans/source/2026-07-16/scan2.pdf",
    )
    two_issuances = _scan(issuance_digit="2", scan_id="scan3")
    batch = _export_result_models(
        (first, equivalent, two_issuances), workspace_root=tmp_path
    )
    assert [item.attempt_number for item in batch.appended_attempts] == [1, 2]

    _setup(tmp_path / "conflict")
    contradictory = replace(
        first,
        score=0,
        answers=(ScoredAnswer(1, "B", False),),
        source_scan_id="scan4",
    )
    conflict = _export_result_models(
        (first, contradictory), workspace_root=tmp_path / "conflict"
    )
    assert conflict.failures[0].stage == "integrity"


def test_export_batch_uses_content_identity_without_changing_manual_identities(
    tmp_path,
):
    path = tmp_path / "results.csv"
    first = _scan()
    same_content_new_intake = replace(
        first,
        source_scan_id="scan2",
        retained_source_relative_path="scans/source/2026-07-16/scan2.pdf",
    )
    with pytest.raises(ValueError, match="content identities"):
        ScoreFormAttemptExportBatch(
            appended_attempts=(ScoreFormExportedAttempt(first, path, 1),),
            already_present_attempts=(
                ScoreFormExportedAttempt(same_content_new_intake, path, 1),
            ),
            output_paths=(path,),
        )

    different_bytes = replace(
        same_content_new_intake,
        source_sha256="b" * 64,
    )
    distinct = ScoreFormAttemptExportBatch(
        appended_attempts=(
            ScoreFormExportedAttempt(first, path, 1),
            ScoreFormExportedAttempt(different_bytes, path, 2),
        ),
        output_paths=(path,),
    )
    assert len(distinct.appended_attempts) == 2

    manual = _manual()
    review = _manual("scan_review_manual")
    unaffected = ScoreFormAttemptExportBatch(
        appended_attempts=(
            ScoreFormExportedAttempt(manual, path, 1),
            ScoreFormExportedAttempt(manual, path, 2),
            ScoreFormExportedAttempt(review, path, 3),
            ScoreFormExportedAttempt(review, path, 4),
        ),
        output_paths=(path,),
    )
    assert len(unaffected.appended_attempts) == 4


def test_deduplication_does_not_mutate_retained_source_evidence(tmp_path):
    _setup(tmp_path)
    retained = tmp_path / "scans" / "source" / "2026-07-16" / "scan1.pdf"
    retained.parent.mkdir(parents=True)
    retained.write_bytes(b"retained evidence")
    first = _scan()
    assert _export_result_models((first,), workspace_root=tmp_path).succeeded
    before = retained.read_bytes()

    duplicate = replace(
        first,
        source_scan_id="scan2",
        retained_source_relative_path="scans/source/2026-07-16/scan2.pdf",
    )
    batch = _export_result_models((duplicate,), workspace_root=tmp_path)

    assert batch.already_present_attempts
    assert retained.read_bytes() == before
