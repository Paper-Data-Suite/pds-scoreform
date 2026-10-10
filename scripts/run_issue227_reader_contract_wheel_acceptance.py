"""Build candidate ScoreForm and qualify reader v1 against exact released Core 0.6.5.

All staging is confined to --work. No classroom or workspace path is opened.
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

CORE_VERSION = "0.6.5"
CORE_WHEEL_SHA256 = "9ace75f17b23b7f0ed6a709d531af5120db43d0325b4148d26f2d6ba1d4b3c18"
CORE_WHEEL_NAME = "pds_core-0.6.5-py3-none-any.whl"


class ReaderWheelAcceptanceError(RuntimeError):
    """Bounded installed-wheel qualification failure."""


def _run(args: list[str], *, cwd: Path, workspace: Path) -> None:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    environment["PYTHONNOUSERSITE"] = "1"
    environment["PDS_WORKSPACE_ROOT"] = str(workspace)
    subprocess.run(args, cwd=cwd, env=environment, check=True)


def require_empty_work(work: Path, repository: Path) -> Path:
    repository = repository.resolve(strict=True)
    if work.is_symlink():
        raise ReaderWheelAcceptanceError("--work must not be a symbolic link.")
    work = work.resolve()
    if work == repository or work.is_relative_to(repository) or repository.is_relative_to(work):
        raise ReaderWheelAcceptanceError("--work must be separate from the repository.")
    if work.exists():
        if not work.is_dir() or any(work.iterdir()):
            raise ReaderWheelAcceptanceError("--work must be absent or empty.")
    else:
        work.mkdir(parents=True)
    return work


def verify_released_core_wheel(wheel: Path) -> None:
    if not wheel.is_file() or wheel.name != CORE_WHEEL_NAME:
        raise ReaderWheelAcceptanceError("Expected exact released Core 0.6.5 wheel filename.")
    if hashlib.sha256(wheel.read_bytes()).hexdigest() != CORE_WHEEL_SHA256:
        raise ReaderWheelAcceptanceError("Core release wheel SHA-256 differs.")
    try:
        with zipfile.ZipFile(wheel) as archive:
            names = [name for name in archive.namelist()
                     if name.endswith(".dist-info/METADATA")]
            if names != ["pds_core-0.6.5.dist-info/METADATA"]:
                raise ReaderWheelAcceptanceError("Core wheel metadata entry is not exact.")
            info = BytesParser(policy=policy.default).parsebytes(archive.read(names[0]))
            if info.get("Name") != "pds-core" or info.get("Version") != CORE_VERSION:
                raise ReaderWheelAcceptanceError("Core wheel metadata identity differs.")
    except zipfile.BadZipFile as error:
        raise ReaderWheelAcceptanceError("Core wheel archive is invalid.") from error


def _isolated_python(environment: Path) -> Path:
    if os.name == "nt":
        return environment / "Scripts" / "python.exe"
    return environment / "bin" / "python"


def _wheel_version(wheel: Path) -> str:
    with zipfile.ZipFile(wheel) as archive:
        names = [name for name in archive.namelist()
                 if name.count("/") == 1 and name.endswith(".dist-info/METADATA")]
        if len(names) != 1:
            raise ReaderWheelAcceptanceError("ScoreForm wheel metadata entry is ambiguous.")
        document = BytesParser(policy=policy.default).parsebytes(archive.read(names[0]))
    if document.get("Name") != "scoreform":
        raise ReaderWheelAcceptanceError("Candidate wheel is not ScoreForm.")
    version = document.get("Version")
    if not version or wheel.name != f"scoreform-{version}-py3-none-any.whl":
        raise ReaderWheelAcceptanceError("Candidate wheel version/name differs.")
    return version


def run_acceptance(*, repository: Path, work: Path, core_wheel: Path) -> dict[str, str]:
    repository = repository.resolve(strict=True)
    core_wheel = core_wheel.resolve(strict=True)
    verify_released_core_wheel(core_wheel)
    work = require_empty_work(work, repository)
    source = work / "source"
    artifacts = work / "artifacts"
    outside = work / "outside-source"
    environment = work / "venv"
    workspace = work / "workspace-must-remain-absent"

    shutil.copytree(
        repository,
        source,
        symlinks=True,
        ignore=shutil.ignore_patterns(
            ".git", ".venv", "build", "dist", "*.egg-info", ".pytest_cache",
            ".mypy_cache", ".ruff_cache", "__pycache__", "*.pyc", "*.pyo",
            "classes", "scans_inbox", "local_outputs",
        ),
    )
    if any(path.is_symlink() for path in source.rglob("*")):
        raise ReaderWheelAcceptanceError("Source checkout contains an unsupported symlink.")
    artifacts.mkdir()
    outside.mkdir()

    _run([
        sys.executable, "-m", "build", "--wheel", "--sdist", "--outdir",
        str(artifacts),
    ], cwd=source, workspace=workspace)
    wheels = tuple(artifacts.glob("scoreform-*-py3-none-any.whl"))
    sdists = tuple(artifacts.glob("scoreform-*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise ReaderWheelAcceptanceError("Expected one candidate wheel and one sdist.")
    wheel = wheels[0]
    version = _wheel_version(wheel)
    _run([
        sys.executable, str(source / "scripts" / "verify_release_artifacts.py"),
        "--version", version, "--dist", str(artifacts),
    ], cwd=source, workspace=workspace)

    venv.EnvBuilder(with_pip=True).create(environment)
    python = _isolated_python(environment)
    if not python.is_file():
        raise ReaderWheelAcceptanceError("Isolated environment was not created.")
    _run([str(python), "-m", "pip", "install", "--no-index", "--no-deps", str(core_wheel)],
         cwd=outside, workspace=workspace)
    _run([str(python), "-m", "pip", "install", str(wheel)],
         cwd=outside, workspace=workspace)
    _run([str(python), "-m", "pip", "check"], cwd=outside, workspace=workspace)
    _run([
        str(python), str(source / "scripts" / "verify_installed_issue227_reader_contract.py"),
        "--repository", str(source),
        "--workspace", str(workspace),
        "--scoreform-version", version,
        "--core-version", CORE_VERSION,
    ], cwd=outside, workspace=workspace)
    if workspace.exists():
        raise ReaderWheelAcceptanceError("Installed qualification created workspace state.")
    return {
        "result": "passed",
        "scoreform_candidate_version": version,
        "scoreform_candidate_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
        "core_release_version": CORE_VERSION,
        "core_release_sha256": CORE_WHEEL_SHA256,
        "installed_isolation": "noneditable-wheel-outside-source",
        "workspace": "not_created",
        "scoreform_wheel": str(wheel),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--core-wheel", type=Path, required=True)
    options = parser.parse_args()
    try:
        result = run_acceptance(
            repository=options.repository,
            work=options.work,
            core_wheel=options.core_wheel,
        )
    except (ReaderWheelAcceptanceError, OSError, subprocess.CalledProcessError,
            zipfile.BadZipFile) as error:
        print(f"Issue #227 wheel acceptance failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
