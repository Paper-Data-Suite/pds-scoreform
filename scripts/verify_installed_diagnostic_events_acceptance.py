"""Clean-wheel installed acceptance for ScoreForm issue #192."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import subprocess
import sys
from importlib import metadata
from pathlib import Path

import pds_core

from scoreform.diagnostic_events import (
    build_diagnostic_event,
    diagnostic_event_path,
    record_diagnostic_event,
)


class AcceptanceFailure(RuntimeError):
    """Bounded installed-acceptance failure."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AcceptanceFailure(message)


def _module_origin(module_name: str) -> Path:
    module = importlib.import_module(module_name)
    module_file = getattr(module, "__file__", None)
    if not isinstance(module_file, str) or not module_file:
        raise AcceptanceFailure(f"{module_name} has no import origin.")
    return Path(module_file).resolve()


def _is_isolated_installed_origin(path: Path) -> bool:
    try:
        resolved = path.resolve()
        prefix = Path(sys.prefix).resolve()
        return (
            resolved.is_relative_to(prefix)
            and "site-packages" in {part.lower() for part in resolved.parts}
        )
    except (OSError, RuntimeError, ValueError):
        return False


def _scoreform_executable() -> Path:
    name = "scoreform.exe" if os.name == "nt" else "scoreform"
    candidate = Path(sys.executable).with_name(name)
    if not candidate.is_file():
        raise AcceptanceFailure(
            f"installed ScoreForm console entry point was not found at {candidate}"
        )
    return candidate


def _run(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _installed_environment(workspace: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment["PDS_WORKSPACE_ROOT"] = os.fspath(workspace)
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    return environment


def _verify_installed_provenance(
    workspace: Path,
    *,
    version: str,
    expected_core_version: str,
) -> None:
    _require(not workspace.exists(), f"workspace must begin absent: {workspace}")
    _require(metadata.version("scoreform") == version, "ScoreForm version mismatch.")
    _require(
        metadata.version("pds-core") == expected_core_version,
        "PDS Core distribution version mismatch.",
    )
    _require(
        getattr(pds_core, "__version__", None) == expected_core_version,
        "PDS Core module/distribution versions disagree.",
    )

    for module_name in (
        "scoreform",
        "scoreform.cli",
        "scoreform.cli_diagnostics",
        "scoreform.diagnostic_events",
        "pds_core",
    ):
        origin = _module_origin(module_name)
        _require(
            _is_isolated_installed_origin(origin),
            f"{module_name} did not import from isolated site-packages: {origin}",
        )

    requirements = tuple(metadata.requires("scoreform") or ())
    folded = "\n".join(requirements).casefold()
    for forbidden in (
        "sentry",
        "opentelemetry",
        "requests",
        "httpx",
        "analytics",
    ):
        _require(
            forbidden not in folded,
            f"installed ScoreForm unexpectedly depends on telemetry/network package {forbidden!r}.",
        )

    pip_check = _run(
        [sys.executable, "-m", "pip", "check"],
        cwd=workspace.parent,
        env=_installed_environment(workspace),
    )
    _require(
        pip_check.returncode == 0,
        f"installed pip check failed: {pip_check.stdout} {pip_check.stderr}",
    )
    _require(
        not workspace.exists(),
        "installed provenance checks created workspace state.",
    )


def _verify_absent_workspace_list_is_read_only(workspace: Path) -> None:
    executable = _scoreform_executable()
    result = _run(
        [os.fspath(executable), "diagnostics", "list", "--format", "json"],
        cwd=workspace.parent,
        env=_installed_environment(workspace),
    )
    _require(result.returncode == 0, "installed diagnostics list failed.")
    payload = json.loads(result.stdout)
    _require(payload == {"events": [], "warning_codes": []}, "empty list JSON changed.")
    _require(
        not workspace.exists(),
        "installed diagnostics list created an absent configured workspace.",
    )


def _verify_installed_round_trip(workspace: Path) -> None:
    workspace.mkdir(parents=True)
    event = build_diagnostic_event(
        component="scan_intake",
        workflow="process_scan",
        stage="decode",
        outcome="failure",
        code="qr_missing",
        class_id="class1",
        assignment_id="quiz1",
        exception=RuntimeError(
            "PRIVATE-STUDENT-SENTINEL C:\\Users\\Teacher Name\\private"
        ),
    )
    record_diagnostic_event(workspace, event)
    event_path = diagnostic_event_path(workspace, event.event_id)
    _require(event_path.is_file(), "installed diagnostic event was not persisted.")

    raw = event_path.read_text(encoding="utf-8")
    for forbidden in (
        "PRIVATE-STUDENT-SENTINEL",
        "Teacher Name",
        '"student_id"',
        '"answers"',
        '"score"',
        '"payload"',
        '"traceback"',
    ):
        _require(
            forbidden not in raw,
            f"installed structured event leaked prohibited value {forbidden!r}.",
        )

    executable = _scoreform_executable()
    environment = _installed_environment(workspace)
    listed = _run(
        [
            os.fspath(executable),
            "diagnostics",
            "list",
            "--limit",
            "20",
            "--format",
            "json",
        ],
        cwd=workspace.parent,
        env=environment,
    )
    _require(listed.returncode == 0, "installed diagnostics JSON list failed.")
    list_payload = json.loads(listed.stdout)
    _require(len(list_payload["events"]) == 1, "installed list did not return one event.")
    listed_event = list_payload["events"][0]
    _require(listed_event["event_id"] == event.event_id, "listed event ID changed.")
    _require(listed_event["code"] == "qr_missing", "listed event code changed.")
    _require(
        listed_event["class_id"] == "class1"
        and listed_event["assignment_id"] == "quiz1",
        "listed work context changed.",
    )

    shown = _run(
        [
            os.fspath(executable),
            "diagnostics",
            "show",
            "--event-id",
            event.event_id,
            "--format",
            "json",
        ],
        cwd=workspace.parent,
        env=environment,
    )
    _require(shown.returncode == 0, "installed diagnostics JSON show failed.")
    show_payload = json.loads(shown.stdout)
    _require(show_payload == listed_event, "installed list/show event models disagree.")

    before = event_path.read_bytes()
    repeated = _run(
        [os.fspath(executable), "diagnostics", "list", "--limit", "20"],
        cwd=workspace.parent,
        env=environment,
    )
    _require(repeated.returncode == 0, "installed diagnostics text list failed.")
    _require(event.event_id in repeated.stdout, "text list omitted event ID.")
    _require(event_path.read_bytes() == before, "read-only CLI mutated event bytes.")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--expected-core-version", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    options = _parse_args(argv)
    workspace = options.workspace.resolve()
    try:
        _verify_installed_provenance(
            workspace,
            version=options.version,
            expected_core_version=options.expected_core_version,
        )
        _verify_absent_workspace_list_is_read_only(workspace)
        _verify_installed_round_trip(workspace)
    except (
        AcceptanceFailure,
        json.JSONDecodeError,
        OSError,
        ValueError,
    ) as error:
        print(f"FAILED: {error}")
        return 1

    print("Installed issue #192 diagnostic-event acceptance passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
