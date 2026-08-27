from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import pytest

from scripts.verify_v011_physical_equivalence import (
    EquivalenceError,
    verify_equivalence,
)


def _wheel(
    path: Path,
    *,
    version: str,
    runtime: bytes = b'"""ScoreForm package."""\n',
    dependency: str = "pds-core<0.7,>=0.6.2",
) -> Path:
    dist = f"scoreform-{version}.dist-info"
    metadata = (
        "Metadata-Version: 2.4\n"
        "Name: scoreform\n"
        f"Version: {version}\n"
        "Requires-Python: >=3.11\n"
        f"Requires-Dist: {dependency}\n"
        "Requires-Dist: numpy\n"
        "\n"
        f"Synthetic ScoreForm {version} metadata text.\n"
    ).encode()
    entry_points = (
        "[console_scripts]\n"
        "scoreform = scoreform.cli:main\n"
        "\n"
        "[paper_data_suite.modules]\n"
        "scoreform = scoreform.pds_module:get_module_profile\n"
        "\n"
        "[paper_data_suite.publication_producers]\n"
        "scoreform = scoreform.pds_publication:get_publication_producer_profile\n"
        "\n"
        "[paper_data_suite.module_operations]\n"
        "scoreform = scoreform.pds_operations:get_module_operations_profile\n"
    ).encode()
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("scoreform/__init__.py", runtime)
        archive.writestr("scoreform/cli.py", b"def main():\n    return 0\n")
        archive.writestr(f"{dist}/METADATA", metadata)
        archive.writestr(f"{dist}/entry_points.txt", entry_points)
        archive.writestr(f"{dist}/top_level.txt", b"scoreform\n")
    return path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_metadata_only_version_bridge_passes(tmp_path: Path) -> None:
    baseline = _wheel(tmp_path / "scoreform-0.10.0.whl", version="0.10.0")
    release = _wheel(tmp_path / "scoreform-0.11.0.whl", version="0.11.0")

    result = verify_equivalence(
        baseline,
        release,
        expected_baseline_sha256=_sha(baseline),
    )

    assert result["runtime_payload_equivalent"] is True
    assert result["physical_acceptance"] == "not_claimed"
    assert result["owner_carry_forward_required"] is True


def test_runtime_change_forces_failure(tmp_path: Path) -> None:
    baseline = _wheel(tmp_path / "baseline.whl", version="0.10.0")
    release = _wheel(
        tmp_path / "release.whl",
        version="0.11.0",
        runtime=b'"""changed runtime"""\n',
    )

    with pytest.raises(EquivalenceError, match="runtime payload changed"):
        verify_equivalence(
            baseline,
            release,
            expected_baseline_sha256=_sha(baseline),
        )


def test_dependency_change_forces_failure(tmp_path: Path) -> None:
    baseline = _wheel(tmp_path / "baseline.whl", version="0.10.0")
    release = _wheel(
        tmp_path / "release.whl",
        version="0.11.0",
        dependency="pds-core<0.8,>=0.6.2",
    )

    with pytest.raises(EquivalenceError, match="Requires-Dist"):
        verify_equivalence(
            baseline,
            release,
            expected_baseline_sha256=_sha(baseline),
        )


def test_wrong_baseline_hash_forces_failure(tmp_path: Path) -> None:
    baseline = _wheel(tmp_path / "baseline.whl", version="0.10.0")
    release = _wheel(tmp_path / "release.whl", version="0.11.0")

    with pytest.raises(EquivalenceError, match="baseline wheel SHA-256"):
        verify_equivalence(
            baseline,
            release,
            expected_baseline_sha256="0" * 64,
        )
