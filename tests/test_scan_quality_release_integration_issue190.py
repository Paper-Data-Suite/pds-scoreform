"""Release-readiness integration coverage for ScoreForm issue #190."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_sf_ac08_installed_verifier_is_wired_into_all_release_gates() -> None:
    verifier = "verify_installed_scan_quality_diagnostics_acceptance.py"

    run_tests = _text("run_tests.ps1")
    workflow = _text(".github/workflows/release-readiness.yml")
    validate = _text("scripts/validate_release_install.ps1")

    assert verifier in run_tests
    assert verifier in workflow
    assert verifier in validate
    assert "RunScanQualityDiagnosticsAcceptance" in validate
    assert "scoreform.scan_teacher_diagnostics" in run_tests
    assert "scoreform.scan_teacher_diagnostics" in validate


def test_sf_ac08_documentation_records_boundaries_and_physical_gate() -> None:
    guide = _text("docs/teacher_scan_quality_recovery.md")
    acceptance = _text("docs/v0.11.0_usability_acceptance_cases.md")
    readme = _text("README.md")
    cli_contract = _text("docs/cli_contract.md")

    for expected in (
        "SF-AC08",
        "Problem",
        "Evidence",
        "Recommended next step",
        "T. Technical details",
        "source_scan_id",
        "#192",
        "#195",
    ):
        assert expected in guide

    normalized_acceptance = " ".join(acceptance.split())
    assert "Implemented by #190" in acceptance
    assert "installed-wheel" in acceptance
    assert "physical confirmation remains open for #195" in normalized_acceptance
    assert "teacher_scan_quality_recovery.md" in readme
    assert "teacher_scan_quality_recovery.md" in cli_contract


def test_issue190_preserves_compatibility_and_authority_boundaries() -> None:
    pyproject = _text("pyproject.toml")
    diagnostics = _text("scoreform/scan_teacher_diagnostics.py")
    menu = _text("scoreform/menu_scan_review.py")

    assert 'pds-core>=0.6.2,<0.7' in pyproject
    assert "meridian" not in diagnostics.casefold()
    assert "meridian" not in menu.casefold()
    assert "teacher_diagnostics.json" not in diagnostics
    assert "scan_quality.json" not in diagnostics
