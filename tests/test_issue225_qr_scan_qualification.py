"""Issue #225 Slice 6: sanitized, non-routing qualification evidence."""

from __future__ import annotations

import json
from types import SimpleNamespace

import numpy as np
import pytest

from scoreform.qr_scan_qualification import (
    PageQualification,
    build_report,
    classify_detection,
    qualify_pages,
    select_pages,
)

SENSITIVE_TEXT = "PDS2|m=scoreform|c=class_private|w=assignment_private|r=rt_" + "a" * 32


def _image():
    return np.full((45, 75, 3), 255, dtype=np.uint8)


def _detection(text, method):
    return SimpleNamespace(raw_payload_text=text, decode_method=method)


def _parse(text):
    if text != SENSITIVE_TEXT:
        raise ValueError("invalid input includes student-private-text")
    return object()


def test_opencv_decode_is_recorded_only_as_validated_status():
    record = classify_detection(page=2, image=_image(), detection=_detection(SENSITIVE_TEXT, "raw"), parse_payload=_parse)
    assert record == PageQualification(2, "valid_pds2", "opencv", 75, 45)
    assert SENSITIVE_TEXT not in json.dumps(build_report(3, (record,)))


def test_zxing_result_is_not_reported_as_route_registered():
    record = classify_detection(page=4, image=_image(), detection=_detection(SENSITIVE_TEXT, "zxing-cpp:tight"), parse_payload=_parse)
    report = build_report(29, (record,))
    assert report["pages"] == [{"page": 4, "outcome": "valid_pds2", "engine": "zxing-cpp", "image_width": 75, "image_height": 45}]
    assert report["route_registration_checked"] is False
    assert report["student_identity_checked"] is False
    assert report["answer_scoring_performed"] is False
    assert report["all_pages_examined"] is False


def test_invalid_payload_errors_and_raw_text_never_leak():
    record = classify_detection(page=1, image=_image(), detection=_detection("invalid student-private-text", "zxing-cpp:page"), parse_payload=_parse)
    assert record.outcome == "invalid_pds2"
    serialized = json.dumps(build_report(1, (record,)))
    assert "private" not in serialized
    assert "invalid" in serialized


def test_missing_qr_remains_unresolved():
    record = classify_detection(page=7, image=_image(), detection=_detection(None, None), parse_payload=_parse)
    assert record == PageQualification(7, "qr_unreadable", "none", 75, 45)


def test_load_and_detection_failures_are_page_isolated():
    seen = []

    def loader(n):
        if n == 2:
            raise OSError("sensitive/path/Student.pdf")
        return _image()

    def detector(_image, n):
        if n == 3:
            raise RuntimeError("sensitive student name")
        return _detection(SENSITIVE_TEXT, "raw")

    rows = qualify_pages(total_pages=3, selection=None, load_page=loader, detect=detector, parse_payload=_parse, on_page=seen.append)
    assert [x.outcome for x in rows] == ["valid_pds2", "page_load_error", "qr_unreadable"]
    assert tuple(seen) == rows
    report = json.dumps(build_report(3, rows))
    assert "sensitive" not in report
    assert "Student.pdf" not in report


def test_selected_pages_and_totals_are_deterministic():
    rows = qualify_pages(total_pages=29, selection=(28, 4, 25, 11), load_page=lambda _: _image(), detect=lambda _img, _: _detection(None, None), parse_payload=_parse)
    assert [x.page for x in rows] == [4, 11, 25, 28]
    report = build_report(29, rows)
    assert report["source_total_pages"] == 29
    assert report["pages_examined"] == 4
    assert report["outcomes"]["qr_unreadable"] == 4
    assert report["decoders"]["none"] == 4


@pytest.mark.parametrize("selection", [(0,), (30,), (2, 2), (), (True,)])
def test_invalid_selections_fail_closed(selection):
    with pytest.raises(ValueError):
        select_pages(29, selection)


def test_duplicate_page_records_are_rejected():
    row = PageQualification(1, "qr_unreadable", "none", 75, 45)
    with pytest.raises(ValueError, match="unique"):
        build_report(2, (row, row))


def test_rejects_inconsistent_qualification_model():
    with pytest.raises(ValueError):
        PageQualification(4, "qr_unreadable", "zxing-cpp", 75, 45)
    with pytest.raises(ValueError):
        PageQualification(4, "page_load_error", "none", 75, 45)


def test_synthetic_core_retained_image_round_trip(tmp_path):
    """Real installed scanner integration; no classroom scan is part of tests."""
    import cv2
    import qrcode
    from pds_core.pds2 import serialize_pds2_payload
    from pds_core.routing_models import ModuleWorkRef, RouteLocator

    from scoreform.qr_scan_qualification import qualify_source_scan

    locator = RouteLocator(
        "PDS2",
        ModuleWorkRef("scoreform", "class1", "quiz1"),
        "rt_" + "1" * 32,
    )
    payload = serialize_pds2_payload(locator)
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=8, border=4)
    qr.add_data(payload)
    qr.make(fit=True)
    image = np.asarray(qr.make_image(fill_color="black", back_color="white").convert("RGB"))
    source = tmp_path / "synthetic.png"
    assert cv2.imwrite(str(source), cv2.cvtColor(image, cv2.COLOR_RGB2BGR))
    report = qualify_source_scan(source)
    assert report["outcomes"]["valid_pds2"] == 1
    assert report["pages"][0]["engine"] == "opencv"
    assert payload not in json.dumps(report)

def test_qualification_suppresses_nested_diagnostic_stdout(tmp_path, monkeypatch, capsys):
    """Temp diagnostic paths cannot escape through decoder print statements."""
    import cv2

    from scoreform import pds2_scan_dispatch
    from scoreform.qr_scan_qualification import qualify_source_scan

    source = tmp_path / "synthetic_empty.png"
    assert cv2.imwrite(str(source), _image())

    def noisy_decoder(*_args, **_kwargs):
        print("Saved diagnostic to C:/users/private/Student-123/tmp")
        return _detection(None, None)

    monkeypatch.setattr(pds2_scan_dispatch, "detect_qr_payload_text", noisy_decoder)
    report = qualify_source_scan(
        source,
        on_page=lambda page: print(f"Page {page.page}: {page.outcome}"),
    )
    assert report["outcomes"]["qr_unreadable"] == 1
    assert capsys.readouterr().out == "Page 1: qr_unreadable\n"


def test_quiet_decoder_restores_stdout_after_exception(capsys):
    from scoreform.qr_scan_qualification import _quiet_qualification_decode

    def noisy_failure():
        print("PRIVATE PRIVATE PRIVATE")
        raise RuntimeError("private diagnostic failed")

    with pytest.raises(RuntimeError, match="private diagnostic failed"):
        _quiet_qualification_decode(noisy_failure)
    print("Visible summary")
    assert capsys.readouterr().out == "Visible summary\n"
