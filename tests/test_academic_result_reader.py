from __future__ import annotations

import builtins
import json
from pathlib import Path

import pytest

import scoreform.academic_result_reader as reader_module
from scoreform.academic_result_manifest import (
    AcademicResultManifest,
    AssignmentSourceSnapshot,
    Pds2ScanProvenance,
    PlainPaperManualProvenance,
    ResultsHistorySourceSnapshot,
    ScanReviewManualProvenance,
    manifest_from_json_bytes,
)
from scoreform.academic_result_reader import (
    ScoreFormAcademicResultReaderDecodeError,
    ScoreFormAcademicResultReaderNotFoundError,
    ScoreFormAcademicResultReaderValidationError,
    lookup_academic_result_attempt,
    lookup_academic_result_question,
    lookup_academic_result_response,
    lookup_academic_result_source,
    lookup_academic_result_student,
    read_academic_result_manifest,
    validate_academic_result_manifest,
)

FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "publication"
    / "scoreform_academic_result_manifest_v1.json"
)

EXPECTED_PUBLIC = {
    "AcademicResultManifest",
    "AcademicResultSourceName",
    "AcademicResultSourceSnapshot",
    "AssignmentSourceSnapshot",
    "Attempt",
    "Question",
    "Response",
    "ResultsHistorySourceSnapshot",
    "ScoreFormAcademicResultReaderDecodeError",
    "ScoreFormAcademicResultReaderError",
    "ScoreFormAcademicResultReaderNotFoundError",
    "ScoreFormAcademicResultReaderValidationError",
    "StudentResults",
    "lookup_academic_result_attempt",
    "lookup_academic_result_question",
    "lookup_academic_result_response",
    "lookup_academic_result_source",
    "lookup_academic_result_student",
    "read_academic_result_manifest",
    "validate_academic_result_manifest",
}


def fixture_bytes() -> bytes:
    return FIXTURE.read_bytes()


def test_public_reader_exports_exact_stable_surface() -> None:
    assert set(reader_module.__all__) == EXPECTED_PUBLIC
    assert reader_module.AcademicResultManifest is AcademicResultManifest


def test_canonical_fixture_reads_through_existing_contract() -> None:
    raw = fixture_bytes()
    assert read_academic_result_manifest(raw) == manifest_from_json_bytes(raw)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda raw: json.dumps(
            json.loads(raw),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8"),
        lambda raw: (
            json.dumps(
                dict(reversed(list(json.loads(raw).items()))),
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        ).encode("utf-8"),
        lambda raw: raw.removesuffix(b"\n"),
        lambda raw: raw + b" ",
        lambda raw: raw.replace(
            b"2026-01-15T17:00:00.000000Z",
            b"2026-01-15T17:00:00Z",
            1,
        ),
    ],
    ids=[
        "minified",
        "top-level-key-order",
        "missing-final-newline",
        "trailing-space",
        "timestamp-rendering",
    ],
)
def test_semantically_valid_noncanonical_bytes_fail_closed(mutation) -> None:
    raw = mutation(fixture_bytes())
    with pytest.raises(
        ScoreFormAcademicResultReaderValidationError, match="not canonical"
    ):
        read_academic_result_manifest(raw)


@pytest.mark.parametrize(
    "raw",
    [
        b"not json",
        b"\xff",
        b'{"record_type":"a","record_type":"b"}',
        b'{"number":NaN}',
    ],
)
def test_decode_failures_are_normalized_without_payload_leak(raw: bytes) -> None:
    with pytest.raises(
        ScoreFormAcademicResultReaderDecodeError, match="bytes are invalid"
    ) as caught:
        read_academic_result_manifest(raw)
    assert str(caught.value) == "Academic-result manifest bytes are invalid."


def test_reader_requires_exact_immutable_bytes_type() -> None:
    with pytest.raises(
        ScoreFormAcademicResultReaderValidationError, match="immutable bytes"
    ):
        read_academic_result_manifest("not bytes")  # type: ignore[arg-type]
    with pytest.raises(
        ScoreFormAcademicResultReaderValidationError, match="immutable bytes"
    ):
        read_academic_result_manifest(bytearray(fixture_bytes()))  # type: ignore[arg-type]


def test_invalid_semantic_manifest_is_wrapped_without_sensitive_value() -> None:
    data = json.loads(fixture_bytes())
    data["students"][0]["attempts"][0]["responses"][0]["selected_answer"] = "Z"
    raw = (
        json.dumps(
            data,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            separators=(",", ": "),
        )
        + "\n"
    ).encode("utf-8")
    with pytest.raises(ScoreFormAcademicResultReaderDecodeError) as caught:
        read_academic_result_manifest(raw)
    assert "Z" not in str(caught.value)
    assert "student_alpha" not in str(caught.value)


def test_existing_manifest_model_validates_without_mutation() -> None:
    manifest = read_academic_result_manifest(fixture_bytes())
    assert validate_academic_result_manifest(manifest) is manifest
    with pytest.raises(ScoreFormAcademicResultReaderValidationError):
        validate_academic_result_manifest(object())  # type: ignore[arg-type]


def test_source_lookup_returns_exact_embedded_snapshots_without_io(monkeypatch) -> None:
    manifest = read_academic_result_manifest(fixture_bytes())

    def forbidden_open(*_args, **_kwargs):
        raise AssertionError("source lookup must not open native files")

    monkeypatch.setattr(builtins, "open", forbidden_open)
    assignment = lookup_academic_result_source(manifest, "assignment")
    results = lookup_academic_result_source(manifest, "results_history")
    assert isinstance(assignment, AssignmentSourceSnapshot)
    assert isinstance(results, ResultsHistorySourceSnapshot)
    assert assignment is manifest.source_snapshot.assignment
    assert results is manifest.source_snapshot.results_history


def test_source_lookup_rejects_unknown_name() -> None:
    manifest = read_academic_result_manifest(fixture_bytes())
    with pytest.raises(
        ScoreFormAcademicResultReaderValidationError, match="source must be"
    ):
        lookup_academic_result_source(manifest, "native_file")  # type: ignore[arg-type]


def test_student_lookup_returns_exact_student_and_preserves_all_attempts() -> None:
    manifest = read_academic_result_manifest(fixture_bytes())
    student = lookup_academic_result_student(manifest, "student_alpha")
    assert student is manifest.students[0]
    assert tuple(attempt.attempt_number for attempt in student.attempts) == (1, 2)


def test_student_lookup_absence_and_invalid_id_are_privacy_safe() -> None:
    manifest = read_academic_result_manifest(fixture_bytes())
    secret = "student_secret"
    with pytest.raises(ScoreFormAcademicResultReaderNotFoundError) as caught:
        lookup_academic_result_student(manifest, secret)
    assert secret not in str(caught.value)
    with pytest.raises(ScoreFormAcademicResultReaderValidationError):
        lookup_academic_result_student(manifest, "../unsafe")


def test_attempt_lookup_is_exact_without_latest_highest_or_neighbor_fallback() -> None:
    manifest = read_academic_result_manifest(fixture_bytes())
    first = lookup_academic_result_attempt(manifest, "student_alpha", 1)
    second = lookup_academic_result_attempt(manifest, "student_alpha", 2)
    assert first is manifest.students[0].attempts[0]
    assert second is manifest.students[0].attempts[1]
    assert first.points_earned == 2
    assert second.points_earned == 1
    with pytest.raises(ScoreFormAcademicResultReaderNotFoundError):
        lookup_academic_result_attempt(manifest, "student_beta", 2)


@pytest.mark.parametrize("value", [0, -1, True, False, "1", 1.0])
def test_attempt_lookup_rejects_invalid_numbers(value) -> None:
    manifest = read_academic_result_manifest(fixture_bytes())
    with pytest.raises(ScoreFormAcademicResultReaderValidationError):
        lookup_academic_result_attempt(
            manifest,
            "student_alpha",
            value,  # type: ignore[arg-type]
        )


def test_question_lookup_preserves_exact_alignment_without_rating() -> None:
    manifest = read_academic_result_manifest(fixture_bytes())
    question = lookup_academic_result_question(manifest, 1)
    assert question is manifest.assignment.questions[0]
    assert question.standard_ids == ("ela_reading_1",)
    assert not hasattr(question, "standards_rating")
    with pytest.raises(ScoreFormAcademicResultReaderNotFoundError):
        lookup_academic_result_question(manifest, 4)


@pytest.mark.parametrize("value", [0, -1, True, "1"])
def test_question_lookup_rejects_invalid_numbers(value) -> None:
    manifest = read_academic_result_manifest(fixture_bytes())
    with pytest.raises(ScoreFormAcademicResultReaderValidationError):
        lookup_academic_result_question(manifest, value)  # type: ignore[arg-type]


def test_response_lookup_preserves_selected_blank_and_ambiguous_states() -> None:
    manifest = read_academic_result_manifest(fixture_bytes())
    selected = lookup_academic_result_response(manifest, "student_alpha", 1, 1)
    blank = lookup_academic_result_response(manifest, "student_alpha", 1, 2)
    ambiguous = lookup_academic_result_response(manifest, "student_alpha", 2, 2)

    assert (selected.response_state, selected.selected_answer, selected.correct) == (
        "selected",
        "A",
        True,
    )
    assert (blank.response_state, blank.selected_answer, blank.correct) == (
        "blank",
        None,
        False,
    )
    assert (
        ambiguous.response_state,
        ambiguous.selected_answer,
        ambiguous.correct,
    ) == ("ambiguous", None, False)
    assert not hasattr(selected, "answer_key")


def test_response_lookup_does_not_choose_another_question() -> None:
    manifest = read_academic_result_manifest(fixture_bytes())
    with pytest.raises(ScoreFormAcademicResultReaderNotFoundError):
        lookup_academic_result_response(manifest, "student_alpha", 1, 4)


def test_all_native_provenance_types_are_returned_unchanged() -> None:
    manifest = read_academic_result_manifest(fixture_bytes())
    pds2 = lookup_academic_result_attempt(manifest, "student_alpha", 1)
    review = lookup_academic_result_attempt(manifest, "student_alpha", 2)
    manual = lookup_academic_result_attempt(manifest, "student_beta", 1)
    assert isinstance(pds2.provenance, Pds2ScanProvenance)
    assert isinstance(review.provenance, ScanReviewManualProvenance)
    assert isinstance(manual.provenance, PlainPaperManualProvenance)
    assert pds2.provenance is manifest.students[0].attempts[0].provenance
    assert review.provenance is manifest.students[0].attempts[1].provenance
    assert manual.provenance is manifest.students[1].attempts[0].provenance


def test_reader_source_has_no_consumer_workspace_or_publication_or_io_boundary() -> None:
    source = Path("scoreform/academic_result_reader.py").read_text(encoding="utf-8")
    lowered = source.lower()
    for forbidden in (
        "meridian",
        "vitrine",
        "quillan",
        "concord",
        "portia",
        "scoreform.workspace",
        "academic_result_manifest_generation",
        "academic_result_publication",
        "publication_storage",
        "academic_catalog",
        "registry_services",
    ):
        assert forbidden not in lowered
    assert "open(" not in source
    assert "Path(" not in source


def test_reader_public_functions_do_not_print_or_write(capsys) -> None:
    manifest = read_academic_result_manifest(fixture_bytes())
    lookup_academic_result_source(manifest, "assignment")
    lookup_academic_result_student(manifest, "student_alpha")
    lookup_academic_result_attempt(manifest, "student_alpha", 1)
    lookup_academic_result_question(manifest, 1)
    lookup_academic_result_response(manifest, "student_alpha", 1, 1)
    assert capsys.readouterr() == ("", "")
