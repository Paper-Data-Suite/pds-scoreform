"""Issue #219 Slice 7: ScoreForm v0.12.0 release-preparation guards."""

from __future__ import annotations

import tomllib
from pathlib import Path

import scripts.verify_release_compatibility as compatibility
from scripts.run_results_analysis_wheel_acceptance import (
    CORE_VERSION as RESULTS_CORE_VERSION,
)
from scripts.run_results_analysis_wheel_acceptance import (
    CORE_WHEEL_SHA256 as RESULTS_CORE_HASH,
)
from scripts.run_v012_combined_wheel_acceptance import (
    CORE_VERSION as COMBINED_CORE_VERSION,
)
from scripts.run_v012_combined_wheel_acceptance import (
    CORE_WHEEL_SHA256 as COMBINED_CORE_HASH,
)

ROOT = Path(__file__).resolve().parents[1]
CORE_HASH = "48cea9317f2967bdc0f2d4c14349a56677c7c3f8211f0f33978ccb1a1c75859b"


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_active_distribution_identity_is_v012() -> None:
    project = tomllib.loads(_text("pyproject.toml"))["project"]
    assert project["version"] == "0.12.0"
    assert "pds-core>=0.6.4,<0.7" in project["dependencies"]
    assert compatibility.RELEASE_VERSION == "0.12.0"


def test_generic_release_defaults_are_v012() -> None:
    for relative in (
        "scripts/validate_release_install.ps1",
        "scripts/verify_installed_release.py",
        "scripts/verify_installed_producer_acceptance.py",
        "scripts/verify_release_artifacts.py",
    ):
        text = _text(relative)
        assert "0.12.0" in text
        assert 'default="0.11.0"' not in text
        assert '$Version = "0.11.0"' not in text


def test_current_release_files_and_historical_v011_evidence_are_distinct() -> None:
    for relative in (
        "RELEASE_NOTES_v0.12.0.md",
        "docs/v0.12.0_release_audit.md",
        "docs/release_checklist.md",
    ):
        assert "0.12.0" in _text(relative)

    assert "0.11.0" in _text("RELEASE_NOTES_v0.11.0.md")
    assert "0.11.0" in _text("docs/v0.11.0_release_audit.md")
    assert "RELEASE_NOTES_v0.11.0.md" in _text("README.md")


def test_v012_combined_and_results_harnesses_use_exact_core_064() -> None:
    assert COMBINED_CORE_VERSION == RESULTS_CORE_VERSION == "0.6.4"
    assert COMBINED_CORE_HASH == RESULTS_CORE_HASH == CORE_HASH

    runner = _text("scripts/run_v012_combined_wheel_acceptance.py")
    verifier = _text("scripts/verify_installed_v012_combined_acceptance.py")
    assert "run_v011_combined" not in runner
    assert "verify_installed_v011" not in runner
    assert "v0.12" in runner
    assert "v0.12" in verifier


def test_active_ci_and_local_gate_use_v012_and_results_acceptance() -> None:
    ci = _text(".github/workflows/ci.yml")
    release = _text(".github/workflows/release-readiness.yml")
    local = _text("run_tests.ps1")

    assert "combined-v012-wheel-qualification" in ci
    assert "run_v012_combined_wheel_acceptance.py" in ci
    assert "results-analysis-wheel-qualification" in ci
    assert "run_results_analysis_wheel_acceptance.py" in ci

    assert "run_v012_combined_wheel_acceptance.py" in release
    assert "run_results_analysis_wheel_acceptance.py" in release

    assert "Validate combined installed v0.12 workflow" in local
    assert "run_v012_combined_wheel_acceptance.py" in local
    assert "Validate installed Results Analysis workflow" in local
    assert "run_results_analysis_wheel_acceptance.py" in local
    assert "ScoreForm 0.12.0" in local


def test_readme_names_current_and_historical_release_records() -> None:
    readme = _text("README.md")
    assert "Current version: `0.12.0`." in readme
    assert "scoreform-0.12.0-py3-none-any.whl" in readme
    assert "RELEASE_NOTES_v0.12.0.md" in readme
    assert "v0.12.0_release_audit.md" in readme
    assert "## v0.11.0 release records" in readme


def test_changelog_opens_v012_release_and_new_unreleased_bucket() -> None:
    changelog = _text("CHANGELOG.md")
    assert "## [Unreleased]" in changelog
    assert "## [v0.12.0] - 2026-10-02" in changelog
    assert "Results Analysis" in changelog
    assert "pds-core>=0.6.4,<0.7" in changelog


def test_physical_boundary_is_not_automatically_carried_forward() -> None:
    checklist = _text("docs/release_checklist.md")
    audit = _text("docs/v0.12.0_release_audit.md")
    for text in (checklist, audit):
        assert "physical_acceptance: not_claimed" in text
        assert "v0.11" in text
    assert "must **not** be used" in checklist

def test_local_gate_bootstraps_released_core_before_editable_install() -> None:
    local = _text("run_tests.ps1")

    bootstrap_install = local.index(
        "Install authenticated released pds-core 0.6.4 into release environment"
    )
    editable_install = local.index(
        "Install ScoreForm editable with development extras"
    )
    later_core_gate = local.index(
        "$CoreWheelWasSet = Test-Path Env:PDS_CORE_WHEEL"
    )

    assert bootstrap_install < editable_install < later_core_gate
    assert "scoreform-bootstrap-core-wheel-" in local
    assert "pds_core-0.6.4-py3-none-any.whl" in local[:editable_install]
    assert CORE_HASH in local[:editable_install]
    assert (
        "& $Python -m pip install --quiet $BootstrapResolvedCoreWheel"
        in local[:editable_install]
    )
    assert "--no-deps" not in local[:editable_install]

def test_release_compatibility_summary_names_preserved_v010_v011_history() -> None:
    source = _text("scripts/verify_release_compatibility.py")

    assert "historical v0.10.0/v0.11.0 " in source
    assert "historical v0.10.0 " not in source
