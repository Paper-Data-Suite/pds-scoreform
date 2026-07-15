import os
import re
import sys

import cv2
import numpy as np

from scoreform import workspace
from scoreform.config import (
    LOCAL_TEMPLATE_PDF,
    LOCAL_TEMPLATE_PNG,
    MAX_ASSIGNMENT_QUESTION_COUNT,
)
from scoreform.folders import ensure_parent_dir
from scoreform.layouts import get_layout
from scoreform.migration import migration_pending
from scoreform.paging import page_count_for_question_count, question_range_for_page


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


def generate_student_pdf(output_path, assignment_data, student_data):
    """Generate a personalized student PDF answer sheet compatible with the scorer.

    Returns True on success, False on failure.
    """
    migration_pending("Personalized answer-sheet generation", "#141")

    try:
        import qrcode  # noqa: F401 - dependency availability check
    except ImportError:
        print("Error: The 'qrcode' package is required to generate QR codes.")
        print('Please run: python -m pip install "qrcode[pil]"')
        return False

    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas
    except Exception:
        print("Error: The 'reportlab' package is required to generate student PDFs.")
        return False

    try:
        c = canvas.Canvas(output_path, pagesize=letter)
        c.setFillColorRGB(0, 0, 0)
        c.setStrokeColorRGB(0, 0, 0)

        layout = get_layout(assignment_data.get("layout_id"))
        page_count = page_count_for_question_count(assignment_data["question_count"], layout)
        for assessment_page in range(1, page_count + 1):
            if not draw_student_answer_sheet_page(
                c, assignment_data, student_data, assessment_page, layout
            ):
                print(f"Error: Failed to draw student answer sheet page for '{output_path}'")
                return False
            c.showPage()
        c.save()
        return True

    except Exception as e:
        print(f"Error generating student PDF '{output_path}': {e}")
        return False


def build_qr_payload(assignment_data, student_data, page_number=1):
    """Reject QR generation until authoritative PDS2 records exist."""
    migration_pending("Answer-sheet QR payload generation", "#141")


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


def draw_qr_code(c, assignment_data, student_data, page_number=1, layout=None):
    """Build the QR payload, generate the QR image, and draw it onto the ReportLab canvas."""
    payload = build_qr_payload(assignment_data, student_data, page_number)
    if payload is None:
        return False

    # Coordinates specified by requirements
    layout = get_layout(assignment_data.get("layout_id")) if layout is None else layout

    # Convert template coordinates to PDF points
    pd_x, pd_y = _pdf_coord(layout.qr_x, layout.qr_y, layout)
    pd_w = layout.qr_size * layout.pdf_scale
    pd_h = layout.qr_size * layout.pdf_scale

    try:
        qr_img = make_qr_image(payload)
        c.drawImage(qr_img, pd_x, pd_y - pd_h, pd_w, pd_h)
        return True
    except Exception as e:
        print(f"Error drawing QR code: {e}")
        return False


def draw_student_answer_sheet_page(c, assignment_data, student_data, page_number=1, layout=None):
    """Draw a single personalized answer-sheet page onto an existing ReportLab canvas.

    This function uses the assignment's question_count to render the correct number
    of question rows while preserving the existing layout for A-D choices.
    """
    # Draw registration marks
    layout = get_layout(assignment_data.get("layout_id")) if layout is None else layout
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

    question_count = assignment_data.get("question_count", 10)
    if not isinstance(question_count, int) or question_count < 1 or question_count > MAX_ASSIGNMENT_QUESTION_COUNT:
        question_count = 10

    page_count = page_count_for_question_count(question_count, layout)
    try:
        question_start, question_end = question_range_for_page(page_number, question_count, layout)
    except ValueError as error:
        print(f"Error: {error}")
        return False
    context_x, context_y = _pdf_coord(layout.page_context_x, layout.page_context_y, layout)
    c.setFont("Helvetica", 10)
    c.drawString(context_x, context_y, f"Page {page_number} of {page_count}")
    c.drawString(context_x, context_y - 13, f"Questions {question_start}-{question_end}")

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
    if not draw_qr_code(c, assignment_data, student_data, page_number, layout):
        return False

    return True


def generate_class_packet_pdf(output_path, assignment_data, roster_data):
    """Generate a single PDF containing one personalized page per student (roster order).

    Returns True on success, False on failure.
    """
    migration_pending("Class-packet QR generation", "#141")

    try:
        import qrcode  # noqa: F401 - dependency availability check
    except ImportError:
        print("Error: The 'qrcode' package is required to generate QR codes.")
        print('Please run: python -m pip install "qrcode[pil]"')
        return False

    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas
    except Exception:
        print("Error: The 'reportlab' package is required to generate PDFs.")
        return False

    try:
        c = canvas.Canvas(output_path, pagesize=letter)
        c.setFillColorRGB(0, 0, 0)
        c.setStrokeColorRGB(0, 0, 0)

        students = roster_data.get('students', [])
        layout = get_layout(assignment_data.get("layout_id"))
        page_count = page_count_for_question_count(assignment_data["question_count"], layout)
        for student in students:
            for assessment_page in range(1, page_count + 1):
                if not draw_student_answer_sheet_page(
                    c, assignment_data, student, assessment_page, layout
                ):
                    student_id = student.get('student_id', '<unknown>')
                    print(f"Error: Failed to draw class packet page for student_id='{student_id}'")
                    return False
                c.showPage()

        c.save()
        return True

    except Exception as e:
        print(f"Error generating class packet PDF '{output_path}': {e}")
        return False
