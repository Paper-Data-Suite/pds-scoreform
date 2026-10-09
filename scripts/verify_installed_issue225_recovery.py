"""Issue #225 Slice 14: installed ScoreForm/Core synthetic recovery acceptance.

Only optical scoring is substituted; routing, decision persistence, result
history, and CLI command dispatch use installed packages. This is NOT a
physical-scanner or actual mark-recognition qualification.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import io
import json
import os
import subprocess
import sys
from contextlib import redirect_stdout
from importlib import metadata
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
import pds_core
from pds_core.pds2 import serialize_pds2_payload
from pds_core.scan_failure_metadata import (
    RoutingFailureMetadata,
    write_routing_failure_metadata,
)
from pds_core.scan_retention import retain_source_scan
from pds_core.workspace import ensure_workspace_root
from reportlab.pdfgen import canvas

from scoreform.answer_sheet_persistence import (
    transition_answer_sheet_issuance,
    write_answer_sheet_record_set,
)
from scoreform.answer_sheet_records import build_answer_sheet_record_set
from scoreform.answer_sheet_routes import (
    persist_answer_sheet_route_set,
    plan_answer_sheet_route_set,
)
from scoreform.cli import main as scoreform_main
from scoreform.folders import setup_assignment_folder
from scoreform.page_scoring import ScoredAnswer, ScoreFormPageDispatchResult
from scoreform.qr_scan_recovery_completion import inspect_scoreform_recovery_completion
from scoreform.results import load_routed_results_history
from scoreform.scan_review_details import scoreform_failure_details
from scoreform.work_paths import scoreform_work_paths


class InstalledRecoveryAcceptanceError(RuntimeError):
    """Installed recovery did not preserve a required boundary."""


def require(value: bool, message: str) -> None:
    if not value:
        raise InstalledRecoveryAcceptanceError(message)


def check_installed(repository: Path, scoreform_version: str, core_version: str) -> None:
    require(metadata.version("scoreform") == scoreform_version, "ScoreForm version differs.")
    require(metadata.version("pds-core") == core_version, "Core version differs.")
    require(getattr(pds_core, "__version__", None) == core_version, "Core module version differs.")
    for name in (
        "scoreform", "scoreform.cli", "scoreform.cli_scan_recovery",
        "scoreform.menu_scan_recovery", "scoreform.qr_scan_recovery_workflow",
        "scoreform.qr_scan_recovery_completion", "scoreform.qr_scan_recovery_persistence",
        "pds_core", "pds_core.module_dispatch", "pds_core.scan_retention",
    ):
        origin = Path(importlib.import_module(name).__file__).resolve()
        require(
            origin.is_relative_to(Path(sys.prefix).resolve())
            and not origin.is_relative_to(repository.resolve())
            and "site-packages" in {x.lower() for x in origin.parts},
            f"{name} was not imported from isolated site-packages.",
        )


def snapshot(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*") if path.is_file()
    }


def fixture(root: Path, *, pages: int) -> tuple[tuple[object, ...], object]:
    root.mkdir(parents=True)
    # Model the normal Core-managed workspace *before* read-only snapshots.
    # The installed CLI otherwise creates .pds/workspace.json on first use.
    ensure_workspace_root(root)
    count = pages * 15
    assignment = {
        "assignment_id": "quiz1", "title": "Synthetic Recovery Acceptance",
        "question_count": count, "choices": ["A", "B", "C", "D"],
        "layout_id": "standard_15q_abcd_v1",
        "answer_key": {str(n): "A" for n in range(1, count + 1)},
        "standards": {str(n): [] for n in range(1, count + 1)},
    }
    student = {
        "class_id": "class1", "student_id": "student1", "last_name": "Synthetic",
        "first_name": "Student", "period": "4",
    }
    setup = setup_assignment_folder(
        {"class_id": "class1", "students": [student]}, assignment,
        workspace_root=root,
    )
    require(setup is not None, "Cannot prepare managed assignment.")
    work = setup["paths"].work_ref
    records = build_answer_sheet_record_set(
        "class1", assignment, student,
        generation_id="gen_" + "1" * 32, artifact_id="art_" + "2" * 32,
        output_kind="individual_pdf", reason="initial",
        issuance_id="iss_" + "3" * 32,
        page_ids=tuple("pg_" + str(i + 4) * 32 for i in range(pages)),
        clock=lambda: "2026-07-15T12:00:00+00:00",
    )
    names = iter("rt_" + str(i + 7) * 32 for i in range(pages))
    routes = plan_answer_sheet_route_set(
        work, records, route_id_generator=lambda: next(names)
    )
    write_answer_sheet_record_set(root, work, records)
    persist_answer_sheet_route_set(root, work, records, routes)
    transition_answer_sheet_issuance(
        root, work, records.issuance.issuance_id,
        expected_revision=1, new_status="issued",
        timestamp="2026-07-15T12:01:00+00:00",
    )
    if pages == 1:
        original = root / "original.png"
        require(bool(cv2.imwrite(str(original), np.full((90, 90, 3), 255, np.uint8))),
                "Cannot create synthetic image.")
    else:
        original = root / "original.pdf"
        pdf = canvas.Canvas(str(original), pagesize=(360, 360))
        for number in range(1, pages + 1):
            pdf.drawString(20, 200, f"Synthetic source page {number}")
            pdf.showPage()
        pdf.save()
    retained = retain_source_scan(root, original)
    for number in range(1, pages + 1):
        write_routing_failure_metadata(
            root,
            RoutingFailureMetadata(
                schema_version="2", failure_id=f"failure{number}", scope="page",
                stage="payload_detection", created_at="2026-01-01T00:00:00+00:00",
                failure_category="payload_missing", failure_message="No QR was detected.",
                source_filename=retained.source_filename,
                source_scan_id=retained.source_scan_id,
                source_sha256=retained.source_sha256,
                retained_source_path=retained.retained_source_relative_path,
                review_copy_path=None, source_page_number=number,
                detected_payload=None, route_locator=None, target=None,
                module_details=scoreform_failure_details(
                    origin="page_decode", category="qr_detection"
                ),
            ),
        )
    return tuple(routes), retained


class SyntheticScorer:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[int] = []
        self.fail = fail

    def __call__(self, _image, **kwargs):
        number = kwargs["source_page_number"]
        self.calls.append(number)
        if self.fail:
            raise RuntimeError("synthetic interrupted optical scoring")
        page = kwargs["page_context"].page
        answers = tuple(
            ScoredAnswer(n, "A", True)
            for n in range(page.question_start, page.question_end + 1)
        )
        return ScoreFormPageDispatchResult(
            route_id=kwargs["route_id"], page_id=page.page_id,
            issuance_id=page.issuance_id, generation_id=page.generation_id,
            artifact_id=page.artifact_id, class_id=page.class_id,
            assignment_id=page.assignment_id, student_id=page.student_id,
            logical_page=page.logical_page, total_pages=page.total_pages,
            question_start=page.question_start, question_end=page.question_end,
            layout_id=page.layout_id, score=len(answers), total_points=len(answers),
            answers=answers, source_scan_id=kwargs["source_scan_id"],
            source_page_number=number,
            retained_source_relative_path=kwargs["retained_source_relative_path"],
            source_sha256=kwargs["source_sha256"], diagnostic_paths=(),
        )


def cli(root: Path, args: list[str], scorer: SyntheticScorer) -> tuple[int, str]:
    capture = io.StringIO()
    with (
        patch("scoreform.workspace.get_scoreform_workspace_root", return_value=root),
        patch("scoreform.route_handler.score_authoritative_answer_sheet_page", scorer),
        redirect_stdout(capture),
    ):
        status = scoreform_main(["recover-scan-review", *args])
    return status, capture.getvalue()


def saved_rows(root: Path):
    path = scoreform_work_paths(root, "class1", "quiz1").results_path
    return load_routed_results_history(path)


def resolution_count(root: Path) -> int:
    directory = root / "scans" / "review" / "resolutions"
    return len(tuple(directory.glob("*.json"))) if directory.exists() else 0


def require_cli(status: int, output: str, expected_status: int, marker: str) -> None:
    require(status == expected_status, f"Recovery CLI returned unexpected status {status}.")
    require(marker in output, f"Recovery CLI omitted expected status {marker}.")


def direct_console(root: Path, route, outside: Path) -> None:
    executable = Path(sys.prefix) / ("Scripts/scoreform.exe" if os.name == "nt" else "bin/scoreform")
    require(executable.is_file(), "Installed ScoreForm console entry point missing.")
    env = os.environ.copy()
    env["PDS_WORKSPACE_ROOT"] = str(root)
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    help_run = subprocess.run(
        [str(executable), "--help"], cwd=outside, env=env,
        check=False, text=True, capture_output=True,
    )
    require(help_run.returncode == 0 and "recover-scan-review" in help_run.stdout,
            "Installed console help does not expose recovery.")
    before = snapshot(root)
    preview = subprocess.run(
        [str(executable), "recover-scan-review", "--page",
         f"failure1={serialize_pds2_payload(route.locator)}"],
        cwd=outside, env=env, check=False, text=True, capture_output=True,
    )
    require(preview.returncode == 0 and "READ ONLY" in preview.stdout,
            "Installed console preview failed.")
    after = snapshot(root)
    require(
        after == before,
        "Installed CLI preview changed workspace files; "
        f"added={sorted(after.keys() - before.keys())}; "
        f"removed={sorted(before.keys() - after.keys())}; "
        f"modified={sorted(k for k in before.keys() & after.keys() if before[k] != after[k])}.",
    )


def exercise(workspace: Path, outside: Path) -> dict[str, str]:
    # The interpreter running this verifier imports only installed packages.
    first = workspace / "one-page"
    routes, retained = fixture(first, pages=1)
    direct_console(first, routes[0], outside)
    commands = ["--page", f"failure1={serialize_pds2_payload(routes[0].locator)}",
                "--apply", "--confirm", "RECOVER"]
    scorer = SyntheticScorer()
    status, shown = cli(first, commands, scorer)
    require_cli(status, shown, 0, "verified_complete")
    require(scorer.calls == [1], "First recovery did not score exactly the original page.")
    rows = saved_rows(first)
    require(len(rows) == 1, "First recovery did not persist exactly one result.")
    result = rows[0].result
    require(result.source_sha256 == retained.source_sha256, "Stored SHA-256 source mismatch.")
    require(result.source_scan_id == retained.source_scan_id, "Stored source scan mismatch.")
    require(result.source_page_numbers == (1,) and result.score == 15,
            "Persisted score/page provenance mismatch.")
    require(resolution_count(first) == 1, "Exactly one route decision required.")
    before_retry = snapshot(first)
    retry_scorer = SyntheticScorer()
    status, shown = cli(first, commands, retry_scorer)
    require_cli(status, shown, 0, "already_complete")
    require(not retry_scorer.calls, "Idempotent retry rescored a complete attempt.")
    require(snapshot(first) == before_retry, "Retry modified result or resolution files.")
    recorded_args = ["--page", "failure1=@recorded", "--apply", "--confirm", "RECOVER"]
    status, shown = cli(first, recorded_args, retry_scorer)
    require_cli(status, shown, 0, "already_complete")
    require(snapshot(first) == before_retry, "Historical route retry mutated stored records.")
    require(inspect_scoreform_recovery_completion(first, "failure1").verified,
            "Durable completion reader did not verify result.")

    interrupted = workspace / "interrupted"
    routes, _ = fixture(interrupted, pages=1)
    params = ["--page", f"failure1={serialize_pds2_payload(routes[0].locator)}",
              "--apply", "--confirm", "RECOVER"]
    status, _ = cli(interrupted, params, SyntheticScorer(fail=True))
    require(status == 1 and resolution_count(interrupted) == 1,
            "Interrupted dispatch failed to preserve exactly one route decision.")
    require(not list(interrupted.rglob("results.csv")),
            "Interrupted dispatch unexpectedly persisted an attempt.")
    status, shown = cli(interrupted, recorded_args, SyntheticScorer())
    require_cli(status, shown, 0, "verified_complete")
    require(resolution_count(interrupted) == 1 and len(saved_rows(interrupted)) == 1,
            "Restart duplicated a route decision or result.")

    multi = workspace / "multi-page"
    routes, retained_multi = fixture(multi, pages=2)
    first_only = ["--page", f"failure1={serialize_pds2_payload(routes[0].locator)}",
                  "--apply", "--confirm", "RECOVER"]
    status, shown = cli(multi, first_only, SyntheticScorer())
    require_cli(status, shown, 2, "needs_pages")
    require("Missing logical pages: 2" in shown, "Missing logical-page information omitted.")
    require(not list(multi.rglob("results.csv")), "Partial multi-page result persisted.")
    both = ["--page", "failure1=@recorded", "--page",
            f"failure2={serialize_pds2_payload(routes[1].locator)}",
            "--apply", "--confirm", "RECOVER"]
    status, shown = cli(multi, both, SyntheticScorer())
    require_cli(status, shown, 0, "verified_complete")
    require(resolution_count(multi) == 2, "Multi-page recovery decision count incorrect.")
    rows = saved_rows(multi)
    require(len(rows) == 1 and rows[0].result.total_points == 30,
            "Multi-page recovery did not create exactly one complete attempt.")
    require(rows[0].result.source_sha256 == retained_multi.source_sha256,
            "Multi-page result lost original retained provenance.")
    before = snapshot(multi)
    both_recorded = ["--page", "failure1=@recorded", "--page", "failure2=@recorded",
                     "--apply", "--confirm", "RECOVER"]
    status, shown = cli(multi, both_recorded, SyntheticScorer())
    require_cli(status, shown, 0, "already_complete")
    require(snapshot(multi) == before, "Multi-page retry wrote additional records.")

    tampered = workspace / "changed-source"
    routes, retained_tampered = fixture(tampered, pages=1)
    retained_tampered.retained_source_path.write_bytes(b"source changed")
    before = snapshot(tampered)
    status, _ = cli(tampered,
                    ["--page", f"failure1={serialize_pds2_payload(routes[0].locator)}"],
                    SyntheticScorer())
    require(status == 1 and snapshot(tampered) == before,
            "Changed retained-source bytes were accepted or mutated.")
    require(resolution_count(tampered) == 0, "Changed scan generated a route decision.")
    return {
        "isolated_console_preview": "passed",
        "one_page_persistence": "passed",
        "idempotent_retries": "passed",
        "interrupted_dispatch_resume": "passed",
        "multi_page_completeness": "passed",
        "retained_source_integrity": "passed",
        "physical_scan_acceptance": "not_claimed",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--scoreform-version", required=True)
    parser.add_argument("--core-version", required=True)
    options = parser.parse_args(argv)
    try:
        require(not options.workspace.exists(), "Acceptance workspace must begin absent.")
        check_installed(options.repository, options.scoreform_version, options.core_version)
        report = exercise(options.workspace, options.workspace.parent)
    except (InstalledRecoveryAcceptanceError, OSError, ValueError) as error:
        print(f"Installed recovery verification failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
