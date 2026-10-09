"""Issue #227 Slice 1: stable, producer-owned reader-contract baseline."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from scoreform.academic_result_manifest import (
    manifest_from_mapping,
    manifest_to_canonical_json_bytes,
)
from scoreform.academic_result_reader import (
    ScoreFormAcademicResultReaderDecodeError,
    ScoreFormAcademicResultReaderError,
    ScoreFormAcademicResultReaderNotFoundError,
    ScoreFormAcademicResultReaderValidationError,
    lookup_academic_result_attempt,
    lookup_academic_result_question,
    lookup_academic_result_response,
    read_academic_result_manifest,
)
from scoreform.pds_contract import (
    ACADEMIC_RESULT_MANIFEST_CONTRACT_VERSION,
    SCOREFORM_ACADEMIC_RESULT_READER_CONTRACT_VERSION,
    SCOREFORM_MODULE_ID,
)

_FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "publication"
    / "scoreform_academic_result_manifest_v1.json"
)


def test_issue227_versioned_reader_identity_is_distinct_from_manifest() -> None:
    assert SCOREFORM_MODULE_ID == "scoreform"
    assert (
        ACADEMIC_RESULT_MANIFEST_CONTRACT_VERSION
        == "scoreform_academic_result_manifest_v1"
    )
    assert (
        SCOREFORM_ACADEMIC_RESULT_READER_CONTRACT_VERSION
        == "scoreform_academic_result_reader_v1"
    )
    assert (
        SCOREFORM_ACADEMIC_RESULT_READER_CONTRACT_VERSION
        != ACADEMIC_RESULT_MANIFEST_CONTRACT_VERSION
    )


def test_issue227_reader_public_calls_keep_exact_lookup_parameters() -> None:
    functions = (
        (read_academic_result_manifest, ("value",)),
        (lookup_academic_result_attempt, ("manifest", "student_id", "attempt_number")),
        (lookup_academic_result_question, ("manifest", "question_number")),
        (
            lookup_academic_result_response,
            ("manifest", "student_id", "attempt_number", "question_number"),
        ),
    )
    for function, names in functions:
        assert tuple(inspect.signature(function).parameters) == names


def test_issue227_public_error_hierarchy_remains_distinguishable() -> None:
    assert issubclass(
        ScoreFormAcademicResultReaderValidationError,
        ScoreFormAcademicResultReaderError,
    )
    assert issubclass(
        ScoreFormAcademicResultReaderDecodeError,
        ScoreFormAcademicResultReaderValidationError,
    )
    assert issubclass(
        ScoreFormAcademicResultReaderNotFoundError,
        ScoreFormAcademicResultReaderError,
    )
    assert not issubclass(
        ScoreFormAcademicResultReaderNotFoundError,
        ScoreFormAcademicResultReaderValidationError,
    )


def test_issue227_reader_preserves_standards_and_attempt_evidence() -> None:
    data = json.loads(_FIXTURE.read_bytes())
    profile = "english12.njsls.2023"
    standard = "njsls-ela:RL.TS.11-12.4"
    data["assignment"]["standards_profile_id"] = profile
    data["assignment"]["questions"][0]["standard_ids"] = [standard]
    encoded = manifest_to_canonical_json_bytes(manifest_from_mapping(data))
    manifest = read_academic_result_manifest(encoded)
    assert manifest.contract_version == ACADEMIC_RESULT_MANIFEST_CONTRACT_VERSION
    assert manifest.assignment.standards_profile_id == profile
    assert lookup_academic_result_question(manifest, 1).standard_ids == (standard,)
    for student in manifest.students:
        for attempt in student.attempts:
            observed = lookup_academic_result_attempt(
                manifest, student.student_id, attempt.attempt_number
            )
            assert observed is attempt
            for response in attempt.responses:
                assert lookup_academic_result_response(
                    manifest,
                    student.student_id,
                    attempt.attempt_number,
                    response.question_number,
                ) is response


def test_issue227_reader_rejects_mutable_or_noncanonical_bytes() -> None:
    canonical = _FIXTURE.read_bytes()
    with pytest.raises(ScoreFormAcademicResultReaderValidationError):
        read_academic_result_manifest(bytearray(canonical))  # type: ignore[arg-type]
    with pytest.raises(ScoreFormAcademicResultReaderValidationError):
        read_academic_result_manifest(canonical + b" ")
