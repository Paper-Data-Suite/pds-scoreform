"""Issue #227: active Core 0.6.5 migration, with preserved release history."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from pip._vendor.packaging.specifiers import SpecifierSet

from scripts.verify_core_wheel import EXPECTED_VERSION
from scripts.verify_installed_release import CORE_VERSION_SPECIFIER
from scripts.verify_release_artifacts import EXPECTED_CORE_SPECIFIER
from scripts.verify_release_compatibility import (
    EXPECTED_CORE_SPECIFIER as COMPATIBILITY_CORE_SPECIFIER,
)

ROOT = Path(__file__).resolve().parents[1]
CORE_SHA = "9ace75f17b23b7f0ed6a709d531af5120db43d0325b4148d26f2d6ba1d4b3c18"


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_active_distribution_and_gates_require_core_065() -> None:
    project = tomllib.loads(_read("pyproject.toml"))["project"]
    assert "pds-core>=0.6.5,<0.7" in project["dependencies"]
    expected = SpecifierSet(">=0.6.5,<0.7")
    assert EXPECTED_CORE_SPECIFIER == expected
    assert COMPATIBILITY_CORE_SPECIFIER == expected
    assert CORE_VERSION_SPECIFIER == expected
    assert str(EXPECTED_VERSION) == "0.6.5"
    assert project["version"] == "0.12.1"  # no release yet


@pytest.mark.parametrize(
    "relative",
    [
        ".github/workflows/ci.yml",
        ".github/workflows/release-readiness.yml",
        "run_tests.ps1",
    ],
)
def test_active_release_qualification_authenticates_core_065(relative: str) -> None:
    source = _read(relative)
    assert "pds_core-0.6.5-py3-none-any.whl" in source
    assert CORE_SHA in source
    assert "pds_core-0.6.4-py3-none-any.whl" not in source


def test_source_tree_still_preserves_historical_release_evidence() -> None:
    assert "0.6.4" in _read("docs/v0.12.1_release_audit.md")
    assert "0.6.4" in _read("docs/release_checklist.md")
    assert "pds-core>=0.6.4,<0.7" in _read("CHANGELOG.md")
    assert "historical v0.12.1 release" in _read("README.md")


def test_migration_preserves_publication_contract_for_followup_slice() -> None:
    from scoreform.pds_contract import (
        ACADEMIC_RESULT_MANIFEST_CONTRACT_VERSION,
        SCOREFORM_ACADEMIC_RESULT_READER_CONTRACT_VERSION,
    )

    assert ACADEMIC_RESULT_MANIFEST_CONTRACT_VERSION == "scoreform_academic_result_manifest_v1"
    assert SCOREFORM_ACADEMIC_RESULT_READER_CONTRACT_VERSION == "scoreform_academic_result_reader_v1"
