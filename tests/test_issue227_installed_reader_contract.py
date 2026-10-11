"""Issue #227 Slice 4: isolated release-wheel acceptance guardrails.

The heavyweight wheel exercise runs separately, not inside routine pytest.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.run_issue227_reader_contract_wheel_acceptance import (
    CORE_VERSION,
    CORE_WHEEL_NAME,
    CORE_WHEEL_SHA256,
    ReaderWheelAcceptanceError,
    _isolated_python,
    require_empty_work,
    verify_released_core_wheel,
)
from scripts.verify_installed_issue227_reader_contract import (
    FIXTURE,
    MANIFEST,
    READER,
    _is_installed_origin,
)


def test_exact_core_wheel_release_is_pinned() -> None:
    assert CORE_VERSION == "0.6.5"
    assert CORE_WHEEL_NAME == "pds_core-0.6.5-py3-none-any.whl"
    assert CORE_WHEEL_SHA256 == (
        "9ace75f17b23b7f0ed6a709d531af5120db43d0325b4148d26f2d6ba1d4b3c18"
    )


def test_fixture_and_public_contract_are_stable() -> None:
    assert MANIFEST == "scoreform_academic_result_manifest_v1"
    assert READER == "scoreform_academic_result_reader_v1"
    assert FIXTURE == Path(
        "tests/fixtures/publication/scoreform_academic_result_manifest_v1.json"
    )
    assert FIXTURE.is_file()


def test_work_must_be_empty_and_separate_from_checkout(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    work = tmp_path / "isolated"
    assert require_empty_work(work, repository) == work
    assert work.is_dir() and not list(work.iterdir())
    (work / "keep.txt").write_text("KEEP", encoding="utf-8")
    with pytest.raises(ReaderWheelAcceptanceError, match="absent or empty"):
        require_empty_work(work, repository)
    assert (work / "keep.txt").read_text(encoding="utf-8") == "KEEP"

    with pytest.raises(ReaderWheelAcceptanceError, match="separate"):
        require_empty_work(repository / "nested", repository)
    with pytest.raises(ReaderWheelAcceptanceError, match="separate"):
        require_empty_work(tmp_path, repository)


def test_work_rejects_existing_file(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    file = tmp_path / "work-file"
    file.write_bytes(b"preserve")
    with pytest.raises(ReaderWheelAcceptanceError, match="absent or empty"):
        require_empty_work(file, repository)
    assert file.read_bytes() == b"preserve"


def test_wrong_core_wheel_is_refused_before_install(tmp_path: Path) -> None:
    wrong = tmp_path / CORE_WHEEL_NAME
    wrong.write_bytes(b"not authenticated")
    with pytest.raises(ReaderWheelAcceptanceError, match="SHA-256"):
        verify_released_core_wheel(wrong)

    misleading = tmp_path / "pds_core-0.6.4-py3-none-any.whl"
    misleading.write_bytes(b"not authenticated")
    with pytest.raises(ReaderWheelAcceptanceError, match="filename"):
        verify_released_core_wheel(misleading)


def test_installed_origin_rejects_arbitrary_files(tmp_path: Path) -> None:
    class SourceModule:
        __file__ = str(tmp_path / "scoreform.py")

    assert not _is_installed_origin(SourceModule())
    assert not _is_installed_origin(object())


def test_isolated_python_is_cross_platform(tmp_path: Path) -> None:
    python = _isolated_python(tmp_path)
    assert python.name in ("python.exe", "python")
    assert python.parent.name in ("Scripts", "bin")


def test_release_readiness_invokes_installed_verifier_outside_checkout() -> None:
    workflow = Path(".github/workflows/release-readiness.yml").read_text(
        encoding="utf-8"
    )
    assert "Verify installed Issue 227 reader contract v1" in workflow
    assert 'cd "$RUNNER_TEMP"' in workflow
    assert '"$GITHUB_WORKSPACE/scripts/verify_installed_issue227_reader_contract.py"' in workflow
    assert "--scoreform-version 0.13.0" in workflow
    assert "--core-version 0.6.5" in workflow
    assert "scoreform-reader-contract-workspace-must-not-exist" in workflow


def test_acceptance_requires_real_wheel_not_checkout_imports() -> None:
    verifier = Path("scripts/verify_installed_issue227_reader_contract.py").read_text(
        encoding="utf-8"
    )
    harness = Path("scripts/run_issue227_reader_contract_wheel_acceptance.py").read_text(
        encoding="utf-8"
    )
    assert "metadata.entry_points().select(" in verifier
    assert '"scoreform.academic_result_reader" not in sys.modules' in verifier
    assert "_is_installed_origin(pds_core)" in verifier
    assert "_is_installed_origin(sys.modules[" in verifier
    assert "lookup_publication_reader_support(" in verifier
    assert "manifest_to_canonical_json_bytes(" in verifier
    assert "reader_support=()" in verifier
    assert "read_academic_result_manifest(raw + b\" \"" in verifier
    assert "Pds2ScanProvenance" in verifier
    assert "PlainPaperManualProvenance" in verifier
    assert "ScanReviewManualProvenance" in verifier
    assert '"PDS_WORKSPACE_ROOT"] = str(workspace)' in harness
    assert '"--no-index", "--no-deps", str(core_wheel)' in harness
    assert '"-m", "pip", "check"' in harness
    assert "ScoreForm and Core must import from isolated site-packages." in verifier
