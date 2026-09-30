"""Deterministic versioned JSON renderer for ScoreForm Issue #217."""

from __future__ import annotations

import json
from typing import Any

from scoreform.results_analysis import (
    PerformanceSummary,
    QuestionDetail,
    StandardPerformance,
    StudentAttemptAnalysis,
)
from scoreform.results_report_artifacts import (
    RenderedReportArtifact,
    RenderedResultsReport,
)
from scoreform.results_reporting import (
    ConfirmedResultsReportPlan,
    ResultsReportingError,
)

JSON_MEDIA_TYPE = "application/json; charset=utf-8"
JSON_FILENAME = "results_analysis.json"


def _performance(summary: PerformanceSummary) -> dict[str, Any]:
    return {
        "correct": summary.correct,
        "responses": summary.responses,
        "percent_correct": summary.percent_correct,
        "question_numbers": list(summary.question_numbers),
    }


def _standard(standard: StandardPerformance) -> dict[str, Any]:
    return {
        "standard_id": standard.standard_id,
        "display_label": standard.standard_id,
        "correct": standard.correct,
        "responses": standard.responses,
        "percent_correct": standard.percent_correct,
        "question_numbers": list(standard.question_numbers),
    }


def _response_state(question: QuestionDetail) -> str:
    if question.selected_answer == "BLANK":
        return "BLANK"
    if question.selected_answer == "AMBIGUOUS":
        return "AMBIGUOUS"
    return "SELECTED"


def _overview(student: StudentAttemptAnalysis) -> dict[str, Any]:
    return {
        "student_id": student.student_id,
        "name": student.name,
        "attempt_number": student.attempt_number,
        "attempt_count": student.attempt_count,
        "recorded_at": student.recorded_at,
        "score": student.score,
        "total_points": student.total_points,
    }


def _student_detail(detail: StudentAttemptAnalysis) -> dict[str, Any]:
    return {
        "student_id": detail.student_id,
        "last_name": detail.last_name,
        "first_name": detail.first_name,
        "name": detail.name,
        "period": detail.period,
        "attempt_number": detail.attempt_number,
        "attempt_count": detail.attempt_count,
        "recorded_at": detail.recorded_at,
        "score": detail.score,
        "total_points": detail.total_points,
        "questions": [
            {
                "question_number": question.question_number,
                "response_state": _response_state(question),
                "selected_answer": question.selected_answer,
                "keyed_answer": question.keyed_answer,
                "outcome": question.outcome,
                "correct": question.correct,
                "standard_ids": list(question.standard_ids),
            }
            for question in detail.questions
        ],
        "standards_analysis": [
            _standard(standard) for standard in detail.standards
        ],
        "unaligned": _performance(detail.unaligned),
    }


def _assignment(snapshot: Any) -> dict[str, Any]:
    assignment = snapshot.assignment
    return {
        "assignment_id": assignment.assignment_id,
        "title": assignment.title,
        "question_count": assignment.question_count,
        "choices": list(assignment.choices),
        "answer_key": [
            {
                "question_number": question_number,
                "answer": answer,
            }
            for question_number, answer in enumerate(
                assignment.answer_key,
                start=1,
            )
        ],
        "standards_profile_id": assignment.standards_profile_id,
        "standards_by_question": [
            {
                "question_number": question_number,
                "standard_ids": list(standard_ids),
            }
            for question_number, standard_ids in enumerate(
                assignment.standards_by_question,
                start=1,
            )
        ],
    }


def _payload(confirmed: ConfirmedResultsReportPlan) -> dict[str, Any]:
    snapshot = confirmed.plan.snapshot
    payload: dict[str, Any] = {
        "schema_version": snapshot.schema_version,
        "generated_at": snapshot.generated_at,
        "scope": snapshot.scope,
        "class_id": snapshot.class_id,
        "assignment": _assignment(snapshot),
        "report_basis": {
            "statements": list(snapshot.basis_statements),
            "standards_basis": "current assignment alignment",
            "include_individual_response_rows": (
                snapshot.include_individual_response_rows
            ),
        },
    }

    if snapshot.scope == "class_analysis":
        analysis = snapshot.class_analysis
        assert analysis is not None
        payload["report_basis"]["attempt_basis"] = analysis.attempt_basis
        payload["class_analysis"] = {
            "students_represented": analysis.students_represented,
            "assignment_overview": [
                _overview(student) for student in analysis.students
            ],
            "question_analysis": [
                {
                    "question_number": question.question_number,
                    "keyed_answer": question.keyed_answer,
                    "correct": question.correct,
                    "incorrect": question.incorrect,
                    "blank": question.blank,
                    "ambiguous": question.ambiguous,
                    "total": question.total,
                    "percent_correct": question.percent_correct,
                    "response_distribution": [
                        {
                            "response": response.response,
                            "count": response.count,
                            "is_keyed_answer": response.is_keyed_answer,
                        }
                        for response in question.response_distribution
                    ],
                }
                for question in analysis.questions
            ],
            "standards_analysis": [
                _standard(standard) for standard in analysis.standards
            ],
            "unaligned": _performance(analysis.unaligned),
        }
    else:
        detail = snapshot.student_detail
        assert detail is not None
        payload["student_detail"] = _student_detail(detail)

    return payload


def render_results_report_json(
    confirmed: ConfirmedResultsReportPlan,
) -> RenderedResultsReport:
    """Render one confirmed report plan as deterministic versioned JSON bytes."""
    if not isinstance(confirmed, ConfirmedResultsReportPlan):
        raise ResultsReportingError(
            "JSON rendering requires a ConfirmedResultsReportPlan."
        )
    if confirmed.plan.output_format != "json":
        raise ResultsReportingError("Confirmed report format is not JSON.")

    content = (
        json.dumps(
            _payload(confirmed),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")

    return RenderedResultsReport(
        output_format="json",
        scope=confirmed.plan.snapshot.scope,
        artifacts=(
            RenderedReportArtifact(
                filename=JSON_FILENAME,
                media_type=JSON_MEDIA_TYPE,
                content=content,
            ),
        ),
    )
