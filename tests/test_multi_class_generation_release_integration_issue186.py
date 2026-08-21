"""Release/docs integration checks for ScoreForm issue #186."""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (PROJECT_ROOT / relative).read_text(encoding="utf-8")


def test_release_paths_include_installed_multi_class_acceptance() -> None:
    script = "scripts/verify_installed_multi_class_generation_acceptance.py"
    run_tests = _read("run_tests.ps1")
    workflow = _read(".github/workflows/release-readiness.yml")
    validate_install = _read("scripts/validate_release_install.ps1")

    assert script.replace("/", "\\") in run_tests
    assert script in workflow
    assert "--expected-core-version 0.6.0" in workflow
    assert "RunMultiClassGenerationAcceptance" in validate_install
    assert "verify_installed_multi_class_generation_acceptance.py" in validate_install


def test_multi_class_generation_contract_is_documented_and_linked() -> None:
    contract = _read("docs/multi_class_generation.md")
    cli_contract = _read("docs/cli_contract.md")
    readme = _read("README.md")

    for expected in (
        "SF-AC05",
        "read-only readiness planning",
        "scoreform generate-batch",
        "CLEAN SUCCESS",
        "PARTIAL — DURABLE OUTPUT EXISTS",
        "NOT ATTEMPTED",
        "artifact_id",
        "issuance_id",
        "page_id",
        "route_id",
        "scripts/verify_installed_multi_class_generation_acceptance.py",
        "Meridian owns attempt-selection",
    ):
        assert expected in contract

    assert "multi_class_generation.md" in cli_contract
    assert "scoreform generate-batch" in cli_contract
    assert "scoreform generate-batch" in readme
    assert "docs/multi_class_generation.md" in readme


def test_installed_acceptance_script_has_required_sf_ac05_guards() -> None:
    script = _read("scripts/verify_installed_multi_class_generation_acceptance.py")

    for expected in (
        'metadata.version("pds-core")',
        '"scoreform.multi_class_generation"',
        '"scoreform.cli_multi_class_generation"',
        '"copy-assignment"',
        '"generate-batch"',
        '"--target"',
        '"--apply"',
        "blocked --apply batch partially generated a ready target",
        "plan-only multi-class generation changed managed work state",
        "load_route_registration",
        "load_answer_sheet_page",
        "identity was reused across selected targets",
        "list_academic_work_registration_revisions",
        "list_publication_records",
    ):
        assert expected in script
