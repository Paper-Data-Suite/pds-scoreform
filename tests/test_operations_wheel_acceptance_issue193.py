"""Release/installed-qualification guards for ScoreForm issue #193."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from scripts.run_operations_wheel_acceptance import (
    CORE_WHEEL_SHA256,
    OperationsWheelAcceptanceError,
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


def test_operations_harness_authenticates_minimum_and_current_core() -> None:
    assert CORE_WHEEL_SHA256 == {
        "0.6.2": "b9d5de7d467d18716f415da87f359e940603d9c738a3a9ae9309272ebe78a848",
        "0.6.3": "98d7596ce0eed26e4d56a17bbbbd644db3014259b56a45783a173fe8237af5e5",
    }

    source = (ROOT / "scripts" / "run_operations_wheel_acceptance.py").read_text(
        encoding="utf-8"
    )
    assert 'choices=("0.6.2", "0.6.3")' in source
    assert "verify_release_artifacts.py" in source
    assert "verify_installed_operations_acceptance.py" in source
    assert "--minimum-floor-only" in source
    assert '"-e"' not in source


def test_installed_acceptance_requires_exact_operations_contract() -> None:
    source = (
        ROOT / "scripts" / "verify_installed_operations_acceptance.py"
    ).read_text(encoding="utf-8")
    assert "paper_data_suite.module_operations" not in source or (
        "MODULE_OPERATIONS_ENTRY_POINT_GROUP" in source
    )
    assert "scoreform.pds_operations:get_module_operations_profile" in source
    assert 'SpecifierSet(">=0.6.2,<0.7")' in source
    assert "profile.readiness_provider is None" in source
    assert "module_operations.evaluation_unavailable" in source
    assert "scoreform_incomplete_attempt" in source
    assert "scoreform_scan_review" in source
    assert "scoreform_results_registration_pending" in source
    assert "scoreform_results_manifest_pending" in source
    assert "scoreform_results_publication_pending" in source
    assert "changing only diagnostic history changed authoritative attention" in source


def test_ci_qualifies_operations_wheel_on_both_platforms_and_core_endpoints() -> None:
    source = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    assert "operations-wheel-qualification:" in source
    assert "windows-latest" in source
    assert "ubuntu-latest" in source
    assert 'core: ["0.6.2", "0.6.3"]' in source
    assert "run_operations_wheel_acceptance.py" in source


def test_release_readiness_runs_current_installed_operations_acceptance() -> None:
    source = (
        ROOT / ".github" / "workflows" / "release-readiness.yml"
    ).read_text(encoding="utf-8")
    assert "verify_installed_operations_acceptance.py" in source
    assert "--expected-core-version 0.6.3" in source


def test_active_docs_and_share_results_acceptance_use_new_core_floor() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    ci_doc = (ROOT / "docs" / "continuous_integration.md").read_text(
        encoding="utf-8"
    )
    share_acceptance = (
        ROOT / "scripts" / "verify_installed_share_results_with_meridian_acceptance.py"
    ).read_text(encoding="utf-8")

    assert "pds-core>=0.6.2,<0.7" in readme
    assert "pds-core>=0.6,<0.7" not in readme
    assert "pds-core>=0.6.2,<0.7" in ci_doc
    assert "pds-core>=0.6,<0.7" not in ci_doc
    assert 'SpecifierSet(">=0.6.2,<0.7")' in share_acceptance
    assert "must remain pds-core>=0.6.2,<0.7" in share_acceptance


def test_harness_refuses_nonempty_work_directory(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    (work / "sentinel").write_text("keep", encoding="utf-8")
    core = tmp_path / "pds_core-0.6.2-py3-none-any.whl"
    core.write_bytes(b"synthetic")
    repository = tmp_path / "repo"
    repository.mkdir()

    with pytest.raises(
        (OperationsWheelAcceptanceError, OSError),
    ):
        run_acceptance(
            repository=repository,
            work=work,
            core_wheel=core,
            expected_core_version="0.6.2",
        )

    assert (work / "sentinel").read_text(encoding="utf-8") == "keep"
