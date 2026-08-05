"""Verify installed ScoreForm metadata and Core module-profile discovery."""

from __future__ import annotations

import argparse
import importlib
import inspect
import sys
from importlib import metadata
from pathlib import Path

from pds_core.module_profiles import discover_module_profiles, validate_module_profile
from pds_core.routing_models import (
    ModuleRecordRef,
    ModuleWorkRef,
    RouteLocator,
    RouteRegistration,
)
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

CORE_VERSION_SPECIFIER = SpecifierSet(">=0.6,<0.7")


def core_version_is_supported(value: str) -> bool:
    return Version(value) in CORE_VERSION_SPECIFIER


def validate_core_runtime_versions(
    distribution_version: str,
    module_version: str | None,
    expected_version: str | None = None,
) -> None:
    if not core_version_is_supported(distribution_version):
        raise SystemExit(
            f"installed pds-core does not satisfy >=0.6,<0.7: {distribution_version}"
        )
    if module_version != distribution_version:
        raise SystemExit(
            "installed pds-core distribution and pds_core.__version__ disagree: "
            f"{distribution_version!r} != {module_version!r}"
        )
    if expected_version is not None and distribution_version != expected_version:
        raise SystemExit(
            f"installed pds-core version {distribution_version} does not match "
            f"expected baseline {expected_version}"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default="0.9.1")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--expected-core-version")
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
    pds_core = importlib.import_module("pds_core")
    module_core_version = getattr(pds_core, "__version__", None)
    validate_core_runtime_versions(
        core_version, module_core_version, args.expected_core_version
    )

    for module_name in (
        "pds_core.academic_work_registrations",
        "pds_core.publication_records",
        "pds_core.publication_compatibility",
        "scoreform.academic_work_registration",
        "scoreform.cli_academic_work",
        "scoreform.academic_result_manifest_generation",
        "scoreform.cli_manifest",
    ):
        importlib.import_module(module_name)

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

    page_id = "pg_" + "2" * 32
    registration = RouteRegistration(
        schema_version="1",
        locator=RouteLocator(
            "PDS2",
            ModuleWorkRef("scoreform", "class1", "quiz1"),
            "rt_" + "1" * 32,
        ),
        target=ModuleRecordRef("scoreform", "answer_sheet_page", page_id, "1"),
        created_at="2026-01-01T00:00:00+00:00",
        status="active",
        human_fallback=(
            "ScoreForm | class=class1 | assignment=quiz1 | student=student1 | "
            f"page=1/1 | page_id={page_id}"
        ),
        module_details={
            "issuance_id": "iss_" + "3" * 32,
            "logical_page": 1,
            "total_pages": 1,
        },
    )
    before_details = registration.module_details
    if first.registration_validator(registration) is not None:
        raise SystemExit("ScoreForm registration validator must return None")
    if registration.module_details != before_details:
        raise SystemExit("ScoreForm registration validator mutated the Core model")

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
