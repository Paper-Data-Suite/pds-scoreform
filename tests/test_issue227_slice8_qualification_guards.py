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
