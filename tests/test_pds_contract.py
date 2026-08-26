from __future__ import annotations

import importlib.metadata
import os
import subprocess
import sys
import tomllib
from pathlib import Path

from pds_core.module_profiles import CORE_ROUTING_CONTRACT_VERSION
from pds_core.routing_models import PDS2_SCHEMA, ROUTE_REGISTRATION_SCHEMA_VERSION

from scoreform.pds_contract import (
    ANSWER_SHEET_PAGE_CONTRACT_VERSION,
    ANSWER_SHEET_PAGE_RECORD_KIND,
    SCOREFORM_DISPLAY_NAME,
    SCOREFORM_MODULE_ID,
    SUPPORTED_CORE_ROUTING_CONTRACT_VERSIONS,
    SUPPORTED_QR_SCHEMAS,
    SUPPORTED_ROUTE_REGISTRATION_SCHEMA_VERSIONS,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _project_metadata() -> dict:
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)["project"]


def test_package_python_and_core_dependency_contract() -> None:
    project = _project_metadata()

    assert project["requires-python"] == ">=3.11"
    assert "pds-core>=0.6.2,<0.7" in project["dependencies"]

    version = importlib.metadata.version("pds-core")
    major, minor = (int(part) for part in version.split(".")[:2])
    assert (major, minor) == (0, 6)


def test_scoreform_pds_contract_uses_core_public_constants() -> None:
    assert SCOREFORM_MODULE_ID == "scoreform"
    assert SCOREFORM_DISPLAY_NAME == "ScoreForm"
    assert ANSWER_SHEET_PAGE_RECORD_KIND == "answer_sheet_page"
    assert ANSWER_SHEET_PAGE_CONTRACT_VERSION == "1"
    assert SUPPORTED_QR_SCHEMAS == frozenset({PDS2_SCHEMA}) == frozenset({"PDS2"})
    assert SUPPORTED_ROUTE_REGISTRATION_SCHEMA_VERSIONS == frozenset(
        {ROUTE_REGISTRATION_SCHEMA_VERSION}
    )
    assert SUPPORTED_CORE_ROUTING_CONTRACT_VERSIONS == frozenset(
        {CORE_ROUTING_CONTRACT_VERSION}
    )


def test_import_help_and_version_are_workspace_side_effect_free(tmp_path) -> None:
    workspace_root = tmp_path / "workspace-must-not-exist"
    env = os.environ.copy()
    env["PDS_WORKSPACE_ROOT"] = os.fspath(workspace_root)
    code = (
        "import scoreform; import scoreform.pds_contract; import scoreform.cli; "
        "assert scoreform.cli.main(['--help']) == 0; "
        "assert scoreform.cli.main(['--version']) == 0"
    )

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert not workspace_root.exists()


def test_active_code_does_not_import_removed_core_apis() -> None:
    forbidden = (
        "pds_core.pds1",
        "pds_core.qr_payload",
        "pds_core.assignments",
        "assignment_config_path",
        "assignment_debug_dir",
        "assignment_scans_dir",
        "assignment_templates_dir",
    )
    offenders = []
    for path in sorted((PROJECT_ROOT / "scoreform").glob("*.py")):
        source = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in source:
                offenders.append(f"{path.name}: {token}")

    assert offenders == []


def test_dependency_files_delegate_to_package_metadata() -> None:
    requirements = (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8")
    dev_requirements = (PROJECT_ROOT / "requirements-dev.txt").read_text(
        encoding="utf-8"
    )
    checker = (PROJECT_ROOT / "check_dependencies.ps1").read_text(encoding="utf-8")

    assert requirements.splitlines()[-1] == "."
    assert dev_requirements.splitlines()[-1] == "-e .[dev]"
    assert "../pds-core" not in dev_requirements
    assert "..\\pds-core" not in checker
    assert "-m pip check" in checker
    assert ">=0.6.2,<0.7" in checker
