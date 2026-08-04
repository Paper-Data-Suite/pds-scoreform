"""Deterministically validate ScoreForm release artifact names and contents."""

from __future__ import annotations

import argparse
import re
import tarfile
import zipfile
from email import policy
from email.message import Message
from email.parser import Parser
from pathlib import Path, PurePosixPath

from pip._vendor.packaging.requirements import InvalidRequirement, Requirement
from pip._vendor.packaging.specifiers import InvalidSpecifier, SpecifierSet
from pip._vendor.packaging.utils import canonicalize_name
from pip._vendor.packaging.version import InvalidVersion, Version

FORBIDDEN_PARTS = {
    ".git",
    ".venv",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "__pycache__",
    "build",
    "classes",
    "dist",
    "htmlcov",
    "local_outputs",
    "scans_inbox",
}
FORBIDDEN_SUFFIXES = {".diff", ".patch", ".pdf", ".pyc", ".pyo"}
EXPECTED_CORE_SPECIFIER = SpecifierSet(">=0.6,<0.7")
EXPECTED_PYTHON_SPECIFIER = SpecifierSet(">=3.11")


class ArtifactValidationError(Exception):
    """Raised when a release artifact violates the release contract."""


def _normalized_member(name: str) -> PurePosixPath:
    member = PurePosixPath(name.replace("\\", "/"))
    if member.is_absolute() or ".." in member.parts:
        raise ArtifactValidationError(f"unsafe artifact member: {name}")
    return member


def validate_member_names(names: list[str]) -> None:
    for name in names:
        member = _normalized_member(name)
        lowered_parts = {part.lower() for part in member.parts}
        lowered_name = member.name.lower()
        if "pds_core" in lowered_parts:
            raise ArtifactValidationError(f"artifact bundles pds_core: {name}")
        if lowered_parts & FORBIDDEN_PARTS:
            raise ArtifactValidationError(f"forbidden artifact member: {name}")
        if member.suffix.lower() in FORBIDDEN_SUFFIXES:
            raise ArtifactValidationError(f"forbidden artifact member: {name}")
        if lowered_name in {"results.csv", "coverage.xml"}:
            raise ArtifactValidationError(f"forbidden artifact member: {name}")
        if lowered_name.endswith("_results.csv") or lowered_name.startswith("debug_"):
            raise ArtifactValidationError(f"forbidden artifact member: {name}")


def validate_sdist_members(members: list[tarfile.TarInfo]) -> None:
    validate_member_names([member.name for member in members])
    for member in members:
        if member.issym():
            raise ArtifactValidationError(
                f"source distribution contains a symbolic link: {member.name}"
            )
        if member.islnk():
            raise ArtifactValidationError(
                f"source distribution contains a hard link: {member.name}"
            )


def _single_metadata_value(message: Message, field: str, label: str) -> str:
    values = message.get_all(field, [])
    if len(values) != 1:
        raise ArtifactValidationError(
            f"{label} metadata must contain exactly one {field} field"
        )
    return str(values[0]).strip()


def validate_core_requirement_strings(values: list[str], label: str) -> Requirement:
    parsed: list[Requirement] = []
    for value in values:
        try:
            parsed.append(Requirement(value))
        except InvalidRequirement as error:
            raise ArtifactValidationError(
                f"{label} contains an invalid Requires-Dist value: {value}"
            ) from error
    core = [
        requirement
        for requirement in parsed
        if canonicalize_name(requirement.name) == canonicalize_name("pds-core")
    ]
    if len(core) != 1:
        raise ArtifactValidationError(
            f"{label} must contain exactly one pds-core Requires-Dist field"
        )
    requirement = core[0]
    if requirement.url is not None:
        raise ArtifactValidationError(f"{label} pds-core requirement must not use a URL")
    if requirement.marker is not None:
        raise ArtifactValidationError(
            f"{label} pds-core requirement must not use an environment marker"
        )
    if requirement.extras:
        raise ArtifactValidationError(f"{label} pds-core requirement must not use extras")
    if requirement.specifier != EXPECTED_CORE_SPECIFIER:
        raise ArtifactValidationError(
            f"{label} pds-core requirement must be exactly >=0.6,<0.7"
        )
    return requirement


def validate_package_metadata(text: str, version: str, label: str) -> None:
    message = Parser(policy=policy.default).parsestr(text)
    name = _single_metadata_value(message, "Name", label)
    if canonicalize_name(name) != canonicalize_name("scoreform"):
        raise ArtifactValidationError(f"{label} package name must be scoreform")

    reported_version = _single_metadata_value(message, "Version", label)
    try:
        if Version(reported_version) != Version(version):
            raise ArtifactValidationError(
                f"{label} metadata does not report version {version}"
            )
    except InvalidVersion as error:
        raise ArtifactValidationError(
            f"{label} metadata contains an invalid version: {reported_version}"
        ) from error

    requires_python = _single_metadata_value(message, "Requires-Python", label)
    try:
        parsed_python = SpecifierSet(requires_python)
    except InvalidSpecifier as error:
        raise ArtifactValidationError(
            f"{label} metadata contains invalid Requires-Python: {requires_python}"
        ) from error
    if parsed_python != EXPECTED_PYTHON_SPECIFIER:
        raise ArtifactValidationError(f"{label} Requires-Python must be exactly >=3.11")

    requirements = [str(value) for value in message.get_all("Requires-Dist", [])]
    validate_core_requirement_strings(requirements, label)


def validate_wheel(path: Path, version: str) -> None:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        validate_member_names(names)
        metadata_names = [name for name in names if name.endswith(".dist-info/METADATA")]
        entry_names = [name for name in names if name.endswith(".dist-info/entry_points.txt")]
        if len(metadata_names) != 1 or len(entry_names) != 1:
            raise ArtifactValidationError(
                f"{path.name} must contain one METADATA and one entry_points.txt"
            )
        validate_package_metadata(
            archive.read(metadata_names[0]).decode("utf-8"), version, path.name
        )
        entry_text = archive.read(entry_names[0]).decode("utf-8")
        required = (
            "[paper_data_suite.modules]\n"
            "scoreform = scoreform.pds_module:get_module_profile"
        )
        if required not in entry_text.replace("\r\n", "\n"):
            raise ArtifactValidationError(
                f"{path.name} is missing the exact ScoreForm module entry point"
            )


def validate_sdist(path: Path, version: str) -> None:
    with tarfile.open(path, "r:gz") as archive:
        members = archive.getmembers()
        validate_sdist_members(members)
        package_info = [
            member
            for member in members
            if PurePosixPath(member.name).name == "PKG-INFO"
            and len(PurePosixPath(member.name).parts) == 2
        ]
        if len(package_info) != 1:
            raise ArtifactValidationError(f"{path.name} must contain one root PKG-INFO")
        extracted = archive.extractfile(package_info[0])
        if extracted is None:
            raise ArtifactValidationError(f"could not read {package_info[0].name}")
        validate_package_metadata(
            extracted.read().decode("utf-8"), version, path.name
        )


def validate_dist(dist: Path, version: str) -> tuple[Path, Path]:
    artifacts = sorted(path for path in dist.iterdir() if path.is_file())
    wheels = [path for path in artifacts if path.suffix == ".whl"]
    sdists = [path for path in artifacts if path.name.endswith(".tar.gz")]
    expected_wheel = re.compile(rf"^scoreform-{re.escape(version)}-[^-]+-[^-]+-[^-]+\.whl$")
    if len(artifacts) != 2 or len(wheels) != 1 or len(sdists) != 1:
        raise ArtifactValidationError(
            "dist must contain exactly one wheel and one source distribution"
        )
    wheel, sdist = wheels[0], sdists[0]
    if not expected_wheel.fullmatch(wheel.name):
        raise ArtifactValidationError(f"unexpected wheel filename: {wheel.name}")
    if sdist.name != f"scoreform-{version}.tar.gz":
        raise ArtifactValidationError(f"unexpected sdist filename: {sdist.name}")
    validate_wheel(wheel, version)
    validate_sdist(sdist, version)
    return wheel, sdist


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist", type=Path, default=Path("dist"))
    parser.add_argument("--version", default="0.9.1")
    args = parser.parse_args()
    try:
        wheel, sdist = validate_dist(args.dist, args.version)
    except (OSError, ArtifactValidationError, tarfile.TarError, zipfile.BadZipFile) as exc:
        print(f"Artifact validation failed: {exc}")
        return 1
    print(f"Validated {wheel.name}")
    print(f"Validated {sdist.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
