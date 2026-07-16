"""Verify installed ScoreForm metadata and Core module-profile discovery."""

from __future__ import annotations

import argparse
import importlib
import inspect
import sys
from importlib import metadata
from pathlib import Path

from pds_core.module_profiles import discover_module_profiles, validate_module_profile
from pip._vendor.packaging.specifiers import SpecifierSet
from pip._vendor.packaging.version import Version

try:
    from scripts.verify_release_artifacts import (
        ArtifactValidationError,
        validate_core_requirement_strings,
    )
except ModuleNotFoundError:
    from verify_release_artifacts import (  # type: ignore[no-redef]
        ArtifactValidationError,
        validate_core_requirement_strings,
    )

CORE_VERSION_SPECIFIER = SpecifierSet(">=0.5,<0.6")


def core_version_is_supported(value: str) -> bool:
    return Version(value) in CORE_VERSION_SPECIFIER


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default="0.9.1")
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()

    if args.workspace.exists():
        raise SystemExit(f"workspace unexpectedly exists before discovery: {args.workspace}")
    if metadata.version("scoreform") != args.version:
        raise SystemExit("installed ScoreForm metadata version mismatch")
    scoreform_requirements = metadata.requires("scoreform") or []
    try:
        core_requirement = validate_core_requirement_strings(
            scoreform_requirements, "installed ScoreForm"
        )
    except ArtifactValidationError as error:
        raise SystemExit(str(error)) from error
    core_version = metadata.version("pds-core")
    if Version(core_version) not in core_requirement.specifier:
        raise SystemExit(
            f"installed pds-core does not satisfy ScoreForm's declared dependency: "
            f"{core_version}"
        )

    entries = [
        entry
        for entry in metadata.entry_points(group="paper_data_suite.modules")
        if entry.name == "scoreform"
    ]
    if len(entries) != 1:
        raise SystemExit(f"expected one ScoreForm entry point, found {len(entries)}")
    entry = entries[0]
    if entry.value != "scoreform.pds_module:get_module_profile":
        raise SystemExit(f"unexpected ScoreForm entry-point value: {entry.value}")
    provider = entry.load()
    if inspect.signature(provider).parameters:
        raise SystemExit("ScoreForm profile provider must take no arguments")

    first = validate_module_profile(provider())
    second = validate_module_profile(provider())
    if first != second:
        raise SystemExit("ScoreForm profile provider is not repeatable")
    expected = {
        "module_id": "scoreform",
        "display_name": "ScoreForm",
        "supported_core_routing_contract_versions": frozenset({"1"}),
        "supported_qr_schemas": frozenset({"PDS2"}),
        "supported_route_registration_schema_versions": frozenset({"1"}),
        "dispatchable_route_statuses": frozenset({"active"}),
    }
    for field, value in expected.items():
        if getattr(first, field) != value:
            raise SystemExit(f"profile mismatch for {field}: {getattr(first, field)!r}")

    discovered = [
        profile for profile in discover_module_profiles() if profile.module_id == "scoreform"
    ]
    if discovered != [first]:
        raise SystemExit("Core did not discover exactly one equivalent ScoreForm profile")
    forbidden = [name for name in sys.modules if "quillan" in name.lower() or "concord" in name.lower()]
    if forbidden:
        raise SystemExit(f"profile discovery imported sibling modules: {forbidden}")
    if args.workspace.exists():
        raise SystemExit("profile discovery created workspace state")

    scoreform = importlib.import_module("scoreform")
    pds_core = importlib.import_module("pds_core")

    for module in (scoreform, pds_core):
        module_file = module.__file__
        if module_file is None:
            raise SystemExit(f"installed module has no file origin: {module.__name__}")
        origin = Path(module_file).resolve()
        if "site-packages" not in {part.lower() for part in origin.parts}:
            raise SystemExit(f"module did not import from isolated installation: {origin}")
    print(f"ScoreForm {args.version}; pds-core {core_version}; profile discovery passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
