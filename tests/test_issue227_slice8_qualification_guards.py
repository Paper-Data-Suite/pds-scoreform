"""Issue #227 Slice 8: ensure candidate installed gates are cross-platform and truthfully scoped."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE_SHA = "9ace75f17b23b7f0ed6a709d531af5120db43d0325b4148d26f2d6ba1d4b3c18"


def _text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_issue227_reader_wheel_ci_is_cross_platform_and_authenticated() -> None:
    ci = _text(".github/workflows/ci.yml")
    assert ci.count("  issue227-reader-wheel-qualification:\n") == 1
    job = ci.split("  issue227-reader-wheel-qualification:\n", 1)[1]
    assert "os: [windows-latest, ubuntu-latest]" in job
    assert 'python-version: "3.11"' in job
    assert CORE_SHA in job
    assert "pds_core-0.6.5-py3-none-any.whl" in job
    assert "run_issue227_reader_contract_wheel_acceptance.py" in job
    assert '--repository .' in job
    assert '--work "${{ runner.temp }}/scoreform-issue227-reader-wheel"' in job
    assert '--core-wheel "${{ runner.temp }}/pds_core-0.6.5-py3-none-any.whl"' in job
    assert "--expected-core-version 0.6.4" not in job
    # Ordinary matrix, release readiness and the new installed gate remain distinct.
    assert 'matrix.python' in ci
    assert 'python-version: "3.14"' in ci or '"3.14"' in ci
    release = _text(".github/workflows/release-readiness.yml")
    assert "verify_installed_issue227_reader_contract.py" in release
    assert "--core-version 0.6.5" in release


def test_candidate_evidence_is_not_misreported_as_an_existing_release() -> None:
    docs = _text("docs/issue-227-slice8-final-qualification.md")
    assert "82824a0" in docs
    assert "2,451 passed, 16 skipped" in docs
    assert "9fa5d910f574dd29f024c6d5f08bbaa774078d0cbf4e9503a9c8d9cd27252624" in docs
    assert CORE_SHA in docs
    assert "**not** evidence for the later" in docs
    assert "physical_acceptance: not_claimed" in docs
    assert "Meridian #111" in docs and "Vitrine #103" in docs
    assert "separate release decisions" in docs
    assert "[ ] Pull request CI green" in docs
    release = _text("docs/release_checklist.md")
    assert "# ScoreForm v0.12.1 release checklist" in release
    assert "pds-core>=0.6.4,<0.7" in release


def test_installed_reader_runner_and_ci_docs_remain_isolated() -> None:
    runner = _text("scripts/run_issue227_reader_contract_wheel_acceptance.py")
    assert "verify_released_core_wheel(core_wheel)" in runner
    assert '"noneditable-wheel-outside-source"' in runner
    assert "workspace-must-remain-absent" in runner
    guide = _text("docs/continuous_integration.md")
    assert "issue227-reader-wheel-qualification" in guide
    assert "Windows and Ubuntu" in guide
    assert "noneditably" in guide
    assert "physical printer/scanner acceptance" in guide


def test_issue227_combined_wheel_verifier_matches_core065_runner() -> None:
    """The active v0.12 gate must not retain a Core 0.6.4 release assertion."""
    verifier = _text("scripts/verify_installed_v012_combined_acceptance.py")
    runner = _text("scripts/run_v012_combined_wheel_acceptance.py")
    ci = _text(".github/workflows/ci.yml")
    readiness = _text(".github/workflows/release-readiness.yml")
    assert 'CORE_VERSION = "0.6.5"' in runner
    assert 'expected_core_version == "0.6.5"' in verifier
    assert 'SpecifierSet(">=0.6.5,<0.7")' in verifier
    assert 'expected_core_version == "0.6.4"' not in verifier
    assert 'SpecifierSet(">=0.6.4,<0.7")' not in verifier
    assert "combined-v012-wheel-qualification:" in ci
    assert "--expected-core-version 0.6.5" in ci
    assert "Verify combined installed v0.12 workflow" in readiness
    assert "--expected-core-version 0.6.5" in readiness

    # The pre-0.12.1 historical v0.11 qualification remains undisturbed.
    historical = _text("scripts/verify_installed_v011_combined_acceptance.py")
    assert 'expected_core_version == "0.6.4"' in historical
    assert 'SpecifierSet(">=0.6.4,<0.7")' in historical
    assert "# ScoreForm v0.12.1 release checklist" in _text("docs/release_checklist.md")


def test_historical_v011_combined_runner_matches_core064_verifier() -> None:
    """Do not silently migrate the historical v0.11 qualification to Core 0.6.5."""
    historical_runner = _text("scripts/run_v011_combined_wheel_acceptance.py")
    historical_verifier = _text("scripts/verify_installed_v011_combined_acceptance.py")
    active_runner = _text("scripts/run_v012_combined_wheel_acceptance.py")
    active_verifier = _text("scripts/verify_installed_v012_combined_acceptance.py")
    assert 'CORE_VERSION = "0.6.4"' in historical_runner
    assert "48cea9317f2967bdc0f2d4c14349a56677c7c3f8211f0f33978ccb1a1c75859b" in historical_runner
    assert 'expected_core_version == "0.6.4"' in historical_verifier
    assert 'SpecifierSet(">=0.6.4,<0.7")' in historical_verifier
    assert 'CORE_VERSION = "0.6.5"' in active_runner
    assert CORE_SHA in active_runner
    assert 'expected_core_version == "0.6.5"' in active_verifier
    assert 'SpecifierSet(">=0.6.5,<0.7")' in active_verifier
