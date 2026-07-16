from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
import pytest
from pds_core.module_dispatch import RouteDispatchRequest, RouteDispatchSuccess
from pds_core.module_profiles import ModuleProfile
from pds_core.routing_models import (
    ModuleRecordRef,
    ModuleWorkRef,
    RouteLocator,
    RouteRegistration,
    RouteResolution,
)
from pds_core.scan_retention import retain_source_scan

from scoreform import attempt_assembly
from scoreform.answer_sheet_persistence import write_answer_sheet_record_set
from scoreform.answer_sheet_records import build_answer_sheet_record_set
from scoreform.attempt_assembly import (
    ScoreFormAssembledAttempt,
    ScoreFormAttemptAssemblyBatch,
    ScoreFormPageObservation,
    ScoreFormRoutedScoringBatch,
    assemble_scoreform_attempts,
)
from scoreform.cli_score import _eligible_for_scan_filing
from scoreform.folders import setup_assignment_folder
from scoreform.module_errors import (
    ScoreFormAttemptAssemblyError,
    ScoreFormAttemptConflictError,
    ScoreFormDuplicatePageError,
    ScoreFormIncompleteAttemptError,
    ScoreFormRoutedResultWriteError,
)
from scoreform.page_scoring import ScoredAnswer, ScoreFormPageDispatchResult
from scoreform.pds2_scan_dispatch import Pds2ScanDispatchResult, Pds2ScanPageOutcome
from scoreform.results import (
    ScoreFormAttemptExportBatch,
    ScoreFormAttemptExportFailure,
    ScoreFormExportedAttempt,
    export_scoreform_attempts,
)
from scoreform.scan_review_persistence import persist_routed_scoring_failures
from scoreform.scan_review_resolution import (
    discover_scan_review_items,
    resolve_scan_review_item,
)
from scoreform.work_paths import scoreform_work_paths


def _batch(
    tmp_path: Path, *, missing_first: bool = False, question_count: int = 16,
    observed_logical_pages: tuple[int, ...] | None = None,
):
    assignment = {
        "assignment_id": "quiz", "title": "Quiz", "question_count": question_count,
        "choices": ["A", "B", "C", "D"],
        "layout_id": "standard_15q_abcd_v1",
        "answer_key": {str(number): "A" for number in range(1, question_count + 1)},
        "standards": {str(number): [] for number in range(1, question_count + 1)},
    }
    student = {
        "class_id": "class1", "student_id": "1001", "last_name": "Issued",
        "first_name": "Student", "period": "2",
    }
    roster = {"class_id": "class1", "students": [student]}
    assert setup_assignment_folder(roster, assignment, workspace_root=tmp_path)
    records = build_answer_sheet_record_set(
        "class1", assignment, student,
        generation_id="gen_" + "1" * 32, artifact_id="art_" + "2" * 32,
        output_kind="individual_pdf", reason="initial",
        issuance_id="iss_" + "3" * 32,
        page_ids=tuple(
            "pg_" + format(4 + index, "x") * 32
            for index in range((question_count + 14) // 15)
        ),
        clock=lambda: "2026-07-15T12:00:00+00:00",
    )
    paths = scoreform_work_paths(tmp_path, "class1", "quiz")
    write_answer_sheet_record_set(tmp_path, paths.work_ref, records)
    source = tmp_path / "scan.png"
    assert cv2.imwrite(str(source), np.full((20, 20, 3), 255, np.uint8))
    retained = retain_source_scan(tmp_path, source)
    profile = ModuleProfile(
        "scoreform", "ScoreForm", frozenset({"1"}), frozenset({"PDS2"}),
        frozenset({"1"}), frozenset({"active"}), lambda *_args: None,
    )
    outcomes = []
    # Deliberately reverse source order relative to authoritative logical order.
    selected = tuple(
        (page, source_number, format(6 + source_number, "x"))
        for source_number, page in enumerate(reversed(records.pages), 1)
    )
    if missing_first:
        selected = tuple(item for item in selected if item[0].logical_page != 1)
    if observed_logical_pages is not None:
        selected = tuple(
            item for item in selected if item[0].logical_page in observed_logical_pages
        )
    for page, source_number, route_digit in selected:
        route_id = "rt_" + route_digit * 32
        locator = RouteLocator("PDS2", paths.work_ref, route_id)
        request = RouteDispatchRequest(locator, retained, source_number)
        registration = RouteRegistration(
            "1", locator, ModuleRecordRef("scoreform", "answer_sheet_page", page.page_id, "1"),
            "2026-07-15T12:00:00+00:00", "active", "test", {},
        )
        resolution = RouteResolution(locator, registration, tmp_path / "classes" / "class1", paths.work_root.parent.parent, paths.work_root)
        answers = tuple(
            ScoredAnswer(number, "A", True)
            for number in range(page.question_start, page.question_end + 1)
        )
        result = ScoreFormPageDispatchResult(
            route_id, page.page_id, page.issuance_id, page.generation_id,
            page.artifact_id, page.class_id, page.assignment_id, page.student_id,
            page.logical_page, page.total_pages, page.question_start, page.question_end,
            page.layout_id, len(answers), len(answers), answers,
            retained.source_scan_id, source_number,
            retained.retained_source_relative_path, retained.source_sha256,
            (f"debug/source_{source_number}.png",),
        )
        success = RouteDispatchSuccess(request, profile, resolution, result)
        outcomes.append(Pds2ScanPageOutcome(
            source_number, raw_payload_text="PDS2|test", locator=locator,
            dispatch_request=request, dispatch_outcome=success,
        ))
    return Pds2ScanDispatchResult(retained, tuple(outcomes), ("scoreform",))


def test_complete_issuance_uses_authoritative_order_and_snapshot(tmp_path: Path):
    assembled = assemble_scoreform_attempts(_batch(tmp_path), workspace_root=tmp_path)
    assert not assembled.failures
    result = assembled.completed_attempts[0].routed_result
    assert result.logical_pages == (1, 2)
    assert result.source_page_numbers == (2, 1)
    assert result.last_name == "Issued"
    assert result.score == result.total_points == 16


@pytest.mark.parametrize(
    ("question_count", "expected_logical", "expected_source"),
    (
        (1, (1,), (1,)),
        (31, (1, 2, 3), (3, 2, 1)),
    ),
)
def test_one_and_three_page_issuances_aggregate_exactly(
    tmp_path: Path, question_count, expected_logical, expected_source
):
    assembled = assemble_scoreform_attempts(
        _batch(tmp_path, question_count=question_count), workspace_root=tmp_path
    )
    assert not assembled.failures
    result = assembled.completed_attempts[0].routed_result
    assert result.logical_pages == expected_logical
    assert result.source_page_numbers == expected_source
    assert result.score == result.total_points == question_count
    assert tuple(answer.question_number for answer in result.answers) == tuple(
        range(1, question_count + 1)
    )


def test_missing_page_is_an_immutable_nonexportable_failure(tmp_path: Path):
    assembled = assemble_scoreform_attempts(
        _batch(tmp_path, missing_first=True), workspace_root=tmp_path
    )
    assert not assembled.completed_attempts
    assert assembled.failures[0].category == "missing_pages"
    assert assembled.failures[0].missing_logical_pages == (1,)
    assert isinstance(assembled.failures[0].error, ScoreFormIncompleteAttemptError)
    assert assembled.failures[0].observed_route_ids
    assert assembled.failures[0].generation_id.startswith("gen_")
    assert assembled.failures[0].source_scan_id.startswith("scan_")


@pytest.mark.parametrize(
    ("observed", "missing"),
    (
        ((2, 3), (1,)),
        ((1, 3), (2,)),
        ((1, 2), (3,)),
        ((2,), (1, 3)),
    ),
)
def test_first_middle_last_and_multiple_missing_pages_are_preserved(
    tmp_path: Path, observed, missing
):
    assembled = assemble_scoreform_attempts(
        _batch(
            tmp_path, question_count=31, observed_logical_pages=observed
        ),
        workspace_root=tmp_path,
    )
    assert not assembled.completed_attempts
    assert assembled.failures[0].missing_logical_pages == missing


def test_incomplete_pages_are_never_reconciled_between_batches(tmp_path: Path):
    dispatch = _batch(tmp_path)
    first = replace(dispatch, pages=(dispatch.pages[1],))
    second = replace(dispatch, pages=(dispatch.pages[0],))
    first_result = assemble_scoreform_attempts(first, workspace_root=tmp_path)
    second_result = assemble_scoreform_attempts(second, workspace_root=tmp_path)
    assert not first_result.completed_attempts and not second_result.completed_attempts
    assert first_result.failures[0].missing_logical_pages == (2,)
    assert second_result.failures[0].missing_logical_pages == (1,)


def test_loader_failure_preserves_typed_error_and_chained_cause(
    tmp_path: Path, monkeypatch
):
    dispatch = _batch(tmp_path)
    cause = RuntimeError("issuance store unavailable")
    monkeypatch.setattr(
        attempt_assembly, "load_answer_sheet_record_set",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(cause),
    )
    assembled = assemble_scoreform_attempts(dispatch, workspace_root=tmp_path)
    failure = assembled.failures[0]
    assert failure.category == "inconsistent_issuance"
    assert type(failure.error) is ScoreFormAttemptAssemblyError
    assert failure.error.__cause__ is cause


def test_contradictory_dispatch_target_becomes_identity_failure(tmp_path: Path):
    dispatch = _batch(tmp_path)
    wrapper = dispatch.pages[0]
    success = wrapper.dispatch_outcome
    assert isinstance(success, RouteDispatchSuccess)
    wrong_target = replace(success.resolution.registration.target, record_kind="wrong_kind")
    registration = replace(success.resolution.registration, target=wrong_target)
    resolution = replace(success.resolution, registration=registration)
    forged_success = replace(success, resolution=resolution)
    forged_page = replace(wrapper, dispatch_outcome=forged_success)
    forged = replace(dispatch, pages=(forged_page, *dispatch.pages[1:]))
    assembled = assemble_scoreform_attempts(forged, workspace_root=tmp_path)
    assert assembled.invalid_observations[0].source_page_number == wrapper.source_page_number
    assert type(assembled.invalid_observations[0].error) is ScoreFormAttemptAssemblyError
    assert assembled.failures[0].category == "missing_pages"


@pytest.mark.parametrize(
    "forgery",
    (
        "wrong_locator_class", "wrong_locator_assignment", "wrong_locator_module",
        "wrong_target_module", "wrong_target_contract",
        "correct_route_wrong_work", "correct_target_wrong_locator_work",
    ),
)
def test_forged_locator_and_target_contracts_are_identity_failures(
    tmp_path: Path, forgery: str
):
    dispatch = _batch(tmp_path)
    wrapper = dispatch.pages[0]
    success = wrapper.dispatch_outcome
    assert isinstance(success, RouteDispatchSuccess)
    locator = success.request.locator
    target = success.resolution.registration.target
    if forgery in {"wrong_locator_class", "correct_route_wrong_work"}:
        locator = replace(locator, work=replace(locator.work, class_id="another_class"))
    elif forgery in {"wrong_locator_assignment", "correct_target_wrong_locator_work"}:
        locator = replace(locator, work=replace(locator.work, work_id="another_assignment"))
    elif forgery in {"wrong_locator_module", "wrong_target_module"}:
        locator = replace(
            locator,
            work=ModuleWorkRef("another_module", locator.work.class_id, locator.work.work_id),
        )
        target = replace(target, module_id="another_module")
    elif forgery == "wrong_target_contract":
        target = replace(target, contract_version="2")

    request = replace(success.request, locator=locator)
    registration = replace(
        success.resolution.registration, locator=locator, target=target
    )
    resolution = replace(success.resolution, locator=locator, registration=registration)
    forged_success = replace(
        success, request=request, resolution=resolution
    )
    forged_wrapper = replace(
        wrapper, locator=locator, dispatch_request=request,
        dispatch_outcome=forged_success,
    )
    forged = replace(dispatch, pages=(forged_wrapper, *dispatch.pages[1:]))
    assembled = assemble_scoreform_attempts(forged, workspace_root=tmp_path)
    invalid = assembled.invalid_observations[0]
    assert type(invalid.error) is ScoreFormAttemptAssemblyError
    assert invalid.source_page_number == wrapper.source_page_number
    assert invalid.source_scan_id and invalid.retained_source_relative_path
    assert assembled.failures[0].category == "missing_pages"


def test_assembly_model_constructors_reject_contradictory_state(tmp_path: Path):
    completed = assemble_scoreform_attempts(_batch(tmp_path), workspace_root=tmp_path)
    attempt = completed.completed_attempts[0]
    with pytest.raises(TypeError):
        ScoreFormPageObservation({})  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        ScoreFormAssembledAttempt(attempt.routed_result, tuple(reversed(attempt.observations)))
    with pytest.raises(ValueError):
        ScoreFormAttemptAssemblyBatch(
            completed.dispatch_result, (attempt, attempt), ()
        )
    missing = assemble_scoreform_attempts(
        _batch(tmp_path / "failure", missing_first=True),
        workspace_root=tmp_path / "failure",
    ).failures[0]
    with pytest.raises(ValueError):
        replace(missing, category="unsupported")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        replace(missing, error=ScoreFormAttemptAssemblyError("wrong type"))
    with pytest.raises(TypeError):
        replace(missing, error=None)  # type: ignore[arg-type]
    other_result = replace(attempt.routed_result, source_scan_id="another_scan")
    exported = ScoreFormAttemptExportBatch(
        appended_attempts=(ScoreFormExportedAttempt(other_result, tmp_path / "x.csv", 1),),
        output_paths=(tmp_path / "x.csv",),
    )
    with pytest.raises(ValueError):
        ScoreFormRoutedScoringBatch(
            completed.dispatch_result, completed, exported
        )


def test_assembly_batch_requires_exact_dispatch_objects_and_failure_provenance(
    tmp_path: Path,
):
    completed = assemble_scoreform_attempts(_batch(tmp_path), workspace_root=tmp_path)
    attempt = completed.completed_attempts[0]
    cloned_observations = tuple(
        ScoreFormPageObservation(replace(observation.page_result))
        for observation in attempt.observations
    )
    cloned_attempt = ScoreFormAssembledAttempt(
        attempt.routed_result, cloned_observations
    )
    with pytest.raises(ValueError, match="exact clean dispatch"):
        ScoreFormAttemptAssemblyBatch(
            completed.dispatch_result, (cloned_attempt,), ()
        )

    failed_batch = assemble_scoreform_attempts(
        _batch(tmp_path / "failed", missing_first=True),
        workspace_root=tmp_path / "failed",
    )
    failure = failed_batch.failures[0]
    invented = replace(failure, observed_route_ids=("rt_" + "f" * 32,))
    with pytest.raises(ValueError, match="exact clean dispatch"):
        ScoreFormAttemptAssemblyBatch(failed_batch.dispatch_result, (), (invented,))


def test_failure_constructor_rejects_relational_contradictions(tmp_path: Path):
    missing_batch = assemble_scoreform_attempts(
        _batch(tmp_path / "missing", missing_first=True),
        workspace_root=tmp_path / "missing",
    )
    missing = missing_batch.failures[0]
    with pytest.raises(ValueError, match="aligned"):
        replace(missing, observed_route_ids=())
    with pytest.raises(ValueError, match="authoritative expected"):
        replace(missing, missing_page_ids=("pg_" + "f" * 32,))
    with pytest.raises(ValueError, match="scans/source"):
        replace(missing, retained_source_relative_path="other/scan.png")
    with pytest.raises(ValueError, match="canonical"):
        replace(
            missing,
            retained_source_relative_path="scans/source/20260715/scan.png",
        )

    duplicate_batch = assemble_scoreform_attempts(
        _duplicate_source_page(_batch(tmp_path / "duplicate"), 1),
        workspace_root=tmp_path / "duplicate",
    )
    duplicate = duplicate_batch.failures[0]
    with pytest.raises(ValueError, match="derived from observations"):
        replace(duplicate, duplicate_page_ids=("pg_" + "f" * 32,))


def _duplicate_source_page(dispatch, wrapper_index, *, conflicting=False):
    wrapper = dispatch.pages[wrapper_index]
    success = wrapper.dispatch_outcome
    assert isinstance(success, RouteDispatchSuccess)
    new_number = max(page.source_page_number for page in dispatch.pages) + 1
    request = replace(success.request, source_page_number=new_number)
    result = replace(success.module_result, source_page_number=new_number)
    if conflicting:
        first_answer = result.answers[0]
        answers = (replace(first_answer, selected_answer="B", correct=False), *result.answers[1:])
        result = replace(result, answers=answers, score=result.score - 1)
    duplicate_success = replace(success, request=request, module_result=result)
    duplicate = replace(
        wrapper, source_page_number=new_number, dispatch_request=request,
        dispatch_outcome=duplicate_success,
    )
    return replace(dispatch, pages=(*dispatch.pages, duplicate))


def _forged_extra_page(
    dispatch, wrapper_index=0, *, changes=None, wrong_target=False,
    source_page_number=None,
):
    wrapper = dispatch.pages[wrapper_index]
    success = wrapper.dispatch_outcome
    assert isinstance(success, RouteDispatchSuccess)
    new_number = source_page_number or (
        max(page.source_page_number for page in dispatch.pages) + 1
    )
    request = replace(success.request, source_page_number=new_number)
    result = replace(
        success.module_result, source_page_number=new_number, **(changes or {})
    )
    resolution = success.resolution
    if wrong_target:
        target = replace(resolution.registration.target, contract_version="2")
        registration = replace(resolution.registration, target=target)
        resolution = replace(resolution, registration=registration)
    forged_success = replace(
        success, request=request, resolution=resolution, module_result=result
    )
    return replace(
        wrapper, source_page_number=new_number, dispatch_request=request,
        dispatch_outcome=forged_success,
    )


@pytest.mark.parametrize(
    ("field", "forged_value"),
    (
        ("issuance_id", "invalid"),
        ("page_id", "invalid"),
        ("generation_id", "invalid"),
        ("artifact_id", "invalid"),
        ("class_id", "bad class"),
        ("assignment_id", "bad assignment"),
        ("student_id", "bad student"),
        ("source_scan_id", "bad scan"),
        ("retained_source_relative_path", "../unsafe.png"),
        ("source_sha256", "not-a-sha"),
        ("route_id", "invalid"),
    ),
)
def test_malformed_page_results_never_escape_and_retain_raw_provenance(
    tmp_path: Path, field: str, forged_value
):
    dispatch = _batch(tmp_path)
    wrapper = dispatch.pages[0]
    success = wrapper.dispatch_outcome
    assert isinstance(success, RouteDispatchSuccess)
    malformed = replace(success.module_result, **{field: forged_value})
    assert isinstance(malformed, ScoreFormPageDispatchResult)
    forged_success = replace(success, module_result=malformed)
    forged_wrapper = replace(wrapper, dispatch_outcome=forged_success)
    forged = replace(dispatch, pages=(forged_wrapper, *dispatch.pages[1:]))

    assembled = assemble_scoreform_attempts(forged, workspace_root=tmp_path)
    assert len(assembled.invalid_observations) == 1
    invalid = assembled.invalid_observations[0]
    assert invalid.page_result is malformed
    assert invalid.source_page_number == wrapper.source_page_number
    assert getattr(invalid, f"raw_{field}") is getattr(malformed, field)
    assert invalid.source_scan_id == dispatch.retained_source.source_scan_id
    assert invalid.retained_source_relative_path == (
        dispatch.retained_source.retained_source_relative_path
    )
    assert type(invalid.error) is ScoreFormAttemptAssemblyError
    assert not assembled.completed_attempts
    assert assembled.failures[0].category == "missing_pages"


def test_malformed_duplicate_with_same_raw_issuance_is_isolated(
    tmp_path: Path,
):
    dispatch = _batch(tmp_path)
    malformed = _forged_extra_page(
        dispatch, changes={"page_id": "invalid"}
    )
    assembled = assemble_scoreform_attempts(
        replace(dispatch, pages=(*dispatch.pages, malformed)),
        workspace_root=tmp_path,
    )
    assert len(assembled.invalid_observations) == 1
    assert len(assembled.completed_attempts) == 1
    assert not assembled.failures
    exported = export_scoreform_attempts(assembled, workspace_root=tmp_path)
    assert len(exported.appended_attempts) == 1
    assert dispatch.retained_source.retained_source_path.is_file()


def test_malformed_page_before_unrelated_complete_issuance_does_not_suppress_it(
    tmp_path: Path,
):
    dispatch = _batch(tmp_path)
    malformed = _forged_extra_page(
        dispatch, changes={"issuance_id": "invalid"}, source_page_number=1
    )
    valid_pages = (
        _forged_extra_page(dispatch, 0, source_page_number=2),
        _forged_extra_page(dispatch, 1, source_page_number=3),
    )
    assembled = assemble_scoreform_attempts(
        replace(dispatch, pages=(malformed, *valid_pages)),
        workspace_root=tmp_path,
    )
    assert len(assembled.invalid_observations) == 1
    assert len(assembled.completed_attempts) == 1
    assert not assembled.failures


def test_forged_target_duplicate_isolated_from_valid_complete_observations(
    tmp_path: Path,
):
    dispatch = _batch(tmp_path)
    forged = _forged_extra_page(dispatch, wrong_target=True)
    assembled = assemble_scoreform_attempts(
        replace(dispatch, pages=(*dispatch.pages, forged)),
        workspace_root=tmp_path,
    )
    assert len(assembled.invalid_observations) == 1
    assert len(assembled.completed_attempts) == 1
    assert not assembled.failures


def test_two_malformed_observations_with_same_raw_issuance_remain_separate(
    tmp_path: Path,
):
    dispatch = _batch(tmp_path)
    first = _forged_extra_page(
        dispatch, 0, changes={"issuance_id": "invalid"}, source_page_number=3
    )
    second = _forged_extra_page(
        dispatch, 1, changes={"issuance_id": "invalid"}, source_page_number=4
    )
    assembled = assemble_scoreform_attempts(
        replace(dispatch, pages=(*dispatch.pages, first, second)),
        workspace_root=tmp_path,
    )
    assert tuple(
        item.source_page_number for item in assembled.invalid_observations
    ) == (3, 4)
    assert all(
        item.raw_issuance_id == "invalid"
        for item in assembled.invalid_observations
    )
    assert len(assembled.completed_attempts) == 1
    assert not assembled.failures


def test_identical_and_conflicting_duplicate_pages_have_no_winner(tmp_path: Path):
    dispatch = _batch(tmp_path)
    identical = assemble_scoreform_attempts(
        _duplicate_source_page(dispatch, 1), workspace_root=tmp_path
    )
    assert not identical.completed_attempts
    assert identical.failures[0].category == "duplicate_page"
    assert isinstance(identical.failures[0].error, ScoreFormDuplicatePageError)

    conflicting = assemble_scoreform_attempts(
        _duplicate_source_page(dispatch, 1, conflicting=True), workspace_root=tmp_path
    )
    assert not conflicting.completed_attempts
    failure = conflicting.failures[0]
    assert failure.category == "conflicting_duplicate"
    assert isinstance(failure.error, ScoreFormAttemptConflictError)
    assert failure.conflicting_page_ids == (failure.observed_page_ids[1],)


def test_repeated_logical_page_preserves_both_conflicting_page_ids(tmp_path: Path):
    dispatch = _batch(tmp_path)
    second = dispatch.pages[1]
    success = second.dispatch_outcome
    assert isinstance(success, RouteDispatchSuccess)
    forged_result = replace(success.module_result, logical_page=2)
    forged_success = replace(success, module_result=forged_result)
    forged_page = replace(second, dispatch_outcome=forged_success)
    forged = replace(dispatch, pages=(dispatch.pages[0], forged_page))
    assembled = assemble_scoreform_attempts(forged, workspace_root=tmp_path)
    failure = assembled.failures[0]
    assert failure.category == "conflicting_duplicate"
    assert set(failure.conflicting_page_ids) == set(failure.observed_page_ids)


def test_scan_filing_eligibility_requires_managed_full_success(tmp_path: Path):
    assembly = assemble_scoreform_attempts(_batch(tmp_path), workspace_root=tmp_path)
    result = assembly.completed_attempts[0].routed_result
    exported = ScoreFormAttemptExportBatch(
        appended_attempts=(ScoreFormExportedAttempt(result, tmp_path / "results.csv", 1),),
        output_paths=(tmp_path / "results.csv",),
    )
    batch = ScoreFormRoutedScoringBatch(
        assembly.dispatch_result, assembly, exported
    )
    assert _eligible_for_scan_filing(batch, None)
    assert not _eligible_for_scan_filing(batch, tmp_path / "explicit.csv")

    missing = assemble_scoreform_attempts(
        _batch(tmp_path / "missing", missing_first=True),
        workspace_root=tmp_path / "missing",
    )
    assert not _eligible_for_scan_filing(
        ScoreFormRoutedScoringBatch(missing.dispatch_result, missing, None), None
    )
    write_error = ScoreFormRoutedResultWriteError("locked")
    failed_export = ScoreFormAttemptExportBatch(failures=(
        ScoreFormAttemptExportFailure(
            "class1", "quiz", tmp_path / "results.csv", "locked", write_error,
            stage="replacement", affected_targets=(("class1", "quiz"),),
        ),
    ))
    assert not _eligible_for_scan_filing(
        ScoreFormRoutedScoringBatch(assembly.dispatch_result, assembly, failed_export),
        None,
    )


def test_deterministic_review_smoke_exports_complete_and_preserves_review_history(
    tmp_path: Path,
):
    base = _batch(tmp_path)
    retained = base.retained_source
    assert retained is not None
    first_success = base.pages[0].dispatch_outcome
    assert isinstance(first_success, RouteDispatchSuccess)
    profile = first_success.profile
    paths = scoreform_work_paths(tmp_path, "class1", "quiz")
    assignment = {
        "assignment_id": "quiz", "title": "Quiz", "question_count": 16,
        "choices": ["A", "B", "C", "D"],
        "layout_id": "standard_15q_abcd_v1",
        "answer_key": {str(number): "A" for number in range(1, 17)},
        "standards": {str(number): [] for number in range(1, 17)},
    }
    student = {
        "class_id": "class1", "student_id": "1001", "last_name": "Issued",
        "first_name": "Student", "period": "2",
    }

    def records(digit):
        value = build_answer_sheet_record_set(
            "class1", assignment, student, generation_id="gen_" + digit * 32,
            artifact_id="art_" + digit * 32, output_kind="individual_pdf",
            reason="initial", issuance_id="iss_" + digit * 32,
            page_ids=("pg_" + digit * 31 + "1", "pg_" + digit * 31 + "2"),
            clock=lambda: "2026-07-15T12:00:00+00:00",
        )
        write_answer_sheet_record_set(tmp_path, paths.work_ref, value)
        return value

    def outcome(page, source_number, route_digit):
        route_id = "rt_" + route_digit * 32
        locator = RouteLocator("PDS2", paths.work_ref, route_id)
        request = RouteDispatchRequest(locator, retained, source_number)
        registration = RouteRegistration(
            "1", locator,
            ModuleRecordRef("scoreform", "answer_sheet_page", page.page_id, "1"),
            "2026-07-15T12:00:00+00:00", "active", "test", {},
        )
        resolution = RouteResolution(
            locator, registration, tmp_path / "classes" / "class1",
            paths.work_root.parent.parent, paths.work_root,
        )
        answers = tuple(
            ScoredAnswer(number, "A", True)
            for number in range(page.question_start, page.question_end + 1)
        )
        result = ScoreFormPageDispatchResult(
            route_id, page.page_id, page.issuance_id, page.generation_id,
            page.artifact_id, page.class_id, page.assignment_id, page.student_id,
            page.logical_page, page.total_pages, page.question_start,
            page.question_end, page.layout_id, len(answers), len(answers), answers,
            retained.source_scan_id, source_number,
            retained.retained_source_relative_path, retained.source_sha256,
            (f"debug/source_{source_number}.png",),
        )
        success = RouteDispatchSuccess(request, profile, resolution, result)
        return Pds2ScanPageOutcome(
            source_number, raw_payload_text="PDS2|test", locator=locator,
            dispatch_request=request, dispatch_outcome=success,
        )

    incomplete = records("8")
    pages = (
        *base.pages,
        outcome(incomplete.pages[0], 3, "3"),
    )
    dispatch = replace(base, pages=pages)
    assembly = assemble_scoreform_attempts(dispatch, workspace_root=tmp_path)
    assert len(assembly.completed_attempts) == 1
    assert [failure.category for failure in assembly.failures] == ["missing_pages"]
    assert all(
        failure.observed_route_ids and failure.source_scan_id
        and failure.observed_page_ids and failure.diagnostic_paths
        for failure in assembly.failures
    )
    exported = export_scoreform_attempts(assembly, workspace_root=tmp_path)
    batch = ScoreFormRoutedScoringBatch(dispatch, assembly, exported)
    assert batch.status == "partial_success" and batch.exit_code() == 1
    assert len(exported.appended_attempts) == 1
    assert not _eligible_for_scan_filing(batch, None)
    persistence = persist_routed_scoring_failures(
        batch,
        retained.retained_source_relative_path,
        tmp_path,
        now=datetime(2026, 7, 15, 13, 0, tzinfo=timezone.utc),
    )
    assert persistence.complete and len(persistence.persisted) == 1
    failure_path = persistence.persisted[0].metadata_path
    failure_bytes = failure_path.read_bytes()
    assert json.loads(failure_bytes)["schema_version"] == "2"

    discovered = discover_scan_review_items(tmp_path)
    assert [item.failure_id for item in discovered.items] == [
        persistence.persisted[0].failure_id
    ]
    deferred = resolve_scan_review_item(
        tmp_path,
        persistence.persisted[0].failure_id,
        "defer",
        now=datetime(2026, 7, 15, 13, 1, tzinfo=timezone.utc),
    )
    assert deferred.resolution_status == "deferred"
    assert discover_scan_review_items(tmp_path).items[0].status == "deferred"
    final = resolve_scan_review_item(
        tmp_path,
        persistence.persisted[0].failure_id,
        "cannot_route",
        now=datetime(2026, 7, 15, 13, 2, tzinfo=timezone.utc),
    )
    assert final.resolution_status == "resolved"
    projected = discover_scan_review_items(tmp_path, include_resolved=True).items[0]
    assert len(projected.resolution_history) == 2
    assert failure_path.read_bytes() == failure_bytes
    resolution_files = tuple((tmp_path / "scans/review/resolutions").glob("*.json"))
    assert len(resolution_files) == 2
    assert all(json.loads(path.read_bytes())["schema_version"] == "2" for path in resolution_files)
    assert not tuple(paths.scans_dir.glob("*"))
