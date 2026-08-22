"""Release/docs integration checks for ScoreForm issue #187."""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (PROJECT_ROOT / relative).read_text(encoding="utf-8")


def test_assignment_workflow_entry_routes_to_task_oriented_menu() -> None:
    source = _read("scoreform/assignment_workflows.py")

    assert "from scoreform.menu_assignment_tasks import" in source
    assert "launch_task_oriented_assignment_menu" in source
    assert 'print("14. Assessment setup presets")' not in source


def test_release_paths_include_installed_sf_ac01_acceptance() -> None:
    script = "scripts/verify_installed_task_oriented_assignment_menu_acceptance.py"
    run_tests = _read("run_tests.ps1")
    workflow = _read(".github/workflows/release-readiness.yml")
    validate_install = _read("scripts/validate_release_install.ps1")

    assert script.replace("/", "\\") in run_tests
    assert script in workflow
    assert "RunTaskOrientedAssignmentMenuAcceptance" in validate_install
    assert "verify_installed_task_oriented_assignment_menu_acceptance.py" in validate_install


def test_installed_acceptance_script_guards_sf_ac01_contract() -> None:
    script = _read("scripts/verify_installed_task_oriented_assignment_menu_acceptance.py")

    for expected in (
        'metadata.version("pds-core")',
        '"scoreform.menu_assignment_tasks"',
        '"1. Create / Copy / Edit Assessments"',
        '"7. Advanced Tools"',
        '"14. Assessment setup presets"',
        '"_run_create_assignment"',
        '"_run_decode_qr_file"',
        "ReturnToMainMenu",
        "QuitPDS",
        "menu acceptance created workspace/domain state",
    ):
        assert expected in script


def test_current_docs_describe_task_oriented_assignment_management() -> None:
    readme = _read("README.md")
    cli_help = _read("scoreform/cli_help.py")
    cli_contract = _read("docs/cli_contract.md")

    for expected in (
        "Create / Copy / Edit Assessments",
        "Print Answer Sheets",
        "Process Scans",
        "Review Results",
        "Enter Plain-Paper Results",
        "Share Results",
        "Advanced Tools",
    ):
        assert expected in readme
        assert expected in cli_help
        assert expected in cli_contract

    assert "does not automatically send results to Meridian" in cli_help
    assert "direct CLI commands remain available" in cli_contract
