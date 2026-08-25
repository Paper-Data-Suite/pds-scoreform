"""Release/docs integration checks for ScoreForm issue #185."""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (PROJECT_ROOT / relative).read_text(encoding="utf-8")


def test_release_paths_include_installed_bulk_entry_acceptance() -> None:
    script = "scripts/verify_installed_assignment_bulk_entry_acceptance.py"
    run_tests = _read("run_tests.ps1")
    workflow = _read(".github/workflows/release-readiness.yml")
    validate_install = _read("scripts/validate_release_install.ps1")

    assert script.replace("/", "\\") in run_tests
    assert script in workflow
    assert "--expected-core-version 0.6.3" in workflow
    assert "RunBulkEntryAcceptance" in validate_install
    assert "verify_installed_assignment_bulk_entry_acceptance.py" in validate_install


def test_bulk_entry_contract_is_documented_and_linked() -> None:
    contract = _read("docs/assignment_bulk_entry.md")
    cli_contract = _read("docs/cli_contract.md")
    preset_contract = _read("docs/assignment_setup_presets.md")
    readme = _read("README.md")

    for expected in (
        "fast input",
        "complete normalization",
        "complete validation",
        "complete preview",
        "explicit commit",
        "scoreform bulk-edit-assignment",
        "scripts/verify_installed_assignment_bulk_entry_acceptance.py",
        "Meridian owns attempt-selection",
    ):
        assert expected in contract

    assert "assignment_bulk_entry.md" in cli_contract
    assert "scoreform bulk-edit-assignment" in cli_contract
    assert "Issue #185 extends" in preset_contract
    assert "assignment_bulk_entry.md" in preset_contract
    assert "scoreform bulk-edit-assignment" in readme
    assert "docs/assignment_bulk_entry.md" in readme


def test_installed_acceptance_script_has_required_sf_ac04_guards() -> None:
    script = _read("scripts/verify_installed_assignment_bulk_entry_acceptance.py")

    for expected in (
        'metadata.version("pds-core")',
        '"scoreform.assignment_bulk_entry"',
        '"scoreform.assignment_bulk_mutation"',
        '"scoreform.cli_assignment_bulk"',
        '"--answer-key-csv"',
        '"--alignment-json"',
        '"--standards-profile-id"',
        '"--apply"',
        "list_academic_work_registration_revisions",
        "list_publication_records",
        "invalid combined bulk edit",
        "plan-only bulk edit changed assignment bytes",
        "bulk apply changed key input",
        "bulk apply changed alignment input",
    ):
        assert expected in script
