"""Clean-wheel acceptance for ScoreForm issue #186 multi-class generation."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import subprocess
import sys
from importlib import metadata
from pathlib import Path
from typing import cast

import pds_core
from pds_core.academic_work_registration_storage import (
    list_academic_work_registration_revisions,
)
from pds_core.publication_storage import list_publication_records
from pds_core.route_registrations import load_route_registration
from pds_core.routes import class_roster_path
from pds_core.routing_models import (
    ModuleWorkRef,
    RouteRegistration,
    route_registration_from_dict,
)
from pds_core.workspace import ensure_workspace_root

from scoreform.answer_sheet_generation import discover_answer_sheet_issuances
from scoreform.answer_sheet_persistence import load_answer_sheet_page
from scoreform.assignment import assignment_from_json_bytes, validate_assignment_data
from scoreform.layouts import DEFAULT_LAYOUT_ID, require_layout
from scoreform.pds_contract import (
    ANSWER_SHEET_PAGE_CONTRACT_VERSION,
    ANSWER_SHEET_PAGE_RECORD_KIND,
)
from scoreform.work_paths import initialize_scoreform_work_layout, scoreform_work_paths
from scoreform.workflows import write_assignment_json

SOURCE_CLASS_ID = "batch_source_class"
TARGET_CLASS_ID = "batch_target_class"
ASSIGNMENT_ID = "multi_class_acceptance_quiz"
ASSIGNMENT_TITLE = "Synthetic Multi-Class Generation Acceptance"
SOURCE_STUDENT_IDS = ("source_student_1", "source_student_2")
TARGET_STUDENT_IDS = (
    "target_student_1",
    "target_student_2",
    "target_student_3",
)
QUESTION_COUNT = 17
PAGES_PER_STUDENT = 2


class AcceptanceFailure(RuntimeError):
    """Bounded installed-acceptance failure."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AcceptanceFailure(message)


def _module_origin(module_name: str) -> Path:
    module = importlib.import_module(module_name)
    module_file = getattr(module, "__file__", None)
    if not isinstance(module_file, str) or not module_file:
        raise AcceptanceFailure(f"{module_name} has no import origin.")
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


def _scoreform_executable() -> Path:
    name = "scoreform.exe" if os.name == "nt" else "scoreform"
    candidate = Path(sys.executable).with_name(name)
    if not candidate.is_file():
        raise AcceptanceFailure(
            f"installed ScoreForm console entry point was not found at {candidate}"
        )
    return candidate


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
    environment = os.environ.copy()
    environment["PDS_WORKSPACE_ROOT"] = os.fspath(workspace)
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    return _run(
        [os.fspath(executable), *args],
        cwd=workspace.parent,
        env=environment,
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


def _verify_installed_provenance(
    workspace: Path,
    *,
    version: str,
    expected_core_version: str,
) -> Path:
    _require(not workspace.exists(), f"workspace must begin absent: {workspace}")
    _require(
        metadata.version("scoreform") == version,
        "installed ScoreForm metadata version mismatch.",
    )
    _require(
        metadata.version("pds-core") == expected_core_version,
        "installed Core distribution version mismatch.",
    )
    _require(
        getattr(pds_core, "__version__", None) == expected_core_version,
        "Core module and distribution versions disagree.",
    )

    for module_name in (
        "scoreform",
        "scoreform.multi_class_generation",
        "scoreform.multi_class_generation_ui",
        "scoreform.cli_multi_class_generation",
        "scoreform.answer_sheet_generation",
        "scoreform.answer_sheet_routes",
        "pds_core",
        "pds_core.route_registrations",
    ):
        origin = _module_origin(module_name)
        _require(
            _is_isolated_installed_origin(origin),
            f"{module_name} did not import from isolated site-packages: {origin}",
        )

    executable = _scoreform_executable()
    pip_check = _run(
        [sys.executable, "-m", "pip", "check"],
        cwd=workspace.parent,
    )
    _assert_success(pip_check, stage="installed pip check")

    version_result = _run_scoreform(executable, workspace, ["--version"])
    _assert_success(version_result, stage="installed version")
    _require(
        version_result.stdout.strip() == f"ScoreForm {version}",
        "installed ScoreForm --version output mismatch.",
    )

    help_result = _run_scoreform(executable, workspace, ["--help"])
    _assert_success(help_result, stage="installed help")
    _require(
        "scoreform generate-batch" in help_result.stdout,
        "installed top-level help does not advertise generate-batch.",
    )
    batch_help = _run_scoreform(executable, workspace, ["generate-batch", "--help"])
    _assert_success(batch_help, stage="installed generate-batch help")
    for expected in (
        "--target <class_id>/<assignment_id>",
        "--apply",
        "plan-only",
        "Exact duplicate targets are rejected.",
        "There is no force, overwrite, implicit discovery, or identity-reuse mode.",
    ):
        _require(
            expected in batch_help.stdout,
            f"installed generate-batch help is missing {expected!r}.",
        )

    _require(
        not workspace.exists(),
        "installed help/version/pip-check created workspace state unexpectedly.",
    )
    return executable


def _write_roster(
    workspace: Path,
    class_id: str,
    *,
    period: str,
    student_ids: tuple[str, ...],
) -> bytes:
    path = class_roster_path(workspace, class_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = ["class_id,student_id,last_name,first_name,period"]
    rows.extend(
        f"{class_id},{student_id},Synthetic,{index},{period}"
        for index, student_id in enumerate(student_ids, start=1)
    )
    content = ("\n".join(rows) + "\n").encode("utf-8")
    path.write_bytes(content)
    return content


def _synthetic_assignment() -> dict[str, object]:
    layout = require_layout(DEFAULT_LAYOUT_ID)
    candidate: dict[str, object] = {
        "assignment_id": ASSIGNMENT_ID,
        "title": ASSIGNMENT_TITLE,
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
        raise AcceptanceFailure("synthetic assignment failed ScoreForm validation.")
    return cast(dict[str, object], normalized)


def _prepare_native_state(
    workspace: Path,
) -> tuple[bytes, bytes, bytes]:
    ensure_workspace_root(workspace)
    source_roster = _write_roster(
        workspace,
        SOURCE_CLASS_ID,
        period="2",
        student_ids=SOURCE_STUDENT_IDS,
    )
    target_roster = _write_roster(
        workspace,
        TARGET_CLASS_ID,
        period="4",
        student_ids=TARGET_STUDENT_IDS,
    )
    source_paths = initialize_scoreform_work_layout(
        workspace,
        SOURCE_CLASS_ID,
        ASSIGNMENT_ID,
    )
    assignment = _synthetic_assignment()
    _require(
        write_assignment_json(source_paths.assignment_path, assignment),
        "could not write synthetic source assignment.",
    )
    source_bytes = source_paths.assignment_path.read_bytes()
    _require(
        assignment_from_json_bytes(source_bytes) == assignment,
        "synthetic source assignment did not round-trip exactly.",
    )
    return source_bytes, source_roster, target_roster


def _copy_target_assignment(executable: Path, workspace: Path) -> bytes:
    result = _run_scoreform(
        executable,
        workspace,
        [
            "copy-assignment",
            "--source-class-id",
            SOURCE_CLASS_ID,
            "--source-assignment-id",
            ASSIGNMENT_ID,
            "--target-assignment-id",
            ASSIGNMENT_ID,
            "--target-class-id",
            TARGET_CLASS_ID,
            "--apply",
        ],
    )
    _assert_success(result, stage="installed assignment copy for SF-AC05")
    target_path = scoreform_work_paths(
        workspace, TARGET_CLASS_ID, ASSIGNMENT_ID
    ).assignment_path
    _require(target_path.is_file(), "installed copy path did not create target assignment.")
    return target_path.read_bytes()


def _target_args(*, apply: bool, include_blocked: bool = False) -> list[str]:
    args = [
        "generate-batch",
        "--target",
        f"{SOURCE_CLASS_ID}/{ASSIGNMENT_ID}",
        "--target",
        f"{TARGET_CLASS_ID}/{ASSIGNMENT_ID}",
    ]
    if include_blocked:
        args.extend(("--target", f"{TARGET_CLASS_ID}/missing_assignment"))
    if apply:
        args.append("--apply")
    return args


def _tree_signature(root: Path) -> tuple[tuple[str, str, str], ...]:
    if not root.exists():
        return ()
    entries: list[tuple[str, str, str]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            entries.append((relative, "symlink", os.readlink(path)))
        elif path.is_dir():
            entries.append((relative, "dir", ""))
        elif path.is_file():
            entries.append(
                (relative, "file", hashlib.sha256(path.read_bytes()).hexdigest())
            )
        else:
            entries.append((relative, "other", ""))
    return tuple(entries)


def _assert_no_core_publication_side_effects(workspace: Path) -> None:
    for class_id in (SOURCE_CLASS_ID, TARGET_CLASS_ID):
        work = ModuleWorkRef("scoreform", class_id, ASSIGNMENT_ID)
        _require(
            not list_academic_work_registration_revisions(workspace, work),
            f"multi-class generation created Academic Work Registration for {class_id}.",
        )
        _require(
            not any(record.work == work for record in list_publication_records(workspace)),
            f"multi-class generation created Publication Record history for {class_id}.",
        )


def _assert_native_bytes(
    workspace: Path,
    *,
    source_assignment: bytes,
    target_assignment: bytes,
    source_roster: bytes,
    target_roster: bytes,
) -> None:
    source_paths = scoreform_work_paths(workspace, SOURCE_CLASS_ID, ASSIGNMENT_ID)
    target_paths = scoreform_work_paths(workspace, TARGET_CLASS_ID, ASSIGNMENT_ID)
    _require(
        source_paths.assignment_path.read_bytes() == source_assignment,
        "source assignment bytes changed during multi-class generation.",
    )
    _require(
        target_paths.assignment_path.read_bytes() == target_assignment,
        "copied target assignment bytes changed during multi-class generation.",
    )
    _require(
        class_roster_path(workspace, SOURCE_CLASS_ID).read_bytes() == source_roster,
        "source roster bytes changed during multi-class generation.",
    )
    _require(
        class_roster_path(workspace, TARGET_CLASS_ID).read_bytes() == target_roster,
        "target roster bytes changed during multi-class generation.",
    )


def _verify_plan_only_and_blocked_apply(
    executable: Path,
    workspace: Path,
) -> None:
    roots = tuple(
        scoreform_work_paths(workspace, class_id, ASSIGNMENT_ID).work_root
        for class_id in (SOURCE_CLASS_ID, TARGET_CLASS_ID)
    )
    before = tuple(_tree_signature(root) for root in roots)

    plan = _run_scoreform(executable, workspace, _target_args(apply=False))
    _assert_success(plan, stage="installed multi-class generation plan")
    for expected in (
        "Mode: PLAN ONLY",
        f"Class: {SOURCE_CLASS_ID}",
        f"Class: {TARGET_CLASS_ID}",
        f"Assignment: {ASSIGNMENT_ID}",
        "Pages per student: 2",
        "Ready targets: 2",
        "Blocked targets: 0",
        "Target 1",
        "Target 2",
        "No changes were made.",
    ):
        _require(expected in plan.stdout, f"plan output is missing {expected!r}.")
    for student_id in (*SOURCE_STUDENT_IDS, *TARGET_STUDENT_IDS):
        _require(
            student_id not in plan.stdout and student_id not in plan.stderr,
            "plan output exposed synthetic student identity.",
        )
    _require(
        tuple(_tree_signature(root) for root in roots) == before,
        "plan-only multi-class generation changed managed work state.",
    )

    blocked = _run_scoreform(
        executable,
        workspace,
        _target_args(apply=True, include_blocked=True),
    )
    _assert_expected_failure(blocked, stage="blocked installed multi-class apply")
    _require(
        "Generation cannot start while any selected target is blocked." in blocked.stdout,
        "blocked batch did not report the pre-start generation gate.",
    )
    _require(
        tuple(_tree_signature(root) for root in roots) == before,
        "blocked --apply batch partially generated a ready target.",
    )
    missing_root = scoreform_work_paths(
        workspace, TARGET_CLASS_ID, "missing_assignment"
    ).work_root
    _require(
        not missing_root.exists(),
        "blocked --apply batch created the missing target work root.",
    )


def _load_route_registrations(
    workspace: Path,
    class_id: str,
) -> tuple[RouteRegistration, ...]:
    paths = scoreform_work_paths(workspace, class_id, ASSIGNMENT_ID)
    routes_dir = paths.work_root / "routes"
    _require(routes_dir.is_dir(), f"Core routes directory is missing for {class_id}.")
    registrations: list[RouteRegistration] = []
    for path in sorted(routes_dir.glob("*.json"), key=lambda item: item.name):
        raw = json.loads(path.read_text(encoding="utf-8"))
        registration = route_registration_from_dict(raw)
        reloaded = load_route_registration(workspace, registration.locator)
        _require(reloaded == registration, f"Core route did not reload exactly: {path}")
        _require(
            registration.locator.class_id == class_id
            and registration.locator.work_id == ASSIGNMENT_ID,
            "route locator escaped its selected managed target.",
        )
        _require(
            registration.target.module_id == "scoreform"
            and registration.target.record_kind == ANSWER_SHEET_PAGE_RECORD_KIND
            and registration.target.contract_version == ANSWER_SHEET_PAGE_CONTRACT_VERSION,
            "route target does not identify a ScoreForm answer-sheet page.",
        )
        page = load_answer_sheet_page(
            workspace,
            registration.locator.work,
            registration.target.record_id,
        )
        _require(
            page.page_id == registration.target.record_id,
            "Core route target did not reload the exact answer-sheet page.",
        )
        registrations.append(registration)
    return tuple(registrations)


def _verify_generated_target(
    workspace: Path,
    class_id: str,
    *,
    student_count: int,
) -> tuple[set[str], set[str], set[str], set[str], set[str]]:
    paths = scoreform_work_paths(workspace, class_id, ASSIGNMENT_ID)
    _require(paths.class_packet_path.is_file(), f"class packet missing for {class_id}.")
    individual_pdfs = tuple(paths.individual_templates_dir.glob("*.pdf"))
    _require(
        len(individual_pdfs) == student_count,
        f"unexpected individual PDF count for {class_id}.",
    )

    issuances = discover_answer_sheet_issuances(workspace, paths.work_ref)
    expected_issuances = 2 * student_count
    expected_pages = 2 * student_count * PAGES_PER_STUDENT
    _require(
        len(issuances) == expected_issuances,
        f"unexpected issuance count for {class_id}.",
    )
    _require(
        all(issuance.lifecycle.status == "issued" for issuance in issuances),
        f"not every generated issuance is issued for {class_id}.",
    )

    page_files = tuple(paths.answer_sheet_pages_dir.glob("*.json"))
    _require(len(page_files) == expected_pages, f"unexpected page count for {class_id}.")
    routes = _load_route_registrations(workspace, class_id)
    _require(len(routes) == expected_pages, f"unexpected Core route count for {class_id}.")

    issuance_ids = {issuance.issuance_id for issuance in issuances}
    artifact_ids = {issuance.artifact_id for issuance in issuances}
    page_ids = {path.stem for path in page_files}
    route_ids = {registration.locator.route_id for registration in routes}
    generation_ids = {issuance.generation_id for issuance in issuances}

    _require(len(issuance_ids) == expected_issuances, "issuance IDs are not unique.")
    _require(
        len(artifact_ids) == student_count + 1,
        f"physical PDF artifact IDs are not unique for {class_id}.",
    )
    _require(len(page_ids) == expected_pages, "page IDs are not unique.")
    _require(len(route_ids) == expected_pages, "route IDs are not unique.")
    _require(len(generation_ids) == 1, f"target generation correlation changed in {class_id}.")
    return artifact_ids, issuance_ids, page_ids, route_ids, generation_ids


def _verify_apply(
    executable: Path,
    workspace: Path,
    *,
    source_assignment: bytes,
    target_assignment: bytes,
    source_roster: bytes,
    target_roster: bytes,
) -> None:
    result = _run_scoreform(executable, workspace, _target_args(apply=True))
    _assert_success(result, stage="installed multi-class generation apply")
    for expected in (
        "Mode: APPLY",
        "CLEAN SUCCESS",
        "Targets selected: 2",
        "Clean successes: 2",
        "Partial successes: 0",
        "Failed: 0",
        "Not attempted: 0",
    ):
        _require(expected in result.stdout, f"apply output is missing {expected!r}.")

    source_ids = _verify_generated_target(
        workspace,
        SOURCE_CLASS_ID,
        student_count=len(SOURCE_STUDENT_IDS),
    )
    target_ids = _verify_generated_target(
        workspace,
        TARGET_CLASS_ID,
        student_count=len(TARGET_STUDENT_IDS),
    )
    for label, source_set, target_set in zip(
        ("artifact", "issuance", "page", "route"),
        source_ids[:4],
        target_ids[:4],
        strict=True,
    ):
        _require(
            source_set.isdisjoint(target_set),
            f"{label} identity was reused across selected targets.",
        )
    _require(
        source_ids[4] == target_ids[4],
        "one batch should retain one generation correlation identity across targets.",
    )

    _assert_native_bytes(
        workspace,
        source_assignment=source_assignment,
        target_assignment=target_assignment,
        source_roster=source_roster,
        target_roster=target_roster,
    )
    _assert_no_core_publication_side_effects(workspace)
    _require(
        not tuple(workspace.rglob(".*.tmp.pdf")),
        "multi-class generation left a temporary PDF artifact.",
    )


def verify(
    workspace: Path,
    *,
    version: str,
    expected_core_version: str,
) -> None:
    executable = _verify_installed_provenance(
        workspace,
        version=version,
        expected_core_version=expected_core_version,
    )
    source_assignment, source_roster, target_roster = _prepare_native_state(workspace)
    target_assignment = _copy_target_assignment(executable, workspace)
    _assert_no_core_publication_side_effects(workspace)
    _verify_plan_only_and_blocked_apply(executable, workspace)
    _assert_native_bytes(
        workspace,
        source_assignment=source_assignment,
        target_assignment=target_assignment,
        source_roster=source_roster,
        target_roster=target_roster,
    )
    _verify_apply(
        executable,
        workspace,
        source_assignment=source_assignment,
        target_assignment=target_assignment,
        source_roster=source_roster,
        target_roster=target_roster,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--expected-core-version", required=True)
    args = parser.parse_args()
    try:
        verify(
            args.workspace,
            version=args.version,
            expected_core_version=args.expected_core_version,
        )
    except AcceptanceFailure as error:
        print(f"FAIL: {error}")
        return 1
    print("PASS: installed ScoreForm SF-AC05 multi-class generation acceptance")
    print(f"ScoreForm {args.version}")
    print(f"Core {args.expected_core_version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
