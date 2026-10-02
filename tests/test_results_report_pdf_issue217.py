"""ReportLab PDF renderer tests for ScoreForm Issue #217 Slice 6."""

from __future__ import annotations

import re
from datetime import datetime, timezone

import pytest

from scoreform.page_scoring import ScoredAnswer
from scoreform.results import (
    ScoreFormRoutedResult,
    ScoreFormRoutedResultHistoryRow,
)
from scoreform.results_report_pdf import render_results_report_pdf
from scoreform.results_reporting import (
    REPORT_CONFIRMATION_TOKEN,
    ResultsReportingError,
    confirm_results_report_plan,
    prepare_results_report_plan,
    prepare_results_report_snapshot,
)

GENERATED = datetime(2026, 9, 30, 23, 0, 0, tzinfo=timezone.utc)


def _assignment(question_count=4):
    answer_key = {}
    standards = {}
    choices = ["A", "B", "C", "D"]
    for number in range(1, question_count + 1):
        answer_key[number] = choices[(number - 1) % len(choices)]
        if number % 5 == 0:
            standards[str(number)] = []
        elif number % 2:
            standards[str(number)] = ["STD.A"]
        else:
            standards[str(number)] = ["STD.A", "STD.B"]
    return {
        "assignment_id": "quiz1",
        "title": "Synthetic Results Analysis Assessment",
        "question_count": question_count,
        "choices": choices,
        "answer_key": answer_key,
        "standards": standards,
        "standards_profile_id": "synthetic_profile",
    }


def _answers(question_count, *, offset=0):
    choices = ("A", "B", "C", "D")
    rows = []
    for number in range(1, question_count + 1):
        key = choices[(number - 1) % 4]
        if number % 13 == 0:
            selected = "AMBIGUOUS"
            correct = False
        elif number % 11 == 0:
            selected = "BLANK"
            correct = False
        else:
            selected = choices[(number - 1 + offset) % 4]
            correct = selected == key
        rows.append((number, selected, correct))
    return tuple(rows)


def _row(
    *,
    student_id,
    attempt,
    timestamp,
    question_count=4,
    offset=0,
    last_name="Student",
    first_name="Synthetic",
):
    scored = tuple(
        ScoredAnswer(number, selected, correct)
        for number, selected, correct in _answers(
            question_count,
            offset=offset,
        )
    )
    result = ScoreFormRoutedResult(
        "plain_paper_manual",
        "class1",
        "quiz1",
        student_id,
        last_name,
        first_name,
        "1",
        "manual",
        sum(answer.correct for answer in scored),
        question_count,
        scored,
        source_file="plain_paper_manual_entry",
    )
    return ScoreFormRoutedResultHistoryRow(result, attempt, timestamp)


def _history(question_count=4):
    return (
        _row(
            student_id="1001",
            attempt=1,
            timestamp="2026-09-01T09:00:00+00:00",
            question_count=question_count,
            offset=0,
            last_name="Doe",
            first_name="Jane",
        ),
        _row(
            student_id="1001",
            attempt=2,
            timestamp="2026-09-02T09:00:00+00:00",
            question_count=question_count,
            offset=1,
            last_name="Doe",
            first_name="Jane",
        ),
        _row(
            student_id="1002",
            attempt=1,
            timestamp="2026-09-01T10:00:00+00:00",
            question_count=question_count,
            offset=2,
            last_name="Smith",
            first_name="John",
        ),
    )


def _confirmed(
    scope,
    *,
    question_count=4,
    student_id=None,
    attempt_number=None,
):
    snapshot = prepare_results_report_snapshot(
        _history(question_count),
        _assignment(question_count),
        class_id="class1",
        scope=scope,
        generated_at=GENERATED,
        student_id=student_id,
        attempt_number=attempt_number,
    )
    plan = prepare_results_report_plan(snapshot, output_format="pdf")
    confirmed = confirm_results_report_plan(
        plan,
        REPORT_CONFIRMATION_TOKEN,
    )
    assert confirmed is not None
    return confirmed


def _page_count(pdf_bytes):
    return len(re.findall(rb"/Type\s*/Page(?!s)", pdf_bytes))


def _pdf_text(pdf_bytes):
    """Extract normalized uncompressed ReportLab literal Tj text for assertions."""
    chunks = []
    pattern = rb"\(((?:\\.|[^\\)])*)\)\s*Tj"
    for raw in re.findall(pattern, pdf_bytes):
        raw = re.sub(
            rb"\\([0-7]{1,3})",
            lambda match: bytes([int(match.group(1), 8)]),
            raw,
        )
        raw = raw.replace(rb"\(", b"(")
        raw = raw.replace(rb"\)", b")")
        chunks.append(raw.decode("latin-1"))
    return " ".join(" ".join(chunks).split())

def test_class_pdf_is_first_class_in_memory_report():
    report = render_results_report_pdf(_confirmed("class_analysis"))

    assert report.output_format == "pdf"
    assert report.scope == "class_analysis"
    assert len(report.artifacts) == 1
    artifact = report.artifacts[0]
    assert artifact.filename == "results_analysis.pdf"
    assert artifact.media_type == "application/pdf"
    assert artifact.content.startswith(b"%PDF-")
    assert _page_count(artifact.content) >= 1


def test_class_pdf_contains_required_sections_and_basis_statements():
    pdf = render_results_report_pdf(
        _confirmed("class_analysis")
    ).artifacts[0].content
    text = _pdf_text(pdf)

    assert "ScoreForm Results Analysis" in text
    assert "Class Analysis" in text
    assert "Assignment Overview" in text
    assert "Question Analysis" in text
    assert "Response Distributions" in text
    assert "Standards Analysis" in text
    assert "most recent scored attempt per student for display" in text
    assert "not proficiency or Grade determinations" in text
    assert "current question alignment" in text


def test_class_pdf_does_not_embed_full_student_response_detail_by_default():
    pdf = render_results_report_pdf(
        _confirmed("class_analysis")
    ).artifacts[0].content
    text = _pdf_text(pdf)

    assert "Question-by-Question Detail" not in text
    assert "Student Standards Breakdown" not in text


def test_student_pdf_contains_only_selected_attempt_detail_and_states():
    pdf = render_results_report_pdf(
        _confirmed(
            "student_detail",
            student_id="1001",
            attempt_number=2,
            question_count=13,
        )
    ).artifacts[0].content
    text = _pdf_text(pdf)

    assert "ScoreForm Student Detail" in text
    assert "Doe, Jane" in text
    assert "Attempt" in text
    assert "2 of 2" in text
    assert "Question-by-Question Detail" in text
    assert "Student Standards Breakdown" in text
    assert "BLANK" in text
    assert "AMBIGUOUS" in text
    assert "not proficiency or Grade determinations" in text


def test_large_class_pdf_paginates_instead_of_shrinking_to_one_page():
    pdf = render_results_report_pdf(
        _confirmed("class_analysis", question_count=80)
    ).artifacts[0].content

    assert _page_count(pdf) >= 3
    assert b"Page 1" in pdf
    assert b"Page 2" in pdf


def test_large_student_pdf_paginates_and_repeats_table_headers():
    pdf = render_results_report_pdf(
        _confirmed(
            "student_detail",
            student_id="1001",
            attempt_number=2,
            question_count=100,
        )
    ).artifacts[0].content

    assert _page_count(pdf) >= 2
    assert pdf.count(b"Question") >= 2
    assert b"Page 1" in pdf
    assert b"Page 2" in pdf


def test_pdf_rendering_is_deterministic_for_same_frozen_snapshot():
    confirmed = _confirmed("class_analysis", question_count=12)

    first = render_results_report_pdf(confirmed)
    second = render_results_report_pdf(confirmed)

    assert first == second
    assert first.artifacts[0].sha256_hex == second.artifacts[0].sha256_hex


def test_pdf_renderer_rejects_non_pdf_confirmed_plan():
    snapshot = prepare_results_report_snapshot(
        _history(),
        _assignment(),
        class_id="class1",
        scope="class_analysis",
        generated_at=GENERATED,
    )
    plan = prepare_results_report_plan(snapshot, output_format="json")
    confirmed = confirm_results_report_plan(
        plan,
        REPORT_CONFIRMATION_TOKEN,
    )
    assert confirmed is not None

    with pytest.raises(ResultsReportingError, match="format is not PDF"):
        render_results_report_pdf(confirmed)


def test_pdf_renderer_does_not_write_files(tmp_path):
    before = tuple(tmp_path.iterdir())

    render_results_report_pdf(_confirmed("class_analysis"))

    assert tuple(tmp_path.iterdir()) == before
