"""Release/docs integration checks for ScoreForm issue #189."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_installed_sf_ac07_acceptance_is_wired_into_release_gates() -> None:
    script = ROOT / "scripts" / "verify_installed_guided_scan_to_results_acceptance.py"
    assert script.is_file()

    run_tests = _text("run_tests.ps1")
    workflow = _text(".github/workflows/release-readiness.yml")
    installer = _text("scripts/validate_release_install.ps1")
    name = "verify_installed_guided_scan_to_results_acceptance.py"

    assert name in run_tests
    assert name in workflow
    assert name in installer
    assert "RunGuidedScanToResultsAcceptance" in installer
    for module_name in (
        "scoreform.guided_scan_results",
        "scoreform.guided_scan_context",
        "scoreform.guided_scan_workflow",
    ):
        assert module_name in run_tests
        assert module_name in installer


def test_guided_scan_documentation_records_sf_ac07_boundaries() -> None:
    guide = _text("docs/guided_scan_to_results.md")
    readme = _text("README.md")
    contract = _text("docs/cli_contract.md")

    for required in (
        "SF-AC07",
        "source_scan_id",
        "already present",
        "official attempt",
        "direct `scoreform score",
        "#195",
    ):
        assert required.lower() in guide.lower()

    assert "guided_scan_to_results.md" in readme
    assert "Guided retained scan-to-results" in contract
    assert "source_scan_id" in contract
    assert "direct CLI" in contract


def test_guided_scan_release_slice_preserves_runtime_and_schema_boundaries() -> None:
    pyproject = _text("pyproject.toml")
    workflow = _text("scoreform/guided_scan_workflow.py")
    context = _text("scoreform/guided_scan_context.py")

    assert '"pds-core>=0.6.2,<0.7"' in pyproject
    assert "meridian" not in pyproject.lower()
    assert "meridian" not in workflow.lower()
    assert "meridian" not in context.lower()
    for forbidden in (
        "context.json",
        "guided_scan.json",
        "recent_scan.json",
    ):
        assert forbidden not in workflow
