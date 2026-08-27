"""Verify the ScoreForm v0.11.0 release compatibility boundary."""

from __future__ import annotations

import ast
import inspect
import tomllib
from pathlib import Path

from pds_core.module_operations import (
    MODULE_OPERATIONS_CONTRACT_VERSION,
    validate_module_operations_profile,
)
from pip._vendor.packaging.requirements import Requirement
from pip._vendor.packaging.specifiers import SpecifierSet
from pip._vendor.packaging.utils import canonicalize_name

import scoreform.academic_result_reader as reader
from scoreform.pds_contract import (
    ACADEMIC_RESULT_MANIFEST_CONTRACT_VERSION,
    SCOREFORM_ACADEMIC_WORK_CONTRACT_VERSION,
    SCOREFORM_MODULE_ID,
)
from scoreform.pds_operations import get_module_operations_profile
from scoreform.pds_publication import get_publication_producer_profile
from scoreform.publication_revision_policy import (
    SCOREFORM_ACADEMIC_RESULT_PUBLICATION_KIND,
    SCOREFORM_ACADEMIC_RESULT_RECORD_SET_ID,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RELEASE_VERSION = "0.11.0"
HISTORICAL_RELEASE_VERSION = "0.10.0"
EXPECTED_CORE_SPECIFIER = SpecifierSet(">=0.6.2,<0.7")
EXPECTED_CAPABILITIES = frozenset(
    {"points", "question_evidence", "multiple_attempts"}
)

LIVE_VERSION_FILES = (
    Path("pyproject.toml"),
    Path("run_tests.ps1"),
    Path(".github/workflows/release-readiness.yml"),
    Path("scripts/validate_release_install.ps1"),
    Path("scripts/verify_installed_release.py"),
    Path("scripts/verify_installed_producer_acceptance.py"),
    Path("scripts/verify_release_artifacts.py"),
    Path("tests/test_cli_discoverability.py"),
    Path("tests/test_release_artifacts.py"),
    Path("tests/fixtures/release/physical_acceptance_assignment.json"),
    Path("docs/cli_contract.md"),
    Path("docs/development_plan.md"),
    Path("docs/installed_producer_acceptance.md"),
    Path("docs/release_checklist.md"),
)
HISTORICAL_RELEASE_FILES = (
    Path("RELEASE_NOTES_v0.10.0.md"),
    Path("docs/v0.10.0_release_compatibility.md"),
    Path("docs/physical_acceptance_test.md"),
)
REQUIRED_V011_FILES = (
    Path("RELEASE_NOTES_v0.11.0.md"),
    Path("docs/v0.11.0_release_audit.md"),
    Path("scripts/verify_v011_physical_equivalence.py"),
)
README_RELEASE_MARKERS = (
    "Current version: `0.11.0`.",
    "scoreform-0.11.0-py3-none-any.whl",
    "RELEASE_NOTES_v0.11.0.md",
    "v0.11.0_release_audit.md",
)
CORE_RUNTIME_RELEASE_FILES = (
    Path("pyproject.toml"),
    Path("run_tests.ps1"),
    Path(".github/workflows/release-readiness.yml"),
    Path("scripts/validate_release_install.ps1"),
    Path("scripts/verify_installed_release.py"),
    Path("scripts/verify_installed_producer_acceptance.py"),
    Path("scripts/verify_release_artifacts.py"),
)
FORBIDDEN_CORE_05_MARKERS = (
    "pds-core>=0.5",
    "pds-core <0.6",
    "pds-core<0.6",
    "Core 0.5",
    "core 0.5",
)
SIBLING_DISTRIBUTIONS = frozenset(
    {
        "pds-meridian",
        "meridian",
        "pds-vitrine",
        "vitrine",
        "pds-quillan",
        "quillan",
        "pds-concord",
        "concord",
        "pds-portia",
        "portia",
        "paper-data-suite",
    }
)
SIBLING_IMPORT_ROOTS = frozenset(
    {
        "meridian",
        "pds_meridian",
        "vitrine",
        "pds_vitrine",
        "quillan",
        "pds_quillan",
        "concord",
        "pds_concord",
        "portia",
        "pds_portia",
        "paper_data_suite",
    }
)


class ReleaseCompatibilityError(RuntimeError):
    """Raised when the v0.11.0 release boundary is internally inconsistent."""


def _read(relative: Path) -> str:
    path = PROJECT_ROOT / relative
    if not path.is_file():
        raise ReleaseCompatibilityError(f"missing required release file: {relative}")
    return path.read_text(encoding="utf-8")


def validate_release_identity() -> None:
    project = tomllib.loads(_read(Path("pyproject.toml")))["project"]
    if project.get("name") != "scoreform":
        raise ReleaseCompatibilityError("project distribution name must be scoreform")
    if project.get("version") != RELEASE_VERSION:
        raise ReleaseCompatibilityError(
            f"project version must be {RELEASE_VERSION}"
        )

    for relative in LIVE_VERSION_FILES:
        text = _read(relative)
        if RELEASE_VERSION not in text:
            raise ReleaseCompatibilityError(
                f"live release surface does not name {RELEASE_VERSION}: {relative}"
            )

    for relative in REQUIRED_V011_FILES:
        _read(relative)

    readme = _read(Path("README.md"))
    missing_markers = tuple(
        marker for marker in README_RELEASE_MARKERS if marker not in readme
    )
    if missing_markers:
        raise ReleaseCompatibilityError(
            "README is missing authoritative v0.11.0 release marker(s): "
            + ", ".join(repr(marker) for marker in missing_markers)
        )

    # Historical release evidence must remain historical rather than being
    # rewritten by a blind version sweep.
    for relative in HISTORICAL_RELEASE_FILES:
        text = _read(relative)
        if HISTORICAL_RELEASE_VERSION not in text:
            raise ReleaseCompatibilityError(
                f"historical release surface lost {HISTORICAL_RELEASE_VERSION}: "
                f"{relative}"
            )


def validate_core_dependency() -> None:
    project = tomllib.loads(_read(Path("pyproject.toml")))["project"]
    dependencies = tuple(Requirement(value) for value in project["dependencies"])
    core = tuple(
        requirement
        for requirement in dependencies
        if canonicalize_name(requirement.name) == "pds-core"
    )
    if len(core) != 1 or core[0].specifier != EXPECTED_CORE_SPECIFIER:
        raise ReleaseCompatibilityError(
            "ScoreForm must require exactly pds-core>=0.6.2,<0.7"
        )
    if core[0].url is not None or core[0].marker is not None or core[0].extras:
        raise ReleaseCompatibilityError(
            "pds-core dependency must not use URL, marker, or extras"
        )

    sibling_dependencies = sorted(
        requirement.name
        for requirement in dependencies
        if canonicalize_name(requirement.name)
        in {canonicalize_name(value) for value in SIBLING_DISTRIBUTIONS}
    )
    if sibling_dependencies:
        raise ReleaseCompatibilityError(
            "ScoreForm has sibling runtime dependencies: "
            + ", ".join(sibling_dependencies)
        )

    for relative in CORE_RUNTIME_RELEASE_FILES:
        text = _read(relative)
        for marker in FORBIDDEN_CORE_05_MARKERS:
            if marker in text:
                raise ReleaseCompatibilityError(
                    f"live Core 0.5 marker {marker!r} remains in {relative}"
                )


def _import_root(node: ast.AST) -> tuple[str, ...]:
    if isinstance(node, ast.Import):
        return tuple(alias.name.split(".", 1)[0] for alias in node.names)
    if isinstance(node, ast.ImportFrom) and node.module:
        return (node.module.split(".", 1)[0],)
    return ()


def validate_sibling_import_isolation() -> None:
    offenders: list[str] = []
    for path in sorted((PROJECT_ROOT / "scoreform").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            for root in _import_root(node):
                if root in SIBLING_IMPORT_ROOTS:
                    offenders.append(
                        f"{path.relative_to(PROJECT_ROOT)}:"
                        f"{getattr(node, 'lineno', '?')} imports {root}"
                    )
    if offenders:
        raise ReleaseCompatibilityError(
            "ScoreForm production imports sibling modules: " + "; ".join(offenders)
        )


def validate_producer_profile() -> None:
    profile = get_publication_producer_profile()
    if profile.module_id != SCOREFORM_MODULE_ID or SCOREFORM_MODULE_ID != "scoreform":
        raise ReleaseCompatibilityError("producer module identity changed")
    if profile.supported_core_publication_schema_versions != frozenset({"1"}):
        raise ReleaseCompatibilityError("Core publication schema support changed")
    if profile.supported_academic_work_contract_versions != frozenset(
        {SCOREFORM_ACADEMIC_WORK_CONTRACT_VERSION}
    ):
        raise ReleaseCompatibilityError("Academic Work contract support changed")
    if SCOREFORM_ACADEMIC_WORK_CONTRACT_VERSION != "scoreform_academic_work_v1":
        raise ReleaseCompatibilityError("Academic Work contract identity changed")
    if len(profile.publication_contracts) != 1:
        raise ReleaseCompatibilityError("ScoreForm must expose one publication support row")

    support = profile.publication_contracts[0]
    if (
        support.publication_kind != SCOREFORM_ACADEMIC_RESULT_PUBLICATION_KIND
        or SCOREFORM_ACADEMIC_RESULT_PUBLICATION_KIND != "academic_result_set"
        or support.manifest_contract_versions
        != frozenset({ACADEMIC_RESULT_MANIFEST_CONTRACT_VERSION})
        or ACADEMIC_RESULT_MANIFEST_CONTRACT_VERSION
        != "scoreform_academic_result_manifest_v1"
        or support.supported_capabilities != EXPECTED_CAPABILITIES
        or support.source_record_contracts != ()
        or support.allows_missing_source_record is not True
        or SCOREFORM_ACADEMIC_RESULT_RECORD_SET_ID != "academic_results"
    ):
        raise ReleaseCompatibilityError("ScoreForm publication support row changed")


def validate_operations_profile() -> None:
    profile = validate_module_operations_profile(get_module_operations_profile())
    if profile.module_id != SCOREFORM_MODULE_ID:
        raise ReleaseCompatibilityError("operations module identity changed")
    if profile.supported_core_operations_contract_versions != frozenset(
        {MODULE_OPERATIONS_CONTRACT_VERSION}
    ):
        raise ReleaseCompatibilityError(
            "Core module-operations contract support changed"
        )
    if profile.attention_provider is None:
        raise ReleaseCompatibilityError(
            "ScoreForm operations profile must expose attention"
        )
    if profile.readiness_provider is None:
        raise ReleaseCompatibilityError(
            "ScoreForm operations profile must expose readiness"
        )


def validate_reader_policy_boundary() -> None:
    public = tuple(getattr(reader, "__all__", ()))
    required = {
        "read_academic_result_manifest",
        "validate_academic_result_manifest",
        "lookup_academic_result_source",
        "lookup_academic_result_student",
        "lookup_academic_result_attempt",
        "lookup_academic_result_question",
        "lookup_academic_result_response",
    }
    if not required.issubset(public):
        raise ReleaseCompatibilityError("public reader surface is incomplete")

    forbidden_fragments = (
        "latest",
        "highest",
        "best",
        "official",
        "grade",
        "proficiency",
        "mastery",
        "portfolio",
        "candidate",
    )
    forbidden_public = sorted(
        name
        for name in public
        if any(fragment in name.lower() for fragment in forbidden_fragments)
    )
    if forbidden_public:
        raise ReleaseCompatibilityError(
            "consumer policy leaked into public reader surface: "
            + ", ".join(forbidden_public)
        )

    attempt_signature = inspect.signature(reader.lookup_academic_result_attempt)
    if tuple(attempt_signature.parameters) != (
        "manifest",
        "student_id",
        "attempt_number",
    ):
        raise ReleaseCompatibilityError(
            "attempt lookup must require exact manifest/student/attempt identity"
        )
    if (
        attempt_signature.parameters["attempt_number"].default
        is not inspect.Parameter.empty
    ):
        raise ReleaseCompatibilityError("attempt lookup must not provide a fallback")


def validate_release_compatibility() -> None:
    validate_release_identity()
    validate_core_dependency()
    validate_sibling_import_isolation()
    validate_producer_profile()
    validate_operations_profile()
    validate_reader_policy_boundary()


def main() -> int:
    try:
        validate_release_compatibility()
    except (OSError, SyntaxError, KeyError, ReleaseCompatibilityError) as error:
        print(f"Release compatibility audit failed: {error}")
        return 1

    print(
        "ScoreForm v0.11.0 release compatibility passed: "
        "Core >=0.6.2,<0.7; producer/operations profiles exact; reader "
        "policy-neutral; sibling runtime imports absent; historical v0.10.0 "
        "release evidence preserved."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
