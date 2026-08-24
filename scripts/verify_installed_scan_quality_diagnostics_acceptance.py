"""Clean-wheel SF-AC08 acceptance for ScoreForm issue #190."""

from __future__ import annotations

import argparse
import importlib
import io
import os
import subprocess
import sys
from contextlib import redirect_stdout
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from unittest.mock import patch

import pds_core
from pds_core.scan_failure_metadata import (
    RoutingFailureMetadata,
    write_routing_failure_metadata,
)

from scoreform.cli_score import execute_routed_scoring_operation
from scoreform.menu_scan_review import launch_scan_review_menu
from scoreform.scan_review_details import scoreform_failure_details
from scoreform.scan_review_resolution import discover_scan_review_items


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
        self._values = iter(values)
        self.prompts: list[str] = []

    def __call__(self, prompt: str = "") -> str:
        self.prompts.append(prompt)
        try:
            return next(self._values)
        except StopIteration as exc:
            raise AcceptanceFailure(
                f"scan-review menu requested unexpected additional input: {prompt!r}"
            ) from exc


def _write_blank_png(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image_module = importlib.import_module("PIL.Image")
    image = image_module.new("RGB", (480, 360), (255, 255, 255))
    image.save(path, format="PNG")
    _require(path.is_file() and path.stat().st_size > 0, "blank PNG was not written.")


def _write_retained_fixture(
    workspace: Path,
    *,
    source_scan_id: str,
    filename: str,
) -> tuple[str, str]:
    retained_relative = f"scans/source/2026-08-24/{source_scan_id}/{filename}"
    retained = workspace / retained_relative
    retained.parent.mkdir(parents=True, exist_ok=True)
    retained.write_bytes(b"synthetic retained scan evidence\n")
    return retained_relative, "a" * 64


def _persist_review_fixture(
    workspace: Path,
    *,
    failure_id: str,
    source_scan_id: str,
    filename: str,
    core_category: str,
    scoreform_category: str,
    context: dict[str, object] | None = None,
    detected_payload: str | None = "PDS2|synthetic-technical-payload",
) -> None:
    retained_relative, source_sha256 = _write_retained_fixture(
        workspace,
        source_scan_id=source_scan_id,
        filename=filename,
    )
    assembly_categories = {
        "missing_pages",
        "duplicate_page",
        "duplicate_route",
        "conflicting_duplicate",
        "inconsistent_issuance",
        "unexpected_page",
        "invalid_page_order",
        "invalid_question_coverage",
        "invalid_result_identity",
    }
    metadata_record = RoutingFailureMetadata(
        schema_version="2",
        failure_id=failure_id,
        scope="page",
        stage="review",
        created_at=datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc).isoformat(),
        failure_category=core_category,
        failure_message="Synthetic low-level failure prose that is not teacher guidance.",
        source_filename=filename,
        source_scan_id=source_scan_id,
        source_sha256=source_sha256,
        retained_source_path=retained_relative,
        review_copy_path=None,
        source_page_number=1,
        detected_payload=detected_payload,
        route_locator=None,
        target=None,
        module_details=scoreform_failure_details(
            origin=(
                "attempt_assembly"
                if scoreform_category in assembly_categories
                else "core_dispatch"
            ),
            category=scoreform_category,
            diagnostic_paths=(
                "classes/synthetic/modules/scoreform/work/quiz/debug/diagnostic.png",
            ),
            context={} if context is None else context,
        ),
    )
    write_routing_failure_metadata(workspace, metadata_record)


def _run_review_menu(
    workspace: Path,
    *,
    source_scan_id: str,
    choices: list[str],
) -> tuple[int, str, tuple[str, ...]]:
    prompts = _PromptRecorder(choices)
    output = io.StringIO()
    os.environ["PDS_WORKSPACE_ROOT"] = os.fspath(workspace)
    with (
        patch("builtins.input", prompts),
        patch("scoreform.menu_scan_review.clear_screen", lambda: None),
        patch("scoreform.menu_scan_review.pause_for_user", lambda: None),
        redirect_stdout(output),
    ):
        status = launch_scan_review_menu(source_scan_id=source_scan_id)
    return status, output.getvalue(), tuple(prompts.prompts)


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
        "scoreform.menu_scan_review",
        "scoreform.scan_teacher_diagnostics",
        "scoreform.scan_review_persistence",
        "scoreform.module_errors",
        "scoreform.cli_scan_review",
        "pds_core",
        "pds_core.scan_failure_metadata",
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
    _require(
        not workspace.exists(),
        "installed import/provenance checks created workspace state.",
    )


def _verify_real_qrless_recovery(workspace: Path) -> None:
    fixture = workspace.parent / f"{workspace.name}-fixtures" / "qrless.png"
    _write_blank_png(fixture)
    result = execute_routed_scoring_operation(
        fixture,
        workspace_root=workspace,
    )
    _require(result.batch is not None, "QR-less operation produced no routed batch.")
    _require(result.review is not None, "QR-less operation produced no review batch.")

    matches = tuple(
        item
        for item in discover_scan_review_items(workspace).items
        if item.source_filename == fixture.name
    )
    _require(len(matches) == 1, "QR-less page did not produce exactly one review item.")
    item = matches[0]
    _require(item.source_scan_id is not None, "QR-less retained failure has no source_scan_id.")

    status, output, _prompts = _run_review_menu(
        workspace,
        source_scan_id=item.source_scan_id,
        choices=["1", "b", "b"],
    )
    _require(status == 0, "QR-less source-scoped review did not exit cleanly.")
    for expected in (
        "Review This Scan",
        "Problem",
        "No usable routing code was found",
        "Evidence",
        "safely retained",
        "Recommended next step",
        "Mark rescan needed (recommended)",
        "T. Technical details",
    ):
        _require(expected in output, f"QR-less teacher recovery lacks {expected!r}.")
    for forbidden in (
        "Raw payload:",
        "Failure ID:",
        "Route ID:",
        "Issuance ID:",
        "Source SHA-256:",
    ):
        _require(
            forbidden not in output,
            f"primary QR-less teacher view leaked technical field {forbidden!r}.",
        )


def _verify_registration_and_technical_separation(workspace: Path) -> str:
    source_scan_id = "scan_190_registration"
    _persist_review_fixture(
        workspace,
        failure_id="failure_190_registration",
        source_scan_id=source_scan_id,
        filename="registration_failure.png",
        core_category="processing_error",
        scoreform_category="registration_marks_missing",
    )

    status, primary, _prompts = _run_review_menu(
        workspace,
        source_scan_id=source_scan_id,
        choices=["1", "b", "b"],
    )
    _require(status == 0, "registration primary review did not exit cleanly.")
    for expected in (
        "The page could not be aligned reliably",
        "all four required registration marks",
        "safely retained",
        "Mark rescan needed (recommended)",
    ):
        _require(expected in primary, f"registration recovery lacks {expected!r}.")
    _require(
        "PDS2|synthetic-technical-payload" not in primary,
        "primary registration recovery leaked raw payload.",
    )
    _require(
        "failure_190_registration" not in primary,
        "primary registration recovery leaked failure ID.",
    )

    status, technical, _prompts = _run_review_menu(
        workspace,
        source_scan_id=source_scan_id,
        choices=["1", "t", "b", "b"],
    )
    _require(status == 0, "registration technical review did not exit cleanly.")
    for expected in (
        "Technical Scan Details",
        "Failure ID: failure_190_registration",
        "ScoreForm category: registration_marks_missing",
        "Raw payload: 'PDS2|synthetic-technical-payload'",
        "debug/diagnostic.png",
    ):
        _require(expected in technical, f"technical detail view lacks {expected!r}.")
    return source_scan_id


def _verify_missing_page_and_conflict_guidance(workspace: Path) -> None:
    missing_scan_id = "scan_190_missing_page"
    _persist_review_fixture(
        workspace,
        failure_id="failure_190_missing_page",
        source_scan_id=missing_scan_id,
        filename="three_page_packet.pdf",
        core_category="page_conflict",
        scoreform_category="missing_pages",
        context={
            "expected_logical_pages": [1, 2, 3],
            "missing_logical_pages": [2],
            "missing_page_ids": ["pg_synthetic_secret"],
        },
        detected_payload=None,
    )
    _persist_review_fixture(
        workspace,
        failure_id="failure_190_unrelated",
        source_scan_id="scan_190_unrelated",
        filename="unrelated_scan.pdf",
        core_category="page_conflict",
        scoreform_category="missing_pages",
        context={"expected_logical_pages": [1, 2], "missing_logical_pages": [1]},
        detected_payload=None,
    )

    status, missing_output, _prompts = _run_review_menu(
        workspace,
        source_scan_id=missing_scan_id,
        choices=["1", "b", "b"],
    )
    _require(status == 0, "missing-page review did not exit cleanly.")
    _require(
        "A required answer-sheet page is missing" in missing_output,
        "missing-page teacher headline was not rendered.",
    )
    _require(
        "page 2 of 3" in missing_output,
        "missing-page recovery omitted physical page membership.",
    )
    _require(
        "pg_synthetic_secret" not in missing_output,
        "missing-page primary recovery leaked page ID.",
    )
    _require(
        "unrelated_scan.pdf" not in missing_output,
        "source-scoped recovery leaked a different retained scan.",
    )

    conflict_scan_id = "scan_190_conflict"
    _persist_review_fixture(
        workspace,
        failure_id="failure_190_conflict",
        source_scan_id=conflict_scan_id,
        filename="conflicting_duplicate.pdf",
        core_category="page_conflict",
        scoreform_category="conflicting_duplicate",
        detected_payload=None,
    )
    status, conflict_output, _prompts = _run_review_menu(
        workspace,
        source_scan_id=conflict_scan_id,
        choices=["1", "b", "b"],
    )
    _require(status == 0, "conflicting-duplicate review did not exit cleanly.")
    _require(
        "Conflicting copies of the same answer-sheet page were found"
        in conflict_output,
        "conflicting duplicate did not receive teacher-facing diagnosis.",
    )
    _require(
        "Dismiss duplicate (recommended)" in conflict_output,
        "permitted duplicate recovery was not reflected in available guidance.",
    )


def _verify_nonmanual_cancellation(workspace: Path, source_scan_id: str) -> None:
    before = discover_scan_review_items(
        workspace,
        source_scan_id=source_scan_id,
        include_resolved=True,
    ).items
    _require(len(before) == 1, "registration cancellation fixture is not unique.")
    _require(
        len(before[0].resolution_history) == 0,
        "registration fixture unexpectedly has prior resolution history.",
    )

    status, output, _prompts = _run_review_menu(
        workspace,
        source_scan_id=source_scan_id,
        choices=["1", "3", "NO", "b"],
    )
    _require(status == 0, "cancelled non-manual review did not exit cleanly.")
    _require(
        "Scan Review Not Updated" in output,
        "non-manual cancellation did not use truthful generic heading.",
    )
    _require(
        "Manual Entry Cancelled" not in output,
        "non-manual cancellation was mislabeled as manual entry.",
    )
    _require(
        "No result or resolution record was written." in output,
        "non-manual cancellation did not state its write outcome.",
    )
    _require(
        "retained evidence" in output,
        "non-manual cancellation did not preserve earlier durable-state wording.",
    )

    after = discover_scan_review_items(
        workspace,
        source_scan_id=source_scan_id,
        include_resolved=True,
    ).items
    _require(len(after) == 1, "registration cancellation changed review occurrence count.")
    _require(
        len(after[0].resolution_history) == 0,
        "cancelled non-manual action appended a resolution record.",
    )


def _verify_direct_cli_preserved(workspace: Path, source_scan_id: str) -> None:
    executable = _scoreform_executable()
    environment = os.environ.copy()
    environment["PDS_WORKSPACE_ROOT"] = os.fspath(workspace)
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)

    command = [
        os.fspath(executable),
        "list-scan-review",
        "--source-scan-id",
        source_scan_id,
    ]
    first = _run(command, cwd=workspace.parent, env=environment)
    second = _run(command, cwd=workspace.parent, env=environment)
    _require(first.returncode == 0 and second.returncode == 0, "direct review listing failed.")
    _require(
        (first.stdout, first.stderr, first.returncode)
        == (second.stdout, second.stderr, second.returncode),
        "direct review listing is no longer deterministic.",
    )
    for expected in (
        "ScoreForm scan review items",
        "failure_190_registration",
        "Category: processing_error",
        "ScoreForm category: registration_marks_missing",
    ):
        _require(expected in first.stdout, f"direct review listing lacks {expected!r}.")

    help_result = _run(
        [os.fspath(executable), "resolve-scan-review", "--help"],
        cwd=workspace.parent,
        env=environment,
    )
    _require(help_result.returncode == 0, "direct resolve-scan-review help failed.")
    _require(
        "--action" in help_result.stdout,
        "direct resolve-scan-review contract disappeared from help.",
    )


def _verify_no_shadow_diagnostic_store(workspace: Path) -> None:
    forbidden_names = {
        "teacher_diagnostics.json",
        "scan_quality.json",
        "scan_quality.jsonl",
        "diagnostic_events.jsonl",
        "scan_diagnostic_events.jsonl",
    }
    offenders = tuple(
        path.relative_to(workspace).as_posix()
        for path in workspace.rglob("*")
        if path.is_file() and path.name.casefold() in forbidden_names
    )
    _require(
        not offenders,
        f"#190 created an unauthorized diagnostic shadow store: {offenders}",
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--expected-core-version", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    options = _parse_args(argv)
    workspace = options.workspace.resolve()
    try:
        _verify_installed_provenance(
            workspace,
            version=options.version,
            expected_core_version=options.expected_core_version,
        )
        workspace.mkdir(parents=True)
        _require(
            workspace.is_dir() and not any(workspace.iterdir()),
            "synthetic SF-AC08 workspace was not created empty.",
        )
        _verify_real_qrless_recovery(workspace)
        registration_scan_id = _verify_registration_and_technical_separation(workspace)
        _verify_missing_page_and_conflict_guidance(workspace)
        _verify_nonmanual_cancellation(workspace, registration_scan_id)
        _verify_direct_cli_preserved(workspace, registration_scan_id)
        _verify_no_shadow_diagnostic_store(workspace)
    except (AcceptanceFailure, OSError, ValueError) as error:
        print(f"FAILED: {error}")
        return 1

    print("Installed SF-AC08 actionable scan-quality recovery acceptance passed.")
    print("Physical printer/scanner confirmation remains deferred to issue #195.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
