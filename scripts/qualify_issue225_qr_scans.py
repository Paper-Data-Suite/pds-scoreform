"""Run privacy-bounded Issue #225 QR qualification on local scans.

Usage: python scripts/qualify_issue225_qr_scans.py INPUT.pdf --pages 4,11,25,28
"""

from __future__ import annotations

import argparse
import json
from importlib import import_module
from pathlib import Path

from scoreform.qr_scan_qualification import (
    PageQualification,
    qualify_source_scan,
)


def _parse_page_selection(value: str) -> tuple[int, ...]:
    try:
        pages = tuple(int(part.strip()) for part in value.split(","))
    except ValueError as error:
        raise argparse.ArgumentTypeError("--pages requires comma-separated positive integers") from error
    if not pages or any(page < 1 for page in pages) or len(set(pages)) != len(pages):
        raise argparse.ArgumentTypeError("--pages requires distinct positive page numbers")
    return tuple(sorted(pages))


def _require_native_zxing() -> None:
    try:
        backend = import_module("zxingcpp")
        if not callable(backend.read_barcodes) or backend.BarcodeFormat.QRCode is None:
            raise RuntimeError("unexpected native interface")
    except (ImportError, OSError, AttributeError, RuntimeError) as error:
        raise RuntimeError("ZXing-C++ unavailable; install the qr-zxing extra before qualification") from error


def _progress(page: PageQualification) -> None:
    # Enums only; never include decoded payload, input filename, or identifiers.
    print(f"Page {page.page}: {page.outcome} ({page.engine})", flush=True)


def _write_new_json(destination: Path, report: dict[str, object]) -> None:
    """Create only; avoid accidental overwrite of prior qualification evidence."""
    serialized = json.dumps(report, sort_keys=True, indent=2) + "\n"
    with destination.open("x", encoding="utf-8") as handle:
        handle.write(serialized)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local QR/PDS2 qualification without routing or scoring")
    parser.add_argument("source", type=Path, help="Local PDF/image (path is not written to report)")
    parser.add_argument("--pages", type=_parse_page_selection, help="Selected pages, e.g. 4,11,25,28 (default: all)")
    parser.add_argument("--output", type=Path, help="New JSON report path, outside the repository")
    args = parser.parse_args(argv)
    try:
        _require_native_zxing()
        report = qualify_source_scan(args.source, selected_pages=args.pages, on_page=_progress)
        if args.output is None:
            print(json.dumps(report, sort_keys=True, indent=2))
        else:
            _write_new_json(args.output, report)
            print("Sanitized qualification JSON written successfully.")
        return 0
    except FileExistsError:
        print("Qualification report already exists; choose a new filename. No overwrite performed.")
    except Exception as error:
        # Never interpolate errors: their messages can include source paths.
        print(f"Qualification failed ({type(error).__name__}); no source data printed.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
