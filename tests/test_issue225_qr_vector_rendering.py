"""Issue #225 Slice 3: prove QR PDF vector geometry and rendering isolation."""

from io import BytesIO
from pathlib import Path

import pytest
import qrcode
from reportlab.pdfgen.canvas import Canvas

import scoreform.templates as templates_module
from scoreform.answer_sheet_records import build_answer_sheet_record_set
from scoreform.answer_sheet_routes import (
    RegisteredAnswerSheetPageRoute,
    build_answer_sheet_page_route,
)
from scoreform.layouts import get_layout, supported_layout_ids
from scoreform.templates import (
    QR_QUIET_ZONE_MODULES,
    _build_qr,
    _draw_qr_vector,
    make_qr_image,
)
from scoreform.work_paths import scoreform_work_paths

PDS2_PAYLOAD = (
    "PDS2|m=scoreform|c=class1|w=quiz1|"
    "r=rt_1234567890abcdef1234567890abcdef"
)


class _RecordingPath:
    def __init__(self):
        self.rectangles = []

    def rect(self, x, y, width, height):
        self.rectangles.append((x, y, width, height))


class _RecordingCanvas:
    def __init__(self):
        self.operations = []
        self.color = None
        self.path = None
        self.state_depth = 0

    def saveState(self):
        self.state_depth += 1

    def restoreState(self):
        self.state_depth -= 1

    def setFillColorRGB(self, r, g, b):
        self.color = (r, g, b)

    def rect(self, x, y, width, height, *, stroke, fill):
        self.operations.append(("background", self.color, x, y, width, height, stroke, fill))

    def beginPath(self):
        self.path = _RecordingPath()
        return self.path

    def drawPath(self, path, *, stroke, fill):
        self.operations.append(("modules", self.color, path.rectangles, stroke, fill))

    def drawImage(self, *_args, **_kwargs):
        raise AssertionError("Vector QR drawing must never rasterize to an image")


def _expected_horizontal_runs(matrix, x, top, side):
    module_count = len(matrix)
    pitch = side / module_count
    bottom = top - side
    expected = []
    for row_index, row in enumerate(matrix):
        first = None
        for col_index, dark in enumerate((*row, False)):
            if dark and first is None:
                first = col_index
            elif not dark and first is not None:
                expected.append(
                    (
                        x + first * pitch,
                        bottom + (module_count - row_index - 1) * pitch,
                        (col_index - first) * pitch,
                        pitch,
                    )
                )
                first = None
    return expected


@pytest.mark.parametrize("layout_id", supported_layout_ids())
@pytest.mark.parametrize("payload", (PDS2_PAYLOAD, PDS2_PAYLOAD + "|p=pg_" + "b" * 32))
def test_vector_geometry_reproduces_exact_matrix_and_quiet_zone(layout_id, payload):
    layout = get_layout(layout_id)
    x = layout.qr_x * layout.pdf_scale
    top = layout.pdf_height - layout.qr_y * layout.pdf_scale
    side = layout.qr_size * layout.pdf_scale
    matrix = _build_qr(payload).get_matrix()
    assert len(matrix) == len(matrix[0])
    assert all(not any(row) for row in matrix[:QR_QUIET_ZONE_MODULES])
    assert all(not any(row) for row in matrix[-QR_QUIET_ZONE_MODULES:])
    assert all(not any(row[:QR_QUIET_ZONE_MODULES]) for row in matrix)
    assert all(not any(row[-QR_QUIET_ZONE_MODULES:]) for row in matrix)

    canvas = _RecordingCanvas()
    _draw_qr_vector(canvas, payload, x, top, side)
    assert canvas.state_depth == 0
    assert len(canvas.operations) == 2
    background, black = canvas.operations
    assert background[0:2] == ("background", (1, 1, 1))
    assert background[2:6] == pytest.approx((x, top - side, side, side))
    assert background[6:] == (0, 1)
    assert black[0:2] == ("modules", (0, 0, 0))
    assert black[-2:] == (0, 1)
    expected = _expected_horizontal_runs(matrix, x, top, side)
    assert len(black[2]) == len(expected)
    for actual, desired in zip(black[2], expected):
        assert actual == pytest.approx(desired)


@pytest.mark.parametrize("layout_id", supported_layout_ids())
def test_real_pdf_has_native_qr_geometry_and_no_embedded_image(layout_id):
    layout = get_layout(layout_id)
    stream = BytesIO()
    canvas = Canvas(stream, pagesize=(612, 792), pageCompression=0, invariant=1)
    _draw_qr_vector(
        canvas,
        PDS2_PAYLOAD,
        layout.qr_x * layout.pdf_scale,
        layout.pdf_height - layout.qr_y * layout.pdf_scale,
        layout.qr_size * layout.pdf_scale,
    )
    canvas.showPage()
    canvas.save()
    pdf = stream.getvalue()
    assert pdf.startswith(b"%PDF-")
    assert b"/Subtype /Image" not in pdf
    assert b" re" in pdf  # ReportLab vector rectangle operators
    assert b" f*" in pdf or b" f" in pdf  # Filled, not stroked QR path


def test_legacy_image_helper_kept_and_error_correction_unchanged():
    matrix = _build_qr(PDS2_PAYLOAD).get_matrix()
    assert matrix
    assert _build_qr(PDS2_PAYLOAD).error_correction == qrcode.constants.ERROR_CORRECT_L
    image = make_qr_image(PDS2_PAYLOAD)
    assert image.getSize()[0] == len(matrix) * 10
    assert image.getSize()[1] == len(matrix) * 10


def test_invalid_print_size_fails_before_canvas_mutation():
    canvas = _RecordingCanvas()
    with pytest.raises(ValueError, match="positive"):
        _draw_qr_vector(canvas, PDS2_PAYLOAD, 0, 100, 0)
    assert canvas.state_depth == 0
    assert canvas.operations == []


def test_registered_route_uses_vector_renderer_without_legacy_image(tmp_path, monkeypatch):
    """Exercise the real managed-route entry point, not just its vector helper."""
    assignment = {
        "assignment_id": "quiz1",
        "title": "Synthetic QR Test",
        "question_count": 8,
        "choices": ["A", "B", "C", "D"],
        "layout_id": "standard_15q_abcd_v1",
        "answer_key": {str(i): "A" for i in range(1, 9)},
        "standards": {str(i): [] for i in range(1, 9)},
    }
    student = {
        "class_id": "class1",
        "student_id": "synthetic1",
        "last_name": "Example",
        "first_name": "Test",
        "period": "1",
    }
    records = build_answer_sheet_record_set(
        "class1",
        assignment,
        student,
        generation_id="gen_00000000000000000000000000000001",
        artifact_id="art_00000000000000000000000000000002",
        output_kind="individual_pdf",
        reason="initial",
        issuance_id="iss_00000000000000000000000000000003",
        page_ids=("pg_00000000000000000000000000000004",),
        clock=lambda: "2026-07-15T12:00:00+00:00",
    )
    work_ref = scoreform_work_paths(tmp_path, "class1", "quiz1").work_ref
    route = build_answer_sheet_page_route(
        work_ref,
        records.pages[0],
        route_id="rt_1234567890abcdef1234567890abcdef",
    )
    registered = RegisteredAnswerSheetPageRoute(
        route=route, registration_path=Path(tmp_path) / "synthetic-route.json"
    )

    def forbidden_image(*_args, **_kwargs):
        raise AssertionError("Active PDF rendering must not call make_qr_image")

    monkeypatch.setattr(templates_module, "make_qr_image", forbidden_image)
    canvas = _RecordingCanvas()
    templates_module.draw_qr_code(canvas, registered, get_layout())
    assert canvas.state_depth == 0
    assert len(canvas.operations) == 2
    assert canvas.operations[0][0] == "background"
    assert canvas.operations[1][0] == "modules"
