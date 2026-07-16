"""Build a deterministic two-page PDF for the real #145 CLI smoke."""

from __future__ import annotations

import sys
from pathlib import Path

from pdf2image import convert_from_path
from reportlab.pdfgen import canvas


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: build_partial_cli_smoke.py INPUT.pdf OUTPUT.pdf")
    source, output = Path(sys.argv[1]), Path(sys.argv[2])
    pages = convert_from_path(source, dpi=250, first_page=1, last_page=1)
    if len(pages) != 1:
        raise RuntimeError("Expected exactly one rendered source page.")
    valid = pages[0].convert("RGB")
    width, height = valid.size
    document = canvas.Canvas(str(output), pagesize=(width, height))
    document.drawInlineImage(valid, 0, 0, width=width, height=height)
    document.showPage()
    document.setFillColorRGB(1, 1, 1)
    document.rect(0, 0, width, height, fill=1, stroke=0)
    document.save()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
