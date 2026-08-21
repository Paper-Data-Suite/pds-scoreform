from __future__ import annotations

import json

import pytest
from pds_core.standards import StandardDefinition, StandardsLibrary, StandardsProfile

from scoreform.assignment_bulk_entry import (
    BulkAnswerKey,
    BulkStandardsAlignment,
    format_bulk_diagnostic,
    parse_alignment_csv,
    parse_alignment_json,
    parse_alignment_text,
    parse_answer_key_csv,
    parse_answer_key_json,
    parse_answer_key_text,
)

CHOICES = ["A", "B", "C", "D"]
PROFILE_ID = "english10_2023_njsls"
STANDARD_A = "nj_ela_2023_rl_cr_9_10_1"
STANDARD_B = "nj_ela_2023_w_aw_9_10_1"
STANDARD_OUTSIDE = "nj_math_other"


def _library() -> StandardsLibrary:
    return StandardsLibrary(
        standards=(
            StandardDefinition(
                standard_id=STANDARD_A,
                code="RL.CR.9-10.1",
                source="NJSLS-ELA 2023",
                short_name="Close Reading Evidence",
                description="Cite strong and thorough textual evidence.",
            ),
            StandardDefinition(
                standard_id=STANDARD_B,
                code="W.AW.9-10.1",
                source="NJSLS-ELA 2023",
                short_name="Argument Writing",
                description="Write arguments supported by evidence.",
            ),
            StandardDefinition(
                standard_id=STANDARD_OUTSIDE,
                code="A.REI.1",
                source="Synthetic Math",
                short_name="Outside Profile",
                description="Synthetic outside-profile standard.",
            ),
        ),
        profiles=(
            StandardsProfile(
                profile_id=PROFILE_ID,
                standards=(STANDARD_A, STANDARD_B),
            ),
            StandardsProfile(
                profile_id="other_profile",
                standards=(STANDARD_OUTSIDE,),
            ),
        ),
    )


def _codes(result) -> list[str]:
    return [diagnostic.code for diagnostic in result.diagnostics]


def test_answer_text_whitespace_normalizes_lowercase_and_b_is_data() -> None:
    result = parse_answer_key_text(
        "a b c d",
        question_count=4,
        choices=CHOICES,
    )

    assert result.ok
    assert result.value == BulkAnswerKey(("A", "B", "C", "D"))
    assert result.value.as_assignment_mapping() == {
        "1": "A",
        "2": "B",
        "3": "C",
        "4": "D",
    }


def test_answer_text_comma_format_normalizes_whitespace() -> None:
    result = parse_answer_key_text(
        " A, b ,C,d ",
        question_count=4,
        choices=CHOICES,
    )

    assert result.ok
    assert result.value is not None
    assert result.value.answers == ("A", "B", "C", "D")


@pytest.mark.parametrize(
    ("text", "expected_code"),
    [
        ("A B C", "too_few_answers"),
        ("A B C D A", "too_many_answers"),
        ("A B X D", "invalid_answer"),
        ("A,,C,D", "empty_answer_token"),
    ],
)
def test_answer_text_rejects_incomplete_or_invalid_values(
    text: str,
    expected_code: str,
) -> None:
    result = parse_answer_key_text(text, question_count=4, choices=CHOICES)

    assert not result.ok
    assert expected_code in _codes(result)


def test_answer_text_treats_back_as_invalid_domain_data_not_navigation() -> None:
    result = parse_answer_key_text("A BACK C D", question_count=4, choices=CHOICES)

    assert not result.ok
    assert _codes(result) == ["invalid_answer"]
    assert result.diagnostics[0].question == 2


def test_answer_csv_accepts_bom_and_out_of_order_rows() -> None:
    data = (
        "\ufeffquestion,answer\r\n"
        "4,d\r\n"
        "2,b\r\n"
        "1,a\r\n"
        "3,c\r\n"
    ).encode("utf-8")

    result = parse_answer_key_csv(data, question_count=4, choices=CHOICES)

    assert result.ok
    assert result.value is not None
    assert result.value.answers == ("A", "B", "C", "D")


def test_answer_csv_collects_multiple_independent_row_problems() -> None:
    result = parse_answer_key_csv(
        "question,answer\n1,A\n2,X\n2,B\n5,C\n",
        question_count=4,
        choices=CHOICES,
    )

    assert not result.ok
    assert _codes(result) == [
        "invalid_answer",
        "duplicate_question",
        "question_out_of_range",
        "missing_question",
        "missing_question",
    ]
    assert [d.question for d in result.diagnostics] == [2, 2, 5, 3, 4]


@pytest.mark.parametrize(
    ("data", "expected_code"),
    [
        ("question\n1\n", "missing_column"),
        ("question,answer,extra\n1,A,x\n", "unexpected_column"),
        ("question,answer,answer\n1,A,B\n", "duplicate_header"),
        ("question,answer\n1,\n2,B\n3,C\n4,D\n", "blank_answer"),
        ("question,answer\n1,A,extra\n", "wrong_column_count"),
    ],
)
def test_answer_csv_rejects_structural_contract_violations(
    data: str,
    expected_code: str,
) -> None:
    result = parse_answer_key_csv(data, question_count=4, choices=CHOICES)

    assert not result.ok
    assert expected_code in _codes(result)


def test_answer_json_accepts_exact_mapping_and_normalizes_case() -> None:
    result = parse_answer_key_json(
        b'{"4":"d","1":"a","3":"c","2":"b"}',
        question_count=4,
        choices=CHOICES,
    )

    assert result.ok
    assert result.value is not None
    assert result.value.answers == ("A", "B", "C", "D")


@pytest.mark.parametrize(
    ("data", "expected_code"),
    [
        ('{"1":"A",', "malformed_json"),
        ('["A","B"]', "wrong_json_top_level"),
        ('{"1":"A","1":"B","2":"B","3":"C","4":"D"}', "duplicate_json_key"),
        ('{"1":"A","2":NaN,"3":"C","4":"D"}', "nonfinite_json_constant"),
        ('{"1":"A","2":"B","3":"C"}', "missing_question"),
        ('{"1":"A","2":"B","3":"C","5":"D"}', "question_out_of_range"),
        ('{"assignment_id":"quiz","answer_key":{"1":"A"}}', "invalid_question_key"),
    ],
)
def test_answer_json_rejects_strict_contract_violations(
    data: str,
    expected_code: str,
) -> None:
    result = parse_answer_key_json(data, question_count=4, choices=CHOICES)

    assert not result.ok
    assert expected_code in _codes(result)


def test_alignment_text_supports_ranges_mixed_selectors_and_unaligned() -> None:
    result = parse_alignment_text(
        f"1-2 = {STANDARD_A}\n"
        f"3,4 = {STANDARD_A}, {STANDARD_B}\n"
        "5-6 = -",
        question_count=6,
        standards_profile_id=PROFILE_ID,
        standards_library=_library(),
    )

    assert result.ok
    assert result.value == BulkStandardsAlignment(
        PROFILE_ID,
        (
            (STANDARD_A,),
            (STANDARD_A,),
            (STANDARD_A, STANDARD_B),
            (STANDARD_A, STANDARD_B),
            (),
            (),
        ),
    )
    assert result.value.as_assignment_mapping()["5"] == []


def test_alignment_text_accepts_semicolon_group_separator_for_direct_cli_form() -> None:
    result = parse_alignment_text(
        f"1-2={STANDARD_A};3={STANDARD_B};4=-",
        question_count=4,
        standards_profile_id=PROFILE_ID,
        standards_library=_library(),
    )

    assert result.ok
    assert result.value is not None
    assert result.value.by_question == (
        (STANDARD_A,),
        (STANDARD_A,),
        (STANDARD_B,),
        (),
    )


@pytest.mark.parametrize(
    ("text", "expected_code"),
    [
        (f"1-2={STANDARD_A}\n2-4={STANDARD_B}", "duplicate_question_coverage"),
        (f"1-2={STANDARD_A}\n4={STANDARD_B}", "missing_question_coverage"),
        (f"3-1={STANDARD_A}\n2={STANDARD_A}\n3={STANDARD_A}", "reversed_range"),
        (f"0={STANDARD_A}\n1-4={STANDARD_A}", "question_out_of_range"),
        (f"1--2={STANDARD_A}\n1-4={STANDARD_A}", "malformed_selector"),
        (f"1-4={STANDARD_A},{STANDARD_A}", "duplicate_standard_id"),
        ("1-4=", "blank_standard_list"),
    ],
)
def test_alignment_text_rejects_range_and_standard_contract_violations(
    text: str,
    expected_code: str,
) -> None:
    result = parse_alignment_text(
        text,
        question_count=4,
        standards_profile_id=PROFILE_ID,
        standards_library=_library(),
    )

    assert not result.ok
    assert expected_code in _codes(result)


def test_alignment_text_requires_profile_for_nonempty_alignment() -> None:
    result = parse_alignment_text(
        f"1-4={STANDARD_A}",
        question_count=4,
        standards_profile_id=None,
        standards_library=_library(),
    )

    assert not result.ok
    assert _codes(result) == ["missing_standards_profile"]


def test_alignment_text_all_unaligned_can_omit_profile() -> None:
    result = parse_alignment_text(
        "1-4=-",
        question_count=4,
        standards_profile_id=None,
        standards_library=None,
    )

    assert result.ok
    assert result.value == BulkStandardsAlignment(None, ((), (), (), ()))


def test_alignment_text_reports_unknown_and_outside_profile_standards() -> None:
    result = parse_alignment_text(
        f"1={STANDARD_OUTSIDE}\n2=unknown_standard\n3-4=-",
        question_count=4,
        standards_profile_id=PROFILE_ID,
        standards_library=_library(),
    )

    assert not result.ok
    assert _codes(result) == ["invalid_standard_id", "invalid_standard_id"]
    assert [d.question for d in result.diagnostics] == [1, 2]


def test_alignment_csv_accepts_blank_unaligned_and_semicolon_standard_list() -> None:
    result = parse_alignment_csv(
        "question,standards\n"
        f"4,\n"
        f"2,{STANDARD_A}\n"
        f'1,"{STANDARD_A};{STANDARD_B}"\n'
        "3,\n",
        question_count=4,
        standards_profile_id=PROFILE_ID,
        standards_library=_library(),
    )

    assert result.ok
    assert result.value is not None
    assert result.value.by_question == (
        (STANDARD_A, STANDARD_B),
        (STANDARD_A,),
        (),
        (),
    )


def test_alignment_csv_reports_duplicate_missing_out_of_range_and_duplicate_standard() -> None:
    result = parse_alignment_csv(
        "question,standards\n"
        f"1,{STANDARD_A};{STANDARD_A}\n"
        f"1,{STANDARD_B}\n"
        f"5,{STANDARD_A}\n",
        question_count=4,
        standards_profile_id=PROFILE_ID,
        standards_library=_library(),
    )

    assert not result.ok
    codes = _codes(result)
    assert "duplicate_standard_id" in codes
    assert "duplicate_question_coverage" in codes
    assert "question_out_of_range" in codes
    assert codes.count("missing_question_coverage") == 3


def test_alignment_json_accepts_complete_mapping_and_empty_array() -> None:
    data = json.dumps(
        {
            "4": [],
            "2": [STANDARD_A],
            "1": [STANDARD_A, STANDARD_B],
            "3": [],
        }
    )
    result = parse_alignment_json(
        data,
        question_count=4,
        standards_profile_id=PROFILE_ID,
        standards_library=_library(),
    )

    assert result.ok
    assert result.value is not None
    assert result.value.by_question[0] == (STANDARD_A, STANDARD_B)
    assert result.value.by_question[3] == ()


@pytest.mark.parametrize(
    ("data", "expected_code"),
    [
        ('{"1":[],"1":[]}', "duplicate_json_key"),
        ('{"1":"x","2":[],"3":[],"4":[]}', "wrong_alignment_value_type"),
        ('{"1":["x",3],"2":[],"3":[],"4":[]}', "invalid_standard_id_type"),
        (f'{{"1":["{STANDARD_A}","{STANDARD_A}"],"2":[],"3":[],"4":[]}}', "duplicate_standard_id"),
        ('{"1":[],"2":[],"3":[]}', "missing_question_coverage"),
        ('{"1":[],"2":[],"3":[],"5":[]}', "question_out_of_range"),
        ('{"1":[],', "malformed_json"),
    ],
)
def test_alignment_json_rejects_strict_contract_violations(
    data: str,
    expected_code: str,
) -> None:
    result = parse_alignment_json(
        data,
        question_count=4,
        standards_profile_id=PROFILE_ID,
        standards_library=_library(),
    )

    assert not result.ok
    assert expected_code in _codes(result)


def test_alignment_normalization_is_question_ordered_not_source_ordered() -> None:
    result = parse_alignment_csv(
        "question,standards\n4,\n3,\n2,\n1,\n",
        question_count=4,
        standards_profile_id=None,
        standards_library=None,
    )

    assert result.ok
    assert result.value is not None
    assert result.value.as_assignment_mapping() == {
        "1": [],
        "2": [],
        "3": [],
        "4": [],
    }


def test_formatted_diagnostic_includes_bounded_location_fields() -> None:
    result = parse_answer_key_csv(
        "question,answer\n1,A\n2,X\n3,C\n4,D\n",
        question_count=4,
        choices=CHOICES,
    )
    diagnostic = result.diagnostics[0]

    assert format_bulk_diagnostic(diagnostic) == (
        "[row 3 / Q2 / answer] Question 2 answer 'X' is not one of A, B, C, D."
    )
