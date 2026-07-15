import os
import re
import sys

import cv2
import numpy as np
from pds_core.pds2 import parse_pds2_payload, serialize_pds2_payload
from pds_core.routing_models import RouteLocator

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
from scoreform.layouts import get_layout
from scoreform.paging import question_range_for_page


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
        border=0,
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

    # Metadata area (away from corners and questions)
    c.setFont("Helvetica-Bold", 14)
    meta_x, meta_y = _pdf_coord(150, 260, layout)
    c.drawString(meta_x, meta_y, f"Assignment: {assignment_data.get('title', '')}")

    c.setFont("Helvetica", layout.question_font_size)
    meta_y -= 16
    student_line = f"Student: {student_data.get('last_name','')}, {student_data.get('first_name','')}"
    c.drawString(meta_x, meta_y, student_line)
    meta_y -= 14
    c.drawString(meta_x, meta_y, f"ID: {student_data.get('student_id','')}")
    meta_y -= 14
    c.drawString(meta_x, meta_y, f"Class: {student_data.get('class_id', '')}")
    meta_y -= 14
    c.drawString(meta_x, meta_y, f"Period: {student_data.get('period','')}")

    page_count = page.total_pages
    question_start, question_end = page.question_start, page.question_end
    context_x, context_y = _pdf_coord(layout.page_context_x, layout.page_context_y, layout)
    c.setFont("Helvetica", 10)
    c.drawString(context_x, context_y, f"Page {page.logical_page} of {page_count}")
    c.drawString(context_x, context_y - 13, f"Questions {question_start}\N{EN DASH}{question_end}")

    identity_x, identity_y = _pdf_coord(
        layout.identity_context_x, layout.identity_context_y, layout
    )
    c.setFont("Helvetica", 7)
    c.drawString(identity_x, identity_y, f"Sheet ID: {page.page_id}")
    c.drawString(identity_x, identity_y - 10, f"Route ID: {route.locator.route_id}")

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
