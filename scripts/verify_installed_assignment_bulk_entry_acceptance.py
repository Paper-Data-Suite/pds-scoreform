"""Clean-wheel acceptance for ScoreForm issue #185 bulk assignment entry."""

from __future__ import annotations

import argparse
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
from pds_core.routing_models import ModuleWorkRef
from pds_core.standards import (
    StandardDefinition,
    StandardsLibrary,
    StandardsProfile,
    standards_library_path,
    write_standards_library,
)
from pds_core.workspace import ensure_workspace_root

from scoreform.assignment import assignment_from_json_bytes, validate_assignment_data
from scoreform.layouts import DEFAULT_LAYOUT_ID, require_layout
from scoreform.work_paths import scoreform_work_paths

CLASS_ID = "bulk_entry_class"
ASSIGNMENT_ID = "bulk_entry_quiz"
PROFILE_ID = "bulk_entry_profile"
STANDARD_A = "synthetic_bulk_standard_a"
STANDARD_B = "synthetic_bulk_standard_b"


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
        "scoreform.assignment_bulk_entry",
        "scoreform.assignment_bulk_mutation",
        "scoreform.cli_assignment_bulk",
        "scoreform.work_paths",
        "pds_core",
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
        "scoreform bulk-edit-assignment" in help_result.stdout,
        "installed top-level help does not advertise bulk-edit-assignment.",
    )

    bulk_help = _run_scoreform(
        executable,
        workspace,
        ["bulk-edit-assignment", "--help"],
    )
    _assert_success(bulk_help, stage="installed bulk-edit help")
    for expected in (
        "--answer-key-text",
        "--answer-key-csv",
        "--answer-key-json",
        "--alignment-text",
        "--alignment-csv",
        "--alignment-json",
        "Without --apply",
        "There is no --force or --overwrite mode.",
    ):
        _require(
            expected in bulk_help.stdout,
            f"installed bulk-edit help is missing {expected!r}.",
        )

    _require(
        not workspace.exists(),
        "installed help/version/pip-check created workspace state unexpectedly.",
    )
    return executable


def _synthetic_standards_library() -> StandardsLibrary:
    return StandardsLibrary(
        standards=(
            StandardDefinition(
                standard_id=STANDARD_A,
                code="SYN.A",
                source="Synthetic acceptance",
                short_name="Synthetic A",
                description="Synthetic standard A for installed acceptance.",
                subject="Synthetic",
                available_modules=("scoreform",),
            ),
            StandardDefinition(
                standard_id=STANDARD_B,
                code="SYN.B",
                source="Synthetic acceptance",
                short_name="Synthetic B",
                description="Synthetic standard B for installed acceptance.",
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
                title="Synthetic Bulk Entry Profile",
            ),
        ),
    )


def _synthetic_assignment() -> dict[str, object]:
    layout = require_layout(DEFAULT_LAYOUT_ID)
    candidate: dict[str, object] = {
        "assignment_id": ASSIGNMENT_ID,
        "title": "Synthetic Bulk Entry Quiz",
        "question_count": 3,
        "choices": list(layout.choices),
        "layout_id": layout.layout_id,
        "answer_key": {"1": "A", "2": "B", "3": "C"},
        "standards": {"1": [], "2": [], "3": []},
    }
    normalized = validate_assignment_data(candidate)
    if normalized is None:
        raise AcceptanceFailure("synthetic assignment failed native validation.")
    return cast(dict[str, object], normalized)


def _serialize_assignment(assignment: dict[str, object]) -> bytes:
    return (json.dumps(assignment, indent=2, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )


def _prepare_native_state(workspace: Path) -> tuple[Path, bytes, dict[Path, bytes]]:
    ensure_workspace_root(workspace)
    write_standards_library(
        standards_library_path(workspace),
        _synthetic_standards_library(),
    )

    paths = scoreform_work_paths(workspace, CLASS_ID, ASSIGNMENT_ID)
    paths.work_root.mkdir(parents=True, exist_ok=True)
    assignment_bytes = _serialize_assignment(_synthetic_assignment())
    paths.assignment_path.write_bytes(assignment_bytes)
    _require(
        assignment_from_json_bytes(paths.assignment_path.read_bytes())
        == _synthetic_assignment(),
        "synthetic assignment did not round-trip through strict bytes validation.",
    )

    sentinels: dict[Path, bytes] = {}
    for path, content in (
        (paths.results_path, b"synthetic-results-sentinel\n"),
        (paths.templates_dir / "existing-sheet.pdf", b"synthetic-sheet-sentinel"),
        (paths.scans_dir / "existing-scan.bin", b"synthetic-scan-sentinel"),
        (paths.debug_dir / "existing-debug.txt", b"synthetic-debug-sentinel\n"),
        (paths.exports_dir / "existing-export.txt", b"synthetic-export-sentinel\n"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        sentinels[path] = content

    return paths.assignment_path, assignment_bytes, sentinels


def _write_bulk_inputs(workspace: Path) -> tuple[Path, bytes, Path, bytes]:
    input_dir = workspace / "synthetic_bulk_inputs"
    input_dir.mkdir()
    key_path = input_dir / "answer-key.csv"
    key_bytes = b"question,answer\n3,D\n1,B\n2,A\n"
    key_path.write_bytes(key_bytes)

    alignment_path = input_dir / "alignment.json"
    alignment_bytes = (
        json.dumps(
            {
                "1": [STANDARD_A],
                "2": [STANDARD_A],
                "3": [STANDARD_B],
            },
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    alignment_path.write_bytes(alignment_bytes)
    return key_path, key_bytes, alignment_path, alignment_bytes


def _bulk_args(
    key_path: Path,
    alignment_path: Path,
    *,
    apply: bool,
) -> list[str]:
    args = [
        "bulk-edit-assignment",
        "--class-id",
        CLASS_ID,
        "--assignment-id",
        ASSIGNMENT_ID,
        "--answer-key-csv",
        os.fspath(key_path),
        "--alignment-json",
        os.fspath(alignment_path),
        "--standards-profile-id",
        PROFILE_ID,
    ]
    if apply:
        args.append("--apply")
    return args


def _assert_sentinels(sentinels: dict[Path, bytes]) -> None:
    for path, expected in sentinels.items():
        _require(path.read_bytes() == expected, f"downstream sentinel changed: {path}")


def _assert_no_core_side_effects(workspace: Path) -> None:
    work = ModuleWorkRef(
        module_id="scoreform",
        class_id=CLASS_ID,
        work_id=ASSIGNMENT_ID,
    )
    _require(
        not list_academic_work_registration_revisions(workspace, work),
        "bulk assignment entry created Academic Work Registration history.",
    )
    _require(
        not any(record.work == work for record in list_publication_records(workspace)),
        "bulk assignment entry created Publication Record history.",
    )


def _verify_plan_only(
    executable: Path,
    workspace: Path,
    *,
    assignment_path: Path,
    assignment_bytes: bytes,
    sentinels: dict[Path, bytes],
    key_path: Path,
    key_bytes: bytes,
    alignment_path: Path,
    alignment_bytes: bytes,
) -> None:
    result = _run_scoreform(
        executable,
        workspace,
        _bulk_args(key_path, alignment_path, apply=False),
    )
    _assert_success(result, stage="bulk-edit plan")
    for expected in (
        "Mode: PLAN ONLY",
        "Complete normalized answer key",
        "Q1: B",
        "Q2: A",
        "Q3: D",
        f"Standards profile: {PROFILE_ID}",
        f"Q1: {STANDARD_A}",
        f"Q3: {STANDARD_B}",
        "No changes were made.",
    ):
        _require(expected in result.stdout, f"bulk-edit plan is missing {expected!r}.")

    _require(
        assignment_path.read_bytes() == assignment_bytes,
        "plan-only bulk edit changed assignment bytes.",
    )
    _require(key_path.read_bytes() == key_bytes, "plan-only bulk edit changed key input.")
    _require(
        alignment_path.read_bytes() == alignment_bytes,
        "plan-only bulk edit changed alignment input.",
    )
    _assert_sentinels(sentinels)
    _assert_no_core_side_effects(workspace)


def _verify_apply(
    executable: Path,
    workspace: Path,
    *,
    assignment_path: Path,
    sentinels: dict[Path, bytes],
    key_path: Path,
    key_bytes: bytes,
    alignment_path: Path,
    alignment_bytes: bytes,
) -> bytes:
    result = _run_scoreform(
        executable,
        workspace,
        _bulk_args(key_path, alignment_path, apply=True),
    )
    _assert_success(result, stage="bulk-edit apply")
    for expected in (
        "Mode: APPLIED",
        "Complete persisted answer key",
        "Q1: B",
        "Q2: A",
        "Q3: D",
        f"Standards profile: {PROFILE_ID}",
        f"Q1: {STANDARD_A}",
        f"Q3: {STANDARD_B}",
        "Only the canonical assignment definition was replaced.",
        "Historical results were not rescored",
    ):
        _require(expected in result.stdout, f"bulk-edit apply is missing {expected!r}.")

    persisted_bytes = assignment_path.read_bytes()
    persisted = assignment_from_json_bytes(persisted_bytes)
    _require(
        persisted["answer_key"] == {1: "B", 2: "A", 3: "D"},
        "persisted bulk answer key mismatch.",
    )
    _require(
        persisted.get("standards_profile_id") == PROFILE_ID,
        "persisted standards profile mismatch.",
    )
    _require(
        persisted["standards"]
        == {
            "1": [STANDARD_A],
            "2": [STANDARD_A],
            "3": [STANDARD_B],
        },
        "persisted standards alignment mismatch.",
    )
    _require(key_path.read_bytes() == key_bytes, "bulk apply changed key input.")
    _require(
        alignment_path.read_bytes() == alignment_bytes,
        "bulk apply changed alignment input.",
    )
    _assert_sentinels(sentinels)
    _assert_no_core_side_effects(workspace)
    return persisted_bytes


def _verify_invalid_combined_input_is_atomic(
    executable: Path,
    workspace: Path,
    *,
    assignment_path: Path,
    persisted_bytes: bytes,
    sentinels: dict[Path, bytes],
) -> None:
    result = _run_scoreform(
        executable,
        workspace,
        [
            "bulk-edit-assignment",
            "--class-id",
            CLASS_ID,
            "--assignment-id",
            ASSIGNMENT_ID,
            "--answer-key-text",
            "A A A",
            "--alignment-text",
            f"1-2={STANDARD_A};3=not_in_profile",
            "--standards-profile-id",
            PROFILE_ID,
            "--apply",
        ],
    )
    _assert_expected_failure(result, stage="invalid combined bulk edit")
    combined = result.stdout + result.stderr
    _require(
        "not_in_profile" in combined,
        "invalid alignment diagnostic did not identify the bad standard ID.",
    )
    _require(
        assignment_path.read_bytes() == persisted_bytes,
        "invalid combined bulk edit partially changed assignment bytes.",
    )
    _assert_sentinels(sentinels)
    _assert_no_core_side_effects(workspace)


def _verify_profile_retention_plan(
    executable: Path,
    workspace: Path,
    *,
    assignment_path: Path,
    persisted_bytes: bytes,
) -> None:
    result = _run_scoreform(
        executable,
        workspace,
        [
            "bulk-edit-assignment",
            "--class-id",
            CLASS_ID,
            "--assignment-id",
            ASSIGNMENT_ID,
            "--alignment-text",
            f"1={STANDARD_B};2=-;3={STANDARD_A}",
        ],
    )
    _assert_success(result, stage="profile retention plan")
    _require(
        f"Standards profile: {PROFILE_ID}" in result.stdout,
        "alignment replacement did not retain the existing standards profile.",
    )
    _require(
        assignment_path.read_bytes() == persisted_bytes,
        "profile-retention plan changed assignment bytes.",
    )


def _verify_no_partial_temporary_files(workspace: Path) -> None:
    paths = scoreform_work_paths(workspace, CLASS_ID, ASSIGNMENT_ID)
    leftovers = tuple(paths.work_root.glob(f".{paths.assignment_path.name}.*.tmp"))
    _require(not leftovers, f"bulk assignment entry left temporary files: {leftovers}")


def run_acceptance(
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
    assignment_path, assignment_bytes, sentinels = _prepare_native_state(workspace)
    key_path, key_bytes, alignment_path, alignment_bytes = _write_bulk_inputs(workspace)

    _verify_plan_only(
        executable,
        workspace,
        assignment_path=assignment_path,
        assignment_bytes=assignment_bytes,
        sentinels=sentinels,
        key_path=key_path,
        key_bytes=key_bytes,
        alignment_path=alignment_path,
        alignment_bytes=alignment_bytes,
    )
    persisted_bytes = _verify_apply(
        executable,
        workspace,
        assignment_path=assignment_path,
        sentinels=sentinels,
        key_path=key_path,
        key_bytes=key_bytes,
        alignment_path=alignment_path,
        alignment_bytes=alignment_bytes,
    )
    _verify_invalid_combined_input_is_atomic(
        executable,
        workspace,
        assignment_path=assignment_path,
        persisted_bytes=persisted_bytes,
        sentinels=sentinels,
    )
    _verify_profile_retention_plan(
        executable,
        workspace,
        assignment_path=assignment_path,
        persisted_bytes=persisted_bytes,
    )
    _verify_no_partial_temporary_files(workspace)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify installed ScoreForm SF-AC04 bulk assignment entry acceptance."
    )
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--expected-core-version", required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    workspace = cast(Path, args.workspace)
    try:
        run_acceptance(
            workspace,
            version=cast(str, args.version),
            expected_core_version=cast(str, args.expected_core_version),
        )
    except (AcceptanceFailure, OSError, ValueError) as error:
        print(f"ERROR: installed assignment bulk-entry acceptance failed: {error}")
        return 1

    print("PASS: installed ScoreForm SF-AC04 bulk assignment entry acceptance")
    print(f"ScoreForm version: {args.version}")
    print(f"PDS Core version: {args.expected_core_version}")
    print(f"Workspace: {workspace}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
