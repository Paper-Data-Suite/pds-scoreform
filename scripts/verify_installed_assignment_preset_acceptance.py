"""Installed clean-wheel acceptance for ScoreForm assessment setup presets."""

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
from scoreform.assignment_presets import (
    assignment_preset_collection_dir,
    assignment_preset_path,
    load_assignment_preset,
)
from scoreform.layouts import DEFAULT_LAYOUT_ID, require_layout
from scoreform.work_paths import initialize_scoreform_work_layout, scoreform_work_paths
from scoreform.workflows import write_assignment_json

SOURCE_CLASS_ID = "preset_source_class"
TARGET_CLASS_IDS = ("preset_target_class_1", "preset_target_class_2")
SOURCE_ASSIGNMENT_ID = "preset_source_quiz"
TARGET_ASSIGNMENT_ID = "preset_applied_quiz"
PRESET_ID = "reusable_short_quiz"
PRESET_LABEL = "Reusable Short Quiz"
SOURCE_STUDENT_ID = "preset_source_student"
TARGET_STUDENT_IDS = (
    ("preset_target_student_1", "preset_target_student_2"),
    ("preset_target_student_3",),
)

_ALLOWED_PRESET_KEYS = {
    "schema_version",
    "module",
    "record_type",
    "preset_id",
    "label",
    "question_count",
    "choices",
    "layout_id",
    "answer_key",
    "standards",
}


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
        "scoreform.assignment_presets",
        "scoreform.cli_assignment_presets",
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
        "scoreform preset list" in help_result.stdout,
        "installed top-level help does not advertise preset commands.",
    )

    preset_help = _run_scoreform(executable, workspace, ["preset", "--help"])
    _assert_success(preset_help, stage="installed preset help")
    for expected in (
        "scoreform preset list",
        "scoreform preset save",
        "scoreform preset apply",
        "scoreform preset delete",
        "PLAN ONLY",
    ):
        _require(
            expected in preset_help.stdout,
            f"installed preset help is missing {expected!r}.",
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
        "assignment_id": SOURCE_ASSIGNMENT_ID,
        "title": "Synthetic Preset Source",
        "question_count": 3,
        "choices": list(layout.choices),
        "layout_id": layout.layout_id,
        "answer_key": {"1": "A", "2": "B", "3": "C"},
        "standards": {"1": [], "2": [], "3": []},
    }
    normalized = validate_assignment_data(candidate)
    if normalized is None:
        raise AcceptanceFailure("synthetic source assignment failed validation.")
    return cast(dict[str, object], normalized)


def _prepare_native_state(
    workspace: Path,
) -> tuple[bytes, bytes, dict[str, bytes]]:
    ensure_workspace_root(workspace)
    source_roster = _write_roster(
        workspace,
        SOURCE_CLASS_ID,
        period="2",
        student_ids=(SOURCE_STUDENT_ID,),
    )
    target_rosters: dict[str, bytes] = {}
    for index, class_id in enumerate(TARGET_CLASS_IDS):
        target_rosters[class_id] = _write_roster(
            workspace,
            class_id,
            period=str(4 + index * 2),
            student_ids=TARGET_STUDENT_IDS[index],
        )

    source_paths = initialize_scoreform_work_layout(
        workspace,
        SOURCE_CLASS_ID,
        SOURCE_ASSIGNMENT_ID,
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
    return source_bytes, source_roster, target_rosters


def _save_args(*, apply: bool) -> list[str]:
    args = [
        "preset",
        "save",
        "--preset-id",
        PRESET_ID,
        "--source-class-id",
        SOURCE_CLASS_ID,
        "--source-assignment-id",
        SOURCE_ASSIGNMENT_ID,
        "--label",
        PRESET_LABEL,
    ]
    if apply:
        args.append("--apply")
    return args


def _apply_args(*, apply: bool) -> list[str]:
    args = [
        "preset",
        "apply",
        "--preset-id",
        PRESET_ID,
        "--target-assignment-id",
        TARGET_ASSIGNMENT_ID,
        "--title",
        "Applied from Preset",
    ]
    for class_id in TARGET_CLASS_IDS:
        args.extend(["--target-class-id", class_id])
    if apply:
        args.append("--apply")
    return args


def _verify_save_plan_only(executable: Path, workspace: Path) -> None:
    collection = assignment_preset_collection_dir(workspace)
    _require(not collection.exists(), "preset collection existed before plan-only save.")
    result = _run_scoreform(executable, workspace, _save_args(apply=False))
    _assert_success(result, stage="preset save plan")
    for expected in (
        "Mode: PLAN ONLY",
        f"preset_id: {PRESET_ID}",
        "source assignment/class identity persisted: no",
        "student/operational/result history persisted: no",
        "No changes were made.",
    ):
        _require(expected in result.stdout, f"preset save plan is missing {expected!r}.")
    _require(
        not collection.exists(),
        "plan-only preset save created the preset collection.",
    )


def _verify_save_apply(
    executable: Path,
    workspace: Path,
    *,
    source_bytes: bytes,
    source_roster: bytes,
) -> bytes:
    result = _run_scoreform(executable, workspace, _save_args(apply=True))
    _assert_success(result, stage="preset save apply")
    _require(
        "Saved assessment setup preset." in result.stdout,
        "preset save did not report success.",
    )

    snapshot = load_assignment_preset(workspace, PRESET_ID)
    _require(
        set(snapshot.preset) == _ALLOWED_PRESET_KEYS,
        "persisted preset did not use the exact non-student v1 allowlist.",
    )
    _require(snapshot.preset["label"] == PRESET_LABEL, "preset label mismatch.")
    _require(
        snapshot.preset["answer_key"] == {"1": "A", "2": "B", "3": "C"},
        "preset answer key mismatch.",
    )

    raw = snapshot.preset_bytes.decode("utf-8")
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
            forbidden not in raw,
            f"persisted preset leaked forbidden value {forbidden!r}.",
        )

    source_paths = scoreform_work_paths(
        workspace,
        SOURCE_CLASS_ID,
        SOURCE_ASSIGNMENT_ID,
    )
    _require(
        source_paths.assignment_path.read_bytes() == source_bytes,
        "saving a preset changed the source assignment.",
    )
    _require(
        class_roster_path(workspace, SOURCE_CLASS_ID).read_bytes() == source_roster,
        "saving a preset changed the source roster.",
    )
    return snapshot.preset_bytes


def _verify_source_independence(
    executable: Path,
    workspace: Path,
    *,
    preset_bytes: bytes,
) -> None:
    source_paths = scoreform_work_paths(
        workspace,
        SOURCE_CLASS_ID,
        SOURCE_ASSIGNMENT_ID,
    )
    source_paths.assignment_path.unlink()
    show_result = _run_scoreform(
        executable,
        workspace,
        ["preset", "show", "--preset-id", PRESET_ID],
    )
    _assert_success(show_result, stage="preset show after source removal")
    _require(
        f"preset_id: {PRESET_ID}" in show_result.stdout
        and "Q1: A" in show_result.stdout
        and "Q3: C" in show_result.stdout,
        "preset stopped being independently readable after source removal.",
    )
    _require(
        assignment_preset_path(workspace, PRESET_ID).read_bytes() == preset_bytes,
        "source removal changed preset bytes.",
    )


def _verify_apply_plan_only(
    executable: Path,
    workspace: Path,
    *,
    preset_bytes: bytes,
) -> None:
    targets = [
        scoreform_work_paths(workspace, class_id, TARGET_ASSIGNMENT_ID)
        for class_id in TARGET_CLASS_IDS
    ]
    result = _run_scoreform(executable, workspace, _apply_args(apply=False))
    _assert_success(result, stage="preset apply plan")
    for expected in (
        "Mode: PLAN ONLY",
        f"preset_id: {PRESET_ID}",
        f"assignment_id: {TARGET_ASSIGNMENT_ID}",
        "Q1: A",
        "Q2: B",
        "Q3: C",
        "No changes were made.",
    ):
        _require(expected in result.stdout, f"preset apply plan is missing {expected!r}.")
    for target in targets:
        _require(
            not target.work_root.exists(),
            f"plan-only apply mutated target {target.work_ref}.",
        )
    _require(
        assignment_preset_path(workspace, PRESET_ID).read_bytes() == preset_bytes,
        "plan-only apply changed preset bytes.",
    )


def _verify_apply(
    executable: Path,
    workspace: Path,
    *,
    preset_bytes: bytes,
    target_rosters: dict[str, bytes],
) -> dict[str, bytes]:
    result = _run_scoreform(executable, workspace, _apply_args(apply=True))
    _assert_success(result, stage="preset apply")
    _require(
        "Created 2 fresh assignments from preset" in result.stdout,
        "multi-target preset apply did not report both assignments.",
    )

    created_assignment_bytes: dict[str, bytes] = {}
    for class_id in TARGET_CLASS_IDS:
        paths = scoreform_work_paths(workspace, class_id, TARGET_ASSIGNMENT_ID)
        _require(paths.assignment_path.is_file(), f"missing target assignment for {class_id}.")
        created_assignment_bytes[class_id] = paths.assignment_path.read_bytes()
        assignment = assignment_from_json_bytes(created_assignment_bytes[class_id])
        _require(assignment["assignment_id"] == TARGET_ASSIGNMENT_ID, "assignment ID mismatch.")
        _require(assignment["title"] == "Applied from Preset", "assignment title mismatch.")
        _require(
            assignment["answer_key"] == {1: "A", 2: "B", 3: "C"},
            "preset-derived answer key mismatch.",
        )
        _require(
            class_roster_path(workspace, class_id).read_bytes()
            == target_rosters[class_id],
            f"preset apply changed target roster for {class_id}.",
        )
        for forbidden in (
            paths.results_path,
            paths.answer_sheets_dir,
            paths.exports_dir,
            paths.academic_result_manifests_dir,
        ):
            _require(
                not forbidden.exists(),
                f"preset apply unexpectedly created downstream state: {forbidden}",
            )
        _require(
            list_academic_work_registration_revisions(workspace, paths.work_ref) == (),
            f"preset apply unexpectedly registered Academic Work for {class_id}.",
        )
        publications = tuple(
            publication
            for publication in list_publication_records(workspace)
            if publication.work == paths.work_ref
        )
        _require(
            publications == (),
            f"preset apply unexpectedly published state for {class_id}.",
        )

    _require(
        assignment_preset_path(workspace, PRESET_ID).read_bytes() == preset_bytes,
        "applying a preset changed the preset.",
    )
    return created_assignment_bytes


def _verify_delete_independence(
    executable: Path,
    workspace: Path,
    *,
    created_assignment_bytes: dict[str, bytes],
) -> None:
    preset_path = assignment_preset_path(workspace, PRESET_ID)
    plan_result = _run_scoreform(
        executable,
        workspace,
        ["preset", "delete", "--preset-id", PRESET_ID],
    )
    _assert_success(plan_result, stage="preset delete plan")
    _require("Mode: PLAN ONLY" in plan_result.stdout, "delete was not plan-only.")
    _require(preset_path.is_file(), "plan-only delete removed the preset.")

    apply_result = _run_scoreform(
        executable,
        workspace,
        ["preset", "delete", "--preset-id", PRESET_ID, "--apply"],
    )
    _assert_success(apply_result, stage="preset delete apply")
    _require(not preset_path.exists(), "explicit preset delete did not remove preset.")

    for class_id in TARGET_CLASS_IDS:
        paths = scoreform_work_paths(workspace, class_id, TARGET_ASSIGNMENT_ID)
        _require(
            paths.assignment_path.read_bytes() == created_assignment_bytes[class_id],
            f"deleting preset changed prior assignment {class_id}.",
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--version", default="0.10.0")
    parser.add_argument("--expected-core-version", default="0.6.0")
    args = parser.parse_args()

    workspace = args.workspace.resolve()
    try:
        executable = _verify_installed_provenance(
            workspace,
            version=args.version,
            expected_core_version=args.expected_core_version,
        )
        source_bytes, source_roster, target_rosters = _prepare_native_state(workspace)
        _verify_save_plan_only(executable, workspace)
        preset_bytes = _verify_save_apply(
            executable,
            workspace,
            source_bytes=source_bytes,
            source_roster=source_roster,
        )
        _verify_source_independence(
            executable,
            workspace,
            preset_bytes=preset_bytes,
        )
        _verify_apply_plan_only(
            executable,
            workspace,
            preset_bytes=preset_bytes,
        )
        created_assignment_bytes = _verify_apply(
            executable,
            workspace,
            preset_bytes=preset_bytes,
            target_rosters=target_rosters,
        )
        _verify_delete_independence(
            executable,
            workspace,
            created_assignment_bytes=created_assignment_bytes,
        )
    except AcceptanceFailure as error:
        raise SystemExit(
            f"FAILED: installed assignment-preset acceptance: {error}"
        ) from error

    print("PASSED: installed assignment-preset acceptance")
    print(f"ScoreForm version: {args.version}")
    print(f"Core version: {args.expected_core_version}")
    print(f"Preset: {PRESET_ID}")
    print(f"Targets: {', '.join(TARGET_CLASS_IDS)}")
    print("Plan-only mutations: none")
    print("Source dependency after save: none")
    print("Inherited operational/evidence history: none")
    print("Prior assignments changed by preset deletion: none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
