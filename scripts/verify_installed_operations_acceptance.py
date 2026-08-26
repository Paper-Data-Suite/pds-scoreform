"""Clean-wheel installed acceptance for ScoreForm issue #194 operations integration."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.metadata as metadata
import os
import subprocess
import sys
import sysconfig
from pathlib import Path
from typing import cast

import pds_core
from pds_core.module_operations import (
    MODULE_OPERATIONS_ENTRY_POINT_GROUP,
    ModuleAttentionReport,
    ModuleOperationsProfile,
    ModuleOperationsRequest,
    ModuleReadinessReport,
    invoke_module_attention,
    invoke_module_readiness,
    validate_module_operations_profile,
)
from pds_core.provider_diagnostics import (
    diagnose_core_providers,
    inspect_core_provider_entry_points,
)
from pds_core.routes import class_roster_path
from pds_core.routing_models import ModuleWorkRef
from pds_core.scan_failure_metadata import (
    RoutingFailureMetadata,
    write_routing_failure_metadata,
)
from pip._vendor.packaging.requirements import Requirement
from pip._vendor.packaging.specifiers import SpecifierSet
from pip._vendor.packaging.utils import canonicalize_name

from scoreform.assignment import validate_assignment_data
from scoreform.assignment_context import AssignmentContextRef, AssignmentContextSession
from scoreform.diagnostic_events import build_diagnostic_event, record_diagnostic_event
from scoreform.guided_share_results import (
    commit_share_results_manifest,
    commit_share_results_publication,
    commit_share_results_registration,
    prepare_share_results_manifest,
    prepare_share_results_publication,
    prepare_share_results_registration,
)
from scoreform.layouts import DEFAULT_LAYOUT_ID, require_layout
from scoreform.page_scoring import ScoredAnswer
from scoreform.results import ScoreFormRoutedResult, export_scoreform_result_models
from scoreform.scan_review_details import scoreform_failure_details
from scoreform.work_paths import initialize_scoreform_work_layout
from scoreform.workflows import write_assignment_json

SYNTHETIC_CLASS_ID = "attention_acceptance_class"
SYNTHETIC_ASSIGNMENT_ID = "attention_acceptance_quiz"
PRIVATE_STUDENT_ID = "private_student_sentinel"
PRIVATE_TITLE = "Private Attention Acceptance Title"
PRIVATE_SOURCE = "private_student_source_sentinel.pdf"
PRIVATE_FAILURE_MESSAGE = "Private low-level failure message sentinel."


class AcceptanceFailure(RuntimeError):
    """Bounded installed-acceptance failure."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AcceptanceFailure(message)


def _module_origin(module_name: str) -> Path:
    module = importlib.import_module(module_name)
    raw = getattr(module, "__file__", None)
    if not isinstance(raw, str) or not raw:
        raise AcceptanceFailure(f"{module_name} has no import origin.")
    path = Path(raw).resolve()
    if not path.is_file():
        raise AcceptanceFailure(f"{module_name} origin is not a file.")
    return path


def _is_installed_origin(path: Path, repository: Path) -> bool:
    try:
        resolved = path.resolve()
        return (
            resolved.is_relative_to(Path(sys.prefix).resolve())
            and "site-packages" in {part.lower() for part in resolved.parts}
            and not resolved.is_relative_to(repository)
        )
    except (OSError, RuntimeError, ValueError):
        return False


def _inventory(root: Path) -> tuple[tuple[str, str], ...]:
    rows: list[tuple[str, str]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(root).as_posix()
        if path.is_dir():
            rows.append((relative, "dir"))
        elif path.is_file():
            rows.append((relative, hashlib.sha256(path.read_bytes()).hexdigest()))
        else:
            rows.append((relative, "other"))
    return tuple(rows)


def _readiness_report(
    profile: ModuleOperationsProfile,
    request: ModuleOperationsRequest,
    *,
    expected_code: str = "module_operations.evaluated",
) -> ModuleReadinessReport:
    invocation = invoke_module_readiness(profile, request)
    _require(
        invocation.code == expected_code,
        f"readiness invocation returned {invocation.code!r}, expected {expected_code!r}.",
    )
    report = invocation.report
    _require(
        isinstance(report, ModuleReadinessReport),
        "readiness invocation did not return a ModuleReadinessReport.",
    )
    return cast(ModuleReadinessReport, report)


def _assert_readiness_read_only(
    profile: ModuleOperationsProfile,
    request: ModuleOperationsRequest,
    workspace: Path,
    *,
    expected_code: str = "module_operations.evaluated",
) -> ModuleReadinessReport:
    before = _inventory(workspace)
    report = _readiness_report(
        profile,
        request,
        expected_code=expected_code,
    )
    after = _inventory(workspace)
    _require(before == after, "readiness evaluation modified persisted workspace state.")
    return report


def _attention_report(
    profile: ModuleOperationsProfile,
    request: ModuleOperationsRequest,
    *,
    expected_code: str = "module_operations.evaluated",
) -> ModuleAttentionReport:
    invocation = invoke_module_attention(profile, request)
    _require(
        invocation.code == expected_code,
        f"attention invocation returned {invocation.code!r}, expected {expected_code!r}.",
    )
    report = invocation.report
    _require(
        isinstance(report, ModuleAttentionReport),
        "attention invocation did not return a ModuleAttentionReport.",
    )
    return cast(ModuleAttentionReport, report)


def _assert_read_only(
    profile: ModuleOperationsProfile,
    request: ModuleOperationsRequest,
    workspace: Path,
) -> ModuleAttentionReport:
    before = _inventory(workspace)
    report = _attention_report(profile, request)
    after = _inventory(workspace)
    _require(before == after, "attention evaluation modified persisted workspace state.")
    return report


def _assert_private_values_absent(
    report: ModuleAttentionReport | ModuleReadinessReport,
) -> None:
    rendered = repr(report)
    for forbidden in (
        PRIVATE_STUDENT_ID,
        PRIVATE_TITLE,
        PRIVATE_SOURCE,
        PRIVATE_FAILURE_MESSAGE,
        "Private diagnostic event exception sentinel",
    ):
        _require(
            forbidden not in rendered,
            f"shared attention report leaked prohibited value {forbidden!r}.",
        )


def _load_operations_profile(
    repository: Path,
    *,
    version: str,
    expected_core_version: str,
) -> ModuleOperationsProfile:
    _require(metadata.version("scoreform") == version, "ScoreForm version mismatch.")
    _require(
        metadata.version("pds-core") == expected_core_version,
        "PDS Core distribution version mismatch.",
    )
    _require(
        getattr(pds_core, "__version__", None) == expected_core_version,
        "PDS Core module/distribution versions disagree.",
    )

    requirements = tuple(
        Requirement(value) for value in (metadata.requires("scoreform") or ())
    )
    core = tuple(
        requirement
        for requirement in requirements
        if canonicalize_name(requirement.name) == "pds-core"
    )
    _require(
        len(core) == 1
        and core[0].specifier == SpecifierSet(">=0.6.2,<0.7"),
        "installed ScoreForm must declare pds-core>=0.6.2,<0.7.",
    )

    for module_name in (
        "scoreform",
        "scoreform.cli",
        "scoreform.pds_operations",
        "scoreform.attention_provider",
        "scoreform.readiness_provider",
        "scoreform.attention_model",
        "scoreform.attention_work_discovery",
        "scoreform.attention_scan",
        "scoreform.attention_share_results",
        "pds_core",
        "pds_core.module_operations",
    ):
        origin = _module_origin(module_name)
        _require(
            _is_installed_origin(origin, repository),
            f"{module_name} is not isolated installed code: {origin}",
        )

    points = tuple(
        point
        for point in metadata.entry_points(group=MODULE_OPERATIONS_ENTRY_POINT_GROUP)
        if point.name == "scoreform"
    )
    _require(len(points) == 1, "expected exactly one ScoreForm operations entry point.")
    point = points[0]
    _require(
        point.value == "scoreform.pds_operations:get_module_operations_profile",
        f"unexpected ScoreForm operations entry-point target: {point.value}",
    )

    provider = point.load()
    profile = validate_module_operations_profile(provider())
    _require(profile.module_id == "scoreform", "operations module ID changed.")
    _require(
        profile.supported_core_operations_contract_versions == frozenset({"1"}),
        "ScoreForm operations contract support changed.",
    )
    _require(profile.attention_provider is not None, "attention provider is absent.")
    _require(profile.readiness_provider is not None, "readiness provider is absent.")

    inspected = tuple(
        row
        for row in inspect_core_provider_entry_points(
            provider_kind="module_operations"
        )
        if row.entry_point_name == "scoreform"
    )
    _require(
        len(inspected) == 1,
        "Core metadata inspection did not find exactly one ScoreForm operations provider.",
    )
    diagnosed = tuple(
        row
        for row in diagnose_core_providers(provider_kind="module_operations")
        if row.metadata.entry_point_name == "scoreform"
    )
    _require(
        len(diagnosed) == 1 and diagnosed[0].code == "provider.valid",
        f"Core provider diagnostics rejected ScoreForm: {diagnosed!r}",
    )
    return profile


def _verify_minimum_contract(
    profile: ModuleOperationsProfile,
    base: Path,
) -> None:
    missing = base.parent / f"{base.name}-missing"
    _require(not missing.exists(), "minimum-floor missing workspace already exists.")
    missing_request = ModuleOperationsRequest(workspace_root=missing)
    missing_attention = _attention_report(
        profile,
        missing_request,
        expected_code="module_operations.evaluation_unavailable",
    )
    _require(
        missing_attention.evaluation == "unavailable"
        and missing_attention.summaries == (),
        "missing workspace must return unavailable with zero attention.",
    )
    missing_readiness = _readiness_report(
        profile,
        missing_request,
        expected_code="module_operations.evaluation_unavailable",
    )
    _require(
        missing_readiness.evaluation == "unavailable"
        and missing_readiness.ready is None,
        "missing workspace must return unavailable readiness with ready=None.",
    )
    _require(not missing.exists(), "operations evaluation created a missing workspace.")

    empty = base / "empty"
    empty.mkdir(parents=True)
    request = ModuleOperationsRequest(workspace_root=empty)
    attention = _assert_read_only(profile, request, empty)
    _require(
        attention.evaluation == "evaluated"
        and attention.summaries == ()
        and attention.notices == (),
        "empty installed workspace must evaluate with zero attention.",
    )
    readiness = _assert_readiness_read_only(profile, request, empty)
    _require(
        readiness.evaluation == "evaluated"
        and readiness.ready is True
        and readiness.notices == (),
        "empty installed workspace must be ScoreForm-ready.",
    )


def _verify_installed_launcher(version: str) -> None:
    distribution = metadata.distribution("scoreform")
    points = tuple(
        point
        for point in distribution.entry_points
        if point.group == "console_scripts"
    )
    _require(
        len(points) == 1 and points[0].name == "scoreform",
        "installed ScoreForm distribution must expose exactly one console script.",
    )
    _require(
        points[0].value == "scoreform.cli:main",
        f"unexpected installed ScoreForm launcher target: {points[0].value}",
    )

    scripts = sysconfig.get_path("scripts")
    _require(isinstance(scripts, str) and bool(scripts), "scripts path is unavailable.")
    launcher = Path(scripts) / ("scoreform.exe" if os.name == "nt" else "scoreform")
    _require(launcher.is_file(), f"installed ScoreForm launcher is missing: {launcher}")

    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    version_output: str | None = None
    for args in (("--version",), ("--help",)):
        result = subprocess.run(
            (os.fspath(launcher), *args),
            cwd=Path(sys.prefix),
            env=environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=30.0,
        )
        _require(
            result.returncode == 0,
            f"installed ScoreForm launcher probe {args!r} failed: {result.returncode}",
        )
        if args == ("--version",):
            version_output = result.stdout
    _require(
        version_output is not None and version in version_output,
        "installed ScoreForm --version output did not report the installed version.",
    )



def _write_valid_roster(workspace: Path, class_id: str) -> None:
    roster = class_roster_path(workspace, class_id)
    roster.parent.mkdir(parents=True, exist_ok=True)
    roster.write_text(
        "class_id,student_id,last_name,first_name,period\n"
        f"{class_id},{PRIVATE_STUDENT_ID},Private,Student,acceptance\n",
        encoding="utf-8",
    )


def _verify_readiness_contexts(
    profile: ModuleOperationsProfile,
    workspace: Path,
) -> None:
    workspace.mkdir(parents=True)
    missing_class = _assert_readiness_read_only(
        profile,
        ModuleOperationsRequest(
            workspace_root=workspace,
            class_id="missing_acceptance_class",
        ),
        workspace,
    )
    _require(
        missing_class.ready is False
        and missing_class.notices
        and missing_class.notices[0].code == "scoreform_class_not_ready",
        "missing exact class must be evaluated not-ready.",
    )

    broken_class = "broken_acceptance_class"
    broken_roster = class_roster_path(workspace, broken_class)
    broken_roster.parent.mkdir(parents=True)
    broken_roster.write_text(
        "bad_header\nprivate_student_sentinel\n",
        encoding="utf-8",
    )
    broken = _assert_readiness_read_only(
        profile,
        ModuleOperationsRequest(workspace_root=workspace, class_id=broken_class),
        workspace,
    )
    _require(broken.ready is False, "malformed authoritative class must be not-ready.")
    _assert_private_values_absent(broken)

    _write_valid_roster(workspace, SYNTHETIC_CLASS_ID)
    request = ModuleOperationsRequest(
        workspace_root=workspace,
        class_id=SYNTHETIC_CLASS_ID,
    )
    ready = _assert_readiness_read_only(profile, request, workspace)
    _require(ready.ready is True and ready.notices == (), "valid exact class must be ready.")

    session = AssignmentContextSession()
    session.activate(
        AssignmentContextRef(SYNTHETIC_CLASS_ID, SYNTHETIC_ASSIGNMENT_ID),
        workspace_root=workspace,
    )
    before_context = (session.active, session.recent)
    after_context = _assert_readiness_read_only(profile, request, workspace)
    _require(after_context == ready, "recent assignment context changed readiness.")
    _require(
        (session.active, session.recent) == before_context,
        "readiness evaluation mutated recent assignment context.",
    )



def _failure(
    failure_id: str,
    *,
    core_category: str,
    detail_category: str,
) -> RoutingFailureMetadata:
    context: dict[str, object] = {
        "observed_identity": {
            "class_id": SYNTHETIC_CLASS_ID,
            "assignment_id": SYNTHETIC_ASSIGNMENT_ID,
            "student_id": PRIVATE_STUDENT_ID,
        }
    }
    if detail_category == "missing_pages":
        context["expected_logical_pages"] = [1, 2]
        context["missing_logical_pages"] = [2]

    return RoutingFailureMetadata(
        schema_version="2",
        failure_id=failure_id,
        scope="page",
        stage=(
            "attempt_assembly"
            if detail_category == "missing_pages"
            else "payload_detection"
        ),
        created_at="2026-08-25T20:00:00+00:00",
        failure_category=core_category,
        failure_message=PRIVATE_FAILURE_MESSAGE,
        source_filename=PRIVATE_SOURCE,
        source_scan_id=None,
        source_sha256=None,
        retained_source_path=None,
        review_copy_path=None,
        source_page_number=1,
        detected_payload=None,
        route_locator=None,
        target=None,
        module_details=scoreform_failure_details(
            origin=(
                "attempt_assembly"
                if detail_category == "missing_pages"
                else "page_decode"
            ),
            category=detail_category,
            context=context,
        ),
    )


def _verify_scan_attention(
    profile: ModuleOperationsProfile,
    workspace: Path,
) -> None:
    workspace.mkdir(parents=True)
    _write_valid_roster(workspace, SYNTHETIC_CLASS_ID)
    write_routing_failure_metadata(
        workspace,
        _failure(
            "attention_missing_pages",
            core_category="page_conflict",
            detail_category="missing_pages",
        ),
    )
    write_routing_failure_metadata(
        workspace,
        _failure(
            "attention_qr_missing",
            core_category="payload_missing",
            detail_category="missing_qr",
        ),
    )

    request = ModuleOperationsRequest(
        workspace_root=workspace,
        class_id=SYNTHETIC_CLASS_ID,
    )
    report = _assert_read_only(profile, request, workspace)
    by_code = {summary.code: summary for summary in report.summaries}
    _require(
        tuple(by_code) == (
            "scoreform_incomplete_attempt",
            "scoreform_scan_review",
        ),
        f"unexpected installed scan attention: {tuple(by_code)!r}",
    )
    _require(
        by_code["scoreform_incomplete_attempt"].count == 1
        and by_code["scoreform_scan_review"].count == 1,
        "installed scan attention counts changed.",
    )
    for summary in report.summaries:
        _require(
            summary.class_id == SYNTHETIC_CLASS_ID,
            "class-scoped scan attention lost exact request context.",
        )
        _require(summary.work_ref is None, "diagnostic identity became shared work authority.")
        _require(
            summary.action is not None
            and summary.action.module_id == "scoreform"
            and summary.action.action_id == "open_scan_review",
            "scan owner action changed.",
        )
    _assert_private_values_absent(report)
    readiness_before_event = _assert_readiness_read_only(profile, request, workspace)
    _require(
        readiness_before_event.ready is True,
        "open scan attention must not make a valid class not-ready.",
    )
    _assert_private_values_absent(readiness_before_event)

    baseline = report
    event = build_diagnostic_event(
        component="scan_intake",
        workflow="process_scan",
        stage="decode",
        outcome="failure",
        code="qr_missing",
        class_id=SYNTHETIC_CLASS_ID,
        assignment_id=SYNTHETIC_ASSIGNMENT_ID,
        exception=RuntimeError(
            "Private diagnostic event exception sentinel "
            "private_student_sentinel"
        ),
    )
    record_diagnostic_event(workspace, event)
    after_event_before = _inventory(workspace)
    after_event = _attention_report(profile, request)
    after_event_after = _inventory(workspace)
    _require(
        after_event_before == after_event_after,
        "attention query modified diagnostic or canonical state.",
    )
    _require(
        after_event == baseline,
        "changing only diagnostic history changed authoritative attention.",
    )
    _assert_private_values_absent(after_event)
    readiness_after_event = _assert_readiness_read_only(profile, request, workspace)
    _require(
        readiness_after_event == readiness_before_event,
        "changing only diagnostic history changed readiness.",
    )


def _synthetic_assignment() -> dict[str, object]:
    layout = require_layout(DEFAULT_LAYOUT_ID)
    candidate: dict[str, object] = {
        "assignment_id": SYNTHETIC_ASSIGNMENT_ID,
        "title": PRIVATE_TITLE,
        "question_count": 3,
        "choices": list(layout.choices),
        "layout_id": layout.layout_id,
        "answer_key": {"1": "A", "2": "B", "3": "C"},
        "standards": {"1": [], "2": [], "3": []},
    }
    normalized = validate_assignment_data(candidate)
    if normalized is None:
        raise AcceptanceFailure("synthetic attention assignment failed validation.")
    return cast(dict[str, object], normalized)


def _synthetic_result() -> ScoreFormRoutedResult:
    answers = (
        ScoredAnswer(1, "A", True),
        ScoredAnswer(2, "BLANK", False),
        ScoredAnswer(3, "C", True),
    )
    return ScoreFormRoutedResult(
        result_origin="plain_paper_manual",
        class_id=SYNTHETIC_CLASS_ID,
        assignment_id=SYNTHETIC_ASSIGNMENT_ID,
        student_id=PRIVATE_STUDENT_ID,
        last_name="Private",
        first_name="Student",
        period="acceptance",
        page_display="manual",
        score=2,
        total_points=3,
        answers=answers,
        source_file="plain_paper_manual_entry",
    )


def _write_share_fixture(workspace: Path) -> None:
    roster = class_roster_path(workspace, SYNTHETIC_CLASS_ID)
    roster.parent.mkdir(parents=True, exist_ok=True)
    roster.write_text(
        "class_id,student_id,last_name,first_name,period\n"
        f"{SYNTHETIC_CLASS_ID},{PRIVATE_STUDENT_ID},Private,Student,acceptance\n",
        encoding="utf-8",
    )
    paths = initialize_scoreform_work_layout(
        workspace,
        SYNTHETIC_CLASS_ID,
        SYNTHETIC_ASSIGNMENT_ID,
    )
    _require(
        write_assignment_json(paths.assignment_path, _synthetic_assignment()),
        "synthetic attention assignment could not be written.",
    )
    result = export_scoreform_result_models(
        (_synthetic_result(),),
        workspace_root=workspace,
    )
    _require(
        result.succeeded and len(result.appended_attempts) == 1,
        "synthetic attention result was not appended exactly once.",
    )


def _single_share_summary(
    report: ModuleAttentionReport,
    expected_code: str,
) -> None:
    _require(
        len(report.summaries) == 1,
        f"expected one Share Results attention summary: {report.summaries!r}",
    )
    summary = report.summaries[0]
    _require(summary.code == expected_code, f"unexpected share attention code {summary.code}.")
    _require(summary.count == 1, "Share Results attention must count assignments.")
    _require(summary.class_id == SYNTHETIC_CLASS_ID, "share class context changed.")
    _require(
        summary.work_ref
        == ModuleWorkRef(
            "scoreform",
            SYNTHETIC_CLASS_ID,
            SYNTHETIC_ASSIGNMENT_ID,
        ),
        "share work context changed.",
    )
    _require(
        summary.action is not None
        and summary.action.module_id == "scoreform"
        and summary.action.action_id == "open_share_results",
        "Share Results owner action changed.",
    )
    _assert_private_values_absent(report)


def _verify_share_attention(
    profile: ModuleOperationsProfile,
    workspace: Path,
) -> None:
    workspace.mkdir(parents=True)
    _write_share_fixture(workspace)
    request = ModuleOperationsRequest(
        workspace_root=workspace,
        class_id=SYNTHETIC_CLASS_ID,
    )

    register_report = _assert_read_only(profile, request, workspace)
    register_readiness = _assert_readiness_read_only(profile, request, workspace)
    _require(
        register_readiness.ready is True,
        "Share Results attention must not make a valid class not-ready.",
    )
    _single_share_summary(
        register_report,
        "scoreform_results_registration_pending",
    )

    registration_preview = prepare_share_results_registration(
        workspace,
        SYNTHETIC_CLASS_ID,
        SYNTHETIC_ASSIGNMENT_ID,
        academic_intent="summative",
        lifecycle="active",
    )
    commit_share_results_registration(workspace, registration_preview)

    manifest_report = _assert_read_only(profile, request, workspace)
    _single_share_summary(
        manifest_report,
        "scoreform_results_manifest_pending",
    )

    manifest_preview = prepare_share_results_manifest(
        workspace,
        SYNTHETIC_CLASS_ID,
        SYNTHETIC_ASSIGNMENT_ID,
    )
    commit_share_results_manifest(workspace, manifest_preview)

    publication_report = _assert_read_only(profile, request, workspace)
    _single_share_summary(
        publication_report,
        "scoreform_results_publication_pending",
    )

    publication_preview = prepare_share_results_publication(
        workspace,
        SYNTHETIC_CLASS_ID,
        SYNTHETIC_ASSIGNMENT_ID,
    )
    commit_share_results_publication(workspace, publication_preview)

    current_report = _assert_read_only(profile, request, workspace)
    _require(
        current_report.summaries == (),
        "already-current Share Results state must emit no attention.",
    )
    _assert_private_values_absent(current_report)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--repository", required=True, type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--expected-core-version", required=True)
    parser.add_argument("--minimum-floor-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    options = _parse_args(argv)
    base = options.workspace.resolve()
    repository = options.repository.resolve()
    try:
        _require(not base.exists(), f"workspace must begin absent: {base}")
        profile = _load_operations_profile(
            repository,
            version=options.version,
            expected_core_version=options.expected_core_version,
        )
        os.environ["PDS_WORKSPACE_ROOT"] = os.fspath(
            base.parent / "implicit_workspace_must_not_be_used"
        )
        base.mkdir(parents=True)
        _verify_installed_launcher(options.version)
        _verify_minimum_contract(profile, base)
        if not options.minimum_floor_only:
            _verify_readiness_contexts(profile, base / "readiness")
            _verify_scan_attention(profile, base / "scan")
            _verify_share_attention(profile, base / "share")
    except (
        AcceptanceFailure,
        OSError,
        TypeError,
        ValueError,
    ) as error:
        print(f"FAILED: {error}", file=sys.stderr)
        return 1

    mode = "minimum-floor" if options.minimum_floor_only else "full current"
    print(
        "Installed issue #194 module-operations readiness/attention and launcher acceptance passed "
        f"({mode}; Core {options.expected_core_version})."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
