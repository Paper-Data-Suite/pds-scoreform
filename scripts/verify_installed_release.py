"""Verify installed ScoreForm metadata and independent Core profile discovery."""

from __future__ import annotations

import argparse
import importlib
import inspect
import sys
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path

from pds_core.academic_work_registrations import AcademicWorkRegistration
from pds_core.module_profiles import discover_module_profiles, validate_module_profile
from pds_core.publication_compatibility import (
    build_publication_producer_registry,
    discover_publication_producer_profiles,
    evaluate_publication_compatibility,
    validate_publication_producer_profile,
)
from pds_core.publication_records import PublicationRecord
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
        "scoreform.academic_result_reader",
        "scoreform.academic_work_registration",
        "scoreform.cli_academic_work",
        "scoreform.academic_result_manifest_generation",
        "scoreform.academic_result_publication",
        "scoreform.cli_manifest",
        "scoreform.cli_publication",
        "scoreform.menu_publication",
        "scoreform.pds_publication",
    ):
        importlib.import_module(module_name)

    reader = importlib.import_module("scoreform.academic_result_reader")
    expected_reader_public = (
        "AcademicResultManifest",
        "AcademicResultSourceName",
        "AcademicResultSourceSnapshot",
        "AssignmentSourceSnapshot",
        "Attempt",
        "Question",
        "Response",
        "ResultsHistorySourceSnapshot",
        "ScoreFormAcademicResultReaderDecodeError",
        "ScoreFormAcademicResultReaderError",
        "ScoreFormAcademicResultReaderNotFoundError",
        "ScoreFormAcademicResultReaderValidationError",
        "StudentResults",
        "lookup_academic_result_attempt",
        "lookup_academic_result_question",
        "lookup_academic_result_response",
        "lookup_academic_result_source",
        "lookup_academic_result_student",
        "read_academic_result_manifest",
        "validate_academic_result_manifest",
    )
    if getattr(reader, "__all__", None) != expected_reader_public:
        raise SystemExit("installed ScoreForm academic-result reader surface mismatch")

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

    publication_entries = [
        entry
        for entry in metadata.entry_points(
            group="paper_data_suite.publication_producers"
        )
        if entry.name == "scoreform"
    ]
    if len(publication_entries) != 1:
        raise SystemExit(
            "expected one ScoreForm publication-producer entry point, found "
            f"{len(publication_entries)}"
        )
    publication_entry = publication_entries[0]
    expected_publication_value = (
        "scoreform.pds_publication:get_publication_producer_profile"
    )
    if publication_entry.value != expected_publication_value:
        raise SystemExit(
            "unexpected ScoreForm publication entry-point value: "
            f"{publication_entry.value}"
        )
    publication_provider = publication_entry.load()
    if inspect.signature(publication_provider).parameters:
        raise SystemExit("ScoreForm publication profile provider must take no arguments")
    publication_first = validate_publication_producer_profile(
        publication_provider()
    )
    publication_second = validate_publication_producer_profile(
        publication_provider()
    )
    if publication_first != publication_second:
        raise SystemExit("ScoreForm publication profile provider is not repeatable")
    expected_publication = {
        "module_id": "scoreform",
        "display_name": "ScoreForm",
        "supported_core_publication_schema_versions": frozenset({"1"}),
        "supported_academic_work_contract_versions": frozenset(
            {"scoreform_academic_work_v1"}
        ),
    }
    for field, value in expected_publication.items():
        if getattr(publication_first, field) != value:
            raise SystemExit(
                f"publication profile mismatch for {field}: "
                f"{getattr(publication_first, field)!r}"
            )
    if len(publication_first.publication_contracts) != 1:
        raise SystemExit("ScoreForm publication profile must contain one support row")
    support = publication_first.publication_contracts[0]
    if (
        support.publication_kind != "academic_result_set"
        or support.manifest_contract_versions
        != frozenset({"scoreform_academic_result_manifest_v1"})
        or support.supported_capabilities
        != frozenset({"points", "question_evidence", "multiple_attempts"})
        or support.source_record_contracts != ()
        or support.allows_missing_source_record is not True
    ):
        raise SystemExit("ScoreForm publication support row is not exact")

    publication_profiles = [
        profile
        for profile in discover_publication_producer_profiles()
        if profile.module_id == "scoreform"
    ]
    if publication_profiles != [publication_first]:
        raise SystemExit(
            "Core did not discover exactly one equivalent ScoreForm publication profile"
        )
    if (
        build_publication_producer_registry().get("scoreform")
        != publication_first
    ):
        raise SystemExit("Core publication registry did not resolve ScoreForm")

    now = datetime(2026, 8, 6, 12, tzinfo=UTC)
    work = ModuleWorkRef("scoreform", "class1", "quiz1")
    academic_registration = AcademicWorkRegistration(
        schema_version="1",
        record_type="academic_work_registration",
        work=work,
        registration_revision=1,
        producer_contract_version="scoreform_academic_work_v1",
        title="Quiz 1",
        work_kind="assignment",
        academic_intent="summative",
        lifecycle="active",
        created_at=now,
        updated_at=now,
        source_records=(
            ModuleRecordRef("scoreform", "assignment", "quiz1", None),
        ),
    )
    publication = PublicationRecord(
        schema_version="1",
        record_type="publication_record",
        publication_id="pub_" + "1" * 32,
        work=work,
        source_record=None,
        publication_kind="academic_result_set",
        capabilities=("points", "question_evidence", "multiple_attempts"),
        record_set_id="academic_results",
        record_set_revision=1,
        manifest_contract_version="scoreform_academic_result_manifest_v1",
        manifest_path=(
            "classes/class1/modules/scoreform/work/quiz1/"
            "exports/manifests/academic_results/1.json"
        ),
        manifest_digest_algorithm="sha256",
        manifest_digest="0" * 64,
        published_at=now,
        academic_work_registration_revision=1,
        supersedes_publication_id=None,
    )
    compatibility = evaluate_publication_compatibility(
        publication, publication_first, academic_registration
    )
    if not compatibility.compatible or compatibility.codes:
        raise SystemExit(
            f"installed ScoreForm compatibility evaluation failed: {compatibility.codes}"
        )
    if publication.source_record is not None:
        raise SystemExit("synthetic ScoreForm publication source record must be absent")

    sibling_roots = {
        "quillan",
        "concord",
        "portia",
        "meridian",
        "pds_meridian",
        "vitrine",
    }
    forbidden = [
        name for name in sys.modules if name.split(".", 1)[0] in sibling_roots
    ]
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
    print(
        f"ScoreForm {args.version}; pds-core {core_version}; "
        "routing/publication profile discovery and compatibility passed"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
