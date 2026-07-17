import os
import re
import sys
from dataclasses import dataclass

import cv2
import numpy as np
from pds_core.pds2 import parse_pds2_payload, serialize_pds2_payload
from pds_core.routing_models import RouteLocator
from reportlab.pdfbase import pdfmetrics

from scoreform import workspace
from scoreform.answer_sheet_routes import (
    RegisteredAnswerSheetPageRoute,
    validate_answer_sheet_page_route,
)
from scoreform.config import (
    LOCAL_TEMPLATE_PDF,
    LOCAL_TEMPLATE_PNG,
)
from scoreform.folders import ensure_parent_dir
from scoreform.layouts import AnswerSheetLayout, get_layout
from scoreform.paging import question_range_for_page

QR_QUIET_ZONE_MODULES = 4
HEADER_COLUMN_GAP = 10.0
HEADER_TEXT_CLEARANCE = 4.0
HEADER_QUESTION_CLEARANCE = 8.0


@dataclass(frozen=True, slots=True)
class PdfRectangle:
    left: float
    bottom: float
    right: float
    top: float


@dataclass(frozen=True, slots=True)
class HeaderTextRun:
    text: str
    font_name: str
    font_size: float
    x: float
    baseline_y: float


@dataclass(frozen=True, slots=True)
class AnswerSheetHeaderPlan:
    title_runs: tuple[HeaderTextRun, ...]
    left_metadata_runs: tuple[HeaderTextRun, ...]
    page_context_runs: tuple[HeaderTextRun, ...]
    identifier_runs: tuple[HeaderTextRun, ...]
    left_column: PdfRectangle
    right_column: PdfRectangle
    qr_rectangle: PdfRectangle
    first_question_boundary: PdfRectangle
    registration_rectangles: tuple[PdfRectangle, ...]
    page_bounds: PdfRectangle

    @property
    def text_runs(self) -> tuple[HeaderTextRun, ...]:
        return (
            self.title_runs
            + self.left_metadata_runs
            + self.page_context_runs
            + self.identifier_runs
        )


def header_text_bounds(run: HeaderTextRun) -> PdfRectangle:
    width = pdfmetrics.stringWidth(run.text, run.font_name, run.font_size)
    ascent, descent = pdfmetrics.getAscentDescent(run.font_name, run.font_size)
    return PdfRectangle(
        run.x,
        run.baseline_y + descent,
        run.x + width,
        run.baseline_y + ascent,
    )


def rectangles_overlap(
    first: PdfRectangle, second: PdfRectangle, *, clearance: float = 0.0
) -> bool:
    return not (
        first.right + clearance <= second.left
        or second.right + clearance <= first.left
        or first.top + clearance <= second.bottom
        or second.top + clearance <= first.bottom
    )


def _text_fits(text: str, font_name: str, font_size: float, width: float) -> bool:
    return pdfmetrics.stringWidth(text, font_name, font_size) <= width


def _ellipsize_text(
    text: str, font_name: str, font_size: float, width: float
) -> str:
    if _text_fits(text, font_name, font_size, width):
        return text
    ellipsis = "\N{HORIZONTAL ELLIPSIS}"
    if not _text_fits(ellipsis, font_name, font_size, width):
        raise ValueError("Header column is too narrow to render an ellipsis.")
    shortened = text.rstrip()
    while shortened and not _text_fits(
        shortened.rstrip() + ellipsis, font_name, font_size, width
    ):
        shortened = shortened[:-1]
    return shortened.rstrip() + ellipsis


def _wrap_title(
    text: str, font_name: str, font_size: float, width: float
) -> tuple[str, ...]:
    words = text.split()
    if not words:
        return ("Assignment:",)
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if _text_fits(candidate, font_name, font_size, width):
            current = candidate
            continue
        if current:
            lines.append(current)
            current = word
        else:
            lines.append(word)
            current = ""
    if current:
        lines.append(current)
    return tuple(lines)


def _plan_title_runs(
    title: str, x: float, top_baseline: float, width: float
) -> tuple[HeaderTextRun, ...]:
    font_name = "Helvetica-Bold"
    text = f"Assignment: {title}".strip()
    for half_points in range(28, 19, -1):
        font_size = half_points / 2
        lines = _wrap_title(text, font_name, font_size, width)
        if len(lines) <= 2 and all(
            _text_fits(line, font_name, font_size, width) for line in lines
        ):
            line_spacing = font_size + 3.5
            return tuple(
                HeaderTextRun(
                    line,
                    font_name,
                    font_size,
                    x,
                    top_baseline - index * line_spacing,
                )
                for index, line in enumerate(lines)
            )

    font_size = 10.0
    lines = _wrap_title(text, font_name, font_size, width)
    first = _ellipsize_text(lines[0], font_name, font_size, width)
    remainder = " ".join(lines[1:])
    second = _ellipsize_text(remainder, font_name, font_size, width)
    return (
        HeaderTextRun(first, font_name, font_size, x, top_baseline),
        HeaderTextRun(second, font_name, font_size, x, top_baseline - 13.5),
    )


def _fit_single_line_run(
    text: str,
    font_name: str,
    preferred_size: float,
    minimum_size: float,
    x: float,
    baseline_y: float,
    width: float,
) -> HeaderTextRun:
    half_points = round(preferred_size * 2)
    minimum_half_points = round(minimum_size * 2)
    while half_points >= minimum_half_points:
        font_size = half_points / 2
        if _text_fits(text, font_name, font_size, width):
            return HeaderTextRun(text, font_name, font_size, x, baseline_y)
        half_points -= 1
    raise ValueError(f"Header text does not fit its column: {text!r}")


def _registration_rectangles(layout: AnswerSheetLayout) -> tuple[PdfRectangle, ...]:
    size = layout.registration_size * layout.pdf_scale
    rectangles = []
    for x, y in layout.registration_marks:
        left, top = _pdf_coord(x, y, layout)
        rectangles.append(PdfRectangle(left, top - size, left + size, top))
    return tuple(rectangles)


def _first_question_boundary(layout: AnswerSheetLayout) -> PdfRectangle:
    first_question_top = max(
        layout.pdf_height - box.y * layout.pdf_scale
        for slot in layout.question_slots
        for box in slot.boxes
    )
    return PdfRectangle(0.0, 0.0, float(layout.pdf_width), first_question_top)


def _require_inside(inner: PdfRectangle, outer: PdfRectangle, label: str) -> None:
    if not (
        inner.left >= outer.left
        and inner.bottom >= outer.bottom
        and inner.right <= outer.right
        and inner.top <= outer.top
    ):
        raise ValueError(f"{label} falls outside its permitted bounds.")


def _require_clear(
    first: PdfRectangle,
    second: PdfRectangle,
    label: str,
    *,
    clearance: float = HEADER_TEXT_CLEARANCE,
) -> None:
    if rectangles_overlap(first, second, clearance=clearance):
        raise ValueError(f"Header geometry overlaps: {label}.")


def _validate_header_plan(plan: AnswerSheetHeaderPlan) -> None:
    groups = (
        (plan.title_runs, plan.left_column, "assignment title"),
        (plan.left_metadata_runs, plan.left_column, "student metadata"),
        (plan.page_context_runs, plan.right_column, "page context"),
        (plan.identifier_runs, plan.right_column, "page identifiers"),
    )
    for runs, column, label in groups:
        for run in runs:
            bounds = header_text_bounds(run)
            _require_inside(bounds, plan.page_bounds, label)
            _require_inside(bounds, column, label)
            _require_clear(
                bounds,
                plan.first_question_boundary,
                f"{label} and questions",
                clearance=HEADER_QUESTION_CLEARANCE,
            )
            for registration in plan.registration_rectangles:
                _require_clear(bounds, registration, f"{label} and registration mark")

    left_runs = plan.title_runs + plan.left_metadata_runs
    for first_index, first in enumerate(left_runs):
        for second in left_runs[first_index + 1 :]:
            _require_clear(
                header_text_bounds(first),
                header_text_bounds(second),
                "left-column text",
            )

    right_runs = plan.page_context_runs + plan.identifier_runs
    for first_index, first in enumerate(right_runs):
        for second in right_runs[first_index + 1 :]:
            _require_clear(
                header_text_bounds(first),
                header_text_bounds(second),
                "right-column text",
            )

    for run in plan.title_runs + plan.left_metadata_runs:
        _require_clear(header_text_bounds(run), plan.qr_rectangle, "left text and QR")
    for run in plan.page_context_runs + plan.identifier_runs:
        _require_clear(header_text_bounds(run), plan.qr_rectangle, "right text and QR")


def plan_answer_sheet_header(
    *,
    assignment_title: str,
    student_name: str,
    student_id: str,
    class_id: str,
    period: str,
    logical_page: int,
    total_pages: int,
    question_start: int,
    question_end: int,
    page_id: str,
    route_id: str,
    layout: AnswerSheetLayout,
) -> AnswerSheetHeaderPlan:
    """Return a deterministic, validated plan for answer-sheet header text."""
    left_x, _ = _pdf_coord(150, 260, layout)
    context_x, context_y = _pdf_coord(
        layout.page_context_x, layout.page_context_y, layout
    )
    content_right = layout.pdf_width - left_x
    page_bounds = PdfRectangle(
        0.0, 0.0, float(layout.pdf_width), float(layout.pdf_height)
    )
    left_column = PdfRectangle(
        left_x,
        0.0,
        context_x - HEADER_COLUMN_GAP,
        float(layout.pdf_height),
    )
    right_column = PdfRectangle(
        context_x, 0.0, content_right, float(layout.pdf_height)
    )
    qr_left, qr_top = _pdf_coord(layout.qr_x, layout.qr_y, layout)
    qr_size = layout.qr_size * layout.pdf_scale
    qr_rectangle = PdfRectangle(
        qr_left, qr_top - qr_size, qr_left + qr_size, qr_top
    )

    title_runs = _plan_title_runs(
        assignment_title,
        left_column.left,
        qr_rectangle.top,
        left_column.right - left_column.left,
    )
    last_title = title_runs[-1]
    metadata_baseline = last_title.baseline_y - last_title.font_size - 3.5
    metadata_text = (
        f"Student: {student_name}",
        f"ID: {student_id}",
        f"Class: {class_id}",
        f"Period: {period}",
    )
    left_metadata_runs = tuple(
        _fit_single_line_run(
            text,
            "Helvetica",
            10.0,
            7.0,
            left_column.left,
            metadata_baseline - index * 13.5,
            left_column.right - left_column.left,
        )
        for index, text in enumerate(metadata_text)
    )
    page_context_runs = (
        HeaderTextRun(
            f"Page {logical_page} of {total_pages}",
            "Helvetica",
            10.0,
            right_column.left,
            context_y,
        ),
        HeaderTextRun(
            f"Questions {question_start}\N{EN DASH}{question_end}",
            "Helvetica",
            10.0,
            right_column.left,
            context_y - 14.0,
        ),
    )
    identifier_font_size = 7.0
    identifier_ascent, _ = pdfmetrics.getAscentDescent(
        "Helvetica", identifier_font_size
    )
    identifier_baseline = (
        qr_rectangle.bottom - HEADER_TEXT_CLEARANCE - identifier_ascent
    )
    identifier_runs = (
        _fit_single_line_run(
            f"Sheet ID: {page_id}",
            "Helvetica",
            identifier_font_size,
            6.5,
            right_column.left,
            identifier_baseline,
            right_column.right - right_column.left,
        ),
        _fit_single_line_run(
            f"Route ID: {route_id}",
            "Helvetica",
            identifier_font_size,
            6.5,
            right_column.left,
            identifier_baseline - 11.5,
            right_column.right - right_column.left,
        ),
    )
    plan = AnswerSheetHeaderPlan(
        title_runs=title_runs,
        left_metadata_runs=left_metadata_runs,
        page_context_runs=page_context_runs,
        identifier_runs=identifier_runs,
        left_column=left_column,
        right_column=right_column,
        qr_rectangle=qr_rectangle,
        first_question_boundary=_first_question_boundary(layout),
        registration_rectangles=_registration_rectangles(layout),
        page_bounds=page_bounds,
    )
    _validate_header_plan(plan)
    return plan


def _pdf_coord(x, y, layout=None):
    """Convert template coordinates to PDF points with origin at bottom-left."""
    resolved = get_layout() if layout is None else layout
    return x * resolved.pdf_scale, resolved.pdf_height - (y * resolved.pdf_scale)


def _pdf_rect(c, x, y, w, h, fill=False, stroke=True, layout=None):
    resolved = get_layout() if layout is None else layout
    pd_x, pd_y = _pdf_coord(x, y, resolved)
    pd_w = w * resolved.pdf_scale
    pd_h = h * resolved.pdf_scale
    c.rect(pd_x, pd_y - pd_h, pd_w, pd_h, fill=fill, stroke=stroke)


def _generate_template_png(filename="template.png", layout=None):
    """Generates the blank answer sheet template PNG for debugging."""
    ensure_parent_dir(filename)

    # Create a white image
    layout = get_layout() if layout is None else layout
    img = np.ones((layout.img_height, layout.img_width, 3), dtype=np.uint8) * 255

    # Draw registration marks (solid black squares)
    for (x, y) in layout.registration_marks:
        cv2.rectangle(
            img,
            (x, y),
            (x + layout.registration_size, y + layout.registration_size),
            (0, 0, 0),
            -1,
        )

    # Title
    cv2.putText(
        img,
        "Answer Sheet",
        (450, 200),
        cv2.FONT_HERSHEY_SIMPLEX,
        2,
        (0, 0, 0),
        3,
    )

    # Draw questions
    for i, slot in enumerate(layout.question_slots[:10]):
        cv2.putText(
            img,
            f"{i + 1}.",
            (slot.label_x, slot.label_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            1,
            (0, 0, 0),
            2,
        )

        for box in slot.boxes:

            # Draw box
            cv2.rectangle(
                img,
                (box.x, box.y),
                (box.x + box.size, box.y + box.size),
                (0, 0, 0),
                2,
            )

            # Draw letter
            cv2.putText(
                img,
                box.choice,
                (box.x + box.size + 15, slot.label_y),
                cv2.FONT_HERSHEY_SIMPLEX,
                1,
                (0, 0, 0),
                2,
            )

    cv2.imwrite(filename, img)
    print(f"Debug PNG template saved as {filename}")


def _generate_template_pdf(filename="template.pdf", layout=None):
    """Generates a printable letter-size PDF answer sheet."""
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas
    except ImportError:
        print("Error: The 'reportlab' package is required to generate PDF templates.")
        print("Please run: pip install reportlab")
        sys.exit(1)

    ensure_parent_dir(filename)

    layout = get_layout() if layout is None else layout
    c = canvas.Canvas(filename, pagesize=letter)
    c.setFillColorRGB(0, 0, 0)
    c.setStrokeColorRGB(0, 0, 0)
    c.setFont("Helvetica-Bold", 36)
    title_x, title_y = _pdf_coord(450, 200, layout)
    c.drawString(title_x, title_y, "Answer Sheet")

    # Draw registration marks
    for (x, y) in layout.registration_marks:
        _pdf_rect(c, x, y, layout.registration_size, layout.registration_size, fill=True, layout=layout)

    c.setLineWidth(1)
    c.setFont("Helvetica", layout.question_font_size)

    # Draw questions
    for i, slot in enumerate(layout.question_slots[:10]):
        q_x, q_y = _pdf_coord(slot.label_x, slot.label_y, layout)
        c.drawString(q_x, q_y, f"{i + 1}.")

        for box in slot.boxes:
            _pdf_rect(c, box.x, box.y, box.size, box.size, fill=False, layout=layout)
            c.setFont("Helvetica", layout.choice_font_size)
            letter_x, letter_y = _pdf_coord(
                box.x + box.size + layout.choice_label_offset, slot.label_y, layout
            )
            c.drawString(letter_x, letter_y, box.choice)
            c.setFont("Helvetica", layout.question_font_size)

    c.showPage()
    c.save()
    print(f"Template saved as {filename}")


def generate_template(pdf_filename=None, png_filename=None):
    """Generates the answer sheet template PDF and an optional PNG debug template."""
    workspace_root = workspace.get_scoreform_workspace_root()
    if pdf_filename is None:
        pdf_filename = os.fspath(workspace_root / LOCAL_TEMPLATE_PDF)
    if png_filename is None:
        png_filename = os.fspath(workspace_root / LOCAL_TEMPLATE_PNG)

    _generate_template_pdf(pdf_filename)
    _generate_template_png(png_filename)


def safe_filename(text):
    """Return a filesystem-safe lowercase filename fragment for `text`."""
    if text is None:
        return ""
    s = str(text).strip().lower()
    # Replace any non-alphanumeric character with underscore
    s = re.sub(r"[^a-z0-9]+", "_", s)
    # Trim leading/trailing underscores
    s = re.sub(r"^_+|_+$", "", s)
    return s


def student_pdf_filename(student_data):
    """Return a predictable filename for a student PDF, without path."""
    sid = student_data.get("student_id", "")
    last = student_data.get("last_name", "")
    first = student_data.get("first_name", "")
    base = f"{sid}_{last}_{first}"
    return safe_filename(base) + ".pdf"


def build_qr_payload(locator: RouteLocator) -> str:
    """Return Core's canonical locator-only PDS2 serialization."""
    if not isinstance(locator, RouteLocator):
        raise TypeError("build_qr_payload requires a RouteLocator.")
    return serialize_pds2_payload(locator)


def make_qr_image(payload):
    """Create a QR code image from the payload using qrcode."""
    import io

    import qrcode
    from reportlab.lib.utils import ImageReader

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=QR_QUIET_ZONE_MODULES,
    )
    qr.add_data(payload)
    qr.make(fit=True)

    pil_img = qr.make_image(fill_color="black", back_color="white")
    
    img_io = io.BytesIO()
    pil_img.save(img_io, format="PNG")
    img_io.seek(0)
    
    return ImageReader(img_io)


def draw_qr_code(c, route, layout):
    """Draw only an already verified page route's canonical payload."""
    if not isinstance(route, RegisteredAnswerSheetPageRoute):
        raise TypeError("QR drawing requires a registered answer-sheet page route.")
    validate_answer_sheet_page_route(route.route)
    if parse_pds2_payload(route.payload_text) != route.locator:
        raise ValueError("Registered route payload does not reproduce its locator.")
    payload = build_qr_payload(route.locator)
    if payload != route.payload_text:
        raise ValueError("Registered route payload is not canonical.")

    # Convert template coordinates to PDF points
    pd_x, pd_y = _pdf_coord(layout.qr_x, layout.qr_y, layout)
    pd_w = layout.qr_size * layout.pdf_scale
    pd_h = layout.qr_size * layout.pdf_scale

    try:
        qr_img = make_qr_image(payload)
        c.drawImage(qr_img, pd_x, pd_y - pd_h, pd_w, pd_h)
        return None
    except Exception as e:
        raise RuntimeError(f"Error drawing QR code: {e}") from e


def _validate_render_context(assignment_data, student_data, route, layout):
    if not isinstance(route, RegisteredAnswerSheetPageRoute):
        raise TypeError("Page rendering requires a registered page route.")
    validate_answer_sheet_page_route(route.route)
    page = route.page
    expected_assignment = (
        assignment_data.get("assignment_id"),
        assignment_data.get("question_count"),
        assignment_data.get("layout_id"),
        tuple(assignment_data.get("choices", ())),
    )
    if expected_assignment != (
        page.assignment_id,
        page.assignment_question_count,
        page.layout_id,
        tuple(layout.choices),
    ):
        raise ValueError("Page structure does not match the managed assignment.")
    if student_data.get("student_id") != page.student_id:
        raise ValueError("Page student does not match the selected student.")
    if layout.layout_id != page.layout_id:
        raise ValueError("Page layout does not match the resolved layout.")
    expected_range = question_range_for_page(
        page.logical_page, page.assignment_question_count, layout
    )
    if expected_range != (page.question_start, page.question_end):
        raise ValueError("Page question range does not match layout paging.")
    return page


def draw_student_answer_sheet_page(c, assignment_data, student_data, route, layout=None):
    """Draw a single personalized answer-sheet page onto an existing ReportLab canvas.

    This function uses the assignment's question_count to render the correct number
    of question rows while preserving the existing layout for A-D choices.
    """
    # Draw registration marks
    layout = get_layout(assignment_data.get("layout_id")) if layout is None else layout
    page = _validate_render_context(assignment_data, student_data, route, layout)
    for (x, y) in layout.registration_marks:
        _pdf_rect(c, x, y, layout.registration_size, layout.registration_size, fill=True, layout=layout)

    page_count = page.total_pages
    question_start, question_end = page.question_start, page.question_end
    header = plan_answer_sheet_header(
        assignment_title=str(assignment_data.get("title", "")),
        student_name=(
            f"{student_data.get('last_name', '')}, "
            f"{student_data.get('first_name', '')}"
        ),
        student_id=str(student_data.get("student_id", "")),
        class_id=str(student_data.get("class_id", "")),
        period=str(student_data.get("period", "")),
        logical_page=page.logical_page,
        total_pages=page_count,
        question_start=question_start,
        question_end=question_end,
        page_id=page.page_id,
        route_id=route.locator.route_id,
        layout=layout,
    )
    for run in header.text_runs:
        c.setFont(run.font_name, run.font_size)
        c.drawString(run.x, run.baseline_y, run.text)

    # Draw question boxes based on assignment question_count
    c.setLineWidth(1)
    c.setFont("Helvetica", 12)

    for slot, question_number in zip(layout.question_slots, range(question_start, question_end + 1)):
        q_x, q_y = _pdf_coord(slot.label_x, slot.label_y, layout)
        c.drawString(q_x, q_y, f"{question_number}.")

        for box in slot.boxes:
            _pdf_rect(c, box.x, box.y, box.size, box.size, fill=False, layout=layout)
            c.setFont("Helvetica", layout.choice_font_size)
            letter_x, letter_y = _pdf_coord(
                box.x + box.size + layout.choice_label_offset, slot.label_y, layout
            )
            c.drawString(letter_x, letter_y, box.choice)
            c.setFont("Helvetica", layout.question_font_size)

    # Draw QR code
    draw_qr_code(c, route, layout)
    return None


def render_registered_answer_sheet_pdf(
    output_path, assignment_data, student_route_sets
):
    """Render ordered students/pages from registrations already verified on disk."""
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(os.fspath(output_path), pagesize=letter)
    c.setFillColorRGB(0, 0, 0)
    c.setStrokeColorRGB(0, 0, 0)
    layout = get_layout(assignment_data.get("layout_id"))
    for student, routes in student_route_sets:
        for route in routes:
            draw_student_answer_sheet_page(
                c, assignment_data, student, route, layout
            )
            c.showPage()
    c.save()


def generate_student_pdf(output_path, assignment_data, student_data, routes):
    """Low-level compatibility wrapper requiring pre-registered page routes."""
    render_registered_answer_sheet_pdf(
        output_path, assignment_data, ((student_data, tuple(routes)),)
    )
    return True


def generate_class_packet_pdf(output_path, assignment_data, roster_data, route_sets):
    """Low-level packet renderer requiring one registered route set per student."""
    students = tuple(roster_data.get("students", ()))
    routes = tuple(route_sets)
    if len(students) != len(routes):
        raise ValueError("Packet route-set count must match roster student count.")
    render_registered_answer_sheet_pdf(
        output_path,
        assignment_data,
        tuple(zip(students, routes, strict=True)),
    )
    return True
