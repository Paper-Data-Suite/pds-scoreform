"""Issue #192 direct diagnostics CLI and read-only inspection tests."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import scoreform.cli as scoreform_cli
import scoreform.cli_diagnostics as cli_diagnostics
import scoreform.diagnostic_events as diagnostics


def _record(
    root: Path,
    *,
    code: str = "qr_missing",
    occurred_at: datetime | None = None,
    class_id: str | None = None,
    assignment_id: str | None = None,
) -> diagnostics.DiagnosticEvent:
    event = diagnostics.build_diagnostic_event(
        component="scan_intake",
        workflow="process_scan",
        stage="decode",
        outcome="failure",
        code=code,
        class_id=class_id,
        assignment_id=assignment_id,
        occurred_at=occurred_at,
    )
    diagnostics.record_diagnostic_event(root, event)
    return event


@pytest.fixture
def cli_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    monkeypatch.setattr(
        cli_diagnostics.workspace,
        "resolve_workspace_root",
        lambda: tmp_path,
    )
    return tmp_path


def _tree(root: Path) -> tuple[str, ...]:
    return tuple(
        sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))
    )


def test_list_missing_store_is_read_only(
    cli_workspace: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    before = _tree(cli_workspace)

    assert cli_diagnostics.run_diagnostics(["list"]) == 0

    assert _tree(cli_workspace) == before == ()
    assert "No retained ScoreForm diagnostic events." in capsys.readouterr().out


def test_list_defaults_newest_first_and_renders_safe_context(
    cli_workspace: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    older = _record(
        cli_workspace,
        occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    newer = _record(
        cli_workspace,
        occurred_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        class_id="class1",
        assignment_id="quiz1",
    )

    assert cli_diagnostics.run_diagnostics(["list"]) == 0

    output = capsys.readouterr().out
    assert output.index(newer.event_id) < output.index(older.event_id)
    assert "class=class1 assignment=quiz1" in output
    assert "QR detection did not find a usable locator" in output


def test_list_json_contains_only_fixed_event_model(
    cli_workspace: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    event = _record(cli_workspace, class_id="class1", assignment_id="quiz1")

    assert cli_diagnostics.run_diagnostics(
        ["list", "--limit", "1", "--format", "json"]
    ) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["warning_codes"] == []
    assert len(payload["events"]) == 1
    rendered = payload["events"][0]
    assert rendered["event_id"] == event.event_id
    assert set(rendered) == {
        "schema_version",
        "module",
        "record_type",
        "event_id",
        "occurred_at",
        "scoreform_version",
        "core_version",
        "component",
        "workflow",
        "stage",
        "outcome",
        "category",
        "code",
        "class_id",
        "assignment_id",
        "exception_type",
        "safe_summary",
        "path_context",
    }
    forbidden = {
        "student_id",
        "answers",
        "answer_key",
        "score",
        "payload",
        "metadata",
        "details",
        "traceback",
    }
    assert forbidden.isdisjoint(rendered)


@pytest.mark.parametrize("limit", ("0", "201", "not-a-number"))
def test_list_rejects_invalid_limit_without_mutation(
    cli_workspace: Path,
    capsys: pytest.CaptureFixture[str],
    limit: str,
) -> None:
    assert cli_diagnostics.run_diagnostics(["list", "--limit", limit]) == 1
    assert not (cli_workspace / "shared").exists()
    output = capsys.readouterr().out
    assert "Error:" in output
    assert "--limit" in output


def test_show_text_and_json_are_exact_and_read_only(
    cli_workspace: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    event = _record(cli_workspace, class_id="class1", assignment_id="quiz1")
    path = diagnostics.diagnostic_event_path(cli_workspace, event.event_id)
    before = path.read_bytes()

    assert cli_diagnostics.run_diagnostics(
        ["show", "--event-id", event.event_id]
    ) == 0
    text_output = capsys.readouterr().out
    assert f"event_id: {event.event_id}" in text_output
    assert "class_id: class1" in text_output
    assert path.read_bytes() == before

    assert cli_diagnostics.run_diagnostics(
        ["show", "--event-id", event.event_id, "--format", "json"]
    ) == 0
    json_output = json.loads(capsys.readouterr().out)
    assert json_output["event_id"] == event.event_id
    assert json_output["code"] == "qr_missing"
    assert path.read_bytes() == before


def test_show_missing_event_is_bounded_without_traceback(
    cli_workspace: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing = "diag_" + "a" * 32

    assert cli_diagnostics.run_diagnostics(
        ["show", "--event-id", missing]
    ) == 1

    output = capsys.readouterr().out
    assert "Error: Diagnostic event was not found." in output
    assert "Traceback" not in output


def test_list_reports_malformed_entry_without_dumping_bytes(
    cli_workspace: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    directory = diagnostics.diagnostic_events_dir(cli_workspace)
    directory.mkdir(parents=True)
    private = "PRIVATE-STUDENT-SENTINEL"
    (directory / ("diag_" + "b" * 32 + ".json")).write_text(
        private,
        encoding="utf-8",
    )

    assert cli_diagnostics.run_diagnostics(["list"]) == 0

    output = capsys.readouterr().out
    assert "invalid_diagnostic_event" in output
    assert private not in output


def test_main_dispatches_diagnostics_lazily(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(
        cli_diagnostics,
        "run_diagnostics",
        lambda args: calls.append(list(args)) or 0,
    )

    assert scoreform_cli.main(
        ["diagnostics", "list", "--limit", "3"],
        default_to_menu=False,
    ) == 0
    assert calls == [["list", "--limit", "3"]]


def test_help_discovers_diagnostics_commands(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert scoreform_cli.main(["--help"], default_to_menu=False) == 0
    output = capsys.readouterr().out
    assert "scoreform diagnostics list" in output
    assert "scoreform diagnostics show --event-id <event_id>" in output
    assert "Read retained privacy-minimal ScoreForm diagnostic events." in output
