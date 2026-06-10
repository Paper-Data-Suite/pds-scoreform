import re
import sys
import numpy as np
import cv2
from pds_core.pds1 import Pds1PayloadError, build_pds1_payload
from pds_core.qr_payload import QrPayload, QrPayloadValidationError
from scoreform.folders import ensure_parent_dir
from scoreform.config import (
    CORNERS,
    CORNER_SIZE,
    IMG_WIDTH,
    IMG_HEIGHT,
    Q_START_Y,
    Q_STEP_Y,
    BOX_SIZE,
    BOX_START_X,
    BOX_STEP_X,
    PDF_SCALE,
    PDF_HEIGHT,
    LOCAL_TEMPLATE_PDF,
    LOCAL_TEMPLATE_PNG,
    MAX_QUESTION_COUNT,
)
from scoreform.validation import validate_identifier

def _pdf_coord(x, y):
    """Convert template coordinates to PDF points with origin at bottom-left."""
    return x * PDF_SCALE, PDF_HEIGHT - (y * PDF_SCALE)


def _pdf_rect(c, x, y, w, h, fill=False, stroke=True):
    pd_x, pd_y = _pdf_coord(x, y)
    pd_w = w * PDF_SCALE
    pd_h = h * PDF_SCALE
    c.rect(pd_x, pd_y - pd_h, pd_w, pd_h, fill=fill, stroke=stroke)


def _generate_template_png(filename="template.png"):
    """Generates the blank answer sheet template PNG for debugging."""
    ensure_parent_dir(filename)

    # Create a white image
    img = np.ones((IMG_HEIGHT, IMG_WIDTH, 3), dtype=np.uint8) * 255

    # Draw registration marks (solid black squares)
    for (x, y) in CORNERS:
        cv2.rectangle(
            img,
            (x, y),
            (x + CORNER_SIZE, y + CORNER_SIZE),
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
    for i in range(10):
        y = Q_START_Y + i * Q_STEP_Y
        cv2.putText(
            img,
            f"{i + 1}.",
            (150, y + 25),
            cv2.FONT_HERSHEY_SIMPLEX,
            1,
            (0, 0, 0),
            2,
        )

        for j, letter in enumerate(["A", "B", "C", "D"]):
            box_x = BOX_START_X + j * BOX_STEP_X

            # Draw box
            cv2.rectangle(
                img,
                (box_x, y),
                (box_x + BOX_SIZE, y + BOX_SIZE),
                (0, 0, 0),
                2,
            )

            # Draw letter
            cv2.putText(
                img,
                letter,
                (box_x + BOX_SIZE + 15, y + 25),
                cv2.FONT_HERSHEY_SIMPLEX,
                1,
                (0, 0, 0),
                2,
            )

    cv2.imwrite(filename, img)
    print(f"Debug PNG template saved as {filename}")


def _generate_template_pdf(filename="template.pdf"):
    """Generates a printable letter-size PDF answer sheet."""
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas
    except ImportError:
        print("Error: The 'reportlab' package is required to generate PDF templates.")
        print("Please run: pip install reportlab")
        sys.exit(1)

    ensure_parent_dir(filename)

    c = canvas.Canvas(filename, pagesize=letter)
    c.setFillColorRGB(0, 0, 0)
    c.setStrokeColorRGB(0, 0, 0)
    c.setFont("Helvetica-Bold", 36)
    title_x, title_y = _pdf_coord(450, 200)
    c.drawString(title_x, title_y, "Answer Sheet")

    # Draw registration marks
    for (x, y) in CORNERS:
        _pdf_rect(c, x, y, CORNER_SIZE, CORNER_SIZE, fill=True)

    c.setLineWidth(1)
    c.setFont("Helvetica", 12)

    # Draw questions
    for i in range(10):
        y = Q_START_Y + i * Q_STEP_Y
        q_x, q_y = _pdf_coord(150, y + 25)
        c.drawString(q_x, q_y, f"{i + 1}.")

        for j, letter in enumerate(["A", "B", "C", "D"]):
            box_x = BOX_START_X + j * BOX_STEP_X
            _pdf_rect(c, box_x, y, BOX_SIZE, BOX_SIZE, fill=False)
            letter_x, letter_y = _pdf_coord(box_x + BOX_SIZE + 15, y + 25)
            c.drawString(letter_x, letter_y, letter)

    c.showPage()
    c.save()
    print(f"Template saved as {filename}")


def generate_template(pdf_filename=LOCAL_TEMPLATE_PDF, png_filename=LOCAL_TEMPLATE_PNG):
    """Generates the answer sheet template PDF and an optional PNG debug template."""
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
    try:
        import qrcode
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

        if not draw_student_answer_sheet_page(c, assignment_data, student_data):
            print(f"Error: Failed to draw student answer sheet page for '{output_path}'")
            return False

        c.showPage()
        c.save()
        return True

    except Exception as e:
        print(f"Error generating student PDF '{output_path}': {e}")
        return False


def build_qr_payload(assignment_data, student_data):
    """Build the default PDS1 QR code payload string.

    PDS1|module=scoreform|class=<class_id>|aid=<assignment_id>|sid=<student_id>|page=1
    """
    class_id = student_data.get("class_id")
    assignment_id = assignment_data.get("assignment_id")
    student_id = student_data.get("student_id")

    if not class_id or not assignment_id or not student_id:
        print("Error: Missing required student or assignment metadata for QR payload.")
        return None
    if not validate_identifier("class_id", class_id, context="QR payload"):
        return None
    if not validate_identifier("assignment_id", assignment_id, context="QR payload"):
        return None
    if not validate_identifier("student_id", student_id, context="QR payload"):
        return None

    try:
        payload = QrPayload(
            schema="PDS1",
            module="scoreform",
            class_id=class_id,
            assignment_id=assignment_id,
            student_id=student_id,
            page=1,
        )
        return build_pds1_payload(payload)
    except (Pds1PayloadError, QrPayloadValidationError) as error:
        print(f"Error: QR payload invalid: {error}")
        return None


def make_qr_image(payload):
    """Create a QR code image from the payload using qrcode."""
    import qrcode
    import io
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


def draw_qr_code(c, assignment_data, student_data):
    """Build the QR payload, generate the QR image, and draw it onto the ReportLab canvas."""
    payload = build_qr_payload(assignment_data, student_data)
    if payload is None:
        return False

    # Coordinates specified by requirements
    qr_x = 950
    qr_y = 220
    qr_size = 100

    # Convert template coordinates to PDF points
    pd_x, pd_y = _pdf_coord(qr_x, qr_y)
    pd_w = qr_size * PDF_SCALE
    pd_h = qr_size * PDF_SCALE

    try:
        qr_img = make_qr_image(payload)
        c.drawImage(qr_img, pd_x, pd_y - pd_h, pd_w, pd_h)
        return True
    except Exception as e:
        print(f"Error drawing QR code: {e}")
        return False


def draw_student_answer_sheet_page(c, assignment_data, student_data):
    """Draw a single personalized answer-sheet page onto an existing ReportLab canvas.

    This function uses the assignment's question_count to render the correct number
    of question rows while preserving the existing layout for A-D choices.
    """
    # Draw registration marks
    for (x, y) in CORNERS:
        _pdf_rect(c, x, y, CORNER_SIZE, CORNER_SIZE, fill=True)

    # Metadata area (away from corners and questions)
    c.setFont("Helvetica-Bold", 14)
    meta_x, meta_y = _pdf_coord(150, 260)
    c.drawString(meta_x, meta_y, f"Assignment: {assignment_data.get('title', '')}")

    c.setFont("Helvetica", 12)
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
    if not isinstance(question_count, int) or question_count < 1 or question_count > MAX_QUESTION_COUNT:
        question_count = 10

    # Draw question boxes based on assignment question_count
    c.setLineWidth(1)
    c.setFont("Helvetica", 12)

    for i in range(question_count):
        y = Q_START_Y + i * Q_STEP_Y
        q_x, q_y = _pdf_coord(150, y + 25)
        c.drawString(q_x, q_y, f"{i + 1}.")

        for j, letter in enumerate(["A", "B", "C", "D"]):
            box_x = BOX_START_X + j * BOX_STEP_X
            _pdf_rect(c, box_x, y, BOX_SIZE, BOX_SIZE, fill=False)
            letter_x, letter_y = _pdf_coord(box_x + BOX_SIZE + 15, y + 25)
            c.drawString(letter_x, letter_y, letter)

    # Draw QR code
    if not draw_qr_code(c, assignment_data, student_data):
        return False

    return True


def generate_class_packet_pdf(output_path, assignment_data, roster_data):
    """Generate a single PDF containing one personalized page per student (roster order).

    Returns True on success, False on failure.
    """
    try:
        import qrcode
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
        for student in students:
            if not draw_student_answer_sheet_page(c, assignment_data, student):
                student_id = student.get('student_id', '<unknown>')
                print(f"Error: Failed to draw class packet page for student_id='{student_id}'")
                return False
            c.showPage()

        c.save()
        return True

    except Exception as e:
        print(f"Error generating class packet PDF '{output_path}': {e}")
        return False
