"""Clean-wheel SF-AC07 acceptance for ScoreForm issue #189."""

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
from importlib import metadata
from pathlib import Path
from unittest.mock import patch

import pds_core
from pds_core.routes import class_roster_path

from scoreform.assignment_context import AssignmentContextRef, AssignmentContextSession
from scoreform.generate_workflows import regenerate_answer_sheets_for_assignment
from scoreform.guided_scan_workflow import launch_guided_scan_to_results
from scoreform.results_viewer import load_assignment_results
from scoreform.scan_review_resolution import discover_scan_review_items
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


class _PromptRecorder:
    def __init__(self, values: list[str]) -> None:
        self._values: Iterator[str] = iter(values)
        self.prompts: list[str] = []

    def __call__(self, prompt: str = "") -> str:
        self.prompts.append(prompt)
        try:
            return next(self._values)
        except StopIteration as exc:
            raise AcceptanceFailure(
                f"guided workflow requested unexpected additional input: {prompt!r}"
            ) from exc


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


def _write_assignment_fixture(
    workspace: Path,
    *,
    class_id: str,
    assignment_id: str,
) -> None:
    roster_path = class_roster_path(workspace, class_id)
    roster_path.parent.mkdir(parents=True, exist_ok=True)
    roster_path.write_text(
        "\n".join(
            (
                "class_id,student_id,last_name,first_name,period",
                f"{class_id},synthetic_1,Learner,Synthetic,1",
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
                "title": "Synthetic Guided Scan Acceptance",
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


def _write_blank_png(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image_module = importlib.import_module("PIL.Image")
    image = image_module.new("RGB", (480, 360), (255, 255, 255))
    image.save(path, format="PNG")
    _require(path.is_file() and path.stat().st_size > 0, "blank PNG fixture was not written.")


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
        "scoreform.cli",
        "scoreform.cli_score",
        "scoreform.guided_scan_results",
        "scoreform.guided_scan_context",
        "scoreform.guided_scan_workflow",
        "scoreform.menu_scoring",
        "scoreform.menu_scan_review",
        "scoreform.assignment_context",
        "scoreform.assignment_workflows",
        "pds_core",
        "pds_core.scan_retention",
        "pds_core.module_dispatch",
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
    _require(
        "scoreform score <scan.pdf>" in help_result.stdout,
        "installed direct score command disappeared from help.",
    )
    _require(
        not workspace.exists(),
        "installed help/import/provenance checks created workspace state.",
    )


def _generate_registered_sheet(
    workspace: Path,
    *,
    class_id: str,
    assignment_id: str,
) -> Path:
    _write_assignment_fixture(
        workspace,
        class_id=class_id,
        assignment_id=assignment_id,
    )
    generated = regenerate_answer_sheets_for_assignment(
        class_id,
        assignment_id,
        workspace_root=workspace,
    )
    _require(
        generated.generation_result is not None
        and generated.generation_result.success,
        "synthetic managed answer-sheet generation did not succeed.",
    )
    individual_dir = Path(generated.individual_templates_dir)
    candidates = tuple(sorted(individual_dir.glob("*.pdf"), key=lambda path: path.name))
    _require(
        len(candidates) == 1,
        f"expected one generated individual PDF, found {len(candidates)}.",
    )
    return candidates[0]


def _verify_guided_success(
    workspace: Path,
    *,
    source_pdf: Path,
    class_id: str,
    assignment_id: str,
) -> None:
    session = AssignmentContextSession()
    prompts = _PromptRecorder(["1", "2"])
    output = io.StringIO()
    with (
        patch("builtins.input", prompts),
        redirect_stdout(output),
    ):
        status = launch_guided_scan_to_results(
            source_pdf,
            context_session=session,
            clear_screen_fn=lambda: None,
            pause_for_user_fn=lambda: None,
        )

    _require(status == 0, f"guided retained scoring returned {status}.")
    expected_ref = AssignmentContextRef(class_id, assignment_id)
    _require(
        session.active == expected_ref,
        "durable routed target did not activate the exact assignment context.",
    )
    _require(
        not any(
            prompt.strip().casefold().startswith(("select class", "select assignment"))
            for prompt in prompts.prompts
        ),
        f"guided result continuation reselected class/assignment: {prompts.prompts}",
    )

    rendered = output.getvalue()
    for expected in (
        "Scan Processing Summary",
        "Retained by Core: yes",
        "Attempts recorded: 1",
        f"{class_id} / {assignment_id}",
        "Using active assignment:",
        "View Assignment Results",
    ):
        _require(expected in rendered, f"guided success output lacks {expected!r}.")
    retained_root = workspace / "scans" / "source"
    retained_files = tuple(
        path for path in retained_root.rglob("*") if path.is_file()
    )
    _require(
        len(retained_files) == 1,
        f"one guided operation should retain one source, found {len(retained_files)}.",
    )

    paths = scoreform_work_paths(workspace, class_id, assignment_id)
    _require(paths.results_path.is_file(), "guided scoring did not create canonical results.csv.")
    rows = load_assignment_results(paths.results_path)
    _require(len(rows) == 1, f"expected exactly one routed attempt, found {len(rows)}.")


def _run_guided_failure(
    workspace: Path,
    source: Path,
    *,
    choices: list[str],
) -> tuple[int, str, tuple[str, ...]]:
    prompts = _PromptRecorder(choices)
    output = io.StringIO()
    with (
        patch("builtins.input", prompts),
        redirect_stdout(output),
    ):
        status = launch_guided_scan_to_results(
            source,
            context_session=AssignmentContextSession(),
            clear_screen_fn=lambda: None,
            pause_for_user_fn=lambda: None,
        )
    return status, output.getvalue(), tuple(prompts.prompts)


def _verify_exact_source_review_scope(workspace: Path) -> None:
    fixture_root = workspace.parent / f"{workspace.name}-scan-fixtures"
    first = fixture_root / "first_qrless.png"
    second = fixture_root / "second_qrless.png"
    _write_blank_png(first)
    _write_blank_png(second)

    first_status, first_output, _first_prompts = _run_guided_failure(
        workspace,
        first,
        choices=["2"],
    )
    _require(first_status != 0, "QR-less first scan unexpectedly succeeded.")
    _require("Review unresolved items from this scan" in first_output, "first failure offered no review path.")

    first_discovery = discover_scan_review_items(workspace)
    first_items = tuple(
        item for item in first_discovery.items if item.source_filename == first.name
    )
    _require(len(first_items) == 1, "first QR-less scan did not persist one review item.")
    first_item = first_items[0]

    second_status, second_output, _second_prompts = _run_guided_failure(
        workspace,
        second,
        choices=["1", "b", "2"],
    )
    _require(second_status != 0, "QR-less second scan unexpectedly succeeded.")
    _require("Review This Scan" in second_output, "guided failure did not open source-scoped review.")
    _require(second.name in second_output, "source-scoped review omitted the current scan.")
    _require(
        first.name not in second_output,
        "source-scoped review leaked an unresolved item from a different retained scan.",
    )

    discovery = discover_scan_review_items(workspace)
    second_items = tuple(
        item for item in discovery.items if item.source_filename == second.name
    )
    _require(len(second_items) == 1, "second QR-less scan did not persist one review item.")
    second_item = second_items[0]
    _require(
        first_item.source_scan_id != second_item.source_scan_id,
        "distinct retained scans reused source_scan_id.",
    )
    scoped = discover_scan_review_items(
        workspace,
        source_scan_id=second_item.source_scan_id,
    )
    _require(
        tuple(item.failure_id for item in scoped.items) == (second_item.failure_id,),
        "exact source_scan_id discovery returned unrelated review items.",
    )


def _verify_no_guided_shadow_persistence(workspace: Path) -> None:
    files = _workspace_files(workspace)
    forbidden_fragments = (
        "guided_scan",
        "guided-scan",
        "assignment_context.json",
        "recent_context",
        "recent-assignment",
    )
    offenders = tuple(
        relative
        for relative in files
        if any(fragment in relative.casefold() for fragment in forbidden_fragments)
    )
    _require(
        not offenders,
        f"guided workflow created shadow persistence: {offenders}",
    )


def _snapshot_selected_files(
    workspace: Path,
    *,
    include: Callable[[str], bool],
) -> tuple[tuple[str, bytes], ...]:
    captured: list[tuple[str, bytes]] = []
    for path in workspace.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(workspace).as_posix()
        if include(relative):
            captured.append((relative, path.read_bytes()))
    return tuple(sorted(captured, key=lambda item: item[0]))


def _verify_direct_score_is_prompt_free_and_deterministic(workspace: Path) -> None:
    executable = _scoreform_executable()
    environment = os.environ.copy()
    environment["PDS_WORKSPACE_ROOT"] = os.fspath(workspace)
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    missing = workspace.parent / "missing-direct-score.pdf"

    retained_before = _snapshot_selected_files(
        workspace,
        include=lambda relative: relative.startswith("scans/source/"),
    )
    results_before = _snapshot_selected_files(
        workspace,
        include=lambda relative: relative.endswith("/results.csv"),
    )
    review_before = {
        item.failure_id: item
        for item in discover_scan_review_items(
            workspace,
            include_resolved=True,
        ).items
    }

    first = _run(
        [os.fspath(executable), "score", os.fspath(missing)],
        cwd=workspace.parent,
        env=environment,
    )
    second = _run(
        [os.fspath(executable), "score", os.fspath(missing)],
        cwd=workspace.parent,
        env=environment,
    )
    _require(
        first.returncode != 0 and second.returncode != 0,
        "missing-source direct score unexpectedly succeeded.",
    )
    _require(
        (first.stdout, first.stderr, first.returncode)
        == (second.stdout, second.stderr, second.returncode),
        "direct score missing-source behavior was not deterministic.",
    )
    combined = (first.stdout + first.stderr).casefold()
    _require(
        "select class" not in combined and "select assignment" not in combined,
        "direct score unexpectedly prompted for interactive context.",
    )

    _require(
        _snapshot_selected_files(
            workspace,
            include=lambda relative: relative.startswith("scans/source/"),
        )
        == retained_before,
        "missing-source direct score created or changed retained-source evidence.",
    )
    _require(
        _snapshot_selected_files(
            workspace,
            include=lambda relative: relative.endswith("/results.csv"),
        )
        == results_before,
        "missing-source direct score changed ScoreForm result history.",
    )

    review_after = {
        item.failure_id: item
        for item in discover_scan_review_items(
            workspace,
            include_resolved=True,
        ).items
    }
    new_ids = tuple(sorted(set(review_after) - set(review_before)))
    _require(
        len(new_ids) == 2,
        "two missing-source direct-score invocations must append exactly two "
        f"scan-intake review records; observed {len(new_ids)}.",
    )
    for failure_id in new_ids:
        item = review_after[failure_id]
        _require(
            item.stage == "intake"
            and item.failure_category == "source_missing"
            and item.source_filename == missing.name
            and item.source_scan_id is None,
            "missing-source direct score appended an unexpected review record.",
        )

    _verify_no_guided_shadow_persistence(workspace)


def verify(workspace: Path, *, version: str, expected_core_version: str) -> None:
    """Run clean-wheel SF-AC07 acceptance with synthetic data only."""
    _verify_installed_provenance(
        workspace,
        version=version,
        expected_core_version=expected_core_version,
    )
    os.environ["PDS_WORKSPACE_ROOT"] = os.fspath(workspace)
    resolved = get_scoreform_workspace_root()
    _require(resolved == workspace.resolve(), "ScoreForm resolved an unexpected workspace.")

    class_id = "english10_p2"
    assignment_id = "unit_1_quiz"
    source_pdf = _generate_registered_sheet(
        workspace,
        class_id=class_id,
        assignment_id=assignment_id,
    )
    _verify_guided_success(
        workspace,
        source_pdf=source_pdf,
        class_id=class_id,
        assignment_id=assignment_id,
    )
    _verify_exact_source_review_scope(workspace)
    _verify_no_guided_shadow_persistence(workspace)
    _verify_direct_score_is_prompt_free_and_deterministic(workspace)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--expected-core-version", required=True)
    args = parser.parse_args()
    workspace = args.workspace.expanduser().resolve()
    try:
        verify(
            workspace,
            version=args.version,
            expected_core_version=args.expected_core_version,
        )
    except AcceptanceFailure as error:
        print(f"Installed SF-AC07 acceptance failed: {error}", file=sys.stderr)
        return 1
    print("Installed SF-AC07 guided scan-to-results acceptance passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
