"""Strict ScoreForm failure and resolution detail contracts."""

import math
from pathlib import Path

import pytest

from scoreform.scan_review_details import (
    ScoreFormDetailsError,
    isolated_json_value,
    sanitize_single_line,
    scoreform_failure_details,
    scoreform_resolution_details,
    validate_scoreform_failure_details,
    validate_scoreform_resolution_details,
)


class ExplosiveDisplay:
    def __repr__(self):
        raise AssertionError("repr must not be called")

    def __str__(self):
        raise AssertionError("str must not be called")


def test_failure_details_have_exact_shape_and_deep_isolation() -> None:
    context = {"pages": [1, 2], "identity": {"class_id": "class1"}}
    value = scoreform_failure_details(
        origin="attempt_assembly",
        category="missing_pages",
        diagnostic_paths=("classes/class1/debug/a.png",),
        diagnostic_errors=(ValueError("bad\nline\x00"),),
        context=context,
    )
    context["pages"].append(3)

    nested = value["scoreform"]
    assert set(nested) == {
        "details_schema_version",
        "record_kind",
        "failure_origin",
        "scoreform_category",
        "diagnostic_paths",
        "diagnostic_errors",
        "context",
    }
    validated = validate_scoreform_failure_details(value)
    assert validated.context["pages"] == (1, 2)
    assert "\\u000a" in validated.diagnostic_errors[0]["error_message"]
    assert "\\u0000" in validated.diagnostic_errors[0]["error_message"]


def test_unsupported_object_uses_bounded_marker_without_display_hooks() -> None:
    assert isolated_json_value(ExplosiveDisplay()) == {
        "value_type": "ExplosiveDisplay",
        "display": "<unsupported non-JSON value>",
    }


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_nonfinite_context_numbers_are_rejected(value) -> None:
    with pytest.raises(ScoreFormDetailsError, match="finite"):
        isolated_json_value(value)


def test_path_objects_and_unsafe_diagnostic_paths_are_rejected() -> None:
    with pytest.raises(ScoreFormDetailsError):
        scoreform_failure_details(
            origin="page_decode",
            category="missing_qr",
            diagnostic_paths=(Path("debug/a.png"),),  # type: ignore[arg-type]
        )
    with pytest.raises(ScoreFormDetailsError):
        scoreform_failure_details(
            origin="page_decode",
            category="missing_qr",
            diagnostic_paths=("../a.png",),
        )


def test_malformed_scoreform_failure_shape_is_rejected() -> None:
    value = scoreform_failure_details(origin="page_decode", category="missing_qr")
    value["scoreform"]["extra"] = True
    with pytest.raises(ScoreFormDetailsError, match="key set"):
        validate_scoreform_failure_details(value)


def test_resolution_details_have_separate_exact_contract() -> None:
    value = scoreform_resolution_details(
        teacher_action="manual_entry",
        identity_source="teacher_verified",
        identity={
            "class_id": "class1",
            "assignment_id": "work1",
            "student_id": "student1",
        },
        result={
            "result_origin": "scan_review_manual",
            "result_output_path": (
                "classes/class1/modules/scoreform/work/work1/results.csv"
            ),
            "attempt_number": 2,
            "score": 4,
            "total": 5,
            "already_present": False,
        },
    )
    nested = value["scoreform"]
    assert set(nested) == {
        "details_schema_version",
        "record_kind",
        "resolution_origin",
        "teacher_action",
        "identity_source",
        "identity",
        "result",
        "evidence",
    }
    assert validate_scoreform_resolution_details(value).teacher_action == "manual_entry"


def test_resolution_rejects_partial_result_and_path_escape() -> None:
    with pytest.raises(ScoreFormDetailsError):
        scoreform_resolution_details(
            teacher_action="manual_entry",
            identity_source="teacher_verified",
            result={"result_origin": "scan_review_manual"},
        )
    with pytest.raises(ScoreFormDetailsError):
        scoreform_resolution_details(
            teacher_action="evidence_filed",
            identity_source="none",
            evidence={"filed_path": "../outside.pdf"},
        )


@pytest.mark.parametrize(
    "source,identity",
    [
        ("none", {"class_id": "class1"}),
        (
            "validated_locator",
            {
                "class_id": "class1",
                "assignment_id": "work1",
                "route_id": "route1",
                "student_id": "student1",
            },
        ),
        (
            "validated_target",
            {
                "class_id": "class1",
                "assignment_id": "work1",
                "student_id": "student1",
                "route_id": "route1",
                "page_id": "page1",
                "issuance_id": "issuance1",
                "logical_page": 2,
                "total_pages": 1,
            },
        ),
    ],
)
def test_resolution_identity_sources_enforce_relational_shapes(source, identity) -> None:
    with pytest.raises(ScoreFormDetailsError):
        scoreform_resolution_details(
            teacher_action="defer", identity_source=source, identity=identity
        )


def test_resolution_rejects_result_for_nonmanual_action_and_bad_score() -> None:
    identity = {
        "class_id": "class1",
        "assignment_id": "work1",
        "student_id": "student1",
    }
    result = {
        "result_origin": "scan_review_manual",
        "result_output_path": (
            "classes/class1/modules/scoreform/work/work1/results.csv"
        ),
        "attempt_number": 1,
        "score": 6,
        "total": 5,
        "already_present": False,
    }
    with pytest.raises(ScoreFormDetailsError, match="invalid shape"):
        scoreform_resolution_details(
            teacher_action="defer",
            identity_source="teacher_verified",
            identity=identity,
            result={**result, "score": 4},
        )
    with pytest.raises(ScoreFormDetailsError, match="cannot exceed"):
        scoreform_resolution_details(
            teacher_action="manual_entry",
            identity_source="teacher_verified",
            identity=identity,
            result=result,
        )


@pytest.mark.parametrize(
    "action,identity_source,identity",
    [
        ("manual_entry", "teacher_verified", {"class_id": "c", "assignment_id": "a"}),
        ("manual_marks", "none", {}),
        ("manual_marks", "teacher_verified", {"class_id": "c"}),
        ("manual_marks", "teacher_verified", {"assignment_id": "a"}),
        (
            "manual_marks",
            "teacher_verified",
            {"class_id": "c", "assignment_id": "a", "route_id": "rt_" + "1" * 32},
        ),
        ("defer", "teacher_verified", {"class_id": "c", "assignment_id": "a"}),
    ],
)
def test_resolution_action_identity_shapes_are_exact(
    action, identity_source, identity
) -> None:
    with pytest.raises(ScoreFormDetailsError):
        scoreform_resolution_details(
            teacher_action=action,
            identity_source=identity_source,
            identity=identity,
        )


@pytest.mark.parametrize(
    "identity",
    [
        {"class_id": "class1", "assignment_id": "quiz"},
        {"class_id": "class1", "assignment_id": "quiz", "student_id": "student1"},
    ],
)
def test_manual_marks_accepts_only_its_two_exact_teacher_shapes(identity) -> None:
    details = validate_scoreform_resolution_details(
        scoreform_resolution_details(
            teacher_action="manual_marks",
            identity_source="teacher_verified",
            identity=identity,
        )
    )
    assert dict(details.identity) == identity


def test_public_detail_nested_state_is_deeply_immutable() -> None:
    context = {"nested": {"values": [1, 2]}}
    details = validate_scoreform_failure_details(
        scoreform_failure_details(
            origin="page_decode", category="missing_qr", context=context
        )
    )
    context["nested"]["values"].append(3)
    assert details.context["nested"]["values"] == (1, 2)
    with pytest.raises(TypeError):
        details.context["new"] = True
    with pytest.raises(TypeError):
        details.context["nested"]["new"] = True


def test_message_sanitizer_is_bounded_and_control_safe() -> None:
    value = sanitize_single_line(
        "  first\nsecond\u2028third\x00  ", fallback="fallback", limit=40
    )
    assert "\n" not in value and "\x00" not in value and "\u2028" not in value
    assert "\\u000a" in value and "\\u2028" in value
    assert len(value) <= 40
