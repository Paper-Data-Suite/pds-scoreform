"""ScoreForm issue #194 release-artifact guards for readiness code."""

from pathlib import Path


def test_release_artifact_verifier_requires_readiness_provider_in_wheel_and_sdist() -> None:
    source = Path("scripts/verify_release_artifacts.py").read_text(encoding="utf-8")

    assert '"scoreform/readiness_provider.py"' in source
    assert 'f"{root}/scoreform/readiness_provider.py"' in source
