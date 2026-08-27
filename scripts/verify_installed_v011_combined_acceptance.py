"""Combined clean-wheel ScoreForm v0.11.0 installed acceptance for issue #195."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import io
import json
import os
import subprocess
import sys
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import redirect_stdout
from importlib import metadata
from pathlib import Path
from typing import Any, TypeVar, cast
from unittest.mock import patch

import pds_core
from pdf2image import convert_from_path
from pds_core.academic_work_registration_storage import (
    list_academic_work_registration_revisions,
)
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
from pds_core.publication_storage import list_publication_records
from pds_core.routes import class_roster_path
from pds_core.standards import (
    StandardDefinition,
    StandardsLibrary,
    StandardsProfile,
    standards_library_path,
    write_standards_library,
)
from pds_core.workspace import ensure_workspace_root
from pip._vendor.packaging.requirements import Requirement
from pip._vendor.packaging.specifiers import SpecifierSet
from pip._vendor.packaging.utils import canonicalize_name
from reportlab.pdfgen import canvas

from scoreform.answer_sheet_generation import discover_answer_sheet_issuances
from scoreform.assignment import assignment_from_json_bytes, validate_assignment_data
from scoreform.assignment_context import (
    AssignmentContextRef,
    AssignmentContextSession,
    resolve_active_assignment_context,
    resolve_recent_assignment_contexts,
)
from scoreform.assignment_presets import load_assignment_preset
from scoreform.cli_score import execute_routed_scoring_operation
from scoreform.diagnostic_events import (
    build_diagnostic_event,
    diagnostic_event_path,
    record_diagnostic_event,
)
from scoreform.guided_scan_workflow import launch_guided_scan_to_results
from scoreform.guided_share_results import (
    ShareResultsNextStep,
    plan_share_results_readiness,
)
from scoreform.layouts import DEFAULT_LAYOUT_ID, require_layout
from scoreform.menu_share_results import launch_share_results_with_meridian
from scoreform.page_scoring import ScoredAnswer
from scoreform.results import (
    ScoreFormRoutedResult,
    export_scoreform_result_models,
    load_routed_results_history,
)
from scoreform.scan_review_resolution import discover_scan_review_items
from scoreform.scan_teacher_diagnostics import project_teacher_scan_diagnostic
from scoreform.work_paths import initialize_scoreform_work_layout, scoreform_work_paths
from scoreform.workflows import write_assignment_json

SOURCE_CLASS_ID = "combined_source_class"
COPY_CLASS_ID = "combined_copy_class"
PRESET_CLASS_ID = "combined_preset_class"
SOURCE_ASSIGNMENT_ID = "combined_source_quiz"
COPY_ASSIGNMENT_ID = "combined_source_quiz"
PRESET_ASSIGNMENT_ID = "combined_preset_quiz"
PRESET_ID = "combined_reusable_setup"
QUESTION_COUNT = 30
PROFILE_ID = "combined_acceptance_profile"
STANDARD_A = "combined_standard_a"
STANDARD_B = "combined_standard_b"
SOURCE_STUDENT_ID = "combined_source_student"
COPY_STUDENT_ID = "combined_copy_student"
PRESET_STUDENT_ID = "combined_preset_student"
PRIVACY_SENTINEL = "PRIVATE-STUDENT-PAYLOAD-SENTINEL"

T = TypeVar("T")


class AcceptanceFailure(RuntimeError):
    """Bounded combined installed-acceptance failure."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AcceptanceFailure(message)


def _select_one(
    values: Iterable[T],
    predicate: Callable[[T], bool],
    *,
    label: str,
) -> T:
    """Select one semantic record without relying on provider/filesystem order."""

    matches = tuple(value for value in values if predicate(value))
    if len(matches) != 1:
        raise AcceptanceFailure(
            f"expected exactly one {label}; found {len(matches)}"
        )
    return matches[0]


def _pairwise_disjoint(named_sets: Sequence[tuple[str, set[str]]]) -> None:
    """Require independent identity namespaces across selected targets."""

    for index, (left_name, left) in enumerate(named_sets):
        for right_name, right in named_sets[index + 1 :]:
            overlap = left & right
            if overlap:
                raise AcceptanceFailure(
                    f"{left_name} and {right_name} reused identity: {sorted(overlap)!r}"
                )


def _module_origin(module_name: str) -> Path:
    module = importlib.import_module(module_name)
    module_file = getattr(module, "__file__", None)
    if not isinstance(module_file, str) or not module_file:
        raise AcceptanceFailure(f"{module_name} has no import origin.")
    return Path(module_file).resolve()


def _is_isolated_installed_origin(path: Path, repository: Path) -> bool:
    try:
        resolved = path.resolve()
        return (
            resolved.is_relative_to(Path(sys.prefix).resolve())
            and "site-packages" in {part.lower() for part in resolved.parts}
            and not resolved.is_relative_to(repository.resolve())
        )
    except (OSError, RuntimeError, ValueError):
        return False


def _scoreform_executable() -> Path:
    name = "scoreform.exe" if os.name == "nt" else "scoreform"
    candidate = Path(sys.executable).with_name(name)
    if not candidate.is_file():
        raise AcceptanceFailure(
            f"installed ScoreForm console entry point was not found at {candidate}"
        )
    return candidate


def _installed_environment(workspace: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment["PDS_WORKSPACE_ROOT"] = os.fspath(workspace)
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    environment["PYTHONNOUSERSITE"] = "1"
    return environment


def _run(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _run_scoreform(
    executable: Path,
    workspace: Path,
    args: list[str],
) -> subprocess.CompletedProcess[str]:
    return _run(
        [os.fspath(executable), *args],
        cwd=workspace.parent,
        env=_installed_environment(workspace),
    )


def _assert_success(
    result: subprocess.CompletedProcess[str],
    *,
    stage: str,
) -> None:
    if result.returncode != 0:
        stdout = result.stdout.strip().replace("\n", " | ")
        stderr = result.stderr.strip().replace("\n", " | ")
        raise AcceptanceFailure(
            f"{stage} failed with exit {result.returncode}; "
            f"stdout={stdout!r}; stderr={stderr!r}"
        )


def _assert_expected_failure(
    result: subprocess.CompletedProcess[str],
    *,
    stage: str,
) -> None:
    if result.returncode == 0:
        raise AcceptanceFailure(f"{stage} unexpectedly exited zero.")
    combined = result.stdout + result.stderr
    _require("Traceback" not in combined, f"{stage} exposed a traceback.")


class _PromptRecorder:
    def __init__(self, values: list[str]) -> None:
        self._values: Iterator[str] = iter(values)
        self.prompts: list[str] = []

    def __call__(self, prompt: str = "") -> str:
        self.prompts.append(prompt)
        try:
            return next(self._values)
        except StopIteration as error:
            raise AcceptanceFailure(
                f"guided workflow requested unexpected additional input: {prompt!r}"
            ) from error


def _inputs(values: list[str]) -> Callable[[str], str]:
    recorder = _PromptRecorder(values)
    return recorder


def _write_roster(
    workspace: Path,
    class_id: str,
    student_id: str,
    *,
    period: str,
) -> bytes:
    path = class_roster_path(workspace, class_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = (
        "class_id,student_id,last_name,first_name,period\n"
        f"{class_id},{student_id},Synthetic,Student,{period}\n"
    ).encode("utf-8")
    path.write_bytes(content)
    return content


def _synthetic_assignment() -> dict[str, object]:
    layout = require_layout(DEFAULT_LAYOUT_ID)
    candidate: dict[str, object] = {
        "assignment_id": SOURCE_ASSIGNMENT_ID,
        "title": "Synthetic Combined Acceptance",
        "question_count": QUESTION_COUNT,
        "choices": list(layout.choices),
        "layout_id": layout.layout_id,
        "answer_key": {
            str(question): layout.choices[(question - 1) % len(layout.choices)]
            for question in range(1, QUESTION_COUNT + 1)
        },
        "standards": {
            str(question): [] for question in range(1, QUESTION_COUNT + 1)
        },
    }
    normalized = validate_assignment_data(candidate)
    if normalized is None:
        raise AcceptanceFailure("synthetic combined assignment failed validation.")
    return cast(dict[str, object], normalized)


def _synthetic_standards_library() -> StandardsLibrary:
    return StandardsLibrary(
        standards=(
            StandardDefinition(
                standard_id=STANDARD_A,
                code="SYN.A",
                source="Synthetic acceptance",
                short_name="Synthetic A",
                description="Synthetic standard A for combined acceptance.",
                subject="Synthetic",
                available_modules=("scoreform",),
            ),
            StandardDefinition(
                standard_id=STANDARD_B,
                code="SYN.B",
                source="Synthetic acceptance",
                short_name="Synthetic B",
                description="Synthetic standard B for combined acceptance.",
                subject="Synthetic",
                available_modules=("scoreform",),
            ),
        ),
        profiles=(
            StandardsProfile(
                profile_id=PROFILE_ID,
                standards=(STANDARD_A, STANDARD_B),
                subject="Synthetic",
                source="Synthetic acceptance",
                title="Synthetic Combined Acceptance Profile",
            ),
        ),
    )


def _verify_installed_provenance(
    workspace: Path,
    repository: Path,
    *,
    version: str,
    expected_core_version: str,
) -> Path:
    _require(not workspace.exists(), f"workspace must begin absent: {workspace}")
    _require(metadata.version("scoreform") == version, "ScoreForm version mismatch.")
    _require(
        metadata.version("pds-core") == expected_core_version,
        "PDS Core distribution version mismatch.",
    )
    _require(
        getattr(pds_core, "__version__", None) == expected_core_version,
        "PDS Core module/distribution versions disagree.",
    )
    _require(
        expected_core_version == "0.6.3",
        "combined v0.11 acceptance qualifies the exact Core 0.6.3 reference.",
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
        "ScoreForm Core compatibility metadata must remain pds-core>=0.6.2,<0.7.",
    )
    names = {canonicalize_name(requirement.name) for requirement in requirements}
    _require(
        "pds-meridian" not in names and "meridian" not in names,
        "ScoreForm acquired a Meridian runtime dependency.",
    )
    _require(
        "paper-data-suite" not in names,
        "ScoreForm acquired a paper-data-suite runtime dependency.",
    )

    modules = (
        "scoreform",
        "scoreform.cli",
        "scoreform.assignment_copying",
        "scoreform.assignment_presets",
        "scoreform.assignment_bulk_entry",
        "scoreform.multi_class_generation",
        "scoreform.menu_assignment_tasks",
        "scoreform.assignment_context",
        "scoreform.guided_scan_workflow",
        "scoreform.scan_teacher_diagnostics",
        "scoreform.guided_share_results",
        "scoreform.diagnostic_events",
        "scoreform.pds_operations",
        "scoreform.attention_provider",
        "scoreform.readiness_provider",
        "pds_core",
        "pds_core.module_operations",
    )
    for module_name in modules:
        origin = _module_origin(module_name)
        _require(
            _is_isolated_installed_origin(origin, repository),
            f"{module_name} did not import from isolated site-packages: {origin}",
        )

    imported_meridian = tuple(
        name
        for name in sys.modules
        if name.split(".", 1)[0] in {"meridian", "pds_meridian"}
    )
    _require(
        not imported_meridian,
        f"combined acceptance imported Meridian implementation modules: {imported_meridian}",
    )

    executable = _scoreform_executable()
    pip_check = _run(
        [sys.executable, "-m", "pip", "check"],
        cwd=workspace.parent,
        env=_installed_environment(workspace),
    )
    _assert_success(pip_check, stage="installed pip check")

    distribution = metadata.distribution("scoreform")
    console_points = tuple(
        point for point in distribution.entry_points if point.group == "console_scripts"
    )
    _require(
        len(console_points) == 1
        and console_points[0].name == "scoreform"
        and console_points[0].value == "scoreform.cli:main",
        "installed ScoreForm launcher contract changed.",
    )

    version_result = _run_scoreform(executable, workspace, ["--version"])
    _assert_success(version_result, stage="installed version")
    _require(
        version_result.stdout.strip() == f"ScoreForm {version}",
        "installed --version output mismatch.",
    )
    help_result = _run_scoreform(executable, workspace, ["--help"])
    _assert_success(help_result, stage="installed help")
    for expected in (
        "scoreform copy-assignment",
        "scoreform preset",
        "scoreform bulk-edit-assignment",
        "scoreform generate-batch",
        "scoreform score <scan.pdf>",
        "scoreform diagnostics",
        "scoreform publication",
    ):
        _require(
            expected in help_result.stdout,
            f"installed direct CLI help is missing {expected!r}.",
        )
    _require(
        not workspace.exists(),
        "installed provenance/help/version checks created workspace state.",
    )
    return executable


def _prepare_workspace(workspace: Path) -> tuple[bytes, dict[str, bytes]]:
    ensure_workspace_root(workspace)
    rosters = {
        SOURCE_CLASS_ID: _write_roster(
            workspace, SOURCE_CLASS_ID, SOURCE_STUDENT_ID, period="2"
        ),
        COPY_CLASS_ID: _write_roster(
            workspace, COPY_CLASS_ID, COPY_STUDENT_ID, period="4"
        ),
        PRESET_CLASS_ID: _write_roster(
            workspace, PRESET_CLASS_ID, PRESET_STUDENT_ID, period="6"
        ),
    }
    write_standards_library(
        standards_library_path(workspace),
        _synthetic_standards_library(),
    )

    paths = initialize_scoreform_work_layout(
        workspace, SOURCE_CLASS_ID, SOURCE_ASSIGNMENT_ID
    )
    assignment = _synthetic_assignment()
    _require(
        write_assignment_json(paths.assignment_path, assignment),
        "could not write synthetic source assignment.",
    )
    source_bytes = paths.assignment_path.read_bytes()
    _require(
        assignment_from_json_bytes(source_bytes) == assignment,
        "synthetic source assignment did not round-trip exactly.",
    )
    return source_bytes, rosters


def _assert_fresh_reused_target(workspace: Path, class_id: str, assignment_id: str) -> None:
    paths = scoreform_work_paths(workspace, class_id, assignment_id)
    _require(paths.assignment_path.is_file(), f"missing reused assignment {class_id}/{assignment_id}.")
    for forbidden in (
        paths.results_path,
        paths.answer_sheets_dir,
        paths.exports_dir,
        paths.work_root / "routes",
        paths.academic_result_manifests_dir,
    ):
        _require(
            not forbidden.exists(),
            f"reuse unexpectedly copied operational/evidence state: {forbidden}",
        )
    _require(
        not list_academic_work_registration_revisions(workspace, paths.work_ref),
        f"reuse unexpectedly created registration history for {class_id}/{assignment_id}.",
    )
    _require(
        not any(
            record.work == paths.work_ref
            for record in list_publication_records(workspace)
        ),
        f"reuse unexpectedly created publication history for {class_id}/{assignment_id}.",
    )


def _exercise_copy_and_preset(
    executable: Path,
    workspace: Path,
    *,
    source_bytes: bytes,
) -> tuple[bytes, bytes]:
    copy_plan = _run_scoreform(
        executable,
        workspace,
        [
            "copy-assignment",
            "--source-class-id",
            SOURCE_CLASS_ID,
            "--source-assignment-id",
            SOURCE_ASSIGNMENT_ID,
            "--target-assignment-id",
            COPY_ASSIGNMENT_ID,
            "--target-class-id",
            COPY_CLASS_ID,
        ],
    )
    _assert_success(copy_plan, stage="combined copy plan")
    _require("Mode: PLAN ONLY" in copy_plan.stdout, "copy plan did not remain plan-only.")
    copy_root = scoreform_work_paths(workspace, COPY_CLASS_ID, COPY_ASSIGNMENT_ID).work_root
    _require(not copy_root.exists(), "copy plan mutated target work.")

    copy_apply = _run_scoreform(
        executable,
        workspace,
        [
            "copy-assignment",
            "--source-class-id",
            SOURCE_CLASS_ID,
            "--source-assignment-id",
            SOURCE_ASSIGNMENT_ID,
            "--target-assignment-id",
            COPY_ASSIGNMENT_ID,
            "--target-class-id",
            COPY_CLASS_ID,
            "--apply",
        ],
    )
    _assert_success(copy_apply, stage="combined copy apply")
    _assert_fresh_reused_target(workspace, COPY_CLASS_ID, COPY_ASSIGNMENT_ID)

    preset_save = _run_scoreform(
        executable,
        workspace,
        [
            "preset",
            "save",
            "--preset-id",
            PRESET_ID,
            "--source-class-id",
            SOURCE_CLASS_ID,
            "--source-assignment-id",
            SOURCE_ASSIGNMENT_ID,
            "--label",
            "Combined Reusable Setup",
            "--apply",
        ],
    )
    _assert_success(preset_save, stage="combined preset save")
    preset = load_assignment_preset(workspace, PRESET_ID)
    raw_preset = preset.preset_bytes.decode("utf-8")
    for forbidden in (
        SOURCE_CLASS_ID,
        SOURCE_ASSIGNMENT_ID,
        SOURCE_STUDENT_ID,
        "student_id",
        "results",
        "publication",
        "manifest",
    ):
        _require(
            forbidden not in raw_preset,
            f"preset leaked forbidden source/history value {forbidden!r}.",
        )

    preset_plan = _run_scoreform(
        executable,
        workspace,
        [
            "preset",
            "apply",
            "--preset-id",
            PRESET_ID,
            "--target-assignment-id",
            PRESET_ASSIGNMENT_ID,
            "--title",
            "Combined Preset Target",
            "--target-class-id",
            PRESET_CLASS_ID,
        ],
    )
    _assert_success(preset_plan, stage="combined preset apply plan")
    preset_root = scoreform_work_paths(
        workspace, PRESET_CLASS_ID, PRESET_ASSIGNMENT_ID
    ).work_root
    _require(not preset_root.exists(), "preset plan mutated target work.")

    preset_apply = _run_scoreform(
        executable,
        workspace,
        [
            "preset",
            "apply",
            "--preset-id",
            PRESET_ID,
            "--target-assignment-id",
            PRESET_ASSIGNMENT_ID,
            "--title",
            "Combined Preset Target",
            "--target-class-id",
            PRESET_CLASS_ID,
            "--apply",
        ],
    )
    _assert_success(preset_apply, stage="combined preset apply")
    _assert_fresh_reused_target(workspace, PRESET_CLASS_ID, PRESET_ASSIGNMENT_ID)

    source_path = scoreform_work_paths(
        workspace, SOURCE_CLASS_ID, SOURCE_ASSIGNMENT_ID
    ).assignment_path
    _require(
        source_path.read_bytes() == source_bytes,
        "copy/preset reuse changed source assignment bytes.",
    )
    copy_bytes = scoreform_work_paths(
        workspace, COPY_CLASS_ID, COPY_ASSIGNMENT_ID
    ).assignment_path.read_bytes()
    preset_bytes = scoreform_work_paths(
        workspace, PRESET_CLASS_ID, PRESET_ASSIGNMENT_ID
    ).assignment_path.read_bytes()
    return copy_bytes, preset_bytes


def _bulk_key_text() -> str:
    choices = ("B", "C", "D", "A")
    return " ".join(choices[(question - 1) % 4] for question in range(1, QUESTION_COUNT + 1))


def _exercise_bulk_edit(
    executable: Path,
    workspace: Path,
    *,
    source_bytes: bytes,
    copy_bytes: bytes,
) -> bytes:
    paths = scoreform_work_paths(workspace, COPY_CLASS_ID, COPY_ASSIGNMENT_ID)
    args = [
        "bulk-edit-assignment",
        "--class-id",
        COPY_CLASS_ID,
        "--assignment-id",
        COPY_ASSIGNMENT_ID,
        "--answer-key-text",
        _bulk_key_text(),
        "--alignment-text",
        f"1-15={STANDARD_A};16-30={STANDARD_B}",
        "--standards-profile-id",
        PROFILE_ID,
    ]
    plan = _run_scoreform(executable, workspace, args)
    _assert_success(plan, stage="combined bulk plan")
    _require(
        "Mode: PLAN ONLY" in plan.stdout
        and "Complete normalized answer key" in plan.stdout,
        "combined bulk plan did not expose complete normalized preview.",
    )
    _require(paths.assignment_path.read_bytes() == copy_bytes, "bulk plan mutated target.")

    invalid = _run_scoreform(
        executable,
        workspace,
        [
            "bulk-edit-assignment",
            "--class-id",
            COPY_CLASS_ID,
            "--assignment-id",
            COPY_ASSIGNMENT_ID,
            "--answer-key-text",
            _bulk_key_text(),
            "--alignment-text",
            f"1-29={STANDARD_A};30=not_in_profile",
            "--standards-profile-id",
            PROFILE_ID,
            "--apply",
        ],
    )
    _assert_expected_failure(invalid, stage="combined invalid bulk apply")
    _require(
        "not_in_profile" in invalid.stdout + invalid.stderr,
        "invalid bulk edit did not identify the bad standard.",
    )
    _require(
        paths.assignment_path.read_bytes() == copy_bytes,
        "invalid bulk edit partially mutated target assignment.",
    )

    applied = _run_scoreform(executable, workspace, [*args, "--apply"])
    _assert_success(applied, stage="combined bulk apply")
    _require(
        "Mode: APPLIED" in applied.stdout
        and "Only the canonical assignment definition was replaced." in applied.stdout,
        "bulk apply did not report bounded canonical mutation.",
    )
    persisted = paths.assignment_path.read_bytes()
    parsed = assignment_from_json_bytes(persisted)
    _require(
        parsed.get("standards_profile_id") == PROFILE_ID,
        "bulk apply lost standards profile.",
    )
    _require(
        scoreform_work_paths(
            workspace, SOURCE_CLASS_ID, SOURCE_ASSIGNMENT_ID
        ).assignment_path.read_bytes()
        == source_bytes,
        "bulk edit of copied target mutated source assignment.",
    )
    return persisted


def _target_args(*, apply: bool, include_blocked: bool = False) -> list[str]:
    args = [
        "generate-batch",
        "--target",
        f"{COPY_CLASS_ID}/{COPY_ASSIGNMENT_ID}",
        "--target",
        f"{PRESET_CLASS_ID}/{PRESET_ASSIGNMENT_ID}",
    ]
    if include_blocked:
        args.extend(
            ("--target", f"{PRESET_CLASS_ID}/combined_missing_assignment")
        )
    if apply:
        args.append("--apply")
    return args


def _json_records(root: Path) -> tuple[dict[str, Any], ...]:
    if not root.exists():
        return ()
    records: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*.json"), key=lambda item: item.as_posix()):
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise AcceptanceFailure(f"expected JSON object in {path}")
        records.append(value)
    return tuple(records)


def _generated_identity_sets(
    workspace: Path,
    class_id: str,
    assignment_id: str,
) -> tuple[set[str], set[str], set[str], set[str], Path]:
    paths = scoreform_work_paths(workspace, class_id, assignment_id)
    _require(paths.class_packet_path.is_file(), f"class packet missing for {class_id}.")
    individual = tuple(
        path
        for path in paths.individual_templates_dir.glob("*.pdf")
        if path.is_file()
    )
    _require(
        len(individual) == 1,
        f"expected exactly one individual PDF for {class_id}; found {len(individual)}.",
    )

    issuances = discover_answer_sheet_issuances(workspace, paths.work_ref)
    _require(len(issuances) == 2, f"expected two physical issuances for {class_id}.")
    issuance_ids = {issuance.issuance_id for issuance in issuances}
    artifact_ids = {issuance.artifact_id for issuance in issuances}
    generation_ids = {issuance.generation_id for issuance in issuances}
    _require(len(issuance_ids) == 2, f"issuance identity is not unique for {class_id}.")
    _require(len(artifact_ids) == 2, f"artifact identity is not unique for {class_id}.")
    _require(len(generation_ids) == 1, f"target generation identity changed for {class_id}.")

    page_records = _json_records(paths.answer_sheet_pages_dir)
    route_records = _json_records(paths.work_root / "routes")
    _require(len(page_records) == 4, f"expected four page records for {class_id}.")
    _require(len(route_records) == 4, f"expected four route records for {class_id}.")
    page_ids = {
        str(record.get("page_id"))
        for record in page_records
        if isinstance(record.get("page_id"), str)
    }
    route_ids = {
        str(cast(dict[str, Any], record.get("locator", {})).get("route_id"))
        for record in route_records
        if isinstance(record.get("locator"), dict)
        and isinstance(cast(dict[str, Any], record["locator"]).get("route_id"), str)
    }
    _require(len(page_ids) == 4, f"page identities are not unique for {class_id}.")
    _require(len(route_ids) == 4, f"route identities are not unique for {class_id}.")
    return artifact_ids, issuance_ids, page_ids, route_ids, individual[0]


def _exercise_multi_class_generation(
    executable: Path,
    workspace: Path,
    *,
    source_bytes: bytes,
    copy_bytes: bytes,
    preset_bytes: bytes,
    rosters: dict[str, bytes],
) -> tuple[Path, Path]:
    before_roster = {
        class_id: class_roster_path(workspace, class_id).read_bytes()
        for class_id in rosters
    }

    plan = _run_scoreform(executable, workspace, _target_args(apply=False))
    _assert_success(plan, stage="combined generation plan")
    for expected in (
        "Mode: PLAN ONLY",
        "Ready targets: 2",
        "Blocked targets: 0",
        "No changes were made.",
    ):
        _require(expected in plan.stdout, f"generation plan is missing {expected!r}.")

    blocked = _run_scoreform(
        executable, workspace, _target_args(apply=True, include_blocked=True)
    )
    _assert_expected_failure(blocked, stage="combined blocked generation apply")
    _require(
        "Generation cannot start while any selected target is blocked." in blocked.stdout,
        "blocked generation did not stop before durable work.",
    )
    for class_id, assignment_id in (
        (COPY_CLASS_ID, COPY_ASSIGNMENT_ID),
        (PRESET_CLASS_ID, PRESET_ASSIGNMENT_ID),
    ):
        paths = scoreform_work_paths(workspace, class_id, assignment_id)
        _require(
            not paths.answer_sheets_dir.exists(),
            "blocked multi-class generation partially generated a ready target.",
        )

    applied = _run_scoreform(executable, workspace, _target_args(apply=True))
    _assert_success(applied, stage="combined generation apply")
    for expected in (
        "Mode: APPLY",
        "CLEAN SUCCESS",
        "Targets selected: 2",
        "Clean successes: 2",
        "Failed: 0",
    ):
        _require(expected in applied.stdout, f"generation apply is missing {expected!r}.")

    copy_ids = _generated_identity_sets(
        workspace, COPY_CLASS_ID, COPY_ASSIGNMENT_ID
    )
    preset_ids = _generated_identity_sets(
        workspace, PRESET_CLASS_ID, PRESET_ASSIGNMENT_ID
    )
    for label, left, right in zip(
        ("artifact", "issuance", "page", "route"),
        copy_ids[:4],
        preset_ids[:4],
        strict=True,
    ):
        _pairwise_disjoint(
            (
                (f"{COPY_CLASS_ID} {label}", cast(set[str], left)),
                (f"{PRESET_CLASS_ID} {label}", cast(set[str], right)),
            )
        )

    _require(
        scoreform_work_paths(
            workspace, SOURCE_CLASS_ID, SOURCE_ASSIGNMENT_ID
        ).assignment_path.read_bytes()
        == source_bytes,
        "generation mutated source assignment.",
    )
    _require(
        scoreform_work_paths(
            workspace, COPY_CLASS_ID, COPY_ASSIGNMENT_ID
        ).assignment_path.read_bytes()
        == copy_bytes,
        "generation mutated bulk-edited copied assignment.",
    )
    _require(
        scoreform_work_paths(
            workspace, PRESET_CLASS_ID, PRESET_ASSIGNMENT_ID
        ).assignment_path.read_bytes()
        == preset_bytes,
        "generation mutated preset-applied assignment.",
    )
    for class_id, expected in before_roster.items():
        _require(
            class_roster_path(workspace, class_id).read_bytes() == expected,
            f"generation mutated Core roster for {class_id}.",
        )
    return copy_ids[4], preset_ids[4]


def _run_guided_scan(
    source: Path,
    session: AssignmentContextSession,
    choices: list[str],
) -> tuple[int, str, tuple[str, ...]]:
    prompts = _PromptRecorder(choices)
    output = io.StringIO()
    with patch("builtins.input", prompts), redirect_stdout(output):
        status = launch_guided_scan_to_results(
            source,
            context_session=session,
            clear_screen_fn=lambda: None,
            pause_for_user_fn=lambda: None,
        )
    return status, output.getvalue(), tuple(prompts.prompts)


def _verify_routed_history(
    workspace: Path,
    class_id: str,
    assignment_id: str,
    *,
    expected_rows: int,
) -> ScoreFormRoutedResult:
    paths = scoreform_work_paths(workspace, class_id, assignment_id)
    history = load_routed_results_history(paths.results_path)
    _require(
        len(history) == expected_rows,
        f"expected {expected_rows} result rows for {class_id}/{assignment_id}; "
        f"found {len(history)}.",
    )
    result = history[-1].result
    _require(result.result_origin == "pds2_scan", "guided scan result origin changed.")
    _require(
        len(result.page_ids) == 2
        and len(result.route_ids) == 2
        and result.logical_pages == (1, 2)
        and len(result.source_page_numbers) == 2,
        "PDS2 routed provenance arrays are not aligned for a two-page result.",
    )
    _require(
        len(set(result.page_ids)) == 2 and len(set(result.route_ids)) == 2,
        "PDS2 page/route identities are not distinct.",
    )
    _require(
        result.retained_source_relative_path.startswith("scans/source/")
        and len(result.source_sha256) == 64
        and result.source_scan_id is not None,
        "PDS2 retained-source provenance is incomplete.",
    )
    retained = workspace / result.retained_source_relative_path
    _require(retained.is_file(), "PDS2 retained source path does not exist.")
    _require(
        hashlib.sha256(retained.read_bytes()).hexdigest() == result.source_sha256,
        "PDS2 retained source digest mismatch.",
    )
    return result


def _exercise_guided_success_and_idempotency(
    workspace: Path,
    source_pdf: Path,
) -> AssignmentContextSession:
    os.environ["PDS_WORKSPACE_ROOT"] = os.fspath(workspace)
    session = AssignmentContextSession()
    status, output, prompts = _run_guided_scan(source_pdf, session, ["1", "b"])
    _require(status == 0, f"guided successful scan returned {status}.")
    expected_ref = AssignmentContextRef(COPY_CLASS_ID, COPY_ASSIGNMENT_ID)
    _require(session.active == expected_ref, "guided success did not activate exact context.")
    _require(
        not any(
            prompt.strip().casefold().startswith(("select class", "select assignment"))
            for prompt in prompts
        ),
        f"guided success reselected known class/assignment: {prompts!r}",
    )
    for expected in (
        "Scan Processing Summary",
        "Retained by Core: yes",
        "Attempts recorded: 1",
        f"{COPY_CLASS_ID} / {COPY_ASSIGNMENT_ID}",
        "View Assignment Results",
    ):
        _require(expected in output, f"guided success output lacks {expected!r}.")

    result = _verify_routed_history(
        workspace, COPY_CLASS_ID, COPY_ASSIGNMENT_ID, expected_rows=1
    )
    _require(
        result.student_id == COPY_STUDENT_ID,
        "guided scan resolved to the wrong synthetic student.",
    )

    recent = resolve_recent_assignment_contexts(session, workspace_root=workspace)
    _require(
        len(recent) == 1
        and recent[0].is_valid
        and recent[0].ref == expected_ref,
        "recent-context continuity did not retain the exact successful target.",
    )

    duplicate = execute_routed_scoring_operation(source_pdf, workspace_root=workspace)
    _require(duplicate.operation_error is None and duplicate.batch is not None, "duplicate scoring failed.")
    export = duplicate.batch.export_result
    _require(export is not None, "duplicate scoring produced no export decision.")
    _require(
        len(export.appended_attempts) == 0
        and len(export.already_present_attempts) == 1,
        "identical scan content appended a duplicate attempt.",
    )
    _verify_routed_history(
        workspace, COPY_CLASS_ID, COPY_ASSIGNMENT_ID, expected_rows=1
    )

    stale_session = AssignmentContextSession()
    stale_ref = AssignmentContextRef(COPY_CLASS_ID, "combined_stale_assignment")
    stale_session.activate(stale_ref, workspace_root=workspace)
    stale = resolve_active_assignment_context(stale_session, workspace_root=workspace)
    _require(
        stale is not None and not stale.is_valid and stale_session.active is None,
        "stale recent context did not fail closed and clear itself.",
    )
    return session


def _first_page_pdf(source_pdf: Path, destination: Path) -> None:
    """Preserve one routable registered page while omitting the rest of its issuance."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    pages = convert_from_path(
        source_pdf,
        dpi=250,
        first_page=1,
        last_page=1,
    )
    _require(len(pages) == 1, "expected exactly one rendered first page.")
    page = pages[0].convert("RGB")
    width, height = page.size
    document = canvas.Canvas(os.fspath(destination), pagesize=(width, height))
    document.drawInlineImage(page, 0, 0, width=width, height=height)
    document.showPage()
    document.save()
    _require(
        destination.is_file() and destination.stat().st_size > 0,
        "first-page physical-failure PDF fixture was not written.",
    )


def _load_operations_profile(repository: Path) -> ModuleOperationsProfile:
    points = tuple(
        point
        for point in metadata.entry_points(group=MODULE_OPERATIONS_ENTRY_POINT_GROUP)
        if point.name == "scoreform"
    )
    _require(len(points) == 1, "expected exactly one ScoreForm operations provider.")
    _require(
        points[0].value == "scoreform.pds_operations:get_module_operations_profile",
        "ScoreForm operations entry-point target changed.",
    )
    profile = validate_module_operations_profile(points[0].load()())
    _require(
        profile.attention_provider is not None and profile.readiness_provider is not None,
        "ScoreForm operations profile lost attention/readiness.",
    )
    for module_name in ("scoreform.pds_operations", "scoreform.attention_provider", "scoreform.readiness_provider"):
        _require(
            _is_isolated_installed_origin(_module_origin(module_name), repository),
            f"{module_name} is not isolated installed code.",
        )
    return profile


def _inventory(root: Path) -> tuple[tuple[str, str], ...]:
    rows: list[tuple[str, str]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(root).as_posix()
        if path.is_file():
            rows.append((relative, hashlib.sha256(path.read_bytes()).hexdigest()))
        elif path.is_dir():
            rows.append((relative, "dir"))
    return tuple(rows)


def _verify_ready_with_attention(
    workspace: Path,
    repository: Path,
    *,
    class_id: str,
) -> None:
    profile = _load_operations_profile(repository)
    request = ModuleOperationsRequest(workspace_root=workspace, class_id=class_id)
    before = _inventory(workspace)
    readiness_call = invoke_module_readiness(profile, request)
    attention_call = invoke_module_attention(profile, request)
    after = _inventory(workspace)
    _require(before == after, "readiness/attention evaluation mutated workspace state.")
    _require(
        readiness_call.code == "module_operations.evaluated"
        and isinstance(readiness_call.report, ModuleReadinessReport)
        and readiness_call.report.ready is True,
        "usable class did not remain ScoreForm-ready.",
    )
    _require(
        attention_call.code == "module_operations.evaluated"
        and isinstance(attention_call.report, ModuleAttentionReport)
        and bool(attention_call.report.summaries),
        "unresolved scan did not coexist with ready=True attention state.",
    )


def _exercise_failure_recovery(
    executable: Path,
    workspace: Path,
    repository: Path,
    source_pdf: Path,
) -> None:
    os.environ["PDS_WORKSPACE_ROOT"] = os.fspath(workspace)
    partial = workspace.parent / f"{workspace.name}-partial-first-page.pdf"
    _first_page_pdf(source_pdf, partial)

    failure_session = AssignmentContextSession()
    status, output, _prompts = _run_guided_scan(partial, failure_session, ["b"])
    _require(status != 0, "one-page scan of a two-page issuance unexpectedly succeeded.")
    _require(
        "Needs review" in output
        and "Retained by Core: yes" in output
        and "Review items queued:" in output,
        "guided partial scan did not truthfully summarize retained review state.",
    )
    target_paths = scoreform_work_paths(
        workspace, PRESET_CLASS_ID, PRESET_ASSIGNMENT_ID
    )
    _require(
        not target_paths.results_path.exists(),
        "incomplete physical issuance fabricated a result row.",
    )

    items = tuple(
        item
        for item in discover_scan_review_items(workspace).items
        if item.source_filename == partial.name
    )
    item = _select_one(items, lambda candidate: candidate.assignment_id == PRESET_ASSIGNMENT_ID, label="missing-page review item")
    _require(
        item.scoreform_failure_category == "missing_pages",
        f"expected missing_pages review classification; found {item.scoreform_failure_category!r}.",
    )
    diagnostic = project_teacher_scan_diagnostic(
        item,
        allowed_actions=("rescan_needed", "defer"),
    )
    _require(
        diagnostic.family == "incomplete_attempt"
        and diagnostic.evidence_status == "retained"
        and "rescan" in diagnostic.guidance.casefold()
        and "rescan_needed" in diagnostic.recommended_actions,
        "missing-page teacher guidance is not actionable.",
    )

    _verify_ready_with_attention(
        workspace,
        repository,
        class_id=PRESET_CLASS_ID,
    )

    failure_bytes = item.failure_metadata_path.read_bytes()
    resolution = _run_scoreform(
        executable,
        workspace,
        [
            "resolve-scan-review",
            item.failure_id,
            "--action",
            "rescan_needed",
        ],
    )
    _assert_success(resolution, stage="record rescan-needed resolution")
    _require(
        item.failure_metadata_path.read_bytes() == failure_bytes,
        "append-only scan resolution mutated immutable failure bytes.",
    )

    recovered_session = AssignmentContextSession()
    recovered_status, recovered_output, _ = _run_guided_scan(
        source_pdf, recovered_session, ["1", "b"]
    )
    _require(recovered_status == 0, "complete rescan did not recover.")
    _require("Attempts recorded: 1" in recovered_output, "complete rescan recorded no attempt.")
    _verify_routed_history(
        workspace, PRESET_CLASS_ID, PRESET_ASSIGNMENT_ID, expected_rows=1
    )

    reloaded_items = tuple(
        candidate
        for candidate in discover_scan_review_items(
            workspace, include_resolved=True
        ).items
        if candidate.failure_id == item.failure_id
    )
    reloaded = _select_one(reloaded_items, lambda _candidate: True, label="resolved failure")
    _require(
        reloaded.latest_resolution_action == "rescan_needed",
        "rescan-needed resolution was not retained in append-only history.",
    )


def _exercise_diagnostic_privacy(workspace: Path) -> None:
    event = build_diagnostic_event(
        component="diagnostics",
        workflow="retain_diagnostics",
        stage="retention",
        outcome="warning",
        code="diagnostic_retention_warning",
        class_id=PRESET_CLASS_ID,
        assignment_id=PRESET_ASSIGNMENT_ID,
        exception=RuntimeError(
            f"{PRIVACY_SENTINEL} C:\\Users\\Private Teacher\\absolute\\path"
        ),
    )
    record_diagnostic_event(workspace, event)
    path = diagnostic_event_path(workspace, event.event_id)
    raw = path.read_text(encoding="utf-8")
    for forbidden in (
        PRIVACY_SENTINEL,
        "Private Teacher",
        '"student_id"',
        '"answers"',
        '"score"',
        '"payload"',
        '"traceback"',
    ):
        _require(
            forbidden not in raw,
            f"default diagnostic event leaked prohibited value {forbidden!r}.",
        )


def _run_share_results(
    workspace: Path,
    session: AssignmentContextSession,
    responses: list[str],
) -> tuple[int, str]:
    os.environ["PDS_WORKSPACE_ROOT"] = os.fspath(workspace)
    output = io.StringIO()
    with patch("builtins.input", _inputs(responses)), redirect_stdout(output):
        status = launch_share_results_with_meridian(
            clear_screen_fn=lambda: None,
            context_session=session,
        )
    return status, output.getvalue()


def _append_successor_result(workspace: Path) -> None:
    assignment_path = scoreform_work_paths(
        workspace, COPY_CLASS_ID, COPY_ASSIGNMENT_ID
    ).assignment_path
    assignment = assignment_from_json_bytes(assignment_path.read_bytes())
    answer_key = cast(dict[int, str], assignment["answer_key"])
    answers = tuple(
        ScoredAnswer(question, answer_key[question], True)
        for question in range(1, QUESTION_COUNT + 1)
    )
    result = ScoreFormRoutedResult(
        result_origin="plain_paper_manual",
        class_id=COPY_CLASS_ID,
        assignment_id=COPY_ASSIGNMENT_ID,
        student_id=COPY_STUDENT_ID,
        last_name="Synthetic",
        first_name="Student",
        period="4",
        page_display="manual",
        score=QUESTION_COUNT,
        total_points=QUESTION_COUNT,
        answers=answers,
        source_file="plain_paper_manual_entry",
    )
    exported = export_scoreform_result_models((result,), workspace_root=workspace)
    _require(
        exported.succeeded and len(exported.appended_attempts) == 1,
        "legitimate successor native result was not appended exactly once.",
    )


def _exercise_publication(
    workspace: Path,
    session: AssignmentContextSession,
) -> None:
    expected = AssignmentContextRef(COPY_CLASS_ID, COPY_ASSIGNMENT_ID)
    _require(session.active == expected, "publication did not receive successful scan context.")

    first_status, first_output = _run_share_results(
        workspace,
        session,
        ["1", "2", "REGISTER", "GENERATE", "PUBLISH"],
    )
    _require(first_status == 0, "combined first guided publication failed.")
    _require(
        "Results are published through Core and available for Meridian to consume."
        in first_output,
        "combined first publication did not report final teacher status.",
    )
    current = plan_share_results_readiness(
        workspace, COPY_CLASS_ID, COPY_ASSIGNMENT_ID
    )
    _require(
        current.next_step is ShareResultsNextStep.ALREADY_CURRENT
        and current.registration_revision == 1
        and current.producer_head_revision == 1
        and current.core_head_revision == 1,
        "first publication did not reconcile to exact current state.",
    )

    _append_successor_result(workspace)
    cancelled_status, cancelled = _run_share_results(
        workspace, session, ["GENERATE", "b"]
    )
    _require(cancelled_status == 0, "successor cancellation returned nonzero.")
    _require(
        "Manifest revision 2 is already stored." in cancelled
        and "No supersession was written." in cancelled,
        "successor cancellation did not distinguish durable manifest from uncommitted supersession.",
    )
    pending = plan_share_results_readiness(
        workspace, COPY_CLASS_ID, COPY_ASSIGNMENT_ID
    )
    _require(
        pending.next_step is ShareResultsNextStep.SUPERSEDE
        and pending.producer_head_revision == 2
        and pending.core_head_revision == 1
        and pending.expected_current_publication_id is not None,
        "successor publication did not preserve exact pending-head state.",
    )
    predecessor = pending.expected_current_publication_id

    supersede_status, superseded = _run_share_results(
        workspace, session, ["SUPERSEDE"]
    )
    _require(supersede_status == 0, "combined exact supersession failed.")
    _require(
        "previous publication remains in immutable history" in superseded.casefold(),
        "supersession output did not preserve immutable-history semantics.",
    )
    final = plan_share_results_readiness(
        workspace, COPY_CLASS_ID, COPY_ASSIGNMENT_ID
    )
    _require(
        final.next_step is ShareResultsNextStep.ALREADY_CURRENT
        and final.producer_head_revision == 2
        and final.core_head_revision == 2
        and final.core_head_publication_id != predecessor,
        "successor did not become the exact current Core publication head.",
    )

    imported_meridian = tuple(
        name
        for name in sys.modules
        if name.split(".", 1)[0] in {"meridian", "pds_meridian"}
    )
    _require(not imported_meridian, "guided publication imported Meridian runtime code.")


def _verify_no_shadow_context_persistence(workspace: Path) -> None:
    forbidden = (
        "guided_scan",
        "guided-scan",
        "assignment_context.json",
        "recent_context",
        "recent-assignment",
    )
    offenders = tuple(
        path.relative_to(workspace).as_posix()
        for path in workspace.rglob("*")
        if path.is_file()
        and any(fragment in path.name.casefold() for fragment in forbidden)
    )
    _require(
        not offenders,
        f"guided/recent context created shadow persistence: {offenders}",
    )
    _require(
        not (workspace / "classes" / COPY_CLASS_ID / "assignments").exists(),
        "combined workflow recreated an unqualified legacy assignment path.",
    )


def verify(
    workspace: Path,
    repository: Path,
    *,
    version: str,
    expected_core_version: str,
) -> None:
    """Run one coherent installed ScoreForm v0.11 milestone scenario."""

    workspace = workspace.resolve()
    repository = repository.resolve(strict=True)
    executable = _verify_installed_provenance(
        workspace,
        repository,
        version=version,
        expected_core_version=expected_core_version,
    )
    source_bytes, rosters = _prepare_workspace(workspace)
    copy_bytes, preset_bytes = _exercise_copy_and_preset(
        executable,
        workspace,
        source_bytes=source_bytes,
    )
    bulk_bytes = _exercise_bulk_edit(
        executable,
        workspace,
        source_bytes=source_bytes,
        copy_bytes=copy_bytes,
    )
    copy_pdf, preset_pdf = _exercise_multi_class_generation(
        executable,
        workspace,
        source_bytes=source_bytes,
        copy_bytes=bulk_bytes,
        preset_bytes=preset_bytes,
        rosters=rosters,
    )
    success_session = _exercise_guided_success_and_idempotency(
        workspace,
        copy_pdf,
    )
    _exercise_failure_recovery(
        executable,
        workspace,
        repository,
        preset_pdf,
    )
    _exercise_diagnostic_privacy(workspace)
    _exercise_publication(workspace, success_session)
    _verify_no_shadow_context_persistence(workspace)

    for class_id, expected in rosters.items():
        _require(
            class_roster_path(workspace, class_id).read_bytes() == expected,
            f"combined workflow mutated Core roster bytes for {class_id}.",
        )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--expected-core-version", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    options = _parse_args(argv)
    try:
        verify(
            options.workspace,
            options.repository,
            version=options.version,
            expected_core_version=options.expected_core_version,
        )
    except (
        AcceptanceFailure,
        OSError,
        ValueError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
    ) as error:
        print(f"FAILED: combined installed ScoreForm v0.11 acceptance: {error}", file=sys.stderr)
        return 1

    print("PASSED: combined installed ScoreForm v0.11 workflow acceptance")
    print(f"ScoreForm version: {options.version}")
    print(f"Core version: {options.expected_core_version}")
    print("Combined workspace: one synthetic candidate lifecycle")
    print("Physical printer/scanner acceptance: not claimed by automation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
