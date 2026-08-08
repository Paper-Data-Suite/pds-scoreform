"""Installed clean-wheel producer acceptance for ScoreForm academic results."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import sys
from collections.abc import Callable
from importlib import metadata
from pathlib import Path
from typing import Literal, TypeVar, cast

import pds_core
from pds_core.academic_catalog import (
    CatalogPublication,
    PublicationCatalogQuery,
    query_publication_catalog,
    rebuild_academic_catalog,
)
from pds_core.academic_work_registration_storage import (
    load_current_academic_work_registration,
)
from pds_core.academic_work_registrations import AcademicWorkRegistration
from pds_core.publication_storage import (
    get_current_publication_record,
    list_publication_record_set,
    verify_publication_manifest,
)
from pds_core.registry_audit import (
    RegistryAuditOptions,
    audit_academic_registry,
)
from pds_core.registry_paths import (
    publication_record_path,
    publication_withdrawal_path,
)
from pds_core.routing_models import ModuleRecordRef
from pip._vendor.packaging.requirements import Requirement
from pip._vendor.packaging.utils import canonicalize_name
from pip._vendor.packaging.version import Version

from scoreform.academic_result_manifest import (
    AcademicResultManifest,
    PlainPaperManualProvenance,
)
from scoreform.academic_result_manifest_generation import (
    AcademicResultManifestGenerationResult,
    generate_academic_result_manifest,
)
from scoreform.academic_result_publication import (
    SCOREFORM_PUBLICATION_CAPABILITIES,
    AcademicResultPublicationResult,
    AcademicResultWithdrawalResult,
    publish_scoreform_academic_results,
    supersede_scoreform_academic_results,
    withdraw_scoreform_academic_result_publication,
)
from scoreform.academic_result_reader import (
    lookup_academic_result_attempt,
    lookup_academic_result_question,
    lookup_academic_result_response,
    lookup_academic_result_source,
    lookup_academic_result_student,
    read_academic_result_manifest,
)
from scoreform.academic_work_registration import (
    SCOREFORM_ACADEMIC_WORK_KIND,
    SCOREFORM_ASSIGNMENT_SOURCE_RECORD_KIND,
    load_current_scoreform_academic_work_registration,
    register_scoreform_academic_work,
)
from scoreform.assignment import assignment_from_json_bytes, validate_assignment_data
from scoreform.layouts import DEFAULT_LAYOUT_ID, require_layout
from scoreform.page_scoring import ScoredAnswer
from scoreform.pds_contract import (
    ACADEMIC_RESULT_MANIFEST_CONTRACT_VERSION,
    SCOREFORM_ACADEMIC_WORK_CONTRACT_VERSION,
    SCOREFORM_MODULE_ID,
)
from scoreform.publication_revision_policy import (
    SCOREFORM_ACADEMIC_RESULT_PUBLICATION_KIND,
    SCOREFORM_ACADEMIC_RESULT_RECORD_SET_ID,
)
from scoreform.results import (
    ScoreFormRoutedResult,
    export_scoreform_result_models,
    load_routed_results_history,
)
from scoreform.work_paths import (
    ScoreFormWorkPaths,
    initialize_scoreform_work_layout,
    scoreform_work_ref,
)
from scoreform.workflows import write_assignment_json

SYNTHETIC_CLASS_ID = "acceptance_class"
SYNTHETIC_ASSIGNMENT_ID = "acceptance_quiz"
SYNTHETIC_STUDENT_ID = "synthetic_student"
SYNTHETIC_TITLE = "Synthetic Producer Acceptance"
WITHDRAWAL_REASON = "synthetic acceptance withdrawal"

STAGES = (
    "installed provenance",
    "synthetic native work",
    "academic-work registration",
    "manifest revision 1",
    "public reader revision 1",
    "initial publication",
    "publication replay",
    "catalog revision 1",
    "Core verification revision 1",
    "native successor",
    "manifest revision 2",
    "supersession",
    "catalog revision 2",
    "public reader revision 2",
    "withdrawal",
    "final catalog",
    "registry audit",
    "immutability",
)

_T = TypeVar("_T")


class AcceptanceFailure(RuntimeError):
    """Bounded stage-specific failure without student-level payload rendering."""

    def __init__(self, stage: str, message: str) -> None:
        if stage not in STAGES:
            raise ValueError("stage must be a known producer-acceptance stage.")
        if (
            not isinstance(message, str)
            or not message
            or "\n" in message
            or "\r" in message
        ):
            raise ValueError("message must be a nonempty single line.")
        super().__init__(f"{stage}: {message}")
        self.stage = stage
        self.message = message


def _require(condition: bool, stage: str, message: str) -> None:
    if not condition:
        raise AcceptanceFailure(stage, message)


def _run_stage(stage: str, action: Callable[[], _T]) -> _T:
    if stage not in STAGES:
        raise ValueError("unknown producer-acceptance stage")
    print(f"Running: {stage}")
    try:
        value = action()
    except AcceptanceFailure:
        raise
    except Exception as error:
        raise AcceptanceFailure(
            stage,
            f"production operation failed ({type(error).__name__}).",
        ) from error
    print(f"PASSED: {stage}")
    return value


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_path(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _module_origin(module_name: str) -> Path:
    module = importlib.import_module(module_name)
    module_file = getattr(module, "__file__", None)
    if not isinstance(module_file, str) or not module_file:
        raise ValueError("installed module has no file origin")
    return Path(module_file).resolve()


def _is_isolated_installed_origin(path: Path) -> bool:
    try:
        prefix = Path(sys.prefix).resolve()
        resolved = path.resolve()
        return (
            resolved.is_relative_to(prefix)
            and "site-packages" in {part.lower() for part in resolved.parts}
        )
    except (OSError, RuntimeError, ValueError):
        return False


def _synthetic_assignment() -> dict[str, object]:
    layout = require_layout(DEFAULT_LAYOUT_ID)
    candidate: dict[str, object] = {
        "assignment_id": SYNTHETIC_ASSIGNMENT_ID,
        "title": SYNTHETIC_TITLE,
        "question_count": 3,
        "choices": list(layout.choices),
        "layout_id": layout.layout_id,
        "answer_key": {"1": "A", "2": "B", "3": "C"},
        "standards": {"1": [], "2": [], "3": []},
    }
    normalized = validate_assignment_data(candidate)
    if normalized is None:
        raise ValueError("synthetic assignment did not pass ScoreForm validation")
    return cast(dict[str, object], normalized)


def _synthetic_result(version: int) -> ScoreFormRoutedResult:
    if version == 1:
        answers = (
            ScoredAnswer(1, "A", True),
            ScoredAnswer(2, "BLANK", False),
            ScoredAnswer(3, "C", True),
        )
    elif version == 2:
        answers = (
            ScoredAnswer(1, "B", False),
            ScoredAnswer(2, "B", True),
            ScoredAnswer(3, "AMBIGUOUS", False),
        )
    else:
        raise ValueError("synthetic result version must be 1 or 2")
    return ScoreFormRoutedResult(
        result_origin="plain_paper_manual",
        class_id=SYNTHETIC_CLASS_ID,
        assignment_id=SYNTHETIC_ASSIGNMENT_ID,
        student_id=SYNTHETIC_STUDENT_ID,
        last_name="Synthetic",
        first_name="Student",
        period="acceptance",
        page_display="manual",
        score=sum(answer.correct for answer in answers),
        total_points=3,
        answers=answers,
        source_file="plain_paper_manual_entry",
    )


def _series_query(
    state: Literal["current", "series_heads", "historical", "withdrawn", "all"],
) -> PublicationCatalogQuery:
    return PublicationCatalogQuery(
        class_id=SYNTHETIC_CLASS_ID,
        module_id=SCOREFORM_MODULE_ID,
        work_id=SYNTHETIC_ASSIGNMENT_ID,
        publication_kind=SCOREFORM_ACADEMIC_RESULT_PUBLICATION_KIND,
        required_capabilities=SCOREFORM_PUBLICATION_CAPABILITIES,
        manifest_contract_version=ACADEMIC_RESULT_MANIFEST_CONTRACT_VERSION,
        record_set_id=SCOREFORM_ACADEMIC_RESULT_RECORD_SET_ID,
        state=state,
    )


def _query_series(
    workspace: Path,
    state: Literal["current", "series_heads", "historical", "withdrawn", "all"],
) -> tuple[CatalogPublication, ...]:
    return query_publication_catalog(workspace, _series_query(state))


def _verify_reader_revision(
    manifest: AcademicResultManifest,
    *,
    expected_attempts: int,
) -> None:
    assignment_source = lookup_academic_result_source(manifest, "assignment")
    results_source = lookup_academic_result_source(manifest, "results_history")
    _require(
        assignment_source.relative_path == "assignment.json",
        "public reader revision 1" if expected_attempts == 1 else "public reader revision 2",
        "assignment source lookup disagrees.",
    )
    _require(
        results_source.relative_path == "results.csv",
        "public reader revision 1" if expected_attempts == 1 else "public reader revision 2",
        "results source lookup disagrees.",
    )
    student = lookup_academic_result_student(manifest, SYNTHETIC_STUDENT_ID)
    _require(
        len(student.attempts) == expected_attempts,
        "public reader revision 1" if expected_attempts == 1 else "public reader revision 2",
        "reader attempt count disagrees.",
    )
    first = lookup_academic_result_attempt(manifest, SYNTHETIC_STUDENT_ID, 1)
    _require(
        first.attempt_number == 1 and isinstance(first.provenance, PlainPaperManualProvenance),
        "public reader revision 1" if expected_attempts == 1 else "public reader revision 2",
        "reader did not preserve attempt 1 provenance.",
    )
    question = lookup_academic_result_question(manifest, 1)
    _require(
        question.question_number == 1 and question.standard_ids == (),
        "public reader revision 1" if expected_attempts == 1 else "public reader revision 2",
        "question lookup disagrees.",
    )
    response = lookup_academic_result_response(
        manifest, SYNTHETIC_STUDENT_ID, 1, 2
    )
    _require(
        response.response_state == "blank"
        and response.selected_answer is None
        and not response.correct,
        "public reader revision 1" if expected_attempts == 1 else "public reader revision 2",
        "attempt-1 blank response was not preserved.",
    )
    if expected_attempts == 2:
        second = lookup_academic_result_attempt(
            manifest, SYNTHETIC_STUDENT_ID, 2
        )
        _require(
            second.attempt_number == 2
            and isinstance(second.provenance, PlainPaperManualProvenance),
            "public reader revision 2",
            "reader did not preserve attempt 2 provenance.",
        )
        ambiguous = lookup_academic_result_response(
            manifest, SYNTHETIC_STUDENT_ID, 2, 3
        )
        _require(
            ambiguous.response_state == "ambiguous"
            and ambiguous.selected_answer is None
            and not ambiguous.correct,
            "public reader revision 2",
            "attempt-2 ambiguous response was not preserved.",
        )


def _verify_publication_envelope(
    publication: object,
    *,
    revision: int,
    registration_revision: int,
    supersedes: str | None,
    stage: str,
) -> None:
    _require(
        getattr(publication, "work", None)
        == scoreform_work_ref(SYNTHETIC_CLASS_ID, SYNTHETIC_ASSIGNMENT_ID),
        stage,
        "publication work identity disagrees.",
    )
    _require(
        getattr(publication, "publication_kind", None)
        == SCOREFORM_ACADEMIC_RESULT_PUBLICATION_KIND,
        stage,
        "publication kind disagrees.",
    )
    _require(
        getattr(publication, "record_set_id", None)
        == SCOREFORM_ACADEMIC_RESULT_RECORD_SET_ID
        and getattr(publication, "record_set_revision", None) == revision,
        stage,
        "record-set identity or revision disagrees.",
    )
    _require(
        getattr(publication, "manifest_contract_version", None)
        == ACADEMIC_RESULT_MANIFEST_CONTRACT_VERSION,
        stage,
        "manifest contract disagrees.",
    )
    _require(
        getattr(publication, "source_record", object()) is None,
        stage,
        "ScoreForm publication fabricated a source record.",
    )
    _require(
        getattr(publication, "academic_work_registration_revision", None)
        == registration_revision,
        stage,
        "publication registration revision disagrees.",
    )
    _require(
        tuple(getattr(publication, "capabilities", ()))
        == SCOREFORM_PUBLICATION_CAPABILITIES,
        stage,
        "publication capabilities disagree.",
    )
    _require(
        getattr(publication, "manifest_digest_algorithm", None) == "sha256",
        stage,
        "publication digest algorithm disagrees.",
    )
    _require(
        getattr(publication, "supersedes_publication_id", object()) == supersedes,
        stage,
        "publication predecessor disagrees.",
    )


def _installed_provenance(
    workspace: Path,
    *,
    version: str,
    expected_core_version: str,
) -> None:
    _require(not workspace.exists(), "installed provenance", "workspace must begin absent.")
    _require(
        metadata.version("scoreform") == version,
        "installed provenance",
        "installed ScoreForm metadata version disagrees.",
    )
    core_version = metadata.version("pds-core")
    _require(
        core_version == expected_core_version,
        "installed provenance",
        "installed Core distribution version disagrees.",
    )
    _require(
        getattr(pds_core, "__version__", None) == core_version,
        "installed provenance",
        "Core module and distribution versions disagree.",
    )
    requirements = tuple(metadata.requires("scoreform") or ())
    parsed_requirements = tuple(Requirement(item) for item in requirements)
    core_requirements = tuple(
        item
        for item in parsed_requirements
        if canonicalize_name(item.name) == "pds-core"
    )
    _require(
        len(core_requirements) == 1
        and Version(core_version) in core_requirements[0].specifier,
        "installed provenance",
        "ScoreForm Core dependency metadata rejects the installed Core version.",
    )
    for module_name in (
        "scoreform",
        "scoreform.academic_work_registration",
        "scoreform.academic_result_manifest_generation",
        "scoreform.academic_result_publication",
        "scoreform.academic_result_reader",
        "scoreform.results",
        "scoreform.work_paths",
        "pds_core",
        "pds_core.academic_catalog",
        "pds_core.publication_storage",
        "pds_core.registry_audit",
    ):
        _require(
            _is_isolated_installed_origin(_module_origin(module_name)),
            "installed provenance",
            f"{module_name} did not import from isolated site-packages.",
        )
    sibling_roots = {"meridian", "pds_meridian", "vitrine", "quillan", "concord", "portia"}
    imported_siblings = sorted(
        name
        for name in sys.modules
        if name.split(".", 1)[0] in sibling_roots
    )
    _require(
        not imported_siblings,
        "installed provenance",
        "producer acceptance imported a sibling consumer or producer.",
    )


def _native_work(workspace: Path) -> ScoreFormWorkPaths:
    paths = initialize_scoreform_work_layout(
        workspace, SYNTHETIC_CLASS_ID, SYNTHETIC_ASSIGNMENT_ID
    )
    assignment = _synthetic_assignment()
    _require(
        write_assignment_json(paths.assignment_path, assignment),
        "synthetic native work",
        "could not write synthetic managed assignment.",
    )
    parsed = assignment_from_json_bytes(paths.assignment_path.read_bytes())
    _require(
        parsed["assignment_id"] == SYNTHETIC_ASSIGNMENT_ID
        and parsed["question_count"] == 3,
        "synthetic native work",
        "written assignment failed exact native validation.",
    )
    first = export_scoreform_result_models(
        (_synthetic_result(1),), workspace_root=workspace
    )
    _require(
        first.succeeded
        and len(first.appended_attempts) == 1
        and first.appended_attempts[0].attempt_number == 1,
        "synthetic native work",
        "initial schema-v2 manual attempt was not appended exactly once.",
    )
    history = load_routed_results_history(paths.results_path)
    _require(
        len(history) == 1
        and history[0].attempt_number == 1
        and history[0].result.result_origin == "plain_paper_manual",
        "synthetic native work",
        "initial native result history disagrees.",
    )
    return paths


def _register(
    workspace: Path, paths: ScoreFormWorkPaths
) -> AcademicWorkRegistration:
    first = register_scoreform_academic_work(
        workspace,
        SYNTHETIC_CLASS_ID,
        SYNTHETIC_ASSIGNMENT_ID,
        academic_intent="summative",
        lifecycle="active",
    )
    _require(
        first.disposition == "created"
        and first.registration.registration_revision == 1,
        "academic-work registration",
        "initial registration was not revision 1.",
    )
    replay = register_scoreform_academic_work(
        workspace,
        SYNTHETIC_CLASS_ID,
        SYNTHETIC_ASSIGNMENT_ID,
        academic_intent="summative",
        lifecycle="active",
    )
    _require(
        replay.disposition == "existing"
        and replay.registration == first.registration,
        "academic-work registration",
        "exact registration replay did not reuse revision 1.",
    )
    scoreform_current = load_current_scoreform_academic_work_registration(
        workspace, SYNTHETIC_CLASS_ID, SYNTHETIC_ASSIGNMENT_ID
    )
    core_current = load_current_academic_work_registration(
        workspace, paths.work_ref
    )
    expected_source = ModuleRecordRef(
        module_id=SCOREFORM_MODULE_ID,
        record_kind=SCOREFORM_ASSIGNMENT_SOURCE_RECORD_KIND,
        record_id=SYNTHETIC_ASSIGNMENT_ID,
        contract_version=None,
    )
    registration = first.registration
    _require(
        scoreform_current == registration == core_current,
        "academic-work registration",
        "ScoreForm/Core canonical registration reload disagrees.",
    )
    _require(
        registration.producer_contract_version
        == SCOREFORM_ACADEMIC_WORK_CONTRACT_VERSION
        and registration.work_kind == SCOREFORM_ACADEMIC_WORK_KIND
        and registration.work == paths.work_ref
        and registration.source_records == (expected_source,)
        and registration.lifecycle == "active",
        "academic-work registration",
        "registration contract fields disagree.",
    )
    return registration


def _manifest_one(
    workspace: Path, paths: ScoreFormWorkPaths
) -> AcademicResultManifestGenerationResult:
    generated = generate_academic_result_manifest(
        workspace, SYNTHETIC_CLASS_ID, SYNTHETIC_ASSIGNMENT_ID
    )
    _require(
        generated.revision == 1
        and generated.manifest.record_set.record_set_id
        == SCOREFORM_ACADEMIC_RESULT_RECORD_SET_ID
        and generated.manifest.record_set.revision == 1,
        "manifest revision 1",
        "initial producer manifest identity disagrees.",
    )
    _require(
        generated.manifest.source_snapshot.assignment.sha256
        == _sha256_path(paths.assignment_path)
        and generated.manifest.source_snapshot.results_history.sha256
        == _sha256_path(paths.results_path)
        and generated.sha256 == _sha256_bytes(generated.content),
        "manifest revision 1",
        "initial source or manifest digest disagrees.",
    )
    _require(
        generated.path.read_bytes() == generated.content
        and len(generated.manifest.students) == 1
        and len(generated.manifest.students[0].attempts) == 1,
        "manifest revision 1",
        "initial durable manifest content disagrees.",
    )
    return generated


def _reader_one(generated: AcademicResultManifestGenerationResult) -> None:
    manifest = read_academic_result_manifest(generated.content)
    _verify_reader_revision(manifest, expected_attempts=1)


def _publish_one(
    workspace: Path,
    registration_revision: int,
    generated: AcademicResultManifestGenerationResult,
) -> AcademicResultPublicationResult:
    result = publish_scoreform_academic_results(
        workspace,
        SYNTHETIC_CLASS_ID,
        SYNTHETIC_ASSIGNMENT_ID,
        manifest_revision=1,
    )
    _require(
        result.disposition == "created",
        "initial publication",
        "initial publication was not newly created.",
    )
    _verify_publication_envelope(
        result.publication,
        revision=1,
        registration_revision=registration_revision,
        supersedes=None,
        stage="initial publication",
    )
    _require(
        result.publication.manifest_digest == generated.sha256,
        "initial publication",
        "Publication Record digest disagrees with producer bytes.",
    )
    return result


def _replay_publication(
    workspace: Path,
    expected: AcademicResultPublicationResult,
) -> None:
    replay = publish_scoreform_academic_results(
        workspace,
        SYNTHETIC_CLASS_ID,
        SYNTHETIC_ASSIGNMENT_ID,
        manifest_revision=1,
    )
    _require(
        replay.disposition == "existing"
        and replay.publication == expected.publication
        and replay.publication.publication_id
        == expected.publication.publication_id,
        "publication replay",
        "exact publication replay did not preserve identity.",
    )


def _catalog_one(
    workspace: Path,
    publication: AcademicResultPublicationResult,
) -> None:
    rebuild_academic_catalog(workspace)
    rows = _query_series(workspace, "all")
    _require(
        len(rows) == 1
        and rows[0].publication_id == publication.publication.publication_id
        and rows[0].is_series_head
        and not rows[0].is_withdrawn
        and rows[0].is_current_selectable,
        "catalog revision 1",
        "catalog revision-1 row disagrees with canonical publication.",
    )


def _core_verified_bytes(
    workspace: Path,
    generated: AcademicResultManifestGenerationResult,
    publication: AcademicResultPublicationResult,
    *,
    stage: str,
) -> bytes:
    verified_path = verify_publication_manifest(workspace, publication.publication)
    content = verified_path.read_bytes()
    _require(
        verified_path.resolve(strict=True) == generated.path.resolve(strict=True)
        and content == generated.content
        and _sha256_bytes(content) == publication.publication.manifest_digest
        and publication.publication.manifest_digest == generated.sha256,
        stage,
        "Core path/digest verification disagrees with durable producer bytes.",
    )
    return content


def _append_successor(workspace: Path, paths: ScoreFormWorkPaths) -> None:
    second = export_scoreform_result_models(
        (_synthetic_result(2),), workspace_root=workspace
    )
    _require(
        second.succeeded
        and len(second.appended_attempts) == 1
        and second.appended_attempts[0].attempt_number == 2,
        "native successor",
        "second manual result was not appended as attempt 2.",
    )
    history = load_routed_results_history(paths.results_path)
    _require(
        tuple(row.attempt_number for row in history) == (1, 2),
        "native successor",
        "native history did not preserve attempts 1 and 2.",
    )


def _manifest_two(
    workspace: Path,
    revision_one_bytes: bytes,
) -> AcademicResultManifestGenerationResult:
    generated = generate_academic_result_manifest(
        workspace, SYNTHETIC_CLASS_ID, SYNTHETIC_ASSIGNMENT_ID
    )
    _require(
        generated.revision == 2
        and generated.manifest.record_set.revision == 2
        and len(generated.manifest.students) == 1
        and tuple(
            attempt.attempt_number
            for attempt in generated.manifest.students[0].attempts
        )
        == (1, 2),
        "manifest revision 2",
        "successor producer manifest did not preserve both attempts.",
    )
    _require(
        generated.sha256 == _sha256_bytes(generated.content)
        and generated.path.read_bytes() == generated.content,
        "manifest revision 2",
        "successor durable manifest content disagrees.",
    )
    revision_one_path = generated.path.parent / "1.json"
    _require(
        revision_one_path.read_bytes() == revision_one_bytes,
        "manifest revision 2",
        "manifest revision 1 changed while creating revision 2.",
    )
    return generated


def _supersede(
    workspace: Path,
    registration_revision: int,
    predecessor: AcademicResultPublicationResult,
    generated: AcademicResultManifestGenerationResult,
) -> AcademicResultPublicationResult:
    result = supersede_scoreform_academic_results(
        workspace,
        SYNTHETIC_CLASS_ID,
        SYNTHETIC_ASSIGNMENT_ID,
        manifest_revision=2,
        expected_current_publication_id=predecessor.publication.publication_id,
    )
    _require(
        result.disposition == "created"
        and result.publication.publication_id
        != predecessor.publication.publication_id,
        "supersession",
        "successor publication did not receive a new identity.",
    )
    _verify_publication_envelope(
        result.publication,
        revision=2,
        registration_revision=registration_revision,
        supersedes=predecessor.publication.publication_id,
        stage="supersession",
    )
    _require(
        result.publication.manifest_digest == generated.sha256,
        "supersession",
        "successor Publication Record digest disagrees.",
    )
    return result


def _catalog_two(
    workspace: Path,
    predecessor: AcademicResultPublicationResult,
    successor: AcademicResultPublicationResult,
) -> None:
    rebuild_academic_catalog(workspace)
    heads = _query_series(workspace, "series_heads")
    historical = _query_series(workspace, "historical")
    current = _query_series(workspace, "current")
    _require(
        len(heads) == 1
        and heads[0].publication_id == successor.publication.publication_id
        and heads[0].is_series_head
        and not heads[0].is_withdrawn
        and heads[0].is_current_selectable,
        "catalog revision 2",
        "successor catalog head disagrees.",
    )
    _require(
        len(historical) == 1
        and historical[0].publication_id
        == predecessor.publication.publication_id
        and len(current) == 1
        and current[0].publication_id == successor.publication.publication_id,
        "catalog revision 2",
        "historical/current catalog projection disagrees.",
    )


def _reader_two(content: bytes) -> None:
    manifest = read_academic_result_manifest(content)
    _verify_reader_revision(manifest, expected_attempts=2)


def _withdraw(
    workspace: Path,
    successor: AcademicResultPublicationResult,
) -> AcademicResultWithdrawalResult:
    result = withdraw_scoreform_academic_result_publication(
        workspace,
        SYNTHETIC_CLASS_ID,
        SYNTHETIC_ASSIGNMENT_ID,
        publication_id=successor.publication.publication_id,
        reason=WITHDRAWAL_REASON,
    )
    _require(
        result.disposition == "created"
        and result.publication == successor.publication
        and result.withdrawal.publication_id
        == successor.publication.publication_id
        and result.withdrawal.reason == WITHDRAWAL_REASON
        and result.manifest_verification == "verified",
        "withdrawal",
        "final head withdrawal did not preserve canonical publication/evidence.",
    )
    return result


def _final_catalog(
    workspace: Path,
    paths: ScoreFormWorkPaths,
    predecessor: AcademicResultPublicationResult,
    successor: AcademicResultPublicationResult,
) -> None:
    rebuild_academic_catalog(workspace)
    current = _query_series(workspace, "current")
    heads = _query_series(workspace, "series_heads")
    historical = _query_series(workspace, "historical")
    withdrawn = _query_series(workspace, "withdrawn")
    _require(
        current == ()
        and len(heads) == 1
        and heads[0].publication_id == successor.publication.publication_id
        and heads[0].is_withdrawn
        and not heads[0].is_current_selectable,
        "final catalog",
        "withdrawn series head was not represented exactly.",
    )
    _require(
        len(historical) == 1
        and historical[0].publication_id
        == predecessor.publication.publication_id
        and len(withdrawn) == 1
        and withdrawn[0].publication_id == successor.publication.publication_id,
        "final catalog",
        "withdrawn/historical catalog state disagrees.",
    )
    _require(
        get_current_publication_record(
            workspace,
            paths.work_ref,
            SCOREFORM_ACADEMIC_RESULT_PUBLICATION_KIND,
            SCOREFORM_ACADEMIC_RESULT_RECORD_SET_ID,
        )
        is None,
        "final catalog",
        "withdrawal incorrectly restored a predecessor as current.",
    )
    series = list_publication_record_set(
        workspace,
        paths.work_ref,
        SCOREFORM_ACADEMIC_RESULT_PUBLICATION_KIND,
        SCOREFORM_ACADEMIC_RESULT_RECORD_SET_ID,
    )
    _require(
        len(series) == 2,
        "final catalog",
        "canonical publication series did not preserve both records.",
    )


def _audit(workspace: Path) -> None:
    report = audit_academic_registry(
        workspace,
        options=RegistryAuditOptions(
            scopes=(
                "registrations",
                "publications",
                "manifests",
                "contracts",
                "catalog",
                "locks",
            ),
            class_id=SYNTHETIC_CLASS_ID,
            module_id=SCOREFORM_MODULE_ID,
            work_id=SYNTHETIC_ASSIGNMENT_ID,
            require_catalog=True,
            require_producer_profiles=True,
            discover_installed_producer_profiles=True,
        ),
    )
    _require(
        report.ok
        and report.canonical_valid
        and report.manifests_valid is True
        and report.contracts_compatible is True
        and report.catalog_ready is True
        and report.counts.error_findings == 0
        and report.counts.registration_revisions == 1
        and report.counts.publication_records == 2
        and report.counts.withdrawals == 1
        and report.counts.verified_manifests == 2,
        "registry audit",
        "Core registry audit did not validate the completed producer lifecycle.",
    )


def run_acceptance(
    workspace: Path,
    *,
    version: str,
    expected_core_version: str,
) -> None:
    workspace = workspace.resolve(strict=False)

    _run_stage(
        "installed provenance",
        lambda: _installed_provenance(
            workspace,
            version=version,
            expected_core_version=expected_core_version,
        ),
    )
    paths = _run_stage("synthetic native work", lambda: _native_work(workspace))
    registration = _run_stage(
        "academic-work registration", lambda: _register(workspace, paths)
    )
    generated_one = _run_stage(
        "manifest revision 1", lambda: _manifest_one(workspace, paths)
    )
    revision_one_bytes = bytes(generated_one.content)
    _run_stage("public reader revision 1", lambda: _reader_one(generated_one))
    published_one = _run_stage(
        "initial publication",
        lambda: _publish_one(
            workspace, registration.registration_revision, generated_one
        ),
    )
    publication_one_bytes = publication_record_path(
        workspace, published_one.publication.publication_id
    ).read_bytes()
    _run_stage(
        "publication replay",
        lambda: _replay_publication(workspace, published_one),
    )
    _run_stage(
        "catalog revision 1",
        lambda: _catalog_one(workspace, published_one),
    )
    verified_one = _run_stage(
        "Core verification revision 1",
        lambda: _core_verified_bytes(
            workspace,
            generated_one,
            published_one,
            stage="Core verification revision 1",
        ),
    )
    _require(
        read_academic_result_manifest(verified_one) == generated_one.manifest,
        "Core verification revision 1",
        "Core-verified bytes changed producer reader semantics.",
    )

    _run_stage("native successor", lambda: _append_successor(workspace, paths))
    generated_two = _run_stage(
        "manifest revision 2",
        lambda: _manifest_two(workspace, revision_one_bytes),
    )
    published_two = _run_stage(
        "supersession",
        lambda: _supersede(
            workspace,
            registration.registration_revision,
            published_one,
            generated_two,
        ),
    )
    publication_two_path = publication_record_path(
        workspace, published_two.publication.publication_id
    )
    publication_two_bytes = publication_two_path.read_bytes()
    _run_stage(
        "catalog revision 2",
        lambda: _catalog_two(workspace, published_one, published_two),
    )
    def verify_and_read_two() -> None:
        verified_two = _core_verified_bytes(
            workspace,
            generated_two,
            published_two,
            stage="public reader revision 2",
        )
        _reader_two(verified_two)

    _run_stage("public reader revision 2", verify_and_read_two)
    withdrawal = _run_stage(
        "withdrawal", lambda: _withdraw(workspace, published_two)
    )
    _run_stage(
        "final catalog",
        lambda: _final_catalog(workspace, paths, published_one, published_two),
    )
    _run_stage("registry audit", lambda: _audit(workspace))

    def check_immutability() -> None:
        _require(
            generated_one.path.read_bytes() == revision_one_bytes,
            "immutability",
            "manifest revision 1 changed.",
        )
        _require(
            generated_two.path.read_bytes() == generated_two.content,
            "immutability",
            "manifest revision 2 changed.",
        )
        _require(
            publication_record_path(
                workspace, published_one.publication.publication_id
            ).read_bytes()
            == publication_one_bytes,
            "immutability",
            "publication 1 canonical bytes changed.",
        )
        _require(
            publication_two_path.read_bytes() == publication_two_bytes,
            "immutability",
            "publication 2 canonical bytes changed after withdrawal.",
        )
        withdrawal_path = publication_withdrawal_path(
            workspace, published_two.publication.publication_id
        )
        _require(
            withdrawal_path.is_file()
            and withdrawal.withdrawal.publication_id
            == published_two.publication.publication_id,
            "immutability",
            "withdrawal is not preserved as a separate canonical record.",
        )

    _run_stage("immutability", check_immutability)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify installed ScoreForm academic-result producer lifecycle."
    )
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--version", default="0.10.0")
    parser.add_argument("--expected-core-version", default="0.6.0")
    args = parser.parse_args()
    try:
        run_acceptance(
            args.workspace,
            version=args.version,
            expected_core_version=args.expected_core_version,
        )
    except AcceptanceFailure as error:
        print(f"FAILED: {error.stage}: {error.message}", file=sys.stderr)
        return 1
    except Exception:
        print("FAILED: unexpected installed producer-acceptance harness error.", file=sys.stderr)
        return 1
    print("Installed ScoreForm producer acceptance passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
