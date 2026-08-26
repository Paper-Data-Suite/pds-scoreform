"""ScoreForm issue #194 launcher and Suite-ownership boundary tests."""

from __future__ import annotations

import tomllib
from pathlib import Path


def test_public_launcher_identity_is_stable_and_separate_from_operations() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]

    assert project["scripts"] == {"scoreform": "scoreform.cli:main"}
    assert project["entry-points"]["paper_data_suite.module_operations"] == {
        "scoreform": "scoreform.pds_operations:get_module_operations_profile"
    }


def test_operations_boundary_does_not_import_suite_launcher_or_probe_executables() -> None:
    operations = Path("scoreform/pds_operations.py").read_text(encoding="utf-8")
    readiness = Path("scoreform/readiness_provider.py").read_text(encoding="utf-8")
    combined = operations + readiness

    for forbidden in (
        "paper_data_suite.application_launching",
        "paper_data_suite.doctor",
        "shutil.which",
        "subprocess",
        "pdftoppm",
    ):
        assert forbidden not in combined


def test_installed_acceptance_verifies_console_script_and_safe_probes() -> None:
    verifier = Path("scripts/verify_installed_operations_acceptance.py").read_text(
        encoding="utf-8"
    )

    assert 'metadata.distribution("scoreform")' in verifier
    assert 'point.group == "console_scripts"' in verifier
    assert 'len(points) == 1 and points[0].name == "scoreform"' in verifier
    assert 'points[0].value == "scoreform.cli:main"' in verifier
    assert '"scoreform.exe" if os.name == "nt" else "scoreform"' in verifier
    assert '("--version",)' in verifier
    assert '("--help",)' in verifier
    assert 'environment.pop("PYTHONPATH", None)' in verifier
