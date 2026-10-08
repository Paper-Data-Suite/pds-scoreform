"""Read-only QR print geometry baseline for Issue #225.

This module does not change QR generation or scanning behavior.
"""

from __future__ import annotations

from dataclasses import dataclass

import qrcode

from scoreform.layouts import AnswerSheetLayout

QR_BORDER_MODULES = 4  # Existing templates.QR_QUIET_ZONE_MODULES.
QR_ERROR_CORRECTION = qrcode.constants.ERROR_CORRECT_L
PDF_POINTS_PER_INCH = 72.0


@dataclass(frozen=True, slots=True)
class QrPrintBaseline:
    layout_id: str
    payload_characters: int
    matrix_modules: int
    total_modules: int
    size_points: float
    size_inches: float
    module_points: float
    module_inches: float
    error_correction: str = "L"
    border_modules: int = QR_BORDER_MODULES


def measure_qr_print_baseline(
    layout: AnswerSheetLayout, payload: str
) -> QrPrintBaseline:
    """Measure current matrix density and physical size without rendering a sheet.

    The matrix module count excludes the surrounding quiet zone. The current
    image and PDF sizing include that zone, so module pitch uses total_modules.
    The caller supplies an authentic or sanitized representative PDS2 payload.
    """
    if not isinstance(payload, str) or not payload:
        raise ValueError("payload must be nonempty text")
    qr = qrcode.QRCode(
        version=1,
        error_correction=QR_ERROR_CORRECTION,
        box_size=10,
        border=QR_BORDER_MODULES,
    )
    qr.add_data(payload)
    qr.make(fit=True)
    matrix_modules = qr.modules_count
    total_modules = matrix_modules + 2 * QR_BORDER_MODULES
    size_points = layout.qr_size * layout.pdf_scale
    return QrPrintBaseline(
        layout_id=layout.layout_id,
        payload_characters=len(payload),
        matrix_modules=matrix_modules,
        total_modules=total_modules,
        size_points=size_points,
        size_inches=size_points / PDF_POINTS_PER_INCH,
        module_points=size_points / total_modules,
        module_inches=size_points / total_modules / PDF_POINTS_PER_INCH,
    )
