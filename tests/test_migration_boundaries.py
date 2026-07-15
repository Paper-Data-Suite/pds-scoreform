from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from pds_core.routing_models import PDS2_SCHEMA, ModuleWorkRef, RouteLocator

import scoreform.cli
from scoreform.templates import build_qr_payload

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "args, issue",
    [
        (["resolve-scan-review", "failure1", "--action", "defer"], "#145"),
    ],
)
def test_migration_dependent_cli_commands_fail_cleanly_without_writes(
    args, issue, tmp_path, monkeypatch, capsys
) -> None:
    workspace_root = tmp_path / "workspace-must-not-exist"
    monkeypatch.setenv("PDS_WORKSPACE_ROOT", os.fspath(workspace_root))

    assert scoreform.cli.main(args) == 1

    output = capsys.readouterr().out
    assert "temporarily unavailable during the Core 0.5/PDS2 migration" in output
    assert issue in output
    assert "partial routing artifacts" in output
    assert not workspace_root.exists()


def test_setup_assignment_is_available_and_invalid_inputs_do_not_create_workspace(
    tmp_path, monkeypatch, capsys
) -> None:
    workspace_root = tmp_path / "workspace-must-not-exist"
    monkeypatch.setenv("PDS_WORKSPACE_ROOT", os.fspath(workspace_root))

    assert scoreform.cli.main(
        ["setup-assignment", "assignment.json", "roster.csv"]
    ) == 1

    assert "not found" in capsys.readouterr().out
    assert not workspace_root.exists()


def test_qr_builder_has_a_deliberate_service_boundary() -> None:
    locator = RouteLocator(
        PDS2_SCHEMA,
        ModuleWorkRef("scoreform", "class1", "quiz1"),
        "rt_10000000000000000000000000000000",
    )
    assert build_qr_payload(locator) == (
        "PDS2|m=scoreform|c=class1|w=quiz1|"
        "r=rt_10000000000000000000000000000000"
    )
    with pytest.raises(TypeError):
        build_qr_payload({})


def test_main_py_migration_failure_has_no_traceback(tmp_path) -> None:
    workspace_root = tmp_path / "workspace-must-not-exist"
    env = os.environ.copy()
    env["PDS_WORKSPACE_ROOT"] = os.fspath(workspace_root)

    result = subprocess.run(
        [
            sys.executable,
            "main.py",
            "generate",
            "assignment.json",
            "--rosters",
            "roster.csv",
        ],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "not found" in result.stdout
    assert "Traceback" not in result.stdout + result.stderr
    assert not workspace_root.exists()
