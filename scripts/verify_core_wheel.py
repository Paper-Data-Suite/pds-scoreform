"""Validate the current released Core 0.6.3 reference wheel."""

from __future__ import annotations

import argparse
import re
import zipfile
from email import policy
from email.parser import BytesParser
from pathlib import Path

from pip._vendor.packaging.requirements import Requirement
from pip._vendor.packaging.specifiers import SpecifierSet
from pip._vendor.packaging.tags import sys_tags
from pip._vendor.packaging.utils import canonicalize_name, parse_wheel_filename
from pip._vendor.packaging.version import Version

EXPECTED_VERSION = Version("0.6.3")
EXPECTED_DEV_REQUIREMENTS = {
    "build": SpecifierSet(""),
    "mypy": SpecifierSet(""),
    "packaging": SpecifierSet(">=24"),
    "pytest": SpecifierSet(""),
    "ruff": SpecifierSet(""),
    "twine": SpecifierSet(""),
}


def _validate_optional_dependencies(requirements: list[Requirement]) -> None:
    """Require the exact v0.6.3 dev extra and no runtime requirements."""

    by_name = {
        canonicalize_name(requirement.name): requirement
        for requirement in requirements
    }
    if set(by_name) != set(EXPECTED_DEV_REQUIREMENTS):
        raise ValueError(
            "Core 0.6.3 wheel dev-extra dependency names do not match "
            "the released contract"
        )

    for name, requirement in by_name.items():
        expected_specifier = EXPECTED_DEV_REQUIREMENTS[name]
        if requirement.specifier != expected_specifier:
            raise ValueError(
                f"Core 0.6.3 wheel dependency specifier disagrees for {name}"
            )
        if (
            requirement.marker is None
            or requirement.marker.evaluate({"extra": ""})
            or not requirement.marker.evaluate({"extra": "dev"})
        ):
            raise ValueError(
                f"Core 0.6.3 wheel dependency {name} must be dev-extra only"
            )


def validate_core_wheel(path: Path) -> None:
    """Validate exact Core release identity and wheel metadata."""

    if not path.is_file() or path.suffix != ".whl":
        raise ValueError(f"Core reference must be an existing wheel file: {path}")
    name, version, _build, tags = parse_wheel_filename(path.name)
    if canonicalize_name(name) != "pds-core" or version != EXPECTED_VERSION:
        raise ValueError("Core wheel must be pds-core version 0.6.3")
    if not tags.intersection(sys_tags()):
        raise ValueError(f"Core wheel is incompatible with this Python: {path.name}")

    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        metadata_names = [
            name for name in names if name.endswith(".dist-info/METADATA")
        ]
        if len(metadata_names) != 1:
            raise ValueError("Core wheel must contain exactly one METADATA file")
        message = BytesParser(policy=policy.default).parsebytes(
            archive.read(metadata_names[0])
        )
        if canonicalize_name(str(message["Name"])) != "pds-core":
            raise ValueError("Core wheel metadata name must be pds-core")
        if Version(str(message["Version"])) != EXPECTED_VERSION:
            raise ValueError("Core wheel metadata version must be 0.6.3")
        if SpecifierSet(str(message["Requires-Python"])) != SpecifierSet(">=3.11"):
            raise ValueError("Core wheel Requires-Python must be exactly >=3.11")

        requirements = [
            Requirement(str(value))
            for value in message.get_all("Requires-Dist", [])
        ]
        _validate_optional_dependencies(requirements)

        init_names = [name for name in names if name == "pds_core/__init__.py"]
        if len(init_names) != 1:
            raise ValueError("Core wheel must contain pds_core/__init__.py")
        init_text = archive.read(init_names[0]).decode("utf-8")
        if not re.search(
            r'^__version__\s*=\s*["\']0\.6\.3["\']\s*$',
            init_text,
            re.M,
        ):
            raise ValueError("Core wheel pds_core.__version__ must be 0.6.3")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("wheel", nargs="+", type=Path)
    args = parser.parse_args()
    if len(args.wheel) != 1:
        parser.error("expected exactly one Core 0.6.3 wheel")
    try:
        validate_core_wheel(args.wheel[0])
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        print(f"Core wheel validation failed: {error}")
        return 1
    print(f"Validated Core 0.6.3 reference wheel: {args.wheel[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
