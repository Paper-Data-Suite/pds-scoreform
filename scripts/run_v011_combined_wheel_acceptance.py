"""Build and qualify ScoreForm's combined v0.11 installed workflow against Core 0.6.3."""

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

from pip._vendor.packaging.utils import canonicalize_name, parse_wheel_filename

CORE_VERSION = "0.6.3"
CORE_WHEEL_SHA256 = (
    "98d7596ce0eed26e4d56a17bbbbd644db3014259b56a45783a173fe8237af5e5"
)


class CombinedWheelAcceptanceError(RuntimeError):
    """Raised when isolated issue #195 qualification cannot complete."""


def _run(command: list[str], *, cwd: Path) -> None:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    environment["PYTHONNOUSERSITE"] = "1"
    subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        check=True,
    )


def _environment_python(environment: Path) -> Path:
    if os.name == "nt":
        return environment / "Scripts" / "python.exe"
    return environment / "bin" / "python"


def _validate_core_wheel(path: Path, expected_version: str) -> None:
    path = path.resolve(strict=True)
    if expected_version != CORE_VERSION:
        raise CombinedWheelAcceptanceError(
            f"combined v0.11 qualification requires Core {CORE_VERSION}"
        )
    name, version, _build, _tags = parse_wheel_filename(path.name)
    if canonicalize_name(name) != "pds-core" or str(version) != expected_version:
        raise CombinedWheelAcceptanceError(
            f"Core wheel identity does not match {expected_version}: {path.name}"
        )
    actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual_hash != CORE_WHEEL_SHA256:
        raise CombinedWheelAcceptanceError(
            f"Core {expected_version} wheel SHA-256 mismatch: {actual_hash}"
        )


def _wheel_version(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        metadata_names = [
            name
            for name in archive.namelist()
            if name.count("/") == 1 and name.endswith(".dist-info/METADATA")
        ]
        if len(metadata_names) != 1:
            raise CombinedWheelAcceptanceError(
                "built ScoreForm wheel must contain exactly one METADATA file"
            )
        message = BytesParser(policy=policy.default).parsebytes(
            archive.read(metadata_names[0])
        )
    if canonicalize_name(str(message.get("Name", ""))) != "scoreform":
        raise CombinedWheelAcceptanceError("built wheel distribution is not scoreform")
    version = message.get("Version")
    if not isinstance(version, str) or not version:
        raise CombinedWheelAcceptanceError("built ScoreForm wheel version is missing")
    return version


def _copy_source_tree(repository: Path, destination: Path) -> None:
    ignored = shutil.ignore_patterns(
        ".git",
        ".venv",
        "build",
        "dist",
        "scoreform.egg-info",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "__pycache__",
        "*.pyc",
        "*.pyo",
    )
    shutil.copytree(
        repository,
        destination,
        symlinks=False,
        ignore=ignored,
    )


def run_acceptance(
    *,
    repository: Path,
    work: Path,
    core_wheel: Path,
    expected_core_version: str,
) -> dict[str, object]:
    repository = repository.resolve(strict=True)
    core_wheel = core_wheel.resolve(strict=True)
    work = work.resolve()
    _validate_core_wheel(core_wheel, expected_core_version)

    if work.exists():
        if not work.is_dir() or any(work.iterdir()):
            raise CombinedWheelAcceptanceError(
                "--work must be absent or an empty directory"
            )
    else:
        work.mkdir(parents=True)

    source = work / "source"
    _copy_source_tree(repository, source)

    artifacts = work / "artifacts"
    environment = work / "venv"
    outside = work / "outside-source"
    workspace = work / "combined-workspace"
    artifacts.mkdir()
    outside.mkdir()

    _run(
        [
            sys.executable,
            "-m",
            "build",
            "--wheel",
            "--sdist",
            "--outdir",
            str(artifacts),
        ],
        cwd=source,
    )

    wheels = tuple(artifacts.glob("scoreform-*-py3-none-any.whl"))
    sdists = tuple(artifacts.glob("scoreform-*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise CombinedWheelAcceptanceError(
            "build must produce exactly one ScoreForm wheel and one sdist"
        )
    wheel = wheels[0]
    version = _wheel_version(wheel)

    _run(
        [
            sys.executable,
            str(repository / "scripts" / "verify_release_artifacts.py"),
            "--version",
            version,
            "--dist",
            str(artifacts),
        ],
        cwd=repository,
    )

    venv.EnvBuilder(with_pip=True, clear=False).create(environment)
    python = _environment_python(environment)
    if not python.is_file():
        raise CombinedWheelAcceptanceError(
            "isolated environment Python was not created"
        )

    _run(
        [str(python), "-m", "pip", "install", str(core_wheel)],
        cwd=outside,
    )
    _run(
        [str(python), "-m", "pip", "install", str(wheel)],
        cwd=outside,
    )
    _run([str(python), "-m", "pip", "check"], cwd=outside)

    _run(
        [
            str(python),
            str(repository / "scripts" / "verify_installed_v011_combined_acceptance.py"),
            "--workspace",
            str(workspace),
            "--repository",
            str(repository),
            "--version",
            version,
            "--expected-core-version",
            expected_core_version,
        ],
        cwd=outside,
    )

    return {
        "scoreform_version": version,
        "core_version": expected_core_version,
        "wheel": str(wheel),
        "sdist": str(sdists[0]),
        "isolated_environment": str(environment),
        "combined_acceptance": "passed",
        "physical_acceptance": "not_claimed",
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True, type=Path)
    parser.add_argument("--work", required=True, type=Path)
    parser.add_argument("--core-wheel", required=True, type=Path)
    parser.add_argument(
        "--expected-core-version",
        required=True,
        choices=(CORE_VERSION,),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    options = _parse_args(argv)
    try:
        result = run_acceptance(
            repository=options.repository,
            work=options.work,
            core_wheel=options.core_wheel,
            expected_core_version=options.expected_core_version,
        )
    except (
        CombinedWheelAcceptanceError,
        OSError,
        subprocess.CalledProcessError,
        zipfile.BadZipFile,
    ) as error:
        print(
            f"Combined installed-wheel acceptance failed: {error}",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
