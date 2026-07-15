import csv
import json
from dataclasses import replace
from datetime import datetime, timezone

import pytest

import scoreform.answer_sheet_persistence as persistence
from scoreform.answer_sheet_persistence import (
    AnswerSheetCollisionError,
    AnswerSheetIntegrityError,
    AnswerSheetReadError,
    AnswerSheetRevisionConflictError,
    AnswerSheetWriteError,
    load_answer_sheet_page_context,
    load_answer_sheet_record_set,
    transition_answer_sheet_issuance,
    write_answer_sheet_record_set,
)
from scoreform.answer_sheet_records import (
    AnswerSheetLifecycleError,
    AnswerSheetRecordError,
    AnswerSheetRecordSet,
    answer_sheet_issuance_from_mapping,
    answer_sheet_issuance_to_mapping,
    answer_sheet_page_from_mapping,
    answer_sheet_page_target,
    answer_sheet_page_to_mapping,
    build_answer_sheet_record_set,
    generate_artifact_id,
    generate_generation_id,
    generate_issuance_id,
    generate_page_id,
    transition_answer_sheet_lifecycle,
    validate_answer_sheet_record_set,
    validate_artifact_id,
    validate_generation_id,
    validate_issuance_id,
    validate_page_id,
)
from scoreform.work_paths import scoreform_work_paths

GENERATION_ID = "gen_00000000000000000000000000000001"
ARTIFACT_ID = "art_00000000000000000000000000000002"
ISSUANCE_ID = "iss_00000000000000000000000000000003"
PAGE_IDS = (
    "pg_00000000000000000000000000000004",
    "pg_00000000000000000000000000000005",
)
CREATED = datetime(2026, 7, 15, 1, 30, tzinfo=timezone.utc)


def _assignment(question_count=20, layout_id="standard_15q_abcd_v1"):
    return {
        "assignment_id": "quiz1",
        "title": "Quiz One",
        "question_count": question_count,
        "choices": ["A", "B", "C", "D"],
        "layout_id": layout_id,
        "answer_key": {str(index): "A" for index in range(1, question_count + 1)},
        "standards": {str(index): [] for index in range(1, question_count + 1)},
    }


def _student(student_id="1001"):
    return {
        "class_id": "class1",
        "student_id": student_id,
        "last_name": "Doe",
        "first_name": "Jane",
        "period": "2",
    }


def _record_set(**overrides):
    values = {
        "class_id": "class1",
        "assignment": _assignment(),
        "student": _student(),
        "generation_id": GENERATION_ID,
        "artifact_id": ARTIFACT_ID,
        "output_kind": "individual_pdf",
        "reason": "initial",
        "issuance_id": ISSUANCE_ID,
        "page_ids": PAGE_IDS,
        "clock": lambda: CREATED,
    }
    values.update(overrides)
    return build_answer_sheet_record_set(**values)


def _managed_sources(tmp_path, assignment=None, student=None):
    assignment = _assignment() if assignment is None else assignment
    student = _student() if student is None else student
    paths = scoreform_work_paths(tmp_path, "class1", "quiz1")
    paths.work_root.mkdir(parents=True)
    paths.assignment_path.write_text(json.dumps(assignment), encoding="utf-8")
    paths.roster_path.parent.mkdir(parents=True, exist_ok=True)
    with paths.roster_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=("class_id", "student_id", "last_name", "first_name", "period"),
        )
        writer.writeheader()
        writer.writerow(student)
    return paths


@pytest.mark.parametrize(
    ("generator", "validator", "prefix"),
    (
        (generate_generation_id, validate_generation_id, "gen_"),
        (generate_artifact_id, validate_artifact_id, "art_"),
        (generate_issuance_id, validate_issuance_id, "iss_"),
        (generate_page_id, validate_page_id, "pg_"),
    ),
)
def test_identifier_generators_have_exact_safe_128_bit_shape(generator, validator, prefix):
    value = generator()
    assert value.startswith(prefix)
    assert len(value) == len(prefix) + 32
    assert validator(value) == value
    int(value[len(prefix):], 16)


@pytest.mark.parametrize(
    "bad",
    ("pg_1", "PG_00000000000000000000000000000000", "pg_ABCDEF00000000000000000000000000", "iss_00000000000000000000000000000000"),
)
def test_page_identifier_validation_is_strict(bad):
    with pytest.raises(AnswerSheetRecordError):
        validate_page_id(bad)


@pytest.mark.parametrize(
    ("question_count", "layout_id", "ranges"),
    (
        (1, "standard_15q_abcd_v1", ((1, 1),)),
        (20, "standard_15q_abcd_v1", ((1, 15), (16, 20))),
        (25, "compact_25q_abcd_v1", ((1, 25),)),
        (50, "compact_25q_abcd_v1", ((1, 25), (26, 50))),
        (75, "standard_15q_abcd_v1", ((1, 15), (16, 30), (31, 45), (46, 60), (61, 75))),
    ),
)
def test_pure_builder_uses_layout_page_math(tmp_path, question_count, layout_id, ranges):
    page_ids = tuple(f"pg_{index:032x}" for index in range(1, len(ranges) + 1))
    records = _record_set(
        assignment=_assignment(question_count, layout_id), page_ids=page_ids
    )
    assert records.issuance.page_ids == page_ids
    assert tuple((page.question_start, page.question_end) for page in records.pages) == ranges
    assert tuple(page.logical_page for page in records.pages) == tuple(range(1, len(ranges) + 1))
    assert list(tmp_path.iterdir()) == []


def test_builder_rejects_duplicate_ids_and_mismatched_identity():
    with pytest.raises(AnswerSheetRecordError, match="unique"):
        _record_set(page_ids=(PAGE_IDS[0], PAGE_IDS[0]))
    with pytest.raises(AnswerSheetRecordError, match="class_id"):
        _record_set(class_id="other")
    with pytest.raises(AnswerSheetRecordError, match="assignment_id"):
        _record_set(assignment_id="other")


def test_exact_model_round_trips_and_rejects_schema_drift():
    records = _record_set()
    issuance_mapping = answer_sheet_issuance_to_mapping(records.issuance)
    page_mapping = answer_sheet_page_to_mapping(records.pages[0])
    assert answer_sheet_issuance_from_mapping(issuance_mapping) == records.issuance
    assert answer_sheet_page_from_mapping(page_mapping) == records.pages[0]
    issuance_mapping["unknown"] = True
    with pytest.raises(AnswerSheetRecordError, match="unknown"):
        answer_sheet_issuance_from_mapping(issuance_mapping)
    page_mapping["logical_page"] = True
    with pytest.raises(AnswerSheetRecordError, match="integer"):
        answer_sheet_page_from_mapping(page_mapping)


def test_core_target_is_exact_and_side_effect_free(tmp_path):
    target = answer_sheet_page_target(PAGE_IDS[0])
    assert target.module_id == "scoreform"
    assert target.record_kind == "answer_sheet_page"
    assert target.record_id == PAGE_IDS[0]
    assert target.contract_version == "1"
    assert list(tmp_path.iterdir()) == []


def test_exclusive_persistence_and_complete_page_context(tmp_path):
    paths = _managed_sources(tmp_path)
    persisted = write_answer_sheet_record_set(tmp_path, paths.work_ref, _record_set())
    assert all(path.is_file() for path in persisted.page_paths)
    assert persisted.issuance_path.is_file()
    for path in (*persisted.page_paths, persisted.issuance_path):
        text = path.read_text(encoding="utf-8")
        assert text.endswith("\n") and not text.endswith("\n\n")
        assert list(json.loads(text)) == sorted(json.loads(text))
    loaded = load_answer_sheet_record_set(tmp_path, paths.work_ref, ISSUANCE_ID)
    context = load_answer_sheet_page_context(tmp_path, paths.work_ref, PAGE_IDS[1])
    assert loaded == persisted.record_set
    assert context.page == loaded.pages[1]
    assert context.issuance == loaded.issuance
    assert not (paths.work_root / "routes").exists()
    assert not list(paths.work_root.rglob("*.pdf"))
    with pytest.raises(AnswerSheetCollisionError):
        write_answer_sheet_record_set(tmp_path, paths.work_ref, _record_set())


def test_persistence_preflight_rejects_current_source_mismatch_without_records(tmp_path):
    paths = _managed_sources(tmp_path, student={**_student(), "last_name": "Changed"})
    with pytest.raises(AnswerSheetIntegrityError, match="student snapshot"):
        write_answer_sheet_record_set(tmp_path, paths.work_ref, _record_set())
    assert not paths.answer_sheets_dir.exists()


def test_strict_loader_rejects_duplicate_keys_and_incomplete_record_set(tmp_path):
    paths = _managed_sources(tmp_path)
    persisted = write_answer_sheet_record_set(tmp_path, paths.work_ref, _record_set())
    persisted.page_paths[0].write_text('{"page_id":"x","page_id":"y"}\n', encoding="utf-8")
    with pytest.raises(AnswerSheetReadError, match="Duplicate"):
        load_answer_sheet_page_context(tmp_path, paths.work_ref, PAGE_IDS[0])


def test_record_set_write_rolls_back_only_files_created_by_current_call(
    tmp_path, monkeypatch
):
    paths = _managed_sources(tmp_path)
    original = persistence._write_json_exclusive
    calls = 0

    def fail_second_write(path, value):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise AnswerSheetWriteError("simulated write failure")
        original(path, value)

    monkeypatch.setattr(persistence, "_write_json_exclusive", fail_second_write)
    with pytest.raises(AnswerSheetWriteError, match="simulated"):
        write_answer_sheet_record_set(tmp_path, paths.work_ref, _record_set())
    assert list(paths.answer_sheet_pages_dir.iterdir()) == []
    assert list(paths.answer_sheet_issuances_dir.iterdir()) == []


def test_lifecycle_transitions_revision_guard_and_page_immutability(tmp_path):
    paths = _managed_sources(tmp_path)
    persisted = write_answer_sheet_record_set(tmp_path, paths.work_ref, _record_set())
    page_bytes = tuple(path.read_bytes() for path in persisted.page_paths)
    issued = transition_answer_sheet_issuance(
        tmp_path,
        paths.work_ref,
        ISSUANCE_ID,
        expected_revision=1,
        new_status="issued",
        timestamp="2026-07-15T02:00:00+00:00",
    )
    assert issued.lifecycle.revision == 2
    assert issued.lifecycle.issued_at == "2026-07-15T02:00:00+00:00"
    with pytest.raises(AnswerSheetRevisionConflictError):
        transition_answer_sheet_issuance(
            tmp_path,
            paths.work_ref,
            ISSUANCE_ID,
            expected_revision=1,
            new_status="invalidated",
            timestamp="2026-07-15T03:00:00+00:00",
            reason="administrative decision",
        )
    invalidated = transition_answer_sheet_issuance(
        tmp_path,
        paths.work_ref,
        ISSUANCE_ID,
        expected_revision=2,
        new_status="invalidated",
        timestamp="2026-07-15T03:00:00+00:00",
        reason="administrative decision",
    )
    assert invalidated.lifecycle.revision == 3
    assert invalidated.lifecycle.issued_at == issued.lifecycle.issued_at
    assert tuple(path.read_bytes() for path in persisted.page_paths) == page_bytes


def test_forbidden_lifecycle_transition_fails():
    with pytest.raises(AnswerSheetLifecycleError):
        transition_answer_sheet_lifecycle(
            _record_set().issuance,
            "superseded",
            timestamp="2026-07-15T02:00:00+00:00",
            reason="replacement",
            replacement_issuance_id="iss_10000000000000000000000000000000",
        )


def test_separate_physical_copies_have_fresh_identity():
    individual = _record_set()
    packet = _record_set(
        artifact_id="art_10000000000000000000000000000000",
        output_kind="class_packet_pdf",
        issuance_id="iss_10000000000000000000000000000000",
        page_ids=(
            "pg_10000000000000000000000000000000",
            "pg_20000000000000000000000000000000",
        ),
    )
    assert individual.issuance.generation_id == packet.issuance.generation_id
    assert individual.issuance.artifact_id != packet.issuance.artifact_id
    assert individual.issuance.issuance_id != packet.issuance.issuance_id
    assert set(individual.issuance.page_ids).isdisjoint(packet.issuance.page_ids)


def test_record_validation_detects_page_order_mismatch():
    records = _record_set()
    bad_issuance = replace(records.issuance, page_ids=tuple(reversed(PAGE_IDS)))
    mapping = answer_sheet_issuance_to_mapping(bad_issuance)
    assert mapping["page_ids"] == list(reversed(PAGE_IDS))
    with pytest.raises(AnswerSheetRecordError, match="order"):
        validate_answer_sheet_record_set(AnswerSheetRecordSet(bad_issuance, records.pages))
