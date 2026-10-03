"""Issue #219 Slice 5: Core v0.6.4 active compatibility migration."""

from __future__ import annotations

import tomllib
from pathlib import Path

from pip._vendor.packaging.requirements import Requirement
from pip._vendor.packaging.specifiers import SpecifierSet
from pip._vendor.packaging.utils import canonicalize_name

from scripts.run_issue216_wheel_acceptance import (
    CORE_VERSION as ISSUE216_CORE_VERSION,
)
from scripts.run_issue216_wheel_acceptance import (
    CORE_WHEEL_SHA256 as ISSUE216_CORE_HASH,
)
from scripts.run_operations_wheel_acceptance import (
    CORE_WHEEL_SHA256 as OPERATIONS_CORE_HASHES,
)
from scripts.run_v011_combined_wheel_acceptance import (
    CORE_VERSION as COMBINED_CORE_VERSION,
)
from scripts.run_v011_combined_wheel_acceptance import (
    CORE_WHEEL_SHA256 as COMBINED_CORE_HASH,
)
from scripts.verify_core_wheel import EXPECTED_VERSION
from scripts.verify_installed_release import CORE_VERSION_SPECIFIER
from scripts.verify_release_compatibility import EXPECTED_CORE_SPECIFIER

ROOT = Path(__file__).resolve().parents[1]
CORE_HASH = "48cea9317f2967bdc0f2d4c14349a56677c7c3f8211f0f33978ccb1a1c75859b"


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_active_package_floor_is_exact_core_064() -> None:
    project = tomllib.loads(_text("pyproject.toml"))["project"]
    requirements = tuple(Requirement(item) for item in project["dependencies"])
    core = tuple(
        requirement
        for requirement in requirements
        if canonicalize_name(requirement.name) == "pds-core"
    )

    assert len(core) == 1
    assert core[0].specifier == SpecifierSet(">=0.6.4,<0.7")
    assert EXPECTED_CORE_SPECIFIER == SpecifierSet(">=0.6.4,<0.7")
    assert CORE_VERSION_SPECIFIER == SpecifierSet(">=0.6.4,<0.7")


def test_active_harnesses_authenticate_exact_released_core_064() -> None:
    assert str(EXPECTED_VERSION) == "0.6.4"
    assert ISSUE216_CORE_VERSION == "0.6.4"
    assert ISSUE216_CORE_HASH == CORE_HASH
    assert COMBINED_CORE_VERSION == "0.6.4"
    assert COMBINED_CORE_HASH == CORE_HASH
    assert OPERATIONS_CORE_HASHES == {"0.6.4": CORE_HASH}


def test_ci_and_release_readiness_use_only_core_064() -> None:
    for relative in (
        ".github/workflows/ci.yml",
        ".github/workflows/release-readiness.yml",
    ):
        text = _text(relative)
        assert "0.6.2" not in text
        assert "0.6.3" not in text
        assert "pds_core-0.6.4-py3-none-any.whl" in text
        assert CORE_HASH in text

    assert 'core: ["0.6.4"]' in _text(".github/workflows/ci.yml")


def test_local_release_gate_uses_published_core_wheel() -> None:
    source = _text("run_tests.ps1")

    assert (
        '"https://github.com/Paper-Data-Suite/pds-core/releases/download/" +'
        in source
    )
    assert '"v0.6.4/pds_core-0.6.4-py3-none-any.whl"' in source
    assert CORE_HASH in source
    assert "archive --format=zip" not in source
    assert "Build separate pds-core" not in source
    assert "pds-core-v0.6.3.zip" not in source


def test_active_compatibility_surfaces_have_no_pre_064_markers() -> None:
    active = (
        "pyproject.toml",
        "check_dependencies.ps1",
        "run_tests.ps1",
        ".github/workflows/ci.yml",
        ".github/workflows/release-readiness.yml",
        "scripts/validate_release_install.ps1",
        "scripts/verify_core_wheel.py",
        "scripts/verify_installed_release.py",
        "scripts/verify_installed_operations_acceptance.py",
        "scripts/verify_installed_share_results_with_meridian_acceptance.py",
        "scripts/verify_installed_v011_combined_acceptance.py",
        "scripts/verify_release_artifacts.py",
        "scripts/verify_release_compatibility.py",
        "scripts/run_issue216_wheel_acceptance.py",
        "scripts/run_operations_wheel_acceptance.py",
        "scripts/run_v011_combined_wheel_acceptance.py",
        "README.md",
        "docs/continuous_integration.md",
        "docs/share_results_with_meridian.md",
    )
    forbidden = (
        ">=0.6.2,<0.7",
        "Core 0.6.3",
        "core 0.6.3",
        "pds_core-0.6.3",
        "v0.6.3",
    )
    for relative in active:
        text = _text(relative)
        for marker in forbidden:
            assert marker not in text, (relative, marker)


def test_historical_v011_release_audit_is_not_rewritten() -> None:
    assert "0.6.3" in _text("docs/v0.11.0_release_audit.md")

def test_core_wheel_version_regex_matches_active_core_064() -> None:
    source = _text("scripts/verify_core_wheel.py")

    assert r"0\.6\.4" in source
    assert r"0\.6\.3" not in source

def test_issue193_project_floor_test_tracks_active_core_064() -> None:
    source = _text("tests/test_pds_operations_issue193.py")

    assert '"pds-core>=0.6.4,<0.7"' in source
    assert '"pds-core>=0.6.2,<0.7"' not in source

def test_active_release_contract_tests_track_core064() -> None:
    forbidden = ('pds-core>=0.6.2,<0.7', '--expected-core-version 0.6.3', 'pds_core-0.6.3-py3-none-any.whl', 'v0.6.3/pds_core-0.6.3')
    for relative in ('tests/test_assignment_bulk_release_integration_issue185.py', 'tests/test_assignment_context_release_integration_issue188.py', 'tests/test_cross_platform_ci_issue202.py', 'tests/test_multi_class_generation_release_integration_issue186.py', 'tests/test_pds_contract.py', 'tests/test_scan_quality_release_integration_issue190.py', 'tests/test_share_results_release_integration_issue191.py'):
        source = _text(relative)
        for marker in forbidden:
            assert marker not in source, (relative, marker)
