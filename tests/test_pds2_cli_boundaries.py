from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import qrcode

from scoreform import cli_score, pds2_scan_dispatch, qr_workflows
from scoreform.pds2_scan_dispatch import QrPayloadDetectionResult


class _Batch:
    def __init__(self, status: str, code: int) -> None:
        self.batch_status = status
        self._code = code

    def exit_code(self) -> int:
        return self._code


def test_score_cli_uses_dispatch_exit_status_without_later_stage_calls(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    batches = (
        _Batch("complete_success", 0),
        _Batch("partial_success", 1),
        _Batch("zero_success", 1),
    )
    monkeypatch.setattr(cli_score.workspace, "get_scoreform_workspace_root", lambda: tmp_path)
    monkeypatch.setattr(
        cli_score,
        "format_pds2_dispatch_summary",
        lambda batch: f"Batch status: {batch.batch_status}",
    )
    monkeypatch.setattr(
        cli_score,
        "export_to_csv",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("routed export must not run")
        ),
    )
    for batch in batches:
        monkeypatch.setattr(cli_score, "process_file_qr_aware", lambda *_args, **_kwargs: batch)
        assert cli_score.run_score(["scan.pdf"]) == batch.exit_code()
    output = capsys.readouterr().out
    assert "Batch status: complete_success" in output
    assert "Batch status: partial_success" in output
    assert "Batch status: zero_success" in output
    assert "No routed results were written" in output


def test_explicit_qr_csv_rejected_before_workspace_or_processing(
    monkeypatch, capsys
) -> None:
    monkeypatch.setattr(
        cli_score.workspace,
        "get_scoreform_workspace_root",
        lambda: (_ for _ in ()).throw(AssertionError("workspace must not resolve")),
    )
    monkeypatch.setattr(
        cli_score,
        "process_file_qr_aware",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("retention must not run")
        ),
    )
    assert cli_score.run_score(["scan.pdf", "results.csv"]) == 1
    assert "pending #144" in capsys.readouterr().out


def test_decode_unknown_module_uses_retained_bytes_without_dispatch(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    payload = f"PDS2|m=uninstalled|c=class1|w=quiz1|r=rt_{'9' * 32}"
    source = tmp_path / "external.png"
    qrcode.make(payload).save(source)
    monkeypatch.setattr(
        qr_workflows.workspace, "get_scoreform_workspace_root", lambda: tmp_path
    )
    actual_retain = qr_workflows.retain_source_scan
    events = []

    def retain_then_delete(root, selected):
        retained = actual_retain(root, selected)
        events.append("retained")
        Path(selected).unlink()
        return retained

    actual_load = qr_workflows.load_retained_page_for_qr

    def load(retained, number, **kwargs):
        assert events == ["retained"]
        assert not source.exists()
        assert retained.retained_source_path.exists()
        events.append("loaded")
        return actual_load(retained, number, **kwargs)

    monkeypatch.setattr(qr_workflows, "retain_source_scan", retain_then_delete)
    monkeypatch.setattr(qr_workflows, "load_retained_page_for_qr", load)
    monkeypatch.setattr(
        pds2_scan_dispatch,
        "build_scoreform_scan_registry",
        lambda: (_ for _ in ()).throw(AssertionError("decode must not build registry")),
    )
    monkeypatch.setattr(
        pds2_scan_dispatch,
        "dispatch_routes",
        lambda *_args: (_ for _ in ()).throw(AssertionError("decode must not dispatch")),
    )
    assert qr_workflows.run_decode_qr([str(source)]) == 0
    output = capsys.readouterr().out
    assert "Module: uninstalled" in output
    assert "Class: class1" in output
    assert "Work: quiz1" in output
    assert f"Route: rt_{'9' * 32}" in output
    for forbidden in ("student_id", "logical page", "layout", "answer key"):
        assert forbidden not in output.lower()


def test_decode_malformed_page_among_valid_pages_is_nonzero_and_warns(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    source = tmp_path / "source.png"
    assert cv2.imwrite(str(source), np.full((20, 20, 3), 255, np.uint8))
    monkeypatch.setattr(
        qr_workflows.workspace, "get_scoreform_workspace_root", lambda: tmp_path
    )
    monkeypatch.setattr(qr_workflows, "retained_source_page_count", lambda *_args, **_kwargs: 2)
    monkeypatch.setattr(
        qr_workflows,
        "load_retained_page_for_qr",
        lambda *_args, **_kwargs: np.full((20, 20, 3), 255, np.uint8),
    )
    detections = iter(
        (
            QrPayloadDetectionResult(
                f"PDS2|m=missing|c=class1|w=quiz1|r=rt_{'a' * 32}",
                "raw",
            ),
            QrPayloadDetectionResult(
                "PDS2|broken",
                "raw",
                diagnostic_errors=(OSError("diagnostic failed"),),
            ),
        )
    )
    monkeypatch.setattr(
        qr_workflows, "detect_qr_payload_text", lambda *_args, **_kwargs: next(detections)
    )
    assert qr_workflows.run_decode_qr([str(source)]) == 1
    output = capsys.readouterr().out
    assert "Page: 1" in output and "Module: missing" in output
    assert "Page: 2" in output and "Error:" in output
    assert "Diagnostic warning: diagnostic failed" in output
