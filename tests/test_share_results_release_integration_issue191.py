"""Release/docs integration for ScoreForm issue #191."""

from __future__ import annotations

import tomllib
from pathlib import Path

from pip._vendor.packaging.requirements import Requirement
from pip._vendor.packaging.utils import canonicalize_name

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (PROJECT_ROOT / relative).read_text(encoding="utf-8")


def test_package_contract_stays_core_06_range_without_meridian_dependency() -> None:
    pyproject_path = PROJECT_ROOT / "pyproject.toml"
    pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    project = pyproject["project"]
    requirements = [Requirement(item) for item in project["dependencies"]]
    names = {canonicalize_name(item.name) for item in requirements}

    assert "pds-core" in names
    core = next(
        item
        for item in requirements
        if canonicalize_name(item.name) == "pds-core"
    )
    assert str(core.specifier) in {">=0.6.4,<0.7", "<0.7,>=0.6.4"}
    assert "pds-meridian" not in names
    assert "meridian" not in names
    assert project["version"] == "0.12.0"


def test_current_docs_describe_guided_core_mediated_sharing() -> None:
    readme = _read("README.md")
    cli_help = _read("scoreform/cli_help.py")
    cli_contract = _read("docs/cli_contract.md")
    guide = _read("docs/share_results_with_meridian.md")

    for text in (readme, cli_help, cli_contract, guide):
        assert "Share Results with Meridian" in text
        assert "available for Meridian to consume" in text
    assert "pds-core>=0.6.4,<0.7" in guide
    assert "pds-core 0.6.4" in guide
    assert "does not mean that Meridian has already imported" in guide
    assert "does **not** import" in guide


def test_installed_sf_ac10_ac11_is_wired_into_all_release_paths() -> None:
    script = "scripts/verify_installed_share_results_with_meridian_acceptance.py"
    run_tests = _read("run_tests.ps1")
    workflow = _read(".github/workflows/release-readiness.yml")
    validate = _read("scripts/validate_release_install.ps1")

    assert script.replace("/", "\\") in run_tests
    assert script in workflow
    assert "RunShareResultsWithMeridianAcceptance" in validate
    assert "verify_installed_share_results_with_meridian_acceptance.py" in validate


def test_release_reference_is_exact_core_064_but_not_dependency_pin() -> None:
    verifier = _read("scripts/verify_core_wheel.py")
    workflow = _read(".github/workflows/release-readiness.yml")
    validate = _read("scripts/validate_release_install.ps1")
    run_tests = _read("run_tests.ps1")

    assert 'EXPECTED_VERSION = Version("0.6.4")' in verifier
    assert "v0.6.4" in workflow
    assert "pds_core-0.6.4-py3-none-any.whl" in workflow
    assert "48cea9317f2967bdc0f2d4c14349a56677c7c3f8211f0f33978ccb1a1c75859b" in workflow
    assert 'ExpectedCoreVersion = "0.6.4"' in validate
    assert "pds-core 0.6.4" in run_tests
    assert "pds-core==0.6.4" not in _read("pyproject.toml")


def test_guided_production_code_has_no_meridian_import_or_projection_call() -> None:
    production = "\n".join(
        (
            _read("scoreform/guided_share_results.py"),
            _read("scoreform/menu_share_results.py"),
            _read("scoreform/menu_assignment_tasks.py"),
        )
    ).lower()

    assert "import meridian" not in production
    assert "from meridian" not in production
    assert "import pds_meridian" not in production
    assert "subprocess" not in _read("scoreform/menu_share_results.py")
    assert "meridian_ingested" not in production
