"""Issue #225 Slice 14: installed recovery qualification runner guardrails.

The slow, isolated-wheel end-to-end exercise is run separately with a Core
wheel using scripts/run_issue225_recovery_wheel_acceptance.py.
"""

from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

import pytest

from scripts.run_issue225_recovery_wheel_acceptance import (
    RecoveryWheelAcceptanceError,
    inspect_wheel,
    isolated_python,
    require_empty_work,
    sha256,
    validate_core_version,
)


def _wheel(path: Path, name: str, version: str) -> Path:
    with ZipFile(path, "w") as archive:
        archive.writestr(
            f"{name.replace('-', '_')}-{version}.dist-info/METADATA",
            f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n",
        )
    return path


def test_matching_core_wheel_identity(tmp_path):
    core = _wheel(tmp_path / "pds_core-0.6.5-py3-none-any.whl", "pds-core", "0.6.5")
    assert inspect_wheel(core, "pds-core") == "0.6.5"
    assert len(sha256(core)) == 64


def test_matching_scoreform_wheel_identity(tmp_path):
    candidate = _wheel(tmp_path / "scoreform-0.12.1-py3-none-any.whl", "scoreform", "0.12.1")
    assert inspect_wheel(candidate, "scoreform") == "0.12.1"


def test_reject_wrong_wheel_distribution(tmp_path):
    candidate = _wheel(tmp_path / "wrong-0.6.5-py3-none-any.whl", "wrong", "0.6.5")
    with pytest.raises(RecoveryWheelAcceptanceError, match="name or version"):
        inspect_wheel(candidate, "pds-core")


def test_reject_wheel_with_no_metadata(tmp_path):
    candidate = tmp_path / "pds_core-0.6.5-py3-none-any.whl"
    with ZipFile(candidate, "w") as archive:
        archive.writestr("other.txt", "not metadata")
    with pytest.raises(RecoveryWheelAcceptanceError, match="one METADATA"):
        inspect_wheel(candidate, "pds-core")


def test_reject_duplicate_metadata(tmp_path):
    candidate = tmp_path / "pds_core-0.6.5-py3-none-any.whl"
    with ZipFile(candidate, "w") as archive:
        archive.writestr("a.dist-info/METADATA", "Name: pds-core\nVersion: 0.6.5\n")
        archive.writestr("b.dist-info/METADATA", "Name: pds-core\nVersion: 0.6.5\n")
    with pytest.raises(RecoveryWheelAcceptanceError, match="one METADATA"):
        inspect_wheel(candidate, "pds-core")


@pytest.mark.parametrize("version", ["0.6.5", "0.6.6", "0.6.98"])
def test_accept_supported_core_versions(version):
    validate_core_version(version)


@pytest.mark.parametrize("version", ["0.6.3", "0.6.4", "0.7.0", "0.5.99", "1.0.0", "0.6.5rc1", "bad"])
def test_reject_unsupported_core_versions(version):
    with pytest.raises(RecoveryWheelAcceptanceError):
        validate_core_version(version)


def test_fresh_work_directory_is_allowed(tmp_path):
    work = tmp_path / "new"
    require_empty_work(work)
    assert work.is_dir() and not list(work.iterdir())
    require_empty_work(work)


def test_dirty_work_directory_is_refused(tmp_path):
    work = tmp_path / "existing"
    work.mkdir()
    (work / "sentinel").write_bytes(b"must not be overwritten")
    with pytest.raises(RecoveryWheelAcceptanceError, match="absent or empty"):
        require_empty_work(work)
    assert (work / "sentinel").read_bytes() == b"must not be overwritten"


def test_non_directory_work_path_is_refused(tmp_path):
    work = tmp_path / "file"
    work.write_bytes(b"keep")
    with pytest.raises(RecoveryWheelAcceptanceError, match="absent or empty"):
        require_empty_work(work)
    assert work.read_bytes() == b"keep"


def test_isolated_python_is_platform_specific(tmp_path):
    candidate = isolated_python(tmp_path)
    assert candidate.name in {"python.exe", "python"}
    assert candidate.parent.name in {"Scripts", "bin"}


def test_installed_fixture_preinitializes_core_workspace(tmp_path):
    """CLI workspace bootstrap must not masquerade as a preview mutation."""
    from pds_core.workspace import ensure_workspace_root

    from scripts.verify_installed_issue225_recovery import fixture, snapshot

    root = tmp_path / "synthetic-installed-workspace"
    fixture(root, pages=1)
    marker = root / ".pds" / "workspace.json"
    assert marker.is_file()
    before = snapshot(root)
    assert ensure_workspace_root(root) == root.resolve()
    assert snapshot(root) == before
