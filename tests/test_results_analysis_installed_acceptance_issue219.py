"""Issue #219 Slice 6: installed-wheel Results Analysis qualification guards."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from scripts.run_results_analysis_wheel_acceptance import (
    CORE_VERSION,
    CORE_WHEEL_SHA256,
    ResultsAnalysisWheelAcceptanceError,
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


def test_runner_authenticates_exact_released_core_065() -> None:
    assert CORE_VERSION == "0.6.5"
    assert CORE_WHEEL_SHA256 == "9ace75f17b23b7f0ed6a709d531af5120db43d0325b4148d26f2d6ba1d4b3c18"


def test_runner_builds_candidate_artifacts_and_uses_clean_install() -> None:
    source = (
        ROOT / "scripts" / "run_results_analysis_wheel_acceptance.py"
    ).read_text(encoding="utf-8")

    for required in (
        '"--wheel"',
        '"--sdist"',
        "verify_release_artifacts.py",
        "verify_installed_results_analysis_acceptance.py",
        "PYTHONNOUSERSITE",
        "scoreform_wheel_sha256",
    ):
        assert required in source
    assert '"-e"' not in source


def test_installed_verifier_covers_issue217_and_issue219_boundaries() -> None:
    source = (
        ROOT / "scripts" / "verify_installed_results_analysis_acceptance.py"
    ).read_text(encoding="utf-8")

    for required in (
        "ATTEMPT_DISPLAY_BASIS",
        "STANDARDS_ALIGNMENT_BASIS",
        "most recent alpha attempt",
        "BLANK",
        "AMBIGUOUS",
        "STD.UNKNOWN",
        "scoreform_results_analysis_v1",
        "standards_projection",
        "display_label",
        "render_results_report_csv",
        "render_results_report_json",
        "render_results_report_pdf",
        'f"class_analysis_{output_format}_20261002T080000Z"',
        "same-format/same-second",
        "format mismatch",
        "partial report directory survived cleanup",
        "open_generated_output_file",
        "open_generated_output_folder",
        "mocked_boundary_passed",
        "physical_acceptance",
    ):
        assert required in source


def test_harness_refuses_nonempty_work_directory(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    (work / "sentinel").write_text("keep", encoding="utf-8")
    core = tmp_path / "pds_core-0.6.4-py3-none-any.whl"
    core.write_bytes(b"synthetic")
    repository = tmp_path / "repo"
    repository.mkdir()

    with pytest.raises(
        (ResultsAnalysisWheelAcceptanceError, OSError),
    ):
        run_acceptance(
            repository=repository,
            work=work,
            core_wheel=core,
            expected_core_version="0.6.4",
        )

    assert (work / "sentinel").read_text(encoding="utf-8") == "keep"
