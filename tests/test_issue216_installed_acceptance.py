"""Issue #216 final installed-qualification guards."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from scripts.run_issue216_wheel_acceptance import (
    CORE_VERSION,
    CORE_WHEEL_SHA256,
    Issue216WheelAcceptanceError,
    _environment_python,
    run_acceptance,
)

ROOT = Path(__file__).resolve().parents[1]


def test_environment_python_is_platform_specific(tmp_path: Path) -> None:
    path = _environment_python(tmp_path)
    if os.name == "nt":
        assert path == tmp_path / "Scripts" / "python.exe"
    else:
        assert path == tmp_path / "bin" / "python"


def test_issue216_runner_authenticates_exact_core_063() -> None:
    assert CORE_VERSION == "0.6.4"
    assert (
        CORE_WHEEL_SHA256
        == "48cea9317f2967bdc0f2d4c14349a56677c7c3f8211f0f33978ccb1a1c75859b"
    )


def test_installed_acceptance_covers_required_issue216_boundaries() -> None:
    source = (
        ROOT / "scripts" / "verify_installed_issue216_diagnostic_artifacts.py"
    ).read_text(encoding="utf-8")

    for required in (
        "MAX_DIAGNOSTIC_FILENAME_LENGTH",
        "write_png_diagnostic_artifact",
        "len(os.fspath(legacy_path)) > 260",
        "scoreform.scoring.write_png_diagnostic_artifact",
        "diagnostic_artifact_write_failed",
        "diagnostic_persistence",
        "diagnostic_images_unavailable",
        "registration_marks_missing",
        "discover_scan_review_items",
        "load_routed_results_history",
        "already_present_attempts",
        "legacy_preexisting_debug.png",
        "existing_authoritative_workspace_records",
    ):
        assert required in source


def test_installed_acceptance_does_not_depend_on_windows_registry_policy() -> None:
    source = (
        ROOT / "scripts" / "verify_installed_issue216_diagnostic_artifacts.py"
    ).read_text(encoding="utf-8")
    folded = source.casefold()

    assert "winreg" not in folded
    assert "longpathsenabled" not in folded
    assert "reg.exe" not in folded
    assert "set-itemproperty" not in folded


def test_runner_builds_and_installs_candidate_wheel_outside_checkout() -> None:
    source = (
        ROOT / "scripts" / "run_issue216_wheel_acceptance.py"
    ).read_text(encoding="utf-8")

    assert '"--wheel"' in source
    assert '"--sdist"' in source
    assert "verify_release_artifacts.py" in source
    assert "verify_installed_issue216_diagnostic_artifacts.py" in source
    assert "PYTHONNOUSERSITE" in source
    assert '"-e"' not in source
    assert "scoreform_wheel_sha256" in source
    assert '"physical_acceptance": "not_claimed"' in source


def test_ci_keeps_issue216_wheel_qualification_green_through_follow_on_work() -> None:
    source = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    assert "issue216-wheel-qualification:" in source
    assert "run_issue216_wheel_acceptance.py" in source
    assert "windows-latest" in source
    assert "ubuntu-latest" in source
    assert "--expected-core-version 0.6.4" in source


def test_harness_refuses_nonempty_work_directory(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    (work / "sentinel").write_text("keep", encoding="utf-8")
    core = tmp_path / "pds_core-0.6.4-py3-none-any.whl"
    core.write_bytes(b"synthetic")
    repository = tmp_path / "repo"
    repository.mkdir()

    with pytest.raises((Issue216WheelAcceptanceError, OSError)):
        run_acceptance(
            repository=repository,
            work=work,
            core_wheel=core,
            expected_core_version="0.6.4",
        )

    assert (work / "sentinel").read_text(encoding="utf-8") == "keep"


def test_physical_qualification_document_keeps_owner_adjudication_explicit() -> None:
    text = (
        ROOT / "docs" / "issue-216-installed-and-physical-qualification.md"
    ).read_text(encoding="utf-8")
    folded = text.casefold()

    assert "project owner" in folded
    assert "automation does not claim physical acceptance" in folded
    assert "do not change longpathsenabled" in folded
    assert "throwaway workspace" in folded
    assert "existing classroom workspace" in folded
    assert "0.12.0" in text
