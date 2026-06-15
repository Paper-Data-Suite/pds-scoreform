from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pds_core.standards import StandardUsageEvent

from scoreform.standards_usage import (
    build_standard_usage_events_from_assignment_standards,
)

USED_AT = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)


def build_events(
    standards_by_question,
    *,
    assignment_id="rj_act1_quiz",
    school_year="2025-2026",
    class_id="english9_p2",
    used_at=USED_AT,
    event_id_prefix="scoreform_rj_act1_quiz",
    usage_type="assessed",
):
    return build_standard_usage_events_from_assignment_standards(
        assignment_id=assignment_id,
        standards_by_question=standards_by_question,
        school_year=school_year,
        class_id=class_id,
        used_at=used_at,
        event_id_prefix=event_id_prefix,
        usage_type=usage_type,
    )


def test_build_standard_usage_events_empty_alignment_returns_empty_tuple():
    assert build_events({}) == ()
    assert build_events({1: [], 2: []}) == ()


def test_build_standard_usage_events_single_standard():
    events = build_events({1: ["njsls-ela:RL.CR.11-12.1"]})

    assert len(events) == 1
    event = events[0]
    assert isinstance(event, StandardUsageEvent)
    assert event.event_id == "scoreform_rj_act1_quiz_001"
    assert event.standard_id == "njsls-ela:RL.CR.11-12.1"
    assert event.school_year == "2025-2026"
    assert event.class_id == "english9_p2"
    assert event.module == "pds-scoreform"
    assert event.usage_type == "assessed"
    assert event.assignment_id == "rj_act1_quiz"
    assert event.metadata["question_numbers"] == [1]


def test_build_standard_usage_events_aggregates_same_standard_across_questions():
    events = build_events({
        1: ["njsls-ela:RL.CR.11-12.1"],
        2: ["njsls-ela:RL.CR.11-12.1"],
    })

    assert len(events) == 1
    assert events[0].standard_id == "njsls-ela:RL.CR.11-12.1"
    assert events[0].metadata["question_numbers"] == [1, 2]


def test_build_standard_usage_events_sorts_standards_and_assigns_sequential_ids():
    events = build_events({
        2: ["njsls-ela:RL.CR.11-12.1"],
        1: ["njsls-ela:L.VI.11-12.4", "njsls-ela:RL.CR.11-12.1"],
    })

    assert [event.standard_id for event in events] == [
        "njsls-ela:L.VI.11-12.4",
        "njsls-ela:RL.CR.11-12.1",
    ]
    assert [event.event_id for event in events] == [
        "scoreform_rj_act1_quiz_001",
        "scoreform_rj_act1_quiz_002",
    ]
    assert [event.metadata["question_numbers"] for event in events] == [
        [1],
        [1, 2],
    ]


def test_build_standard_usage_events_deduplicates_standards_on_same_question():
    events = build_events({
        1: [
            "njsls-ela:RL.CR.11-12.1",
            "njsls-ela:RL.CR.11-12.1",
        ],
    })

    assert len(events) == 1
    assert events[0].metadata["question_numbers"] == [1]


def test_build_standard_usage_events_strips_standards_before_aggregation():
    events = build_events({
        1: [" njsls-ela:RL.CR.11-12.1 "],
        2: ["njsls-ela:RL.CR.11-12.1"],
    })

    assert len(events) == 1
    assert events[0].standard_id == "njsls-ela:RL.CR.11-12.1"
    assert events[0].metadata["question_numbers"] == [1, 2]


def test_build_standard_usage_events_accepts_custom_usage_type():
    events = build_events(
        {1: ["njsls-ela:RL.CR.11-12.1"]},
        usage_type="reviewed",
    )

    assert events[0].usage_type == "reviewed"


def test_build_standard_usage_events_rejects_invalid_usage_type_through_pds_core():
    with pytest.raises(ValueError):
        build_events(
            {1: ["njsls-ela:RL.CR.11-12.1"]},
            usage_type="graded",
        )


@pytest.mark.parametrize("question_number", [0, -1, 1.5, "1", True, False])
def test_build_standard_usage_events_rejects_invalid_question_numbers(
    question_number,
):
    with pytest.raises(ValueError, match="question number"):
        build_events({question_number: ["njsls-ela:RL.CR.11-12.1"]})


@pytest.mark.parametrize(
    "standards",
    [
        "njsls-ela:RL.CR.11-12.1",
        b"njsls-ela:RL.CR.11-12.1",
        None,
        [123],
        [""],
        ["   "],
    ],
)
def test_build_standard_usage_events_rejects_invalid_standards_collections(
    standards,
):
    with pytest.raises(ValueError):
        build_events({1: standards})


def test_build_standard_usage_events_accepts_iterable_standards_values():
    events = build_events({
        1: ("njsls-ela:RL.CR.11-12.1",),
        2: {"njsls-ela:L.VI.11-12.4"},
    })

    assert [event.standard_id for event in events] == [
        "njsls-ela:L.VI.11-12.4",
        "njsls-ela:RL.CR.11-12.1",
    ]


def test_build_standard_usage_events_has_no_file_side_effects(tmp_path):
    build_events({1: ["njsls-ela:RL.CR.11-12.1"]})

    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("field_name", "kwargs"),
    [
        ("school_year", {"school_year": "2025"}),
        ("class_id", {"class_id": "../english9_p2"}),
        ("used_at", {"used_at": datetime(2026, 6, 15, 12, 0)}),
        ("assignment_id", {"assignment_id": "../rj_act1_quiz"}),
    ],
)
def test_build_standard_usage_events_rejects_invalid_event_fields_through_pds_core(
    field_name,
    kwargs,
):
    with pytest.raises(ValueError, match=field_name):
        build_events({1: ["njsls-ela:RL.CR.11-12.1"]}, **kwargs)
