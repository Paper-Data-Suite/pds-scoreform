"""Issue #227 Slice 5: adversarial conformance for the declared reader v1.

This is a producer-owned, public-reader test suite. It consumes only the
committed synthetic v1 manifest fixture. It does not authorize source access,
select an official attempt, or exercise consumer grading/portfolio policy.
"""

from __future__ import annotations

import builtins
import copy
import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from scoreform.academic_result_manifest import (
    manifest_from_mapping,
    manifest_to_canonical_json_bytes,
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
from scoreform.pds_contract import (
    ACADEMIC_RESULT_MANIFEST_CONTRACT_VERSION,
    SCOREFORM_ACADEMIC_RESULT_READER_CONTRACT_VERSION,
)
from scoreform.pds_publication import get_publication_producer_profile

_FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "publication"
    / "scoreform_academic_result_manifest_v1.json"
)


def _raw() -> bytes:
    return _FIXTURE.read_bytes()


def _data() -> dict:
    return json.loads(_raw())


def _encode(data: dict) -> bytes:
    """Render syntactically valid JSON; the public reader owns validation."""
    return (
        json.dumps(data, sort_keys=True, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")


def _invalid(case: str) -> bytes:
    data = _data()
    first = data["students"][0]["attempts"][0]
    provenance = first["provenance"]
    if case == "wrong-contract":
        data["contract_version"] = "scoreform_academic_result_manifest_v2"
    elif case == "wrong-record-type":
        data["record_type"] = "other_record"
    elif case == "wrong-producer":
        data["producer_module_id"] = "other"
    elif case == "wrong-work":
        data["work"]["work_id"] = "other_work"
    elif case == "wrong-source-path":
        data["source_snapshot"]["assignment"]["relative_path"] = "../private.json"
    elif case == "wrong-source-digest":
        data["source_snapshot"]["results_history"]["sha256"] = "A" * 64
    elif case == "duplicate-student":
        data["students"].append(copy.deepcopy(data["students"][0]))
    elif case == "unsorted-students":
        data["students"].reverse()
    elif case == "duplicate-attempt":
        data["students"][0]["attempts"].append(
            copy.deepcopy(data["students"][0]["attempts"][1])
        )
    elif case == "inconsistent-attempt-score":
        first["points_earned"] = 3
    elif case == "correct-blank":
        first["responses"][1]["correct"] = True
    elif case == "blank-with-selection":
        first["responses"][1]["selected_answer"] = "A"
    elif case == "invalid-selected-choice":
        first["responses"][0]["selected_answer"] = "Z"
    elif case == "out-of-order-responses":
        first["responses"][0]["question_number"] = 2
        first["responses"][1]["question_number"] = 1
    elif case == "duplicate-standard":
        standard = data["assignment"]["questions"][0]["standard_ids"][0]
        data["assignment"]["questions"][0]["standard_ids"].append(standard)
    elif case == "missing-standards-profile":
        data["assignment"]["standards_profile_id"] = None
    elif case == "unsafe-retained-path":
        provenance["retained_source_path"] = "../../private/student.pdf"
    elif case == "pds2-array-mismatch":
        provenance["page_ids"].append("extra_page")
    elif case == "wrong-provenance-model":
        first["result_origin"] = "plain_paper_manual"
    elif case == "unknown-top-level-field":
        data["consumer_grade"] = 87
    elif case == "missing-response-field":
        del first["responses"][0]["correct"]
    elif case == "invalid-generated-at":
        data["generated_at"] = "2026-13-55T17:00:00Z"
    else:
        raise AssertionError(f"unrecognized synthetic case: {case}")
    return _encode(data)


_INVALID_CASES = (
    "wrong-contract",
    "wrong-record-type",
    "wrong-producer",
    "wrong-work",
    "wrong-source-path",
    "wrong-source-digest",
    "duplicate-student",
    "unsorted-students",
    "duplicate-attempt",
    "inconsistent-attempt-score",
    "correct-blank",
    "blank-with-selection",
    "invalid-selected-choice",
    "out-of-order-responses",
    "duplicate-standard",
    "missing-standards-profile",
    "unsafe-retained-path",
    "pds2-array-mismatch",
    "wrong-provenance-model",
    "unknown-top-level-field",
    "missing-response-field",
    "invalid-generated-at",
)


@pytest.mark.parametrize("case", _INVALID_CASES)
def test_invalid_manifest_is_rejected_with_bounded_public_error(case: str) -> None:
    hostile = _invalid(case)
    with pytest.raises(ScoreFormAcademicResultReaderDecodeError) as caught:
        read_academic_result_manifest(hostile)
    assert str(caught.value) == "Academic-result manifest bytes are invalid."
    for sensitive in ("student_alpha", "../../private", "private/student.pdf"):
        assert sensitive not in str(caught.value)


@pytest.mark.parametrize(
    "hostile",
    (
        b"not json",
        b"\xff\x00",
        b'{"secret": NaN}',
        b'{"secret": Infinity}',
        b'{"secret": -Infinity}',
        b'{"student_id":"one", "student_id":"two"}',
        b"\xef\xbb\xbf" + b"{}",
        b"{}\x00",
    ),
    ids=(
        "invalid-json",
        "invalid-utf8",
        "nan",
        "infinity",
        "negative-infinity",
        "duplicate-json-key",
        "utf8-bom",
        "trailing-nul",
    ),
)
def test_invalid_json_fails_closed_without_echoing_bytes(hostile: bytes) -> None:
    with pytest.raises(ScoreFormAcademicResultReaderDecodeError) as caught:
        read_academic_result_manifest(hostile)
    assert str(caught.value) == "Academic-result manifest bytes are invalid."


def test_nested_duplicate_json_keys_are_rejected() -> None:
    raw = _raw()
    needle = b'"student_id": "student_alpha"'
    assert raw.count(needle) == 1
    hostile = raw.replace(
        needle, b'"student_id": "student_alpha", "student_id": "other"', 1
    )
    with pytest.raises(ScoreFormAcademicResultReaderDecodeError):
        read_academic_result_manifest(hostile)


@pytest.mark.parametrize(
    "variation",
    (
        lambda value: value + b" ",
        lambda value: value + b"\n",
        lambda value: value.removesuffix(b"\n"),
        lambda value: value.replace(b"\n", b"\r\n"),
        lambda value: value.replace(b'  "assignment":', b' "assignment":', 1),
    ),
    ids=("trailing-space", "extra-newline", "missing-newline", "crlf", "indentation"),
)
def test_semantically_equivalent_noncanonical_bytes_are_rejected(variation) -> None:
    raw = _raw()
    hostile = variation(raw)
    assert hostile != raw
    with pytest.raises(
        ScoreFormAcademicResultReaderValidationError, match="not canonical"
    ):
        read_academic_result_manifest(hostile)


@pytest.mark.parametrize(
    "supplied",
    ("string", bytearray(b"{}"), memoryview(b"{}"), None, 1),
    ids=("text", "bytearray", "memoryview", "none", "integer"),
)
def test_reader_requires_immutable_exact_bytes(supplied: object) -> None:
    with pytest.raises(
        ScoreFormAcademicResultReaderValidationError, match="immutable bytes"
    ):
        read_academic_result_manifest(supplied)  # type: ignore[arg-type]


def test_bytes_subclass_is_not_a_supported_reader_input() -> None:
    class CustomBytes(bytes):
        pass

    with pytest.raises(
        ScoreFormAcademicResultReaderValidationError, match="immutable bytes"
    ):
        read_academic_result_manifest(CustomBytes(_raw()))


def test_reader_is_deterministic_and_models_remain_frozen() -> None:
    raw = _raw()
    first = read_academic_result_manifest(raw)
    second = read_academic_result_manifest(raw)
    assert first == second
    assert first is not second
    assert validate_academic_result_manifest(first) is first
    assert manifest_to_canonical_json_bytes(first) == raw
    with pytest.raises((FrozenInstanceError, AttributeError)):
        first.students[0].student_id = "changed"  # type: ignore[misc]
    with pytest.raises((FrozenInstanceError, AttributeError)):
        first.students[0].attempts[0].points_earned = 0  # type: ignore[misc]
    with pytest.raises((FrozenInstanceError, AttributeError)):
        first.assignment.questions[0].standard_ids = ()  # type: ignore[misc]


def test_lookup_returns_exact_attempts_never_score_or_time_selected() -> None:
    manifest = read_academic_result_manifest(_raw())
    first = lookup_academic_result_attempt(manifest, "student_alpha", 1)
    second = lookup_academic_result_attempt(manifest, "student_alpha", 2)
    beta = lookup_academic_result_attempt(manifest, "student_beta", 1)
    assert first is manifest.students[0].attempts[0]
    assert second is manifest.students[0].attempts[1]
    assert beta is manifest.students[1].attempts[0]
    assert (first.points_earned, second.points_earned, beta.points_earned) == (2, 1, 3)
    assert lookup_academic_result_response(manifest, "student_alpha", 1, 2).response_state == "blank"
    assert lookup_academic_result_response(manifest, "student_alpha", 2, 2).response_state == "ambiguous"
    assert lookup_academic_result_response(manifest, "student_beta", 1, 2).response_state == "selected"
    with pytest.raises(ScoreFormAcademicResultReaderNotFoundError):
        lookup_academic_result_attempt(manifest, "student_beta", 2)
    with pytest.raises(ScoreFormAcademicResultReaderNotFoundError):
        lookup_academic_result_response(manifest, "student_beta", 2, 1)


@pytest.mark.parametrize(
    "argument",
    (0, -1, True, False, 1.0, "1", None),
    ids=("zero", "negative", "true", "false", "float", "text", "none"),
)
def test_every_numeric_lookup_rejects_invalid_number(argument: object) -> None:
    manifest = read_academic_result_manifest(_raw())
    with pytest.raises(ScoreFormAcademicResultReaderValidationError):
        lookup_academic_result_attempt(manifest, "student_alpha", argument)  # type: ignore[arg-type]
    with pytest.raises(ScoreFormAcademicResultReaderValidationError):
        lookup_academic_result_question(manifest, argument)  # type: ignore[arg-type]
    with pytest.raises(ScoreFormAcademicResultReaderValidationError):
        lookup_academic_result_response(manifest, "student_alpha", 1, argument)  # type: ignore[arg-type]


@pytest.mark.parametrize("invalid_id", ("../private", "student/other", " ", 42))
def test_invalid_student_lookup_is_never_treated_as_absent(invalid_id: object) -> None:
    manifest = read_academic_result_manifest(_raw())
    with pytest.raises(ScoreFormAcademicResultReaderValidationError):
        lookup_academic_result_student(manifest, invalid_id)  # type: ignore[arg-type]


def test_missing_student_question_and_response_use_not_found_not_fallback() -> None:
    manifest = read_academic_result_manifest(_raw())
    secret = "student_not_present"
    with pytest.raises(ScoreFormAcademicResultReaderNotFoundError) as student:
        lookup_academic_result_student(manifest, secret)
    with pytest.raises(ScoreFormAcademicResultReaderNotFoundError) as question:
        lookup_academic_result_question(manifest, 4)
    with pytest.raises(ScoreFormAcademicResultReaderNotFoundError) as response:
        lookup_academic_result_response(manifest, "student_alpha", 1, 4)
    for result in (student, question, response):
        assert secret not in str(result.value)
        assert "student_alpha" not in str(result.value)


def test_source_lookup_is_exact_metadata_without_fs_or_stdout(monkeypatch, capsys) -> None:
    raw = _raw()
    manifest = read_academic_result_manifest(raw)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Reader must not access files or paths")

    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(Path, "open", forbidden)
    reread = read_academic_result_manifest(raw)
    assert reread == manifest
    assert lookup_academic_result_source(manifest, "assignment") is manifest.source_snapshot.assignment
    assert lookup_academic_result_source(manifest, "results_history") is manifest.source_snapshot.results_history
    assert lookup_academic_result_source(manifest, "assignment").relative_path == "assignment.json"
    assert lookup_academic_result_source(manifest, "results_history").relative_path == "results.csv"
    assert capsys.readouterr() == ("", "")
    with pytest.raises(ScoreFormAcademicResultReaderValidationError):
        lookup_academic_result_source(manifest, "../private")  # type: ignore[arg-type]


def test_punctuation_bearing_standards_survive_canonical_read_and_lookup() -> None:
    data = _data()
    data["assignment"]["standards_profile_id"] = "english12.njsls.2023"
    data["assignment"]["questions"][0]["standard_ids"] = [
        "njsls-ela:RL.TS.11-12.4", "njsls-ela:W.NW.11-12.3.D"
    ]
    data["assignment"]["questions"][1]["standard_ids"] = ["njsls-ela:É.11-12.1"]
    canonical = manifest_to_canonical_json_bytes(manifest_from_mapping(data))
    loaded = read_academic_result_manifest(canonical)
    assert loaded.assignment.standards_profile_id == "english12.njsls.2023"
    assert lookup_academic_result_question(loaded, 1).standard_ids == (
        "njsls-ela:RL.TS.11-12.4", "njsls-ela:W.NW.11-12.3.D"
    )
    assert lookup_academic_result_question(loaded, 2).standard_ids == (
        "njsls-ela:É.11-12.1",
    )
    assert canonical == manifest_to_canonical_json_bytes(loaded)
    assert b"njsls-ela:RL.TS.11-12.4" in canonical
    assert "njsls-ela:É.11-12.1".encode() in canonical


def test_declared_reader_contract_is_not_manifest_or_distribution_version() -> None:
    assert (
        ACADEMIC_RESULT_MANIFEST_CONTRACT_VERSION
        == "scoreform_academic_result_manifest_v1"
    )
    assert (
        SCOREFORM_ACADEMIC_RESULT_READER_CONTRACT_VERSION
        == "scoreform_academic_result_reader_v1"
    )
    assert (
        ACADEMIC_RESULT_MANIFEST_CONTRACT_VERSION
        != SCOREFORM_ACADEMIC_RESULT_READER_CONTRACT_VERSION
    )
    profile = get_publication_producer_profile()
    reader = profile.publication_contracts[0].reader_support
    assert len(reader) == 1
    assert reader[0].distribution_name == "scoreform"
    assert reader[0].manifest_contract_version == ACADEMIC_RESULT_MANIFEST_CONTRACT_VERSION
    assert reader[0].reader_contract_version == SCOREFORM_ACADEMIC_RESULT_READER_CONTRACT_VERSION
