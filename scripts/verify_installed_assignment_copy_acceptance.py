"""Installed clean-wheel acceptance for ScoreForm assignment copying."""

from __future__ import annotations

import argparse
import importlib
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
from pds_core.routes import class_roster_path
from pds_core.workspace import ensure_workspace_root

from scoreform.assignment import assignment_from_json_bytes, validate_assignment_data
from scoreform.layouts import DEFAULT_LAYOUT_ID, require_layout
from scoreform.work_paths import initialize_scoreform_work_layout, scoreform_work_paths
from scoreform.workflows import write_assignment_json

SOURCE_CLASS_ID = "copy_source_class"
TARGET_CLASS_ID = "copy_target_class"
ASSIGNMENT_ID = "copy_acceptance_quiz"
ASSIGNMENT_TITLE = "Synthetic Assignment Copy Acceptance"

SOURCE_STUDENT_ID = "source_student"
TARGET_STUDENT_IDS = ("target_student_1", "target_student_2")


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
    executable_name = "scoreform.exe" if os.name == "nt" else "scoreform"
    candidate = Path(sys.executable).with_name(executable_name)
    if not candidate.is_file():
        raise AcceptanceFailure(
            f"installed ScoreForm console entry point was not found at {candidate}"
        )
    return candidate


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
        "question_count": 3,
        "choices": list(layout.choices),
        "layout_id": layout.layout_id,
        "answer_key": {"1": "A", "2": "B", "3": "C"},
        "standards": {"1": [], "2": [], "3": []},
    }
    normalized = validate_assignment_data(candidate)
    if normalized is None:
        raise AcceptanceFailure("synthetic assignment failed ScoreForm validation.")
    return cast(dict[str, object], normalized)


def _run_scoreform(
    executable: Path,
    workspace: Path,
    args: list[str],
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PDS_WORKSPACE_ROOT"] = os.fspath(workspace)
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    return subprocess.run(
        [os.fspath(executable), *args],
        cwd=workspace.parent,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _assert_success(
    result: subprocess.CompletedProcess[str],
    *,
    stage: str,
) -> None:
    if result.returncode != 0:
        stderr = result.stderr.strip().replace("\n", " | ")
        stdout = result.stdout.strip().replace("\n", " | ")
        raise AcceptanceFailure(
            f"{stage} failed with exit {result.returncode}; "
            f"stdout={stdout!r}; stderr={stderr!r}"
        )


def _verify_installed_provenance(
    workspace: Path,
    *,
    version: str,
    expected_core_version: str,
) -> Path:
    _require(
        not workspace.exists(),
        f"workspace must begin absent: {workspace}",
    )
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
        "scoreform.assignment_copying",
        "scoreform.cli_assignment_copy",
        "scoreform.work_paths",
        "pds_core",
        "pds_core.academic_work_registration_storage",
        "pds_core.publication_storage",
    ):
        origin = _module_origin(module_name)
        _require(
            _is_isolated_installed_origin(origin),
            f"{module_name} did not import from isolated site-packages: {origin}",
        )

    executable = _scoreform_executable()

    version_result = _run_scoreform(executable, workspace, ["--version"])
    _assert_success(version_result, stage="installed version")
    _require(
        version_result.stdout.strip() == f"ScoreForm {version}",
        "installed ScoreForm --version output mismatch.",
    )

    help_result = _run_scoreform(executable, workspace, ["--help"])
    _assert_success(help_result, stage="installed help")
    _require(
        "scoreform copy-assignment" in help_result.stdout,
        "installed help does not advertise copy-assignment.",
    )
    _require(
        not workspace.exists(),
        "installed help/version created the workspace unexpectedly.",
    )
    return executable


def _prepare_native_state(workspace: Path) -> tuple[bytes, bytes, bytes]:
    ensure_workspace_root(workspace)
    source_roster = _write_roster(
        workspace,
        SOURCE_CLASS_ID,
        period="2",
        student_ids=(SOURCE_STUDENT_ID,),
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
    parsed = assignment_from_json_bytes(source_bytes)
    _require(
        parsed == assignment,
        "synthetic source assignment did not round-trip exactly.",
    )
    return source_bytes, source_roster, target_roster


def _copy_args(*, apply: bool) -> list[str]:
    args = [
        "copy-assignment",
        "--source-class-id",
        SOURCE_CLASS_ID,
        "--source-assignment-id",
        ASSIGNMENT_ID,
        "--target-assignment-id",
        ASSIGNMENT_ID,
        "--target-class-id",
        TARGET_CLASS_ID,
    ]
    if apply:
        args.append("--apply")
    return args


def _verify_plan_only(
    executable: Path,
    workspace: Path,
) -> None:
    target_paths = scoreform_work_paths(
        workspace,
        TARGET_CLASS_ID,
        ASSIGNMENT_ID,
    )
    _require(
        not target_paths.work_root.exists(),
        "target work root existed before plan-only invocation.",
    )

    result = _run_scoreform(
        executable,
        workspace,
        _copy_args(apply=False),
    )
    _assert_success(result, stage="copy plan")

    required_output = (
        "Mode: PLAN ONLY",
        f"class_id: {SOURCE_CLASS_ID}",
        f"assignment_id: {ASSIGNMENT_ID}",
        f"{TARGET_CLASS_ID}/{ASSIGNMENT_ID}",
        "Q1: A",
        "Q2: B",
        "Q3: C",
        "students: 2",
        "periods: 4",
        "No changes were made.",
    )
    for text in required_output:
        _require(
            text in result.stdout,
            f"copy plan output is missing {text!r}.",
        )

    for sensitive_value in (SOURCE_STUDENT_ID, *TARGET_STUDENT_IDS):
        _require(
            sensitive_value not in result.stdout
            and sensitive_value not in result.stderr,
            "copy plan exposed synthetic student identity.",
        )

    _require(
        not target_paths.work_root.exists(),
        "plan-only invocation mutated the target work root.",
    )


def _verify_apply(
    executable: Path,
    workspace: Path,
    *,
    source_bytes: bytes,
    source_roster: bytes,
    target_roster: bytes,
) -> None:
    result = _run_scoreform(
        executable,
        workspace,
        _copy_args(apply=True),
    )
    _assert_success(result, stage="copy apply")
    _require(
        "Created 1 fresh assignment copy." in result.stdout,
        "copy apply did not report one durable target.",
    )

    source_paths = scoreform_work_paths(
        workspace,
        SOURCE_CLASS_ID,
        ASSIGNMENT_ID,
    )
    target_paths = scoreform_work_paths(
        workspace,
        TARGET_CLASS_ID,
        ASSIGNMENT_ID,
    )

    _require(
        source_paths.assignment_path.read_bytes() == source_bytes,
        "source assignment bytes changed during copying.",
    )
    _require(
        class_roster_path(workspace, SOURCE_CLASS_ID).read_bytes() == source_roster,
        "source Core roster changed during copying.",
    )
    _require(
        class_roster_path(workspace, TARGET_CLASS_ID).read_bytes() == target_roster,
        "target Core roster changed during copying.",
    )

    _require(
        target_paths.assignment_path.is_file(),
        "target assignment.json was not created.",
    )
    source_assignment = assignment_from_json_bytes(source_bytes)
    target_assignment = assignment_from_json_bytes(
        target_paths.assignment_path.read_bytes()
    )
    _require(
        target_assignment == source_assignment,
        "target reusable assignment definition differs from source definition.",
    )

    _require(
        (target_paths.work_root / "templates").is_dir(),
        "target managed templates directory is missing.",
    )
    _require(
        (target_paths.work_root / "templates" / "individual").is_dir(),
        "target managed individual-template directory is missing.",
    )
    _require(
        (target_paths.work_root / "scans").is_dir(),
        "target managed scans directory is missing.",
    )
    _require(
        (target_paths.work_root / "debug").is_dir(),
        "target managed debug directory is missing.",
    )

    forbidden_paths = (
        target_paths.results_path,
        target_paths.answer_sheets_dir,
        target_paths.exports_dir,
        target_paths.work_root / "routes",
        target_paths.academic_result_manifests_dir,
    )
    for forbidden in forbidden_paths:
        _require(
            not forbidden.exists(),
            f"copy unexpectedly created operational/evidence state: {forbidden}",
        )

    _require(
        not tuple((target_paths.work_root / "scans").iterdir()),
        "copy unexpectedly created retained scan state.",
    )
    _require(
        not tuple((target_paths.work_root / "debug").iterdir()),
        "copy unexpectedly created debug state.",
    )
    template_entries = tuple(
        path
        for path in (target_paths.work_root / "templates").rglob("*")
        if path.is_file()
    )
    _require(
        not template_entries,
        "copy unexpectedly created generated template/PDF files.",
    )

    revisions = list_academic_work_registration_revisions(
        workspace,
        target_paths.work_ref,
    )
    _require(
        revisions == (),
        "copy unexpectedly created Academic Work Registration history.",
    )

    target_publications = tuple(
        publication
        for publication in list_publication_records(workspace)
        if publication.work == target_paths.work_ref
    )
    _require(
        target_publications == (),
        "copy unexpectedly created Publication Record history.",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--version", default="0.11.0")
    parser.add_argument("--expected-core-version", default="0.6.0")
    args = parser.parse_args()

    workspace = args.workspace.resolve()
    try:
        executable = _verify_installed_provenance(
            workspace,
            version=args.version,
            expected_core_version=args.expected_core_version,
        )
        source_bytes, source_roster, target_roster = _prepare_native_state(workspace)
        _verify_plan_only(executable, workspace)
        _verify_apply(
            executable,
            workspace,
            source_bytes=source_bytes,
            source_roster=source_roster,
            target_roster=target_roster,
        )

        version_after = _run_scoreform(executable, workspace, ["--version"])
        _assert_success(version_after, stage="post-copy installed version")
        _require(
            version_after.stdout.strip() == f"ScoreForm {args.version}",
            "post-copy installed version output mismatch.",
        )
    except AcceptanceFailure as error:
        raise SystemExit(f"FAILED: installed assignment-copy acceptance: {error}") from error

    print("PASSED: installed assignment-copy acceptance")
    print(f"ScoreForm version: {args.version}")
    print(f"Core version: {args.expected_core_version}")
    print(f"Source: {SOURCE_CLASS_ID}/{ASSIGNMENT_ID}")
    print(f"Target: {TARGET_CLASS_ID}/{ASSIGNMENT_ID}")
    print("Plan-only mutation: none")
    print("Inherited operational/evidence history: none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
