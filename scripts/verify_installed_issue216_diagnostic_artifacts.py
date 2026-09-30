"""Clean-wheel installed acceptance for ScoreForm issue #216."""

from __future__ import annotations

import argparse
import importlib
import os
import sys
from importlib import metadata
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
import pds_core
from pds_core.routes import route_registration_path

from scoreform.answer_sheet_persistence import (
    answer_sheet_issuance_path,
    answer_sheet_page_path,
    transition_answer_sheet_issuance,
    write_answer_sheet_record_set,
)
from scoreform.answer_sheet_records import build_answer_sheet_record_set
from scoreform.answer_sheet_routes import (
    build_answer_sheet_page_route,
    persist_answer_sheet_route_set,
)
from scoreform.cli_score import execute_routed_scoring_operation
from scoreform.config import CORNER_SIZE, CORNERS, IMG_HEIGHT, IMG_WIDTH
from scoreform.diagnostic_artifacts import (
    MAX_DIAGNOSTIC_FILENAME_LENGTH,
    DiagnosticArtifactWarning,
    DiagnosticArtifactWriteResult,
    build_diagnostic_artifact_name,
    write_png_diagnostic_artifact,
)
from scoreform.diagnostic_events import list_diagnostic_events
from scoreform.folders import setup_assignment_folder
from scoreform.guided_scan_results import build_guided_scan_summary
from scoreform.module_errors import ScoreFormPageScoringError
from scoreform.pds2_scan_dispatch import QrPayloadDetectionResult
from scoreform.results import load_routed_results_history
from scoreform.scan_filing_settings import set_scan_filing_mode
from scoreform.scan_review_resolution import discover_scan_review_items

CLASS_ID = "issue216_class_alpha"
ASSIGNMENT_ID = "issue216_quiz_alpha"
STUDENT_ID = "issue216_student_alpha"

GENERATION_ID = "gen_" + "1" * 32
ARTIFACT_ID = "art_" + "2" * 32
ISSUANCE_ID = "iss_" + "3" * 32
PAGE_ID = "pg_" + "4" * 32
ROUTE_ID = "rt_" + "5" * 32

CREATED_AT = "2026-09-29T12:00:00+00:00"
ISSUED_AT = "2026-09-29T12:01:00+00:00"


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


def _verify_installed_provenance(
    workspace: Path,
    repository: Path,
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
        "scoreform.scoring",
        "scoreform.diagnostic_artifacts",
        "scoreform.route_handler",
        "scoreform.pds2_scan_dispatch",
        "pds_core",
    ):
        origin = _module_origin(module_name)
        _require(
            _is_isolated_installed_origin(origin, repository),
            f"{module_name} did not import from isolated site-packages: {origin}",
        )


def _assignment() -> dict[str, object]:
    return {
        "assignment_id": ASSIGNMENT_ID,
        "title": "Synthetic Issue 216 Qualification",
        "question_count": 1,
        "choices": ["A", "B", "C", "D"],
        "layout_id": "standard_15q_abcd_v1",
        "answer_key": {"1": "A"},
        "standards": {"1": []},
    }


def _student() -> dict[str, str]:
    return {
        "class_id": CLASS_ID,
        "student_id": STUDENT_ID,
        "last_name": "Synthetic",
        "first_name": "Learner",
        "period": "1",
    }


def _registered_work(workspace: Path):
    setup = setup_assignment_folder(
        {"class_id": CLASS_ID, "students": [_student()]},
        _assignment(),
        workspace_root=workspace,
    )
    _require(setup is not None, "managed synthetic assignment setup failed.")
    paths = setup["paths"]
    work_ref = paths.work_ref

    records = build_answer_sheet_record_set(
        CLASS_ID,
        _assignment(),
        _student(),
        generation_id=GENERATION_ID,
        artifact_id=ARTIFACT_ID,
        output_kind="individual_pdf",
        reason="initial",
        issuance_id=ISSUANCE_ID,
        page_ids=(PAGE_ID,),
        clock=lambda: CREATED_AT,
    )
    write_answer_sheet_record_set(workspace, work_ref, records)
    route = build_answer_sheet_page_route(
        work_ref,
        records.pages[0],
        route_id=ROUTE_ID,
    )
    persist_answer_sheet_route_set(
        workspace,
        work_ref,
        records,
        (route,),
    )
    transition_answer_sheet_issuance(
        workspace,
        work_ref,
        ISSUANCE_ID,
        expected_revision=1,
        new_status="issued",
        timestamp=ISSUED_AT,
    )
    set_scan_filing_mode("off", workspace_root=workspace)
    return paths, records, route


def _source_image(*, corners: bool) -> np.ndarray:
    image = np.full((IMG_HEIGHT, IMG_WIDTH, 3), 255, np.uint8)
    if corners:
        for x, y in CORNERS:
            cv2.rectangle(
                image,
                (x, y),
                (x + CORNER_SIZE, y + CORNER_SIZE),
                (0, 0, 0),
                -1,
            )
    return image


def _write_source(path: Path, *, corners: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok = cv2.imwrite(os.fspath(path), _source_image(corners=corners))
    _require(ok and path.is_file(), f"could not create synthetic source: {path}")


def _forced_warning_writer(_image: np.ndarray, **kwargs):
    filename = build_diagnostic_artifact_name(
        kind=kwargs["kind"],
        source_sha256=kwargs["source_sha256"],
        source_page_number=kwargs["source_page_number"],
        page_id=kwargs["page_id"],
    )
    return DiagnosticArtifactWriteResult(
        kind=kwargs["kind"],
        intended_filename=filename,
        warning=DiagnosticArtifactWarning(
            kind=kwargs["kind"],
            stage="write",
            exception_type="PermissionError",
        ),
    )


def _detector(payload_text: str):
    def detect(_image, **_kwargs):
        return QrPayloadDetectionResult(
            raw_payload_text=payload_text,
            decode_method="issue216_synthetic",
        )

    return detect


def _page_scoring_error(error: Exception) -> ScoreFormPageScoringError | None:
    seen: set[int] = set()
    current: BaseException | None = error
    while isinstance(current, Exception) and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, ScoreFormPageScoringError):
            return current
        current = current.__cause__ or current.__context__
    return None


def _snapshot_authoritative_setup(workspace: Path, paths, route) -> dict[str, bytes]:
    targets = {
        "assignment": paths.assignment_path,
        "issuance": answer_sheet_issuance_path(
            workspace, paths.work_ref, ISSUANCE_ID
        ),
        "page": answer_sheet_page_path(workspace, paths.work_ref, PAGE_ID),
        "route": route_registration_path(workspace, route.locator),
    }
    return {label: path.read_bytes() for label, path in targets.items()}


def _verify_authoritative_setup_unchanged(
    workspace: Path,
    paths,
    route,
    before: dict[str, bytes],
) -> None:
    after = _snapshot_authoritative_setup(workspace, paths, route)
    _require(
        after == before,
        "issue #216 mutated existing assignment/issuance/page/route authority.",
    )


def _verify_deep_path_boundary(paths) -> None:
    paths.debug_dir.mkdir(parents=True, exist_ok=True)
    sentinel = paths.debug_dir / "legacy_preexisting_debug.png"
    sentinel.write_bytes(b"legacy-diagnostic-sentinel")
    sentinel_before = sentinel.read_bytes()

    legacy_filename = (
        "legacy_scan_"
        + ("x" * 120)
        + "_"
        + ("a" * 64)
        + "_"
        + PAGE_ID
        + "_corners.png"
    )
    legacy_path = paths.debug_dir / legacy_filename
    _require(
        len(os.fspath(legacy_path)) > 260,
        "synthetic legacy identity-heavy diagnostic path did not exceed 260 characters.",
    )

    result = write_png_diagnostic_artifact(
        np.zeros((16, 16, 3), dtype=np.uint8),
        diagnostic_root=paths.debug_dir,
        kind="registration_marks",
        source_sha256="a" * 64,
        source_page_number=1,
        page_id=PAGE_ID,
    )
    _require(result.warning is None, "bounded diagnostic write unexpectedly warned.")
    _require(result.path is not None, "bounded diagnostic write returned no path.")
    created = Path(result.path)
    _require(created.is_file(), "bounded diagnostic artifact was not created.")
    _require(
        len(created.name) <= MAX_DIAGNOSTIC_FILENAME_LENGTH,
        "bounded diagnostic filename exceeded documented maximum.",
    )
    _require(
        not any(
            identity in created.name
            for identity in (CLASS_ID, ASSIGNMENT_ID, STUDENT_ID, PAGE_ID)
        ),
        "bounded diagnostic filename leaked classroom/work identity.",
    )
    if os.name == "nt":
        _require(
            len(os.fspath(created)) < 260,
            "new bounded diagnostic path unexpectedly requires Windows long-path policy.",
        )
    _require(
        sentinel.read_bytes() == sentinel_before,
        "pre-existing legacy diagnostic evidence was modified.",
    )


def _verify_success_fail_soft(
    workspace: Path,
    paths,
    route,
    source: Path,
) -> None:
    with (
        patch(
            "scoreform.pds2_scan_dispatch.detect_qr_payload_text",
            _detector(route.payload_text),
        ),
        patch(
            "scoreform.scoring.write_png_diagnostic_artifact",
            _forced_warning_writer,
        ),
    ):
        operation = execute_routed_scoring_operation(
            source,
            workspace_root=workspace,
        )

    _require(operation.operation_error is None, "successful operation returned error.")
    _require(operation.exit_code == 0, "successful fail-soft scan exited nonzero.")
    _require(operation.batch is not None, "successful scan returned no batch.")
    _require(operation.review is not None, "successful scan returned no review batch.")
    _require(
        operation.review.persisted == () and operation.review.failures == (),
        "diagnostic-only degradation created scan-review work.",
    )
    dispatch = operation.batch.dispatch_result
    _require(
        dispatch.scoreform_page_score_count == 1,
        "successful page did not remain a ScoreForm page result.",
    )
    result = dispatch.scoreform_page_scores[0]
    _require(result.score == 0 and result.total_points == 1, "blank score changed.")
    _require(result.answers[0].selected_answer == "BLANK", "blank answer changed.")
    _require(result.diagnostic_paths == (), "failed diagnostics returned trusted paths.")
    _require(
        len(result.diagnostic_warnings) == 2,
        "expected registration and warped diagnostic warnings.",
    )
    _require(
        {warning.kind for warning in result.diagnostic_warnings}
        == {"registration_marks", "warped_page"},
        "successful page warnings used unexpected diagnostic kinds.",
    )

    export = operation.batch.export_result
    _require(export is not None, "successful attempt was not exported.")
    _require(len(export.appended_attempts) == 1, "first attempt was not appended.")
    _require(export.already_present_attempts == (), "first attempt was already present.")
    _require(export.failures == (), "successful attempt export failed.")

    summary = build_guided_scan_summary(operation, source)
    _require(summary.outcome == "complete", "diagnostic warning downgraded completion.")
    _require(
        summary.diagnostic_images_unavailable == 2,
        "guided summary did not aggregate diagnostic degradation.",
    )

    events = list_diagnostic_events(workspace, limit=200).events
    matching = [
        event
        for event in events
        if event.code == "diagnostic_artifact_write_failed"
        and event.component == "scoring"
        and event.stage == "diagnostic_persistence"
        and event.outcome == "partial_success"
    ]
    _require(matching, "diagnostic warning event was not recorded.")

    discovery = discover_scan_review_items(workspace, include_resolved=True)
    _require(
        discovery.items == (),
        "successful diagnostic degradation created a scan-review occurrence.",
    )


def _verify_idempotent_replay(
    workspace: Path,
    paths,
    route,
    source: Path,
) -> None:
    with (
        patch(
            "scoreform.pds2_scan_dispatch.detect_qr_payload_text",
            _detector(route.payload_text),
        ),
        patch(
            "scoreform.scoring.write_png_diagnostic_artifact",
            _forced_warning_writer,
        ),
    ):
        replay = execute_routed_scoring_operation(
            source,
            workspace_root=workspace,
        )

    _require(replay.operation_error is None, "idempotent replay returned operation error.")
    _require(replay.batch is not None and replay.review is not None, "replay was incomplete.")
    export = replay.batch.export_result
    _require(export is not None, "replay produced no export result.")
    _require(export.appended_attempts == (), "replay appended a duplicate result attempt.")
    _require(
        len(export.already_present_attempts) == 1,
        "replay did not recognize the existing result attempt.",
    )
    _require(export.failures == (), "idempotent replay export failed.")
    history = load_routed_results_history(paths.results_path)
    _require(len(history) == 1, "idempotent replay changed result-history cardinality.")


def _verify_primary_failure_preserved(
    workspace: Path,
    route,
    source: Path,
) -> None:
    with (
        patch(
            "scoreform.pds2_scan_dispatch.detect_qr_payload_text",
            _detector(route.payload_text),
        ),
        patch(
            "scoreform.scoring.write_png_diagnostic_artifact",
            _forced_warning_writer,
        ),
    ):
        operation = execute_routed_scoring_operation(
            source,
            workspace_root=workspace,
        )

    _require(operation.operation_error is None, "failure case lost structured batch.")
    _require(operation.exit_code == 1, "registration failure unexpectedly exited zero.")
    _require(operation.batch is not None and operation.review is not None, "failure batch missing.")
    _require(
        operation.batch.dispatch_result.scoreform_page_score_count == 0,
        "registration failure unexpectedly produced a page score.",
    )
    _require(
        len(operation.review.persisted) == 1 and operation.review.failures == (),
        "registration failure was not persisted exactly once for review.",
    )

    page = operation.batch.dispatch_result.pages[0]
    outcome = page.dispatch_outcome
    error = getattr(outcome, "error", None)
    _require(isinstance(error, Exception), "dispatch failure did not retain an exception.")
    scoring_error = _page_scoring_error(error)
    _require(scoring_error is not None, "primary ScoreForm scoring error was not retained.")
    assert scoring_error is not None
    _require(
        scoring_error.diagnostic_code == "registration_marks_missing",
        "diagnostic persistence replaced the primary registration failure.",
    )
    _require(
        len(scoring_error.diagnostic_warnings) == 1
        and scoring_error.diagnostic_warnings[0].kind == "registration_marks",
        "registration failure lost its subordinate diagnostic warning.",
    )

    retained = operation.batch.dispatch_result.retained_source
    _require(retained is not None, "registration failure lost retained-source provenance.")
    discovery = discover_scan_review_items(
        workspace,
        include_resolved=True,
        source_scan_id=retained.source_scan_id,
    )
    _require(len(discovery.items) == 1, "expected one review item for registration failure.")
    review_item = discovery.items[0]
    _require(
        review_item.scoreform_failure_category == "registration_marks_missing",
        "persisted review classification was replaced by diagnostic persistence.",
    )
    _require(
        review_item.scoreform_failure_category != "diagnostic_write_failed",
        "legacy diagnostic_write_failed category reappeared as review authority.",
    )


def run_acceptance(
    *,
    workspace: Path,
    repository: Path,
    version: str,
    expected_core_version: str,
) -> dict[str, object]:
    workspace = workspace.resolve()
    repository = repository.resolve(strict=True)
    _verify_installed_provenance(
        workspace,
        repository,
        version=version,
        expected_core_version=expected_core_version,
    )

    workspace.mkdir(parents=True)
    paths, _records, route = _registered_work(workspace)
    authoritative_before = _snapshot_authoritative_setup(workspace, paths, route)

    _verify_deep_path_boundary(paths)

    valid_source = workspace.parent / "issue216-valid-page.png"
    failure_source = workspace.parent / "issue216-missing-registration.png"
    _write_source(valid_source, corners=True)
    _write_source(failure_source, corners=False)

    _verify_success_fail_soft(workspace, paths, route, valid_source)
    _verify_authoritative_setup_unchanged(
        workspace, paths, route, authoritative_before
    )

    _verify_idempotent_replay(workspace, paths, route, valid_source)
    _verify_authoritative_setup_unchanged(
        workspace, paths, route, authoritative_before
    )

    _verify_primary_failure_preserved(workspace, route, failure_source)
    _verify_authoritative_setup_unchanged(
        workspace, paths, route, authoritative_before
    )

    return {
        "installed_provenance": "passed",
        "bounded_diagnostic_filename": "passed",
        "representative_legacy_path_gt_260": "passed",
        "windows_registry_policy_mutation": "not_used",
        "successful_scoring_with_forced_diagnostic_failure": "passed",
        "diagnostic_warning_event": "passed",
        "guided_warning_aggregation": "passed",
        "scan_review_noninterference": "passed",
        "registration_failure_primary_category": "registration_marks_missing",
        "result_idempotency": "passed",
        "existing_authoritative_workspace_records": "unchanged",
        "preexisting_legacy_diagnostic": "unchanged",
        "physical_acceptance": "not_claimed",
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--repository", required=True, type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--expected-core-version", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    options = _parse_args(argv)
    try:
        result = run_acceptance(
            workspace=options.workspace,
            repository=options.repository,
            version=options.version,
            expected_core_version=options.expected_core_version,
        )
    except (AcceptanceFailure, OSError, ValueError, TypeError) as error:
        print(f"Issue #216 installed acceptance failed: {error}", file=sys.stderr)
        return 1
    print("Issue #216 installed acceptance passed.")
    for key, value in sorted(result.items()):
        print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
