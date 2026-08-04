from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace
from datetime import timedelta, timezone
from pathlib import Path

import pytest

from scoreform.academic_result_manifest import (
    AcademicResultManifest,
    AssignmentSnapshot,
    ManifestDecodeError,
    ManifestValidationError,
    Pds2ScanProvenance,
    PlainPaperManualProvenance,
    Question,
    Response,
    ScanReviewManualProvenance,
    manifest_from_json_bytes,
    manifest_from_mapping,
    manifest_to_canonical_json_bytes,
    manifest_to_mapping,
)

FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "publication"
    / "scoreform_academic_result_manifest_v1.json"
)


def fixture_bytes() -> bytes:
    return FIXTURE.read_bytes()


def fixture_mapping() -> dict:
    return json.loads(fixture_bytes())


def test_normative_fixture_constructs_every_model_and_round_trips_exactly() -> None:
    raw = fixture_bytes()
    manifest = manifest_from_json_bytes(raw)

    assert isinstance(manifest, AcademicResultManifest)
    assert isinstance(manifest.assignment, AssignmentSnapshot)
    assert all(isinstance(question, Question) for question in manifest.assignment.questions)
    assert all(
        isinstance(response, Response)
        for student in manifest.students
        for attempt in student.attempts
        for response in attempt.responses
    )
    provenances = [
        attempt.provenance
        for student in manifest.students
        for attempt in student.attempts
    ]
    assert any(isinstance(value, Pds2ScanProvenance) for value in provenances)
    assert any(isinstance(value, PlainPaperManualProvenance) for value in provenances)
    assert any(isinstance(value, ScanReviewManualProvenance) for value in provenances)
    assert manifest_to_mapping(manifest) == fixture_mapping()
    assert manifest_to_canonical_json_bytes(manifest) == raw
    assert manifest_to_canonical_json_bytes(manifest) == manifest_to_canonical_json_bytes(manifest)


def test_models_are_defensively_deeply_immutable() -> None:
    data = fixture_mapping()
    manifest = manifest_from_mapping(data)
    data["assignment"]["choices"][0] = "Z"
    data["students"].clear()

    assert manifest.assignment.choices == ("A", "B", "C", "D")
    assert len(manifest.students) == 2
    assert isinstance(manifest.students, tuple)
    assert isinstance(manifest.students[0].attempts, tuple)
    assert isinstance(manifest.students[0].attempts[0].responses, tuple)
    with pytest.raises(FrozenInstanceError):
        manifest.record_type = "changed"  # type: ignore[misc]


def test_constructor_defensively_copies_collection_inputs() -> None:
    standards = ["ela_reading_1"]
    question = Question(1, 1, standards)  # type: ignore[arg-type]
    standards.append("later_mutation")
    responses = [Response(1, "selected", "A", True)]
    parsed = manifest_from_json_bytes(fixture_bytes())
    attempt = replace(
        parsed.students[1].attempts[0],
        points_possible=1,
        points_earned=1,
        responses=responses,  # type: ignore[arg-type]
    )
    responses.clear()

    assert question.standard_ids == ("ela_reading_1",)
    assert len(attempt.responses) == 1


def test_blank_and_ambiguous_states_remain_distinct() -> None:
    manifest = manifest_from_json_bytes(fixture_bytes())
    first = manifest.students[0].attempts[0].responses[1]
    second = manifest.students[0].attempts[1].responses[1]

    assert (first.response_state, first.selected_answer) == ("blank", None)
    assert (second.response_state, second.selected_answer) == ("ambiguous", None)


def test_question_standard_alignment_is_preserved_without_ratings_or_answer_key() -> None:
    mapping = manifest_to_mapping(manifest_from_json_bytes(fixture_bytes()))

    assert mapping["assignment"]["standards_profile_id"] == "synthetic_ela_profile"
    assert mapping["assignment"]["questions"][0]["standard_ids"] == ["ela_reading_1"]
    encoded = fixture_bytes()
    assert b"answer_key" not in encoded
    assert b"standards_rating" not in encoded
    assert b"official" not in encoded
    assert b"grade" not in encoded.lower()


def test_timestamps_are_normalized_to_utc_without_changing_the_instant() -> None:
    manifest = manifest_from_json_bytes(fixture_bytes())
    shifted = replace(
        manifest,
        generated_at=manifest.generated_at.astimezone(timezone(timedelta(hours=-5))),
    )

    assert manifest_to_mapping(shifted)["generated_at"] == "2026-01-15T17:00:00.000000Z"


@pytest.mark.parametrize(
    ("path", "value", "match"),
    [
        (("record_type",), "wrong", "record_type"),
        (("contract_version",), "wrong", "contract_version"),
        (("producer_module_id",), "other", "producer_module_id"),
        (("record_set", "revision"), True, "positive integer"),
        (("record_set", "revision"), 0, "positive integer"),
        (("work", "class_id"), "../unsafe", "safe identifier"),
        (("generated_at",), "2026-01-15T17:00:00", "timezone-aware"),
        (("source_snapshot", "assignment", "sha256"), "A" * 64, "SHA-256"),
        (("source_snapshot", "assignment", "relative_path"), "../assignment.json", "assignment.json"),
        (("source_snapshot", "results_history", "result_schema_version"), "1", "must be 2"),
        (("assignment", "question_count"), True, "positive integer"),
        (("assignment", "total_points"), 4, "total_points"),
        (("students", 0, "attempts", 0, "attempt_number"), False, "positive integer"),
        (("students", 0, "attempts", 0, "points_earned"), 3, "correctness"),
        (("students", 0, "attempts", 0, "points_possible"), 2, "assignment.total_points"),
        (("students", 0, "attempts", 0, "responses", 0, "correct"), 1, "Boolean"),
        (("students", 0, "attempts", 0, "responses", 0, "response_state"), "missing", "unsupported"),
        (("students", 0, "attempts", 0, "responses", 0, "selected_answer"), "Z", "assignment choice"),
        (("students", 0, "attempts", 0, "provenance", "source_sha256"), "bad", "SHA-256"),
        (("students", 0, "attempts", 0, "provenance", "retained_source_path"), "C:\\Users\\name\\scan.pdf", "retained_source_path"),
    ],
)
def test_invalid_values_raise_manifest_validation_error(path, value, match) -> None:
    data = fixture_mapping()
    target = data
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value

    with pytest.raises(ManifestValidationError, match=match):
        manifest_from_mapping(data)


@pytest.mark.parametrize("remove", [True, False])
def test_exact_schema_rejects_missing_and_unknown_fields(remove: bool) -> None:
    data = fixture_mapping()
    if remove:
        del data["work"]["class_id"]
    else:
        data["students"][0]["attempts"][0]["responses"][0]["extra"] = "no"

    with pytest.raises(ManifestValidationError, match="key set"):
        manifest_from_mapping(data)


def test_duplicate_students_attempts_questions_and_response_gaps_are_rejected() -> None:
    mutations = []

    duplicate_student = fixture_mapping()
    duplicate_student["students"].append(duplicate_student["students"][0])
    mutations.append(duplicate_student)

    duplicate_attempt = fixture_mapping()
    duplicate_attempt["students"][0]["attempts"][1]["attempt_number"] = 1
    mutations.append(duplicate_attempt)

    duplicate_question = fixture_mapping()
    duplicate_question["assignment"]["questions"][1]["question_number"] = 1
    mutations.append(duplicate_question)

    response_gap = fixture_mapping()
    response_gap["students"][0]["attempts"][0]["responses"].pop()
    mutations.append(response_gap)

    for data in mutations:
        with pytest.raises(ManifestValidationError):
            manifest_from_mapping(data)


def test_standards_require_profile_and_reject_duplicates() -> None:
    missing_profile = fixture_mapping()
    missing_profile["assignment"]["standards_profile_id"] = None
    duplicate = fixture_mapping()
    duplicate["assignment"]["questions"][0]["standard_ids"].append("ela_reading_1")

    with pytest.raises(ManifestValidationError, match="required"):
        manifest_from_mapping(missing_profile)
    with pytest.raises(ManifestValidationError, match="duplicates"):
        manifest_from_mapping(duplicate)


def test_response_state_relationships_are_strict() -> None:
    selected_without_answer = fixture_mapping()
    selected_without_answer["students"][0]["attempts"][0]["responses"][0]["selected_answer"] = None
    blank_with_answer = fixture_mapping()
    blank_with_answer["students"][0]["attempts"][0]["responses"][1]["selected_answer"] = "B"
    correct_blank = fixture_mapping()
    correct_blank["students"][0]["attempts"][0]["responses"][1]["correct"] = True

    with pytest.raises(ManifestValidationError, match="requires"):
        manifest_from_mapping(selected_without_answer)
    with pytest.raises(ManifestValidationError, match="null"):
        manifest_from_mapping(blank_with_answer)
    with pytest.raises(ManifestValidationError, match="cannot be correct"):
        manifest_from_mapping(correct_blank)


def test_mapping_input_requires_json_native_arrays() -> None:
    data = fixture_mapping()
    data["students"] = tuple(data["students"])

    with pytest.raises(ManifestValidationError, match="JSON array"):
        manifest_from_mapping(data)


def test_origin_and_provenance_are_strictly_discriminated() -> None:
    data = fixture_mapping()
    data["students"][1]["attempts"][0]["result_origin"] = "pds2_scan"

    with pytest.raises(ManifestValidationError, match="key set"):
        manifest_from_mapping(data)


def test_pds2_provenance_arrays_must_be_aligned_and_logical_pages_complete() -> None:
    misaligned = fixture_mapping()
    misaligned["students"][0]["attempts"][0]["provenance"]["route_ids"].append("route_synthetic_2")
    bad_pages = fixture_mapping()
    bad_pages["students"][0]["attempts"][0]["provenance"]["logical_pages"] = [2]

    with pytest.raises(ManifestValidationError, match="aligned"):
        manifest_from_mapping(misaligned)
    with pytest.raises(ManifestValidationError, match="complete"):
        manifest_from_mapping(bad_pages)


@pytest.mark.parametrize(
    "raw",
    [
        b'{"record_type": "a", "record_type": "b"}',
        b'{"outer": {"same": 1, "same": 2}}',
        b'{"number": NaN}',
        b'{"number": Infinity}',
        b'{"number": -Infinity}',
        b"not json",
        b"[]",
        b"\xff",
    ],
)
def test_strict_json_rejects_duplicates_nonfinite_malformed_and_nonobject(raw: bytes) -> None:
    with pytest.raises(ManifestDecodeError):
        manifest_from_json_bytes(raw)


def test_mapping_and_json_errors_do_not_leak_builtin_exceptions() -> None:
    with pytest.raises(ManifestValidationError):
        manifest_from_mapping(None)
    with pytest.raises(ManifestDecodeError):
        manifest_from_json_bytes("not bytes")  # type: ignore[arg-type]


def test_contract_module_has_no_workspace_or_publication_side_effect_surface() -> None:
    source = Path("scoreform/academic_result_manifest.py").read_text(encoding="utf-8")

    assert "scoreform.workspace" not in source
    assert "scoreform.results" not in source
    assert "meridian" not in source.lower()
    assert "PublicationRecord" not in source
    assert "open(" not in source
    assert "write_" not in source
