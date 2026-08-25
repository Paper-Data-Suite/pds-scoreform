"""Clean-wheel SF-AC01 acceptance for ScoreForm issue #187."""

from __future__ import annotations

import argparse
import importlib
import io
import os
import subprocess
import sys
from collections.abc import Callable, Iterator
from contextlib import ExitStack, redirect_stdout
from importlib import metadata
from pathlib import Path
from unittest.mock import patch

import pds_core
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu

from scoreform import menu_assignment_tasks


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
        "scoreform.assignment_workflows",
        "scoreform.menu_assignment_tasks",
        "scoreform.menu_navigation",
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
    help_result = _run([os.fspath(executable), "--help"], cwd=workspace.parent, env=environment)
    _require(help_result.returncode == 0, "installed scoreform --help failed.")
    for command in (
        "generate-batch",
        "score",
        "list-scan-review",
        "resolve-scan-review",
        "decode-qr",
        "validate-assignment",
        "bulk-edit-assignment",
        "copy-assignment",
        "preset",
        "academic-work",
        "manifest",
        "publication",
    ):
        _require(
            f"scoreform {command}" in help_result.stdout,
            f"direct CLI command disappeared from installed help: {command}",
        )
    _require(not workspace.exists(), "installed help/import checks created workspace state.")


def _inputs(values: list[str]) -> Callable[[str], str]:
    iterator: Iterator[str] = iter(values)

    def read(_prompt: str = "") -> str:
        try:
            return next(iterator)
        except StopIteration as exc:
            raise AcceptanceFailure("menu requested unexpected additional input") from exc

    return read


def _capture_menu(values: list[str]) -> str:
    output = io.StringIO()
    with (
        patch("builtins.input", _inputs(values)),
        redirect_stdout(output),
    ):
        status = menu_assignment_tasks.launch_assignment_menu(
            clear_screen_fn=lambda: None,
            pause_for_user_fn=lambda: None,
        )
    _require(status == 0, f"menu returned unexpected status {status}")
    return output.getvalue()


def _verify_structure() -> None:
    output = _capture_menu(["b"])
    expected_top = (
        "1. Create / Copy / Edit Assessments",
        "2. Print Answer Sheets",
        "3. Process Scans",
        "4. Review Results",
        "5. Enter Plain-Paper Results",
        "6. Share Results",
        "7. Advanced Tools",
    )
    for expected in expected_top:
        _require(expected in output, f"top-level task is missing: {expected}")
    for forbidden in (
        "8. Enter Plain-Paper Results",
        "9. Resolve scan review items",
        "10. Academic Work Registration",
        "11. Academic Result Manifests",
        "12. Academic Result Publications",
        "13. Copy an assignment",
        "14. Assessment setup presets",
    ):
        _require(forbidden not in output, f"old peer-level menu entry remains: {forbidden}")
    for navigation in ("B. Back", "M. Main Menu", "Q. Quit"):
        _require(navigation in output, f"shared navigation is missing: {navigation}")

    grouped = _capture_menu(["1", "b", "3", "b", "6", "b", "7", "b", "b"])
    for expected in (
        "1. Create an assignment",
        "2. Copy an assignment",
        "3. Edit an assignment",
        "4. Assessment setup presets",
        "1. Score scanned responses",
        "2. Resolve scan review items",
        "1. Share Results with Meridian",
        "2. Academic Work Registration",
        "3. Academic Result Manifests",
        "4. Academic Result Publications",
        "1. Validate an assignment file",
        "2. Decode QR from a file",
        "publishes ScoreForm evidence through Core",
    ):
        _require(expected in grouped, f"grouped operation is missing: {expected}")


def _verify_navigation_exceptions() -> None:
    menus: tuple[Callable[..., int], ...] = (
        menu_assignment_tasks.launch_assignment_menu,
        menu_assignment_tasks.launch_assessment_definition_menu,
        menu_assignment_tasks.launch_process_scans_menu,
        menu_assignment_tasks.launch_share_results_menu,
        menu_assignment_tasks.launch_advanced_tools_menu,
    )
    for menu in menus:
        with patch("builtins.input", _inputs(["m"])):
            try:
                menu(clear_screen_fn=lambda: None, pause_for_user_fn=lambda: None)
            except ReturnToMainMenu:
                pass
            else:
                raise AcceptanceFailure(
                    f"{menu.__name__} did not propagate ReturnToMainMenu"
                )

        with patch("builtins.input", _inputs(["q"])):
            try:
                menu(clear_screen_fn=lambda: None, pause_for_user_fn=lambda: None)
            except QuitPDS:
                pass
            else:
                raise AcceptanceFailure(f"{menu.__name__} did not propagate QuitPDS")


def _verify_operation_reachability() -> None:
    routes = (
        (["1", "1", "b", "b"], "_run_create_assignment"),
        (["1", "2", "b", "b"], "_run_copy_assignment"),
        (["1", "3", "b", "b"], "_run_edit_assignment"),
        (["1", "4", "b", "b"], "_run_assignment_presets"),
        (["2", "b"], "_run_print_answer_sheets"),
        (["3", "1", "b", "b"], "_run_score_scans"),
        (["3", "2", "b", "b"], "_run_scan_review"),
        (["4", "b"], "_run_review_results"),
        (["5", "b"], "_run_plain_paper_results"),
        (["6", "1", "b", "b"], "_run_share_results_with_meridian"),
        (["6", "2", "b", "b"], "_run_academic_work_registration"),
        (["6", "3", "b", "b"], "_run_academic_result_manifests"),
        (["6", "4", "b", "b"], "_run_academic_result_publications"),
        (["7", "1", "b", "b"], "_run_validate_assignment_file"),
        (["7", "2", "b", "b"], "_run_decode_qr_file"),
    )
    for values, action_name in routes:
        calls: list[str] = []

        def record(**_kwargs: object) -> None:
            calls.append(action_name)

        output = io.StringIO()
        with ExitStack() as stack:
            stack.enter_context(patch.object(menu_assignment_tasks, action_name, record))
            stack.enter_context(patch("builtins.input", _inputs(values)))
            stack.enter_context(redirect_stdout(output))
            status = menu_assignment_tasks.launch_assignment_menu(
                clear_screen_fn=lambda: None,
                pause_for_user_fn=lambda: None,
            )
        _require(status == 0, f"route for {action_name} returned {status}")
        _require(calls == [action_name], f"route for {action_name} dispatched {calls}")


def verify(workspace: Path, *, version: str, expected_core_version: str) -> None:
    """Run installed SF-AC01 acceptance without creating domain state."""
    _verify_installed_provenance(
        workspace,
        version=version,
        expected_core_version=expected_core_version,
    )
    _verify_structure()
    _verify_navigation_exceptions()
    _verify_operation_reachability()
    _require(not workspace.exists(), "menu acceptance created workspace/domain state.")


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

    print("PASS: installed task-oriented Assignment Management satisfies SF-AC01.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
