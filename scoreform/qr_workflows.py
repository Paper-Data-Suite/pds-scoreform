"""Retained-source PDS2 QR decode command."""

from pathlib import Path

from pds_core.pds2 import parse_pds2_payload, serialize_pds2_payload
from pds_core.scan_retention import retain_source_scan

from scoreform import workspace
from scoreform.pds2_scan_dispatch import (
    detect_qr_payload_text,
    validate_pds2_scan_source,
)
from scoreform.retained_page import (
    load_retained_page_for_qr,
    retained_source_page_count,
    validate_retained_source,
)


def run_decode_qr(args):
    """Retain a source and decode only Core-valid PDS2 locator fields."""
    if len(args) != 1:
        print("Usage: scoreform decode-qr <input_file>")
        return 1
    try:
        source = validate_pds2_scan_source(args[0])
        workspace_root = workspace.get_scoreform_workspace_root()
        if not isinstance(workspace_root, Path):
            raise TypeError("workspace root must be a Path")
        retained = retain_source_scan(workspace_root, source)
        validate_retained_source(retained, workspace_root=workspace_root)
        page_count = retained_source_page_count(
            retained, workspace_root=workspace_root
        )
    except Exception as error:
        print(f"Error: Could not retain or enumerate source: {error}")
        return 1

    print(f"Source scan ID: {retained.source_scan_id}")
    print(f"Retained source path: {retained.retained_source_relative_path}")
    print(f"Source SHA-256: {retained.source_sha256}")
    valid = 0
    failed = False
    for number in range(1, page_count + 1):
        try:
            image = load_retained_page_for_qr(
                retained, number, workspace_root=workspace_root
            )
            detection = detect_qr_payload_text(
                image,
                retained_source=retained,
                source_page_number=number,
                workspace_root=workspace_root,
            )
            for diagnostic_error in detection.diagnostic_errors:
                print(f"Diagnostic warning: {diagnostic_error}")
            if detection.raw_payload_text is None:
                raise detection.error or ValueError("No QR payload was detected.")
            locator = parse_pds2_payload(detection.raw_payload_text)
        except Exception as error:
            failed = True
            print(f"Page: {number}")
            print(f"Error: {error}")
            continue
        valid += 1
        print(f"Page: {number}")
        print("Schema: PDS2")
        print(f"Module: {locator.module_id}")
        print(f"Class: {locator.class_id}")
        print(f"Work: {locator.work_id}")
        print(f"Route: {locator.route_id}")
        print(f"Canonical payload: {serialize_pds2_payload(locator)}")
    return 0 if valid == page_count and not failed else 1
