"""Issue #225 Slice 14: build and qualify ScoreForm recovery from an isolated wheel.

No classroom data are required. Supply a locally built Core wheel explicitly.
The installed verifier mocks optical mark recognition ONLY; real Core routing,
retained sources, teacher decisions, schema-v2 persistence, and CLI are used.
This is not physical/printed-scan acceptance or a release gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import venv
import zipfile
from email import policy
from email.parser import BytesParser
from pathlib import Path


class RecoveryWheelAcceptanceError(RuntimeError):
    """An installed acceptance prerequisite or verification failed."""


def inspect_wheel(path: Path, expected_name: str) -> str:
    """Read the wheel's canonical distribution name and version from METADATA."""
    if not path.is_file() or path.suffix.lower() != ".whl":
        raise RecoveryWheelAcceptanceError("An existing .whl file is required.")
    with zipfile.ZipFile(path) as archive:
        metadata = [
            name for name in archive.namelist()
            if name.count("/") == 1 and name.endswith(".dist-info/METADATA")
        ]
        if len(metadata) != 1:
            raise RecoveryWheelAcceptanceError("Wheel must have one METADATA file.")
        document = BytesParser(policy=policy.default).parsebytes(
            archive.read(metadata[0])
        )
    found = str(document.get("Name", "")).lower().replace("_", "-").replace(".", "-")
    version = str(document.get("Version", ""))
    if found != expected_name or not version:
        raise RecoveryWheelAcceptanceError("Wheel name or version is invalid.")
    return version


def validate_core_version(value: str) -> None:
    # Candidate Core 0.6.4 and newer compatible 0.6.x wheels are permitted.
    pieces = value.split(".")
    if len(pieces) != 3 or not all(item.isdecimal() for item in pieces):
        raise RecoveryWheelAcceptanceError("Core must use a stable x.y.z version.")
    if (int(pieces[0]), int(pieces[1])) != (0, 6) or int(pieces[2]) < 4:
        raise RecoveryWheelAcceptanceError("ScoreForm requires Core >=0.6.4,<0.7.")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_empty_work(path: Path) -> None:
    if path.exists():
        if path.is_symlink() or not path.is_dir() or any(path.iterdir()):
            raise RecoveryWheelAcceptanceError("--work must be absent or empty and not linked.")
    else:
        path.mkdir(parents=True)


def isolated_python(root: Path) -> Path:
    return root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def run(command: list[str], *, cwd: Path) -> None:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    env.pop("PDS_WORKSPACE_ROOT", None)
    env["PYTHONNOUSERSITE"] = "1"
    subprocess.run(command, cwd=cwd, env=env, check=True)


def qualify(repository: Path, work: Path, core_wheel: Path, core_sha256: str | None) -> dict[str, str]:
    repository = repository.resolve(strict=True)
    if not (repository / "pyproject.toml").is_file():
        raise RecoveryWheelAcceptanceError("Repository root lacks pyproject.toml.")
    core_wheel = core_wheel.resolve(strict=True)
    core_version = inspect_wheel(core_wheel, "pds-core")
    validate_core_version(core_version)
    actual_core_sha = sha256(core_wheel)
    if core_sha256 is not None and actual_core_sha != core_sha256.lower():
        raise RecoveryWheelAcceptanceError("Supplied Core wheel SHA-256 does not match.")
    # Preserve a linked --work path so the safety check can refuse it.
    work = work.absolute()
    require_empty_work(work)
    source = work / "source"
    artifacts = work / "artifacts"
    outside = work / "outside-source"
    environment = work / "venv"
    workspace = work / "recovery-fixtures"
    shutil.copytree(
        repository, source, symlinks=False,
        ignore=shutil.ignore_patterns(
            ".git", ".venv", "build", "dist", "*.egg-info", ".pytest_cache",
            ".mypy_cache", ".ruff_cache", "__pycache__", "*.pyc", "*.pyo",
        ),
    )
    artifacts.mkdir()
    outside.mkdir()
    run(
        [sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir", str(artifacts)],
        cwd=source,
    )
    wheels = tuple(artifacts.glob("scoreform-*.whl"))
    if len(wheels) != 1:
        raise RecoveryWheelAcceptanceError("Exactly one candidate ScoreForm wheel required.")
    scoreform_wheel = wheels[0]
    scoreform_version = inspect_wheel(scoreform_wheel, "scoreform")
    venv.EnvBuilder(with_pip=True).create(environment)
    python = isolated_python(environment)
    if not python.is_file():
        raise RecoveryWheelAcceptanceError("Isolated Python executable missing.")
    run([str(python), "-m", "pip", "install", str(core_wheel)], cwd=outside)
    run([str(python), "-m", "pip", "install", str(scoreform_wheel)], cwd=outside)
    run([str(python), "-m", "pip", "check"], cwd=outside)
    verifier = repository / "scripts" / "verify_installed_issue225_recovery.py"
    run(
        [str(python), str(verifier), "--repository", str(repository),
         "--workspace", str(workspace), "--scoreform-version", scoreform_version,
         "--core-version", core_version],
        cwd=outside,
    )
    return {
        "acceptance": "installed_synthetic_recovery_passed",
        "core_version": core_version,
        "core_wheel_sha256": actual_core_sha,
        "scoreform_version": scoreform_version,
        "scoreform_wheel_sha256": sha256(scoreform_wheel),
        "physical_scan_acceptance": "not_claimed",
        "optical_recognition": "deterministic_synthetic_substitute",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--core-wheel", type=Path, required=True)
    parser.add_argument("--core-sha256", help="Optional expected SHA-256 of the supplied Core wheel")
    options = parser.parse_args(argv)
    try:
        result = qualify(options.repository, options.work, options.core_wheel, options.core_sha256)
    except (RecoveryWheelAcceptanceError, OSError, subprocess.CalledProcessError,
            ValueError, zipfile.BadZipFile) as error:
        print(f"Issue #225 isolated qualification failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
