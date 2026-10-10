"""Installed-wheel acceptance for ScoreForm reader contract v1 (Issue #227).

Run with an isolated wheel installation from a directory outside the repository.
Reads only the committed synthetic manifest fixture; never accesses a PDS workspace.
"""

from __future__ import annotations

import argparse
import inspect
import json
import site
import sys
from dataclasses import replace
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path

CORE_VERSION = "0.6.5"
MANIFEST = "scoreform_academic_result_manifest_v1"
READER = "scoreform_academic_result_reader_v1"
FIXTURE = Path("tests/fixtures/publication/scoreform_academic_result_manifest_v1.json")


class ReaderContractAcceptanceError(RuntimeError):
    """Bounded installed qualification failure."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ReaderContractAcceptanceError(message)


def _is_installed_origin(module: object) -> bool:
    filename = getattr(module, "__file__", None)
    if not isinstance(filename, str):
        return False
    origin = Path(filename).resolve()
    return any(
        origin.is_relative_to(Path(root).resolve())
        for root in site.getsitepackages()
    )


def verify(
    *,
    repository: Path,
    workspace: Path,
    scoreform_version: str,
    core_version: str,
) -> None:
    repository = repository.resolve(strict=True)
    workspace = workspace.resolve(strict=False)
    require(workspace != repository and not workspace.is_relative_to(repository),
            "Workspace sentinel must be outside the source checkout.")
    require(not workspace.exists(), "Workspace sentinel unexpectedly exists.")
    require(not Path.cwd().resolve().is_relative_to(repository),
            "Installed qualification must run outside the checkout.")
    require(sys.prefix != sys.base_prefix, "Installed qualification requires a virtual environment.")
    require(core_version == CORE_VERSION, "Core qualification version is unsupported.")
    require(metadata.version("scoreform") == scoreform_version,
            "Installed ScoreForm distribution version differs.")
    require(metadata.version("pds-core") == core_version,
            "Installed Core distribution version differs.")

    import pds_core
    from pds_core.academic_work_registrations import AcademicWorkRegistration
    from pds_core.publication_compatibility import (
        PublicationReaderSupport,
        build_publication_producer_registry,
        discover_publication_producer_profiles,
        evaluate_publication_compatibility,
        lookup_publication_reader_support,
        validate_publication_producer_profile,
    )
    from pds_core.publication_records import PublicationRecord
    from pds_core.routing_models import ModuleRecordRef, ModuleWorkRef

    import scoreform

    require(pds_core.__version__ == core_version,
            "Core module/distribution identity differs.")
    require(_is_installed_origin(pds_core) and _is_installed_origin(scoreform),
            "ScoreForm and Core must import from isolated site-packages.")
    require("scoreform.academic_result_reader" not in sys.modules,
            "Reader was imported before metadata discovery.")

    entries = tuple(metadata.entry_points().select(
        group="paper_data_suite.publication_producers", name="scoreform"
    ))
    require(len(entries) == 1,
            "Expected exactly one installed ScoreForm producer entry point.")
    require(entries[0].value ==
            "scoreform.pds_publication:get_publication_producer_profile",
            "Installed producer entry point has changed.")
    provider = entries[0].load()
    require(not inspect.signature(provider).parameters,
            "Installed producer provider must take no arguments.")
    profile = validate_publication_producer_profile(provider())
    require(provider() == profile, "Producer metadata is not repeatable.")
    require(profile.module_id == "scoreform", "Producer module identity differs.")
    require(len(profile.publication_contracts) == 1,
            "Producer support row count differs.")
    support = profile.publication_contracts[0]
    require(support.publication_kind == "academic_result_set" and
            support.manifest_contract_versions == frozenset({MANIFEST}) and
            support.supported_capabilities == frozenset(
                {"points", "question_evidence", "multiple_attempts"}
            ) and support.source_record_contracts == () and
            support.allows_missing_source_record is True,
            "Producer publication contracts differ.")
    declared = PublicationReaderSupport(
        manifest_contract_version=MANIFEST,
        distribution_name="scoreform",
        reader_contract_version=READER,
    )
    require(support.reader_support == (declared,),
            "Reader metadata declaration differs.")
    require(lookup_publication_reader_support(
        profile, "academic_result_set", MANIFEST
    ) == declared, "Exact Core reader lookup failed.")
    require(lookup_publication_reader_support(
        profile, "intervention_record_set", MANIFEST
    ) is None, "Wrong publication kind inferred a reader.")
    require(lookup_publication_reader_support(
        profile, "academic_result_set", "unknown_manifest_v1"
    ) is None, "Wrong manifest contract inferred a reader.")
    legacy = replace(
        profile,
        publication_contracts=(replace(support, reader_support=()),),
    )
    require(lookup_publication_reader_support(
        legacy, "academic_result_set", MANIFEST
    ) is None, "Legacy producer inferred an undeclared reader.")
    discovered = [item for item in discover_publication_producer_profiles()
                  if item.module_id == "scoreform"]
    require(discovered == [profile], "Installed Core discovery differs.")
    require(build_publication_producer_registry().get("scoreform") == profile,
            "Installed Core registry differs.")
    require("scoreform.academic_result_reader" not in sys.modules,
            "Metadata-only Core discovery imported the public reader.")
    require(not workspace.exists(), "Metadata discovery created workspace state.")
    # Reader metadata must not change Core publication compatibility results.
    now = datetime(2026, 8, 6, 12, tzinfo=UTC)
    work = ModuleWorkRef("scoreform", "synthetic_class", "synthetic_quiz")
    published = PublicationRecord(
        schema_version="1",
        record_type="publication_record",
        publication_id="pub_" + "1" * 32,
        work=work,
        source_record=None,
        publication_kind="academic_result_set",
        capabilities=("points", "question_evidence", "multiple_attempts"),
        record_set_id="academic_results",
        record_set_revision=1,
        manifest_contract_version=MANIFEST,
        manifest_path=(
            "classes/synthetic_class/modules/scoreform/work/synthetic_quiz/"
            "exports/manifests/academic_results/1.json"
        ),
        manifest_digest_algorithm="sha256",
        manifest_digest="0" * 64,
        published_at=now,
        academic_work_registration_revision=1,
        supersedes_publication_id=None,
    )
    registration = AcademicWorkRegistration(
        schema_version="1",
        record_type="academic_work_registration",
        work=work,
        registration_revision=1,
        producer_contract_version="scoreform_academic_work_v1",
        title="Synthetic Reader Qualification",
        work_kind="assignment",
        academic_intent="summative",
        lifecycle="active",
        created_at=now,
        updated_at=now,
        source_records=(
            ModuleRecordRef("scoreform", "assignment", "synthetic_quiz", None),
        ),
    )
    for supplied in (registration, None):
        before = evaluate_publication_compatibility(published, legacy, supplied)
        after = evaluate_publication_compatibility(published, profile, supplied)
        require(before == after,
                "Reader metadata changed Core publication compatibility.")
    require(evaluate_publication_compatibility(
        published, profile, registration
    ).compatible, "Synthetic publication compatibility failed.")

    from scoreform.academic_result_manifest import (
        Pds2ScanProvenance,
        PlainPaperManualProvenance,
        ScanReviewManualProvenance,
        manifest_from_mapping,
        manifest_to_canonical_json_bytes,
    )
    from scoreform.academic_result_reader import (
        ScoreFormAcademicResultReaderDecodeError,
        ScoreFormAcademicResultReaderNotFoundError,
        ScoreFormAcademicResultReaderValidationError,
        lookup_academic_result_attempt,
        lookup_academic_result_question,
        lookup_academic_result_response,
        lookup_academic_result_source,
        lookup_academic_result_student,
        read_academic_result_manifest,
        validate_academic_result_manifest,
    )

    require(_is_installed_origin(sys.modules["scoreform.academic_result_reader"]),
            "Public reader did not import from the installed wheel.")
    fixture_path = repository / FIXTURE
    require(fixture_path.is_file(), "Committed synthetic reader fixture is missing.")
    raw = fixture_path.read_bytes()
    loaded = read_academic_result_manifest(raw)
    require(manifest_to_canonical_json_bytes(loaded) == raw,
            "Canonical manifest bytes did not round-trip.")
    require(validate_academic_result_manifest(loaded) == loaded,
            "Public model revalidation changed the manifest.")
    require(loaded.work.module_id == "scoreform" and
            loaded.assignment.assignment_id == "synthetic_quiz_1",
            "Manifest work/assignment identity differs.")
    require(lookup_academic_result_source(loaded, "assignment") ==
            loaded.source_snapshot.assignment and
            lookup_academic_result_source(loaded, "results_history") ==
            loaded.source_snapshot.results_history,
            "Exact source-snapshot lookup differs.")
    require(len(lookup_academic_result_student(loaded, "student_alpha").attempts) == 2,
            "Student attempts were collapsed.")
    first = lookup_academic_result_attempt(loaded, "student_alpha", 1)
    second = lookup_academic_result_attempt(loaded, "student_alpha", 2)
    manual = lookup_academic_result_attempt(loaded, "student_beta", 1)
    require(first.result_origin == "pds2_scan" and
            isinstance(first.provenance, Pds2ScanProvenance) and
            second.result_origin == "scan_review_manual" and
            isinstance(second.provenance, ScanReviewManualProvenance) and
            manual.result_origin == "plain_paper_manual" and
            isinstance(manual.provenance, PlainPaperManualProvenance),
            "Attempt provenance identities differ.")
    require(first.points_earned == 2 and second.points_earned == 1 and
            manual.points_earned == 3,
            "Independent attempt scores differ.")
    require(lookup_academic_result_response(
        loaded, "student_alpha", 1, 2
    ).response_state == "blank", "Blank response was changed.")
    require(lookup_academic_result_response(
        loaded, "student_alpha", 2, 2
    ).response_state == "ambiguous", "Ambiguous response was changed.")
    require(lookup_academic_result_response(
        loaded, "student_beta", 1, 2
    ).response_state == "selected", "Selected response was changed.")

    mapping = json.loads(raw)
    mapping["assignment"]["standards_profile_id"] = "english12.njsls.2023"
    mapping["assignment"]["questions"][0]["standard_ids"] = [
        "njsls-ela:RL.TS.11-12.4"
    ]
    mapping["assignment"]["questions"][1]["standard_ids"] = [
        "njsls-ela:W.NW.11-12.3.D"
    ]
    standards_bytes = manifest_to_canonical_json_bytes(
        manifest_from_mapping(mapping)
    )
    standards = read_academic_result_manifest(standards_bytes)
    require(standards.assignment.standards_profile_id == "english12.njsls.2023" and
            lookup_academic_result_question(
                standards, 1
            ).standard_ids == ("njsls-ela:RL.TS.11-12.4",) and
            lookup_academic_result_question(
                standards, 2
            ).standard_ids == ("njsls-ela:W.NW.11-12.3.D",),
            "Punctuation-bearing Standards identities were altered.")
    require(manifest_to_canonical_json_bytes(standards) == standards_bytes,
            "Standards-aware canonical serialization differs.")

    try:
        read_academic_result_manifest(raw + b" ")
    except ScoreFormAcademicResultReaderValidationError:
        pass
    else:
        raise ReaderContractAcceptanceError("Noncanonical bytes were accepted.")
    try:
        read_academic_result_manifest(b"\xff")
    except ScoreFormAcademicResultReaderDecodeError:
        pass
    else:
        raise ReaderContractAcceptanceError("Malformed bytes were accepted.")
    try:
        lookup_academic_result_attempt(loaded, "student_alpha", 3)
    except ScoreFormAcademicResultReaderNotFoundError:
        pass
    else:
        raise ReaderContractAcceptanceError("Missing attempt was inferred.")

    require(not workspace.exists(), "Reader created workspace state.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--scoreform-version", required=True)
    parser.add_argument("--core-version", required=True)
    args = parser.parse_args()
    try:
        verify(
            repository=args.repository,
            workspace=args.workspace,
            scoreform_version=args.scoreform_version,
            core_version=args.core_version,
        )
    except (ReaderContractAcceptanceError, OSError, metadata.PackageNotFoundError) as error:
        print(f"Issue #227 installed reader acceptance failed: {error}", file=sys.stderr)
        return 1
    print("Issue #227 installed reader contract v1 acceptance passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
