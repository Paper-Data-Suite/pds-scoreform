from __future__ import annotations

from pathlib import Path

from scoreform.attempt_assembly import (
    ScoreFormAttemptAssemblyBatch,
    ScoreFormRoutedScoringBatch,
)
from scoreform.cli_score import RoutedScoringOperationResult
from scoreform.guided_scan_results import (
    GuidedScanResultTarget,
    GuidedScanSummary,
    build_guided_scan_summary,
    derive_durable_result_targets,
    format_guided_scan_summary,
    safe_scan_source_filename,
)
from scoreform.page_scoring import ScoredAnswer
from scoreform.pds2_scan_dispatch import Pds2ScanDispatchResult
from scoreform.results import (
    ScoreFormAttemptExportBatch,
    ScoreFormExportedAttempt,
    ScoreFormRoutedResult,
)
from scoreform.scan_review_models import ScoreFormFailurePersistenceBatch


def _result(
    *,
    class_id: str,
    assignment_id: str,
    token: str,
) -> ScoreFormRoutedResult:
    return ScoreFormRoutedResult(
        result_origin="pds2_scan",
        class_id=class_id,
        assignment_id=assignment_id,
        student_id=f"student_{token}",
        last_name="Synthetic",
        first_name=f"Learner {token}",
        period="1",
        page_display="1",
        score=1,
        total_points=1,
        answers=(ScoredAnswer(1, "A", True),),
        issuance_id=f"iss_{token * 32}",
        generation_id=f"gen_{token * 32}",
        artifact_id=f"art_{token * 32}",
        page_ids=(f"pg_{token * 32}",),
        route_ids=(f"rt_{token * 32}",),
        logical_pages=(1,),
        source_file="synthetic_scan.pdf",
        source_scan_id=f"scan_{token}",
        source_page_numbers=(1,),
        retained_source_relative_path=(
            f"scans/source/2026-08-23/synthetic_{token}.pdf"
        ),
        source_sha256=token * 64,
    )


def test_durable_targets_use_only_appended_and_already_present_exports(
    tmp_path: Path,
) -> None:
    first = _result(class_id="english10", assignment_id="unit1", token="a")
    second = _result(class_id="english10", assignment_id="unit1", token="b")
    third = _result(class_id="apcsp", assignment_id="binary_quiz", token="c")
    export = ScoreFormAttemptExportBatch(
        appended_attempts=(
            ScoreFormExportedAttempt(first, tmp_path / "one.csv", 1),
            ScoreFormExportedAttempt(third, tmp_path / "two.csv", 1),
        ),
        already_present_attempts=(
            ScoreFormExportedAttempt(second, tmp_path / "one.csv", 2),
        ),
        output_paths=(tmp_path / "one.csv", tmp_path / "two.csv"),
    )

    targets = derive_durable_result_targets(export)

    assert targets == (
        GuidedScanResultTarget("apcsp", "binary_quiz", 1, 0),
        GuidedScanResultTarget("english10", "unit1", 1, 1),
    )
    assert derive_durable_result_targets(None) == ()


def test_teacher_summary_exposes_counts_and_assignment_targets_not_student_payload() -> None:
    summary = GuidedScanSummary(
        source_filename="returned_papers.pdf",
        retention_succeeded=True,
        source_scan_id="scan_synthetic",
        source_pages_processed=3,
        completed_attempts=2,
        attempts_appended=1,
        attempts_already_present=1,
        export_failures=0,
        review_items_persisted=1,
        review_persistence_failures=0,
        foreign_success_pages=1,
        targets=(
            GuidedScanResultTarget("english10", "unit1", 1, 1),
        ),
        scoring_status="partial_success",
        outcome="partial",
    )

    rendered = format_guided_scan_summary(summary)

    assert "returned_papers.pdf" in rendered
    assert "Outcome: Partial" in rendered
    assert "Attempts recorded: 1" in rendered
    assert "Attempts already recorded: 1" in rendered
    assert "Review items queued: 1" in rendered
    assert "Other installed modules handled: 1 page(s)" in rendered
    assert "english10 / unit1" in rendered
    for forbidden in (
        "student_synthetic",
        "Learner",
        "issuance",
        "route",
        "page_id",
        "source_scan_id",
        "retained_source",
        "source_sha256",
    ):
        assert forbidden not in rendered


def test_source_filename_is_host_independent_and_never_leaks_parent_paths() -> None:
    assert safe_scan_source_filename(r"C:\\teacher\\private\\returned.pdf") == (
        "returned.pdf"
    )
    assert safe_scan_source_filename("/home/teacher/private/returned.pdf") == (
        "returned.pdf"
    )


def test_operation_error_projects_to_bounded_failed_safe_summary() -> None:
    operation = RoutedScoringOperationResult(
        batch=None,
        review=None,
        operation_error="invalid synthetic dispatch result",
    )

    summary = build_guided_scan_summary(
        operation,
        Path(r"C:\outside\teacher\secret\returned.pdf"),
    )

    assert summary.source_filename == "returned.pdf"
    assert not summary.retention_succeeded
    assert summary.source_scan_id is None
    assert summary.targets == ()
    assert summary.outcome == "failed_safely"
    rendered = format_guided_scan_summary(summary)
    assert r"C:\outside" not in rendered
    assert "returned.pdf" in rendered


def test_assembled_but_unexported_attempt_cannot_become_guided_target() -> None:
    dispatch = Pds2ScanDispatchResult(
        retained_source=None,
        file_error=FileNotFoundError("synthetic missing scan"),
    )
    assembly = ScoreFormAttemptAssemblyBatch(dispatch)
    batch = ScoreFormRoutedScoringBatch(dispatch, assembly, export_result=None)
    operation = RoutedScoringOperationResult(
        batch=batch,
        review=ScoreFormFailurePersistenceBatch(),
    )

    summary = build_guided_scan_summary(operation, "synthetic_scan.pdf")

    assert summary.attempts_appended == 0
    assert summary.attempts_already_present == 0
    assert summary.targets == ()
    assert summary.outcome == "failed_safely"
