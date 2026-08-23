"""Clean-wheel SF-AC06 acceptance for ScoreForm issue #188."""

from __future__ import annotations

import argparse
import importlib
import io
import json
import os
import subprocess
import sys
from collections.abc import Callable, Iterator
from contextlib import redirect_stdout
from dataclasses import fields
from importlib import metadata
from pathlib import Path
from unittest.mock import patch

import pds_core
from pds_core.menu_navigation import ReturnToMainMenu
from pds_core.routes import class_roster_path

from scoreform import cli, menu_assignment_tasks
from scoreform.assignment_context import (
    AssignmentContextRef,
    AssignmentContextSession,
    resolve_active_assignment_context,
    resolve_assignment_context_ref,
)
from scoreform.menu_assignment_context import (
    format_active_context_lines,
    launch_assignment_context_menu,
    select_assignment_for_workflow,
    select_canonical_assignment,
)
from scoreform.work_paths import scoreform_work_paths
from scoreform.workspace import get_scoreform_workspace_root


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
        resolved = path.resolve()
        prefix = Path(sys.prefix).resolve()
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


def _inputs(values: list[str]) -> Callable[[str], str]:
    iterator: Iterator[str] = iter(values)

    def read(_prompt: str = "") -> str:
        try:
            return next(iterator)
        except StopIteration as exc:
            raise AcceptanceFailure("menu requested unexpected additional input") from exc

    return read


def _write_assignment_fixture(
    workspace: Path,
    *,
    class_id: str,
    assignment_id: str,
    title: str,
) -> None:
    roster_path = class_roster_path(workspace, class_id)
    roster_path.parent.mkdir(parents=True, exist_ok=True)
    if not roster_path.exists():
        roster_path.write_text(
            "\n".join(
                (
                    "class_id,student_id,last_name,first_name,period",
                    f"{class_id},synthetic_1,Student,Synthetic,1",
                )
            )
            + "\n",
            encoding="utf-8",
        )

    paths = scoreform_work_paths(workspace, class_id, assignment_id)
    paths.work_root.mkdir(parents=True, exist_ok=True)
    paths.assignment_path.write_text(
        json.dumps(
            {
                "assignment_id": assignment_id,
                "title": title,
                "question_count": 2,
                "choices": ["A", "B", "C", "D"],
                "layout_id": "standard_15q_abcd_v1",
                "answer_key": {"1": "A", "2": "B"},
                "standards": {"1": [], "2": []},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _workspace_files(workspace: Path) -> tuple[str, ...]:
    if not workspace.exists():
        return ()
    return tuple(
        sorted(
            path.relative_to(workspace).as_posix()
            for path in workspace.rglob("*")
            if path.is_file()
        )
    )


def _verify_installed_provenance(
    workspace: Path,
    *,
    version: str,
    expected_core_version: str,
) -> None:
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

    for module_name in (
        "scoreform",
        "scoreform.assignment_context",
        "scoreform.menu_assignment_context",
        "scoreform.menu_assignment_tasks",
        "scoreform.assignment_workflows",
        "scoreform.cli",
        "pds_core",
        "pds_core.menu_navigation",
    ):
        origin = _module_origin(module_name)
        _require(
            _is_isolated_installed_origin(origin),
            f"{module_name} did not import from isolated site-packages: {origin}",
        )

    pip_check = _run(
        [sys.executable, "-m", "pip", "check"],
        cwd=workspace.parent,
    )
    _require(
        pip_check.returncode == 0,
        f"installed pip check failed: {pip_check.stdout} {pip_check.stderr}",
    )

    executable = _scoreform_executable()
    environment = os.environ.copy()
    environment["PDS_WORKSPACE_ROOT"] = os.fspath(workspace)
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    help_result = _run(
        [os.fspath(executable), "--help"],
        cwd=workspace.parent,
        env=environment,
    )
    _require(help_result.returncode == 0, "installed scoreform --help failed.")
    for command in (
        "generate",
        "generate-batch",
        "regenerate-sheets",
        "score",
        "list-scan-review",
        "resolve-scan-review",
        "decode-qr",
        "validate-assignment",
        "validate-roster",
        "setup-assignment",
        "bulk-edit-assignment",
        "copy-assignment",
        "preset",
        "academic-work",
        "manifest",
        "publication",
        "workspace",
        "school-year",
        "scan-filing",
    ):
        _require(
            f"scoreform {command}" in help_result.stdout,
            f"direct CLI command disappeared from installed help: {command}",
        )
    _require(not workspace.exists(), "installed help/import checks created workspace state.")


def _verify_identity_only_model() -> None:
    ref_fields = tuple(field.name for field in fields(AssignmentContextRef))
    _require(
        ref_fields == ("class_id", "assignment_id"),
        f"context reference stores unexpected fields: {ref_fields}",
    )
    session_fields = tuple(field.name for field in fields(AssignmentContextSession))
    _require(
        session_fields == ("_active", "_recent", "_workspace_root"),
        f"context session stores unexpected fields: {session_fields}",
    )


def _verify_selection_and_continuity(workspace: Path) -> None:
    os.environ["PDS_WORKSPACE_ROOT"] = os.fspath(workspace)
    resolved_workspace = get_scoreform_workspace_root()
    _require(
        resolved_workspace == workspace.resolve(),
        "ScoreForm resolved an unexpected canonical workspace.",
    )
    _write_assignment_fixture(
        workspace,
        class_id="english10_p2",
        assignment_id="unit_1_quiz",
        title="Unit 1 Quiz",
    )
    _write_assignment_fixture(
        workspace,
        class_id="english10_p2",
        assignment_id="unit_2_quiz",
        title="Unit 2 Quiz",
    )
    fixture_files = _workspace_files(workspace)

    session = AssignmentContextSession()
    with patch("builtins.input", _inputs(["1", "1"])):
        record = select_canonical_assignment(session, clear_screen_fn=lambda: None)
    _require(record is not None, "canonical assignment selection was cancelled.")
    _require(
        session.active == AssignmentContextRef("english10_p2", "unit_1_quiz"),
        "selected assignment did not become active context.",
    )

    banner = "\n".join(format_active_context_lines(session))
    _require("english10_p2 / unit_1_quiz" in banner, "active banner lacks exact identity.")
    _require("Unit 1 Quiz" in banner, "active banner lacks current canonical title.")
    for forbidden in (str(workspace), "synthetic_1", "results.csv"):
        _require(forbidden not in banner, f"active banner leaked context data: {forbidden}")

    output = io.StringIO()
    with (
        patch("builtins.input", _inputs(["1", "m", "1", "b", "5"])),
        redirect_stdout(output),
    ):
        status = cli.launch_menu(context_session=session)
    _require(status == 0, f"iterative main-menu continuity returned {status}.")
    _require(
        output.getvalue().count("Active assignment: english10_p2 / unit_1_quiz") >= 2,
        "active assignment did not survive Main Menu navigation/re-entry.",
    )

    with patch("builtins.input", _inputs(["2", "1", "2"])):
        switched = select_assignment_for_workflow(
            session,
            clear_screen_fn=lambda: None,
            offer_switch=True,
            workflow_title="Installed Context Acceptance",
        )
    _require(switched is not None, "explicit assignment switch was cancelled.")
    _require(
        session.active == AssignmentContextRef("english10_p2", "unit_2_quiz"),
        "explicit assignment switch did not activate the selected assignment.",
    )
    _require(
        session.recent
        == (
            AssignmentContextRef("english10_p2", "unit_2_quiz"),
            AssignmentContextRef("english10_p2", "unit_1_quiz"),
        ),
        "recent assignment ordering/deduplication is incorrect.",
    )

    with patch("builtins.input", _inputs(["3", "2", "2", "b"])):
        context_status = launch_assignment_context_menu(
            session,
            clear_screen_fn=lambda: None,
            pause_for_user_fn=lambda: None,
        )
    _require(context_status == 0, "Assignment Context menu did not return normally.")
    _require(
        session.active == AssignmentContextRef("english10_p2", "unit_1_quiz"),
        "recent-assignment selection did not restore the requested context.",
    )

    with patch("builtins.input", _inputs(["4", "b"])):
        launch_assignment_context_menu(
            session,
            clear_screen_fn=lambda: None,
            pause_for_user_fn=lambda: None,
        )
    _require(session.recent == (), "explicit recent-history clear did not clear the MRU list.")
    _require(
        _workspace_files(workspace) == fixture_files,
        "context selection/navigation wrote unexpected workspace files.",
    )

    session.activate(
        AssignmentContextRef("english10_p2", "unit_1_quiz"),
        workspace_root=workspace,
    )
    assignment_path = scoreform_work_paths(
        workspace,
        "english10_p2",
        "unit_1_quiz",
    ).assignment_path
    assignment_path.unlink()
    stale = resolve_active_assignment_context(session, workspace_root=workspace)
    _require(stale is not None and not stale.is_valid, "missing assignment did not fail closed.")
    _require(session.active is None, "stale active context was not cleared.")


def _verify_workspace_change_fails_closed(workspace: Path) -> None:
    second = workspace.parent / f"{workspace.name}-second"
    if second.exists():
        raise AcceptanceFailure(f"second workspace unexpectedly exists: {second}")
    _write_assignment_fixture(
        second,
        class_id="english10_p2",
        assignment_id="unit_1_quiz",
        title="Different Workspace Quiz",
    )

    session = AssignmentContextSession()
    ref = AssignmentContextRef("english10_p2", "unit_1_quiz")
    session.activate(ref, workspace_root=workspace)
    outcome = resolve_assignment_context_ref(session, ref, workspace_root=second)
    _require(outcome.workspace_changed, "workspace change was not reported.")
    _require(not outcome.is_valid, "workspace-changed identity was incorrectly reused.")
    _require(session.active is None and session.recent == (), "workspace change did not clear context.")


def _verify_shared_navigation_preserves_context(workspace: Path) -> None:
    os.environ["PDS_WORKSPACE_ROOT"] = os.fspath(workspace)
    session = AssignmentContextSession()
    ref = AssignmentContextRef("english10_p2", "unit_2_quiz")
    session.activate(ref, workspace_root=workspace)
    with patch("builtins.input", _inputs(["m"])):
        try:
            menu_assignment_tasks.launch_assignment_menu(
                clear_screen_fn=lambda: None,
                pause_for_user_fn=lambda: None,
                context_session=session,
            )
        except ReturnToMainMenu:
            pass
        else:
            raise AcceptanceFailure("Assignment Management did not propagate Main Menu.")
    _require(session.active == ref, "Main Menu navigation cleared valid context.")


def verify(workspace: Path, *, version: str, expected_core_version: str) -> None:
    """Run installed SF-AC06 acceptance against synthetic canonical workspace data."""
    _verify_installed_provenance(
        workspace,
        version=version,
        expected_core_version=expected_core_version,
    )
    _verify_identity_only_model()
    _verify_selection_and_continuity(workspace)
    _verify_shared_navigation_preserves_context(workspace)
    _verify_workspace_change_fails_closed(workspace)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--expected-core-version", required=True)
    args = parser.parse_args()

    try:
        verify(
            args.workspace.resolve(),
            version=args.version,
            expected_core_version=args.expected_core_version,
        )
    except AcceptanceFailure as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    print("PASS: installed recent/active assignment context satisfies SF-AC06.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
