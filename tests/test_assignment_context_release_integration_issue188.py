"""Release/docs integration checks for ScoreForm issue #188."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_installed_context_acceptance_is_wired_into_release_gates() -> None:
    script = ROOT / "scripts" / "verify_installed_recent_assignment_context_acceptance.py"
    assert script.is_file()

    run_tests = _text("run_tests.ps1")
    workflow = _text(".github/workflows/release-readiness.yml")
    installer = _text("scripts/validate_release_install.ps1")
    name = "verify_installed_recent_assignment_context_acceptance.py"

    assert name in run_tests
    assert name in workflow
    assert name in installer
    assert "RunRecentAssignmentContextAcceptance" in installer
    assert "scoreform.assignment_context" in run_tests
    assert "scoreform.menu_assignment_context" in run_tests


def test_context_documentation_records_session_privacy_and_cli_boundaries() -> None:
    readme = _text("README.md")
    help_text = _text("scoreform/cli_help.py")
    contract = _text("docs/cli_contract.md")

    for text in (readme, contract):
        assert "C. Assignment Context" in text
        assert "session" in text.lower()
        assert "five" in text.lower()
        assert "student" in text.lower()
        assert "direct CLI" in text

    assert "C. Assignment Context" in help_text
    assert "active assignment" in help_text.lower()
    assert "session" in help_text.lower()


def test_context_release_slice_preserves_dependency_and_runtime_boundaries() -> None:
    pyproject = _text("pyproject.toml")
    context = _text("scoreform/assignment_context.py")

    assert '"pds-core>=0.6.2,<0.7"' in pyproject
    assert "meridian" not in pyproject.lower()
    assert "meridian" not in context.lower()
    assert "context.json" not in context
    for write_primitive in (".write_text(", ".write_bytes(", "mkdir(", "json.dump"):
        assert write_primitive not in context
