from __future__ import annotations

import pytest
from pds_core.standards import StandardDefinition, StandardsLibrary, StandardsProfile

from scoreform.assignment import (
    AssignmentStandardsAlignmentError,
    validate_assignment_data,
    validate_assignment_standard_alignments,
    validate_question_standard_alignments,
)


def _standards_library() -> StandardsLibrary:
    standards = (
        StandardDefinition(
            standard_id="nj_ela_2023_rl_cr_11_12_1",
            code="RL.CR.11-12.1",
            source="NJSLS-ELA 2023",
            short_name="Close Reading Evidence",
            description="Cite strong and thorough textual evidence.",
        ),
        StandardDefinition(
            standard_id="nj_ela_2023_w_aw_11_12_1",
            code="W.AW.11-12.1",
            source="NJSLS-ELA 2023",
            short_name="Argument Writing",
            description="Write arguments supported by evidence.",
        ),
        StandardDefinition(
            standard_id="nj_ela_2023_l_vi_11_12_4",
            code="L.VI.11-12.4",
            source="NJSLS-ELA 2023",
            short_name="Vocabulary in Context",
            description="Determine or clarify meaning of unknown words.",
        ),
    )
    profiles = (
        StandardsProfile(
            profile_id="english12_2023_njsls",
            standards=(
                "nj_ela_2023_rl_cr_11_12_1",
                "nj_ela_2023_w_aw_11_12_1",
            ),
        ),
        StandardsProfile(
            profile_id="english12_2023_language",
            standards=("nj_ela_2023_l_vi_11_12_4",),
        ),
    )
    return StandardsLibrary(standards=standards, profiles=profiles)


def _assignment(**overrides: object) -> dict[str, object]:
    assignment = {
        "assignment_id": "rj_act1_quiz",
        "title": "Romeo and Juliet Act 1 Quiz",
        "question_count": 3,
        "choices": ["A", "B", "C", "D"],
        "answer_key": {"1": "A", "2": "B", "3": "C"},
        "standards_profile_id": "english12_2023_njsls",
        "standards": {
            "1": ["nj_ela_2023_rl_cr_11_12_1"],
            "2": [
                "nj_ela_2023_rl_cr_11_12_1",
                "nj_ela_2023_w_aw_11_12_1",
            ],
            "3": [],
        },
    }
    assignment.update(overrides)
    return assignment


def test_assignment_standard_alignments_accept_valid_shared_ids() -> None:
    assert validate_assignment_standard_alignments(
        _assignment(),
        _standards_library(),
    ) == {
        1: ("nj_ela_2023_rl_cr_11_12_1",),
        2: ("nj_ela_2023_rl_cr_11_12_1", "nj_ela_2023_w_aw_11_12_1"),
        3: (),
    }


def test_question_standard_alignments_return_trimmed_ids() -> None:
    assert validate_question_standard_alignments(
        question_count=2,
        standards_profile_id=" english12_2023_njsls ",
        question_standards={"1": [" nj_ela_2023_rl_cr_11_12_1 "]},
        standards_library=_standards_library(),
    ) == {
        1: ("nj_ela_2023_rl_cr_11_12_1",),
        2: (),
    }


def test_assignment_standard_alignments_reject_missing_profile_id() -> None:
    assignment = _assignment()
    del assignment["standards_profile_id"]

    with pytest.raises(AssignmentStandardsAlignmentError, match="standards_profile_id"):
        validate_assignment_standard_alignments(assignment, _standards_library())


def test_assignment_standard_alignments_reject_unknown_profile_id() -> None:
    with pytest.raises(
        AssignmentStandardsAlignmentError,
        match="question 1.*profile 'missing_profile'.*profile_id",
    ):
        validate_assignment_standard_alignments(
            _assignment(standards_profile_id="missing_profile"),
            _standards_library(),
        )


def test_assignment_standard_alignments_reject_unknown_standard_id() -> None:
    with pytest.raises(
        AssignmentStandardsAlignmentError,
        match="question 1.*nj_ela_2023_missing",
    ):
        validate_assignment_standard_alignments(
            _assignment(standards={"1": ["nj_ela_2023_missing"]}),
            _standards_library(),
        )


def test_assignment_standard_alignments_reject_standard_outside_profile() -> None:
    with pytest.raises(
        AssignmentStandardsAlignmentError,
        match="question 1.*english12_2023_njsls.*nj_ela_2023_l_vi_11_12_4",
    ):
        validate_assignment_standard_alignments(
            _assignment(standards={"1": ["nj_ela_2023_l_vi_11_12_4"]}),
            _standards_library(),
        )


def test_assignment_standard_alignments_reject_duplicate_standard_ids() -> None:
    with pytest.raises(
        AssignmentStandardsAlignmentError,
        match="question 1.*duplicate standard IDs",
    ):
        validate_assignment_standard_alignments(
            _assignment(
                standards={
                    "1": [
                        "nj_ela_2023_rl_cr_11_12_1",
                        " nj_ela_2023_rl_cr_11_12_1 ",
                    ]
                }
            ),
            _standards_library(),
        )


@pytest.mark.parametrize("question_key", ["Q1", 0])
def test_assignment_standard_alignments_reject_invalid_question_numbers(
    question_key: object,
) -> None:
    with pytest.raises(AssignmentStandardsAlignmentError, match="question number"):
        validate_assignment_standard_alignments(
            _assignment(standards={question_key: ["nj_ela_2023_rl_cr_11_12_1"]}),
            _standards_library(),
        )


def test_assignment_standard_alignments_reject_question_numbers_above_count() -> None:
    with pytest.raises(AssignmentStandardsAlignmentError, match="1 through 3"):
        validate_assignment_standard_alignments(
            _assignment(standards={"4": ["nj_ela_2023_rl_cr_11_12_1"]}),
            _standards_library(),
        )


def test_assignment_standard_alignments_preserve_empty_question_lists() -> None:
    assert validate_assignment_standard_alignments(
        _assignment(standards={"1": []}),
        _standards_library(),
    ) == {1: (), 2: (), 3: ()}


def test_assignment_standard_alignments_preserve_missing_question_alignment() -> None:
    assert validate_assignment_standard_alignments(
        _assignment(standards={}),
        _standards_library(),
    ) == {1: (), 2: (), 3: ()}


def test_structural_assignment_validation_does_not_require_standards_library() -> None:
    loaded = validate_assignment_data(_assignment())

    assert loaded is not None
    assert loaded["standards_profile_id"] == "english12_2023_njsls"
    assert loaded["standards"] == {
        "1": ["nj_ela_2023_rl_cr_11_12_1"],
        "2": [
            "nj_ela_2023_rl_cr_11_12_1",
            "nj_ela_2023_w_aw_11_12_1",
        ],
        "3": [],
    }
