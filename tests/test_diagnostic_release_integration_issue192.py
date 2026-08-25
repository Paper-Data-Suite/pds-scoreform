"""Issue #192 release/privacy integration and deep-debug regression tests."""

from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

import scoreform.cli_diagnostics as cli_diagnostics
import scoreform.diagnostic_events as diagnostics
from scoreform.config import FULL_PAGE_DIAGNOSTICS_ENV
from scoreform.scoring import save_qr_failure_diagnostics_with_status

PROJECT_ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_NETWORK_IMPORT_ROOTS = {
    "aiohttp",
    "analytics",
    "httpx",
    "opentelemetry",
    "requests",
    "sentry_sdk",
    "socket",
    "urllib",
}


def _import_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.partition(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.partition(".")[0])
    return roots


def test_diagnostic_subsystem_has_no_network_or_telemetry_imports() -> None:
    production = (
        PROJECT_ROOT / "scoreform" / "diagnostic_events.py",
        PROJECT_ROOT / "scoreform" / "cli_diagnostics.py",
    )
    offenders: dict[str, list[str]] = {}
    for path in production:
        found = sorted(_import_roots(path) & FORBIDDEN_NETWORK_IMPORT_ROOTS)
        if found:
            offenders[path.name] = found
    assert offenders == {}


def test_runtime_metadata_adds_no_telemetry_dependency() -> None:
    pyproject = (PROJECT_ROOT / "pyproject.toml").read_text(
        encoding="utf-8"
    ).casefold()
    for forbidden in (
        "sentry-sdk",
        "sentry_sdk",
        "opentelemetry",
        "requests",
        "httpx",
        "analytics",
    ):
        assert forbidden not in pyproject


def test_direct_list_does_not_create_absent_workspace_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    absent = tmp_path / "configured-workspace-must-remain-absent"
    monkeypatch.setenv("PDS_WORKSPACE_ROOT", str(absent))

    assert cli_diagnostics.run_diagnostics(["list"]) == 0

    assert not absent.exists()
    assert "No retained ScoreForm diagnostic events." in capsys.readouterr().out


def _diagnostic_image() -> np.ndarray:
    return np.full((240, 320, 3), 255, dtype=np.uint8)


def test_full_page_qr_diagnostics_are_off_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(FULL_PAGE_DIAGNOSTICS_ENV, raising=False)
    result = save_qr_failure_diagnostics_with_status(
        _diagnostic_image(),
        "PRIVATE-STUDENT-SCAN.png",
        1,
        now=datetime(2026, 8, 25, tzinfo=timezone.utc),
        workspace_root=tmp_path,
    )
    assert result.paths
    assert not result.errors
    assert not any("full_page_debug" in Path(path).name for path in result.paths)


def test_full_page_qr_diagnostics_require_explicit_opt_in(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(FULL_PAGE_DIAGNOSTICS_ENV, "true")
    result = save_qr_failure_diagnostics_with_status(
        _diagnostic_image(),
        "PRIVATE-STUDENT-SCAN.png",
        1,
        now=datetime(2026, 8, 25, tzinfo=timezone.utc),
        workspace_root=tmp_path,
    )
    full_page_paths = tuple(
        Path(path)
        for path in result.paths
        if "full_page_debug" in Path(path).name
    )
    assert len(full_page_paths) == 1
    assert full_page_paths[0].is_file()


def test_deep_debug_artifact_does_not_relax_structured_event_privacy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(FULL_PAGE_DIAGNOSTICS_ENV, "1")
    result = save_qr_failure_diagnostics_with_status(
        _diagnostic_image(),
        "PRIVATE-STUDENT-SCAN.png",
        1,
        now=datetime(2026, 8, 25, tzinfo=timezone.utc),
        workspace_root=tmp_path,
    )
    full_page = next(
        Path(path)
        for path in result.paths
        if "full_page_debug" in Path(path).name
    )

    event = diagnostics.build_diagnostic_event(
        component="scan_intake",
        workflow="process_scan",
        stage="decode",
        outcome="failure",
        code="qr_missing",
        exception=RuntimeError(
            "PRIVATE-STUDENT-SENTINEL C:\\Users\\Teacher Name\\private"
        ),
        workspace_root=tmp_path,
        path=full_page,
    )
    diagnostics.record_diagnostic_event(tmp_path, event)
    event_path = diagnostics.diagnostic_event_path(tmp_path, event.event_id)
    raw = event_path.read_text(encoding="utf-8")

    assert "PRIVATE-STUDENT-SCAN" not in raw
    assert "PRIVATE-STUDENT-SENTINEL" not in raw
    assert "Teacher Name" not in raw
    assert str(tmp_path) not in raw
    assert '"student_id"' not in raw
    assert '"answers"' not in raw
    assert '"score"' not in raw
    assert '"payload"' not in raw
    assert event.exception_type == "RuntimeError"
