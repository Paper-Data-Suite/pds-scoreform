"""First-class ReportLab PDF renderer for ScoreForm Issue #217."""

from __future__ import annotations

import io
from html import escape
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from scoreform.results_analysis import (
    PerformanceSummary,
    StandardPerformance,
)
from scoreform.results_report_artifacts import (
    RenderedReportArtifact,
    RenderedResultsReport,
)
from scoreform.results_reporting import (
    ConfirmedResultsReportPlan,
    ResultsReportingError,
)

PDF_FILENAME = "results_analysis.pdf"
PDF_MEDIA_TYPE = "application/pdf"

_MARGIN = 0.55 * inch
_HEADER_HEIGHT = 0.34 * inch
_FOOTER_HEIGHT = 0.32 * inch

_TABLE_HEADER_BACKGROUND = colors.HexColor("#E8EDF3")
_SECTION_RULE = colors.HexColor("#6B7280")
_GRID = colors.HexColor("#B6BEC8")


class _InvariantCanvas(canvas.Canvas):
    """Canvas with deterministic metadata/id and inspectable uncompressed streams."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs["invariant"] = 1
        kwargs["pageCompression"] = 0
        super().__init__(*args, **kwargs)


def _styles() -> dict[str, ParagraphStyle]:
    sample = getSampleStyleSheet()
    body = ParagraphStyle(
        "ScoreFormBody",
        parent=sample["BodyText"],
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        spaceAfter=5,
    )
    small = ParagraphStyle(
        "ScoreFormSmall",
        parent=body,
        fontSize=7.5,
        leading=9.5,
        spaceAfter=3,
    )
    heading = ParagraphStyle(
        "ScoreFormHeading",
        parent=sample["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=14,
        spaceBefore=8,
        spaceAfter=6,
        textColor=colors.black,
    )
    title = ParagraphStyle(
        "ScoreFormTitle",
        parent=sample["Title"],
        fontName="Helvetica-Bold",
        fontSize=17,
        leading=20,
        alignment=TA_LEFT,
        spaceAfter=9,
        textColor=colors.black,
    )
    return {
        "body": body,
        "small": small,
        "heading": heading,
        "title": title,
    }


def _paragraph(text: object, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(str(text)), style)


def _percent(value: int | None) -> str:
    return "—" if value is None else f"{value}%"


def _standards_text(values: tuple[str, ...]) -> str:
    return ", ".join(values) if values else "Unaligned"


def _base_table(
    data: list[list[object]],
    *,
    col_widths: list[float] | None = None,
    repeat_rows: int = 1,
    font_size: float = 7.5,
) -> Table:
    table = Table(
        data,
        colWidths=col_widths,
        repeatRows=repeat_rows,
        hAlign="LEFT",
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), _TABLE_HEADER_BACKGROUND),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), font_size),
                ("LEADING", (0, 0), (-1, -1), font_size + 2),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.35, _GRID),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return table


def _section_title(text: str, styles: dict[str, ParagraphStyle]) -> list[object]:
    return [
        Spacer(1, 3),
        _paragraph(text, styles["heading"]),
        Table(
            [[""]],
            colWidths=[7.25 * inch],
            rowHeights=[0.5],
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), _SECTION_RULE),
                    ("LINEBELOW", (0, 0), (-1, -1), 0.5, _SECTION_RULE),
                ]
            ),
        ),
        Spacer(1, 4),
    ]


def _metadata_table(rows: list[tuple[str, object]]) -> Table:
    data: list[list[object]] = [["Field", "Value"]]
    data.extend([[label, value] for label, value in rows])
    return _base_table(
        data,
        col_widths=[1.65 * inch, 5.55 * inch],
        repeat_rows=1,
        font_size=8,
    )


def _standards_table(
    standards: tuple[StandardPerformance, ...],
) -> Table:
    data: list[list[object]] = [
        ["Standard", "Correct", "Responses", "Percent", "Questions"]
    ]
    data.extend(
        [
            standard.standard_id,
            standard.correct,
            standard.responses,
            _percent(standard.percent_correct),
            ", ".join(f"Q{number}" for number in standard.question_numbers),
        ]
        for standard in standards
    )
    if len(data) == 1:
        data.append(["No aligned Standards", "", "", "", ""])
    return _base_table(
        data,
        col_widths=[
            2.15 * inch,
            0.65 * inch,
            0.78 * inch,
            0.72 * inch,
            2.9 * inch,
        ],
    )


def _unaligned_paragraph(
    unaligned: PerformanceSummary,
    styles: dict[str, ParagraphStyle],
) -> Paragraph | None:
    if not unaligned.responses:
        return None
    questions = ", ".join(f"Q{number}" for number in unaligned.question_numbers)
    return _paragraph(
        (
            "Unaligned questions: "
            f"{unaligned.correct} / {unaligned.responses} correct "
            f"({_percent(unaligned.percent_correct)}). "
            f"Questions: {questions}."
        ),
        styles["body"],
    )


def _basis_story(
    statements: tuple[str, ...],
    styles: dict[str, ParagraphStyle],
) -> list[object]:
    story: list[object] = []
    story.extend(_section_title("Report Basis", styles))
    for statement in statements:
        story.append(_paragraph(statement, styles["small"]))
    return story


def _class_story(
    confirmed: ConfirmedResultsReportPlan,
    styles: dict[str, ParagraphStyle],
) -> list[object]:
    snapshot = confirmed.plan.snapshot
    analysis = snapshot.class_analysis
    assert analysis is not None
    assignment = snapshot.assignment

    story: list[object] = [
        _paragraph("ScoreForm Results Analysis", styles["title"]),
        _metadata_table(
            [
                ("Class", snapshot.class_id),
                (
                    "Assignment",
                    f"{assignment.assignment_id} — {assignment.title}",
                ),
                ("Scope", "Class Analysis"),
                ("Generated", snapshot.generated_at),
                ("Students represented", analysis.students_represented),
                ("Attempt basis", analysis.attempt_basis),
                ("Standards basis", analysis.standards_basis),
            ]
        ),
    ]

    story.extend(_section_title("Assignment Overview", styles))
    overview: list[list[object]] = [
        [
            "Student ID",
            "Name",
            "Attempt",
            "Recorded",
            "Score",
            "Total",
            "Attempts",
        ]
    ]
    overview.extend(
        [
            student.student_id,
            student.name,
            student.attempt_number,
            student.recorded_at,
            student.score,
            student.total_points,
            student.attempt_count,
        ]
        for student in analysis.students
    )
    story.append(
        _base_table(
            overview,
            col_widths=[
                0.8 * inch,
                1.65 * inch,
                0.55 * inch,
                1.55 * inch,
                0.5 * inch,
                0.5 * inch,
                0.6 * inch,
            ],
            font_size=7,
        )
    )

    story.extend(_section_title("Question Analysis", styles))
    question_data: list[list[object]] = [
        [
            "Question",
            "Correct",
            "Incorrect",
            "Blank",
            "Ambiguous",
            "Total",
            "% Correct",
        ]
    ]
    question_data.extend(
        [
            f"Q{question.question_number}",
            question.correct,
            question.incorrect,
            question.blank,
            question.ambiguous,
            question.total,
            _percent(question.percent_correct),
        ]
        for question in analysis.questions
    )
    story.append(
        _base_table(
            question_data,
            col_widths=[
                0.82 * inch,
                0.72 * inch,
                0.8 * inch,
                0.62 * inch,
                0.86 * inch,
                0.62 * inch,
                0.85 * inch,
            ],
        )
    )

    story.extend(_section_title("Response Distributions", styles))
    response_headers: list[object] = [
        "Question",
        "Key",
        *assignment.choices,
        "BLANK",
        "AMBIGUOUS",
        "% Correct",
    ]
    response_data: list[list[object]] = [response_headers]
    for question in analysis.questions:
        counts = {
            response.response: response.count
            for response in question.response_distribution
        }
        response_data.append(
            [
                f"Q{question.question_number}",
                question.keyed_answer,
                *(counts.get(choice, 0) for choice in assignment.choices),
                counts.get("BLANK", 0),
                counts.get("AMBIGUOUS", 0),
                _percent(question.percent_correct),
            ]
        )
    available_width = 7.2 * inch
    leading_width = 0.64 * inch
    remaining_columns = len(response_headers) - 1
    other_width = (available_width - leading_width) / remaining_columns
    story.append(
        _base_table(
            response_data,
            col_widths=[leading_width]
            + [other_width] * remaining_columns,
            font_size=7,
        )
    )

    story.extend(_section_title("Standards Analysis", styles))
    story.append(_standards_table(analysis.standards))
    unaligned = _unaligned_paragraph(analysis.unaligned, styles)
    if unaligned is not None:
        story.extend([Spacer(1, 5), unaligned])

    story.extend(_basis_story(snapshot.basis_statements, styles))
    return story


def _student_story(
    confirmed: ConfirmedResultsReportPlan,
    styles: dict[str, ParagraphStyle],
) -> list[object]:
    snapshot = confirmed.plan.snapshot
    detail = snapshot.student_detail
    assert detail is not None
    assignment = snapshot.assignment

    story: list[object] = [
        _paragraph("ScoreForm Student Detail", styles["title"]),
        _metadata_table(
            [
                ("Class", snapshot.class_id),
                (
                    "Assignment",
                    f"{assignment.assignment_id} — {assignment.title}",
                ),
                ("Scope", "Student Detail"),
                (
                    "Student",
                    f"{detail.name or '(name unavailable)'} ({detail.student_id})",
                ),
                ("Attempt", f"{detail.attempt_number} of {detail.attempt_count}"),
                ("Recorded", detail.recorded_at),
                ("Overall", f"{detail.score} / {detail.total_points}"),
                ("Generated", snapshot.generated_at),
                ("Standards basis", "current assignment alignment"),
            ]
        ),
    ]

    story.extend(_section_title("Question-by-Question Detail", styles))
    question_rows: list[list[object]] = [
        ["Question", "Response", "Key", "Result", "Standard(s)"]
    ]
    question_rows.extend(
        [
            f"Q{question.question_number}",
            question.selected_answer,
            question.keyed_answer,
            question.outcome.title(),
            _standards_text(question.standard_ids),
        ]
        for question in detail.questions
    )
    story.append(
        _base_table(
            question_rows,
            col_widths=[
                0.7 * inch,
                0.9 * inch,
                0.62 * inch,
                0.92 * inch,
                4.05 * inch,
            ],
        )
    )

    story.extend(_section_title("Student Standards Breakdown", styles))
    story.append(_standards_table(detail.standards))
    unaligned = _unaligned_paragraph(detail.unaligned, styles)
    if unaligned is not None:
        story.extend([Spacer(1, 5), unaligned])

    story.extend(_basis_story(snapshot.basis_statements, styles))
    return story


def _header_footer(
    canvas_obj: canvas.Canvas,
    doc: SimpleDocTemplate,
    *,
    assignment_title: str,
    scope_label: str,
) -> None:
    canvas_obj.saveState()
    width, height = letter
    canvas_obj.setStrokeColor(_SECTION_RULE)
    canvas_obj.setLineWidth(0.4)
    canvas_obj.line(_MARGIN, height - 0.38 * inch, width - _MARGIN, height - 0.38 * inch)
    canvas_obj.setFont("Helvetica", 7.5)
    canvas_obj.setFillColor(colors.black)
    header = f"ScoreForm · {scope_label} · {assignment_title}"
    canvas_obj.drawString(_MARGIN, height - 0.28 * inch, header[:110])
    canvas_obj.line(_MARGIN, 0.35 * inch, width - _MARGIN, 0.35 * inch)
    canvas_obj.drawString(_MARGIN, 0.23 * inch, "ScoreForm Results Analysis")
    canvas_obj.drawRightString(
        width - _MARGIN,
        0.23 * inch,
        f"Page {doc.page}",
    )
    canvas_obj.restoreState()


def render_results_report_pdf(
    confirmed: ConfirmedResultsReportPlan,
) -> RenderedResultsReport:
    """Render one confirmed report plan as an in-memory, paginated PDF."""
    if not isinstance(confirmed, ConfirmedResultsReportPlan):
        raise ResultsReportingError(
            "PDF rendering requires a ConfirmedResultsReportPlan."
        )
    if confirmed.plan.output_format != "pdf":
        raise ResultsReportingError("Confirmed report format is not PDF.")

    snapshot = confirmed.plan.snapshot
    styles = _styles()
    story = (
        _class_story(confirmed, styles)
        if snapshot.scope == "class_analysis"
        else _student_story(confirmed, styles)
    )

    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=_MARGIN,
        rightMargin=_MARGIN,
        topMargin=_HEADER_HEIGHT + 0.26 * inch,
        bottomMargin=_FOOTER_HEIGHT + 0.24 * inch,
        title="ScoreForm Results Analysis",
        author="ScoreForm",
        subject="Descriptive assessment analysis report",
    )
    scope_label = (
        "Class Analysis"
        if snapshot.scope == "class_analysis"
        else "Student Detail"
    )

    def decorate(canvas_obj: canvas.Canvas, doc: SimpleDocTemplate) -> None:
        _header_footer(
            canvas_obj,
            doc,
            assignment_title=snapshot.assignment.title,
            scope_label=scope_label,
        )

    try:
        document.build(
            story,
            onFirstPage=decorate,
            onLaterPages=decorate,
            canvasmaker=_InvariantCanvas,
        )
    except Exception as error:
        raise ResultsReportingError(
            f"Could not render ScoreForm Results Analysis PDF: {error}"
        ) from error

    content = buffer.getvalue()
    if not content.startswith(b"%PDF-"):
        raise ResultsReportingError("ReportLab did not produce a PDF document.")

    return RenderedResultsReport(
        output_format="pdf",
        scope=snapshot.scope,
        artifacts=(
            RenderedReportArtifact(
                filename=PDF_FILENAME,
                media_type=PDF_MEDIA_TYPE,
                content=content,
            ),
        ),
    )
