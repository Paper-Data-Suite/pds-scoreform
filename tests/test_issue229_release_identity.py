"""Issue #229: release identity stays separate from published v0.12.1 history."""

from __future__ import annotations

import tomllib
from pathlib import Path

import scripts.verify_release_compatibility as compatibility

ROOT = Path(__file__).resolve().parents[1]


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_active_v0130_distribution_and_release_defaults() -> None:
    project = tomllib.loads(_text("pyproject.toml"))["project"]
    assert project["version"] == "0.13.0"
    assert "pds-core>=0.6.5,<0.7" in project["dependencies"]
    assert compatibility.RELEASE_VERSION == "0.13.0"
    for path in (
        "run_tests.ps1",
        ".github/workflows/release-readiness.yml",
        "scripts/verify_installed_release.py",
        "scripts/verify_installed_producer_acceptance.py",
        "scripts/verify_release_artifacts.py",
        "scripts/validate_release_install.ps1",
    ):
        source = _text(path)
        assert "0.13.0" in source
        assert "0.12.1" not in source


def test_prepared_current_release_records_and_historical_evidence() -> None:
    assert "RELEASE_NOTES_v0.13.0.md" in _text("README.md")
    assert "v0.13.0_release_audit.md" in _text("README.md")
    assert "scoreform-0.13.0-py3-none-any.whl" in _text("README.md")
    assert "## [v0.13.0]" in _text("CHANGELOG.md")
    assert "physical_acceptance: not_claimed" in _text("docs/v0.13.0_release_audit.md")
    historical = (
        "RELEASE_NOTES_v0.12.1.md",
        "docs/v0.12.1_release_audit.md",
        "docs/release_checklist.md",
    )
    for path in historical:
        assert "0.12.1" in _text(path)
        assert "0.13.0" not in _text(path)
    assert compatibility.HISTORICAL_V0121_RELEASE_VERSION == "0.12.1"
    compatibility.validate_release_identity()


def test_no_second_full_run_or_rebuild_is_required_by_229_checklist() -> None:
    release = _text("docs/v0.13.0_release_checklist.md")
    assert "tree-identical squash merge" in release
    assert "Build final artifacts" not in release  # wording is build once
    assert "rebuild qualified wheel/sdist" in release
