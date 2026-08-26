"""Privacy and noninterference hardening for ScoreForm issue #193."""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from pds_core.module_operations import ModuleOperationsRequest

import scoreform.attention_provider as provider
from scoreform.diagnostic_events import (
    build_diagnostic_event,
    record_diagnostic_event,
)

ROOT = Path(__file__).resolve().parents[1]


def _inventory(root: Path) -> tuple[tuple[str, str], ...]:
    rows: list[tuple[str, str]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(root).as_posix()
        if path.is_dir():
            rows.append((relative, "dir"))
        elif path.is_file():
            rows.append((relative, hashlib.sha256(path.read_bytes()).hexdigest()))
    return tuple(rows)


def test_attention_runtime_modules_do_not_import_diagnostic_event_authority() -> None:
    for relative in (
        Path("scoreform/attention_model.py"),
        Path("scoreform/attention_work_discovery.py"),
        Path("scoreform/attention_scan.py"),
        Path("scoreform/attention_share_results.py"),
        Path("scoreform/attention_provider.py"),
    ):
        tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imported.add(node.module)
        assert "scoreform.diagnostic_events" not in imported


def test_changing_only_diagnostic_history_does_not_change_attention(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        provider,
        "discover_scan_review_items",
        lambda root, **kwargs: SimpleNamespace(items=(), warning_count=0),
    )
    monkeypatch.setattr(
        provider,
        "discover_scoreform_class_ids",
        lambda root, requested: (),
    )

    request = ModuleOperationsRequest(workspace_root=tmp_path)
    before_report = provider.evaluate_scoreform_attention(request)

    event = build_diagnostic_event(
        component="scan_intake",
        workflow="process_scan",
        stage="decode",
        outcome="failure",
        code="qr_missing",
        class_id="class_private",
        assignment_id="assignment_private",
        exception=RuntimeError("PRIVATE_DIAGNOSTIC_HISTORY_SENTINEL"),
    )
    record_diagnostic_event(tmp_path, event)

    workspace_before_query = _inventory(tmp_path)
    after_report = provider.evaluate_scoreform_attention(request)
    workspace_after_query = _inventory(tmp_path)

    assert after_report == before_report
    assert workspace_after_query == workspace_before_query
    assert "PRIVATE_DIAGNOSTIC_HISTORY_SENTINEL" not in repr(after_report)


def test_attention_provider_does_not_swallow_baseexception_control_signals(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ControlSignal(BaseException):
        pass

    monkeypatch.setattr(
        provider,
        "discover_scan_review_items",
        lambda root, **kwargs: SimpleNamespace(
            items=(SimpleNamespace(),),
            warning_count=0,
        ),
    )
    monkeypatch.setattr(
        provider,
        "project_scan_attention_fact",
        lambda item: (_ for _ in ()).throw(ControlSignal()),
    )

    with pytest.raises(ControlSignal):
        provider.evaluate_scoreform_attention(
            ModuleOperationsRequest(workspace_root=tmp_path)
        )


def test_shared_attention_source_has_no_student_payload_fields() -> None:
    source = "\n".join(
        (ROOT / relative).read_text(encoding="utf-8")
        for relative in (
            Path("scoreform/attention_model.py"),
            Path("scoreform/attention_scan.py"),
            Path("scoreform/attention_share_results.py"),
        )
    )
    for prohibited_field in (
        "student_id=",
        "student_name=",
        "answers=",
        "score=",
        "percentage=",
        "payload=",
        "source_filename=",
    ):
        assert prohibited_field not in source
