from __future__ import annotations

import csv
from dataclasses import replace

import pytest

from scoreform import results as results_module
from scoreform.folders import setup_assignment_folder
from scoreform.page_scoring import ScoredAnswer
from scoreform.results import (
    ScoreFormRoutedResult,
    ScoreFormRoutedResultHistory,
    ScoreFormRoutedResultHistoryRow,
    ScoreFormRoutedResultValidationError,
    ScoreFormTemporaryCleanupFailure,
    _export_result_models,
    load_routed_results_history,
    parse_routed_results_history_csv_bytes,
    routed_results_history_from_csv_bytes,
)
from scoreform.work_paths import scoreform_work_paths


def _setup(tmp_path, assignments=("quiz1",)):
    roster = {"class_id": "class1", "students": [{
        "student_id": "1001", "last_name": "Doe", "first_name": "Jane", "period": "1",
    }]}
    for assignment_id in assignments:
        assignment = {
            "assignment_id": assignment_id, "title": assignment_id,
            "question_count": 1, "choices": ["A", "B", "C", "D"],
            "answer_key": {"1": "A"}, "standards": {"1": []},
        }
        assert setup_assignment_folder(roster, assignment, workspace_root=tmp_path)


def _scan(assignment_id="quiz1", *, issuance_digit="1", scan_id="scan_one"):
    return ScoreFormRoutedResult(
        result_origin="pds2_scan", class_id="class1", assignment_id=assignment_id,
        student_id="1001", last_name="Doe", first_name="Jane", period="1",
        page_display="1", score=1, total_points=1,
        answers=(ScoredAnswer(1, "A", True),),
        issuance_id="iss_" + issuance_digit * 32,
        generation_id="gen_" + issuance_digit * 32,
        artifact_id="art_" + issuance_digit * 32,
        page_ids=("pg_" + issuance_digit * 32,),
        route_ids=("rt_" + issuance_digit * 32,), logical_pages=(1,),
        source_file="scan.png", source_scan_id=scan_id, source_page_numbers=(1,),
        retained_source_relative_path="scans/source/2026-07-15/retained.png",
        source_sha256=issuance_digit * 64,
    )


def _manual(assignment_id="quiz1"):
    return ScoreFormRoutedResult(
        "plain_paper_manual", "class1", assignment_id, "1001", "Doe", "Jane", "1",
        "manual", 1, 1, (ScoredAnswer(1, "A", True),),
        source_file="plain_paper_manual_entry",
    )


@pytest.mark.parametrize("attempt_number", (True, False, 0, -1, "1", 1.0, None))
def test_history_row_rejects_noncanonical_attempt_numbers(attempt_number):
    with pytest.raises(ValueError, match="positive integer"):
        ScoreFormRoutedResultHistoryRow(
            _manual(), attempt_number, "2026-07-16T12:00:00+00:00"
        )


def test_history_row_rejects_naive_timestamp_deliberately():
    with pytest.raises(ValueError, match="timezone-aware ISO 8601"):
        ScoreFormRoutedResultHistoryRow(
            _manual(), 1, "2026-07-16T12:00:00"
        )


def test_history_row_rejects_non_string_timestamp_deliberately():
    with pytest.raises(TypeError, match="scan_timestamp must be a string"):
        ScoreFormRoutedResultHistoryRow(_manual(), 1, None)


def test_history_row_accepts_positive_attempt_and_aware_timestamp():
    row = ScoreFormRoutedResultHistoryRow(
        _manual(), 1, "2026-07-16T12:00:00+00:00"
    )
    assert row.attempt_number == 1
    assert row.scan_timestamp == "2026-07-16T12:00:00+00:00"


def test_structured_byte_parser_preserves_width_without_changing_rows_loader(
    tmp_path,
):
    _setup(tmp_path)
    assert _export_result_models((_manual(),), workspace_root=tmp_path).succeeded
    path = scoreform_work_paths(tmp_path, "class1", "quiz1").results_path
    content = path.read_bytes()

    parsed = parse_routed_results_history_csv_bytes(content)
    rows_only = routed_results_history_from_csv_bytes(content)

    assert isinstance(parsed, ScoreFormRoutedResultHistory)
    assert parsed.question_count == 1
    assert parsed.legacy_header_order is False
    assert parsed.rows == rows_only == load_routed_results_history(path)


def test_structured_byte_parser_reports_accepted_legacy_header_order():
    header = [*results_module._V2_LEGACY_BASE_HEADERS, "Q1", "Q1_Correct"]
    parsed = parse_routed_results_history_csv_bytes(
        (",".join(header) + "\r\n").encode()
    )
    assert parsed.rows == ()
    assert parsed.question_count == 1
    assert parsed.legacy_header_order is True


def test_routed_result_rejects_display_and_retained_path_contradictions():
    valid = _scan()
    with pytest.raises(ScoreFormRoutedResultValidationError):
        replace(valid, page_display="2")
    with pytest.raises(ScoreFormRoutedResultValidationError):
        replace(valid, last_name="Doe\nInjected")
    with pytest.raises(ScoreFormRoutedResultValidationError):
        replace(valid, retained_source_relative_path="elsewhere/retained.png")


@pytest.mark.parametrize(
    "retained_path",
    (
        "scans/source/20260715/file.png",
        "scans/source/2026-7-15/file.png",
        "scans/source/2026-07-15/",
        "scans/source/2026-07-15/subdir/file.png",
    ),
)
def test_routed_result_requires_canonical_retained_date_and_shape(retained_path):
    with pytest.raises(ScoreFormRoutedResultValidationError):
        replace(_scan(), retained_source_relative_path=retained_path)


def test_routed_result_accepts_canonical_retained_date():
    result = replace(
        _scan(),
        retained_source_relative_path="scans/source/2026-07-15/file.png",
    )
    assert result.retained_source_relative_path == (
        "scans/source/2026-07-15/file.png"
    )


def test_duplicate_identity_inside_one_transaction_is_deduplicated_or_rejected(tmp_path):
    _setup(tmp_path)
    result = _scan()
    exact = _export_result_models((result, result), workspace_root=tmp_path)
    assert len(exact.appended_attempts) == 1
    contradictory = replace(
        result, score=0, answers=(ScoredAnswer(1, "B", False),)
    )
    conflict = _export_result_models(
        (replace(result, source_scan_id="scan_two"),
         replace(contradictory, source_scan_id="scan_two")),
        workspace_root=tmp_path,
    )
    assert conflict.failures[0].stage == "integrity"


def test_equivalent_content_identity_duplicates_in_history_are_preserved(tmp_path):
    _setup(tmp_path)
    result = _scan()
    assert _export_result_models((result,), workspace_root=tmp_path).succeeded
    path = scoreform_work_paths(tmp_path, "class1", "quiz1").results_path
    rows = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join((*rows, rows[1])) + "\n", encoding="utf-8")
    batch = _export_result_models((result,), workspace_root=tmp_path)
    assert not batch.failures
    assert not batch.appended_attempts
    assert batch.already_present_attempts[0].attempt_number == 1
    assert len(path.read_text(encoding="utf-8").splitlines()) == 3


def test_pds2_history_rejects_historical_naive_timestamp(tmp_path):
    _setup(tmp_path)
    path = scoreform_work_paths(tmp_path, "class1", "quiz1").results_path
    assert _export_result_models((_scan(),), workspace_root=tmp_path).succeeded
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
        headers = list(rows[0])
    rows[0]["scan_timestamp"] = "2026-01-01 10:00:00"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)
    before = path.read_bytes()
    batch = _export_result_models((_manual(),), workspace_root=tmp_path)
    assert batch.failures
    assert path.read_bytes() == before


def test_scan_and_manual_share_numbering_in_both_directions(tmp_path):
    _setup(tmp_path)
    first = _export_result_models((_scan(),), workspace_root=tmp_path)
    manual = _export_result_models((_manual(),), workspace_root=tmp_path)
    later_scan = _export_result_models(
        (_scan(issuance_digit="2", scan_id="scan_two"),), workspace_root=tmp_path
    )
    assert first.appended_attempts[0].attempt_number == 1
    assert manual.appended_attempts[0].attempt_number == 2
    assert later_scan.appended_attempts[0].attempt_number == 3


def test_two_issuances_for_student_allocate_once_each(tmp_path):
    _setup(tmp_path)
    batch = _export_result_models(
        (_scan(), _scan(issuance_digit="2", scan_id="scan_two")),
        workspace_root=tmp_path,
    )
    assert [item.attempt_number for item in batch.appended_attempts] == [1, 2]


def test_explicit_mixed_assignment_history_and_managed_preflight_all_or_none(
    tmp_path
):
    explicit = tmp_path / "explicit.csv"
    mixed = _export_result_models(
        (_scan("quiz1"), _scan("quiz2", issuance_digit="2", scan_id="scan_two")),
        workspace_root=tmp_path, explicit_output_file=explicit,
    )
    assert mixed.succeeded and explicit.is_file()
    assert len(mixed.appended_attempts) == 2

    _setup(tmp_path, ("quiz1",))
    managed = _export_result_models(
        (_scan("quiz1"), _scan("missing", issuance_digit="3", scan_id="scan_three")),
        workspace_root=tmp_path,
    )
    assert managed.failures
    assert not scoreform_work_paths(tmp_path, "class1", "quiz1").results_path.exists()


def test_staging_failure_changes_no_target_and_reports_no_append(
    tmp_path, monkeypatch
):
    _setup(tmp_path, ("quiz1", "quiz2"))
    seeds = (_scan("quiz1", issuance_digit="1"), _scan("quiz2", issuance_digit="2"))
    assert _export_result_models(seeds, workspace_root=tmp_path).succeeded
    paths = [scoreform_work_paths(tmp_path, "class1", name).results_path for name in ("quiz1", "quiz2")]
    before = [path.read_bytes() for path in paths]
    actual_stage = results_module._stage_history

    def fail_second(path, headers, rows):
        if path.parent.name == "quiz2":
            raise OSError("staging failed")
        return actual_stage(path, headers, rows)

    monkeypatch.setattr(results_module, "_stage_history", fail_second)
    rescans = tuple(
        replace(item, source_scan_id="rescan", source_sha256="f" * 64)
        for item in seeds
    )
    batch = _export_result_models(rescans, workspace_root=tmp_path)
    assert [path.read_bytes() for path in paths] == before
    assert not batch.appended_attempts
    assert any(failure.stage == "staging" for failure in batch.failures)
    assert not tuple(tmp_path.rglob("*.tmp"))


def test_staging_cleanup_failure_is_retained(tmp_path, monkeypatch):
    _setup(tmp_path)
    cleanup = ScoreFormTemporaryCleanupFailure(
        tmp_path / "remaining.tmp", tmp_path / "results.csv",
        OSError("cleanup denied"),
    )
    error = results_module._HistoryStageError(
        "stage failed", temporary_path=cleanup.temporary_path,
        cleanup_failures=(cleanup,),
    )
    monkeypatch.setattr(
        results_module, "_stage_history",
        lambda *_args: (_ for _ in ()).throw(error),
    )
    batch = _export_result_models((_scan(),), workspace_root=tmp_path)
    assert not batch.appended_attempts
    assert batch.failures[0].stage == "staging"
    assert batch.failures[0].cleanup_failures == (cleanup,)


@pytest.mark.parametrize("failure_index", (0, 1, 2))
def test_replacement_failure_reports_only_persisted_attempts(
    tmp_path, monkeypatch, failure_index
):
    names = ("quiz1", "quiz2", "quiz3")
    _setup(tmp_path, names)
    seeds = tuple(_scan(name, issuance_digit=str(index)) for index, name in enumerate(names, 1))
    assert _export_result_models(seeds, workspace_root=tmp_path).succeeded
    actual_replace = results_module.os.replace
    failed_name = names[failure_index]

    def fail_selected(source, target):
        if target.parent.name == failed_name:
            raise PermissionError("locked")
        return actual_replace(source, target)

    monkeypatch.setattr(results_module.os, "replace", fail_selected)
    batch = _export_result_models(
        tuple(
            replace(item, source_scan_id="rescan", source_sha256="f" * 64)
            for item in seeds
        ),
        workspace_root=tmp_path,
    )
    assert [item.result.assignment_id for item in batch.appended_attempts] == list(
        names[:failure_index]
    )
    assert [path.parent.name for path in batch.output_paths] == list(
        names[:failure_index]
    )
    expected_failures = [(failed_name, "replacement")]
    expected_failures.extend(
        (name, "not_attempted") for name in names[failure_index + 1:]
    )
    assert [
        (failure.assignment_id, failure.stage) for failure in batch.failures
    ] == expected_failures


def test_cleanup_failure_remains_attached_to_primary_replacement_failure(
    tmp_path, monkeypatch
):
    _setup(tmp_path)
    seed = _scan()
    assert _export_result_models((seed,), workspace_root=tmp_path).succeeded
    monkeypatch.setattr(
        results_module.os, "replace",
        lambda *_args: (_ for _ in ()).throw(PermissionError("locked")),
    )
    remaining = []

    def fail_cleanup(staged):
        temporary_path, target_path = tuple(staged)[0]
        remaining.append(temporary_path)
        return (ScoreFormTemporaryCleanupFailure(
            temporary_path, target_path, OSError("cleanup denied")
        ),)

    monkeypatch.setattr(results_module, "_cleanup_staged", fail_cleanup)
    batch = _export_result_models(
        (replace(seed, source_scan_id="rescan", source_sha256="f" * 64),),
        workspace_root=tmp_path,
    )
    assert not batch.appended_attempts
    assert batch.failures[0].error.__cause__ is not None
    assert batch.failures[0].cleanup_failures[0].temporary_path == remaining[0]
    assert remaining[0].exists()


@pytest.mark.parametrize("timestamp", ("", "not-a-time", "2026-07-15T12:00:00"))
def test_invalid_v2_timestamp_is_rejected_without_changing_original(
    tmp_path, timestamp
):
    _setup(tmp_path)
    result = _scan()
    assert _export_result_models((result,), workspace_root=tmp_path).succeeded
    path = scoreform_work_paths(tmp_path, "class1", "quiz1").results_path
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
        headers = handle.seek(0) or next(csv.reader(handle))
    rows[0]["scan_timestamp"] = timestamp
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)
    before = path.read_bytes()
    batch = _export_result_models((result,), workspace_root=tmp_path)
    assert batch.failures
    assert path.read_bytes() == before
