from __future__ import annotations

import hashlib
from dataclasses import FrozenInstanceError, replace
from datetime import timedelta
from pathlib import Path
from typing import Any, cast

import pytest

from scoreform.academic_result_manifest import (
    AcademicResultManifest,
    RecordSet,
    WorkReference,
    manifest_from_json_bytes,
    manifest_to_canonical_json_bytes,
)
from scoreform.publication_revision_policy import (
    SCOREFORM_ACADEMIC_RESULT_PUBLICATION_KIND,
    SCOREFORM_ACADEMIC_RESULT_RECORD_SET_ID,
    ManifestRecoveryDisposition,
    ManifestRecoveryError,
    ManifestRevisionAllocationError,
    ManifestRevisionDisposition,
    ManifestRevisionReason,
    ManifestRevisionReplayConflictError,
    ManifestRevisionTransitionError,
    ScoreFormPublicationRevisionPolicyError,
    ScoreFormPublicationRevisionPolicyValidationError,
    manifests_have_same_publication_content,
    next_record_set_revision,
    plan_manifest_revision,
    plan_missing_manifest_recovery,
    require_publication_supersession,
    validate_manifest_revision_transition,
)

FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "publication"
    / "scoreform_academic_result_manifest_v1.json"
)


def _manifest(revision: int = 1) -> AcademicResultManifest:
    value = manifest_from_json_bytes(FIXTURE.read_bytes())
    return replace(
        value,
        record_set=RecordSet(SCOREFORM_ACADEMIC_RESULT_RECORD_SET_ID, revision),
    )


def _bytes(value: AcademicResultManifest) -> bytes:
    return manifest_to_canonical_json_bytes(value)


def _with_source_hash(
    value: AcademicResultManifest, *, assignment: str | None = None, results: str | None = None
) -> AcademicResultManifest:
    source = value.source_snapshot
    return replace(
        value,
        source_snapshot=replace(
            source,
            assignment=replace(
                source.assignment, sha256=assignment or source.assignment.sha256
            ),
            results_history=replace(
                source.results_history,
                sha256=results or source.results_history.sha256,
            ),
        ),
    )


def _with_appended_attempt(
    value: AcademicResultManifest, *, student_index: int = 0
) -> AcademicResultManifest:
    student = value.students[student_index]
    prior = student.attempts[-1]
    appended = replace(
        prior,
        attempt_number=prior.attempt_number + 1,
        recorded_at=prior.recorded_at + timedelta(hours=1),
    )
    students = list(value.students)
    students[student_index] = replace(
        student, attempts=student.attempts + (appended,)
    )
    return replace(value, students=tuple(students))


def _plan_successor(
    predecessor: AcademicResultManifest,
    successor: AcademicResultManifest,
    **kwargs: object,
):
    return plan_manifest_revision(
        successor,
        predecessor_manifest=predecessor,
        allocated_revisions=(predecessor.record_set.revision,),
        **kwargs,  # type: ignore[arg-type]
    )


def test_production_identity_and_revision_allocation() -> None:
    assert SCOREFORM_ACADEMIC_RESULT_PUBLICATION_KIND == "academic_result_set"
    assert SCOREFORM_ACADEMIC_RESULT_RECORD_SET_ID == "academic_results"
    assert next_record_set_revision(()) == 1
    assert next_record_set_revision((1,)) == 2
    assert next_record_set_revision((1, 3, 8)) == 9


@pytest.mark.parametrize("revisions", [(True,), (0,), (-1,), (1, 1), "1"])
def test_revision_allocation_rejects_invalid_or_reused_values(revisions: object) -> None:
    with pytest.raises(ManifestRevisionAllocationError):
        next_record_set_revision(revisions)  # type: ignore[arg-type]


def test_initial_revision_must_be_one_and_models_are_frozen() -> None:
    plan = plan_manifest_revision(_manifest(1))
    assert plan.disposition is ManifestRevisionDisposition.CREATE_INITIAL
    assert plan.reason is ManifestRevisionReason.INITIAL_PUBLICATION
    assert plan.revision == 1
    assert plan.new_immutable_revision_required
    assert not plan.reuse_existing_bytes
    with pytest.raises(FrozenInstanceError):
        plan.revision = 2  # type: ignore[misc]
    with pytest.raises(ManifestRevisionAllocationError):
        plan_manifest_revision(_manifest(2))


def test_content_comparison_ignores_only_generated_at_and_revision() -> None:
    first = _manifest(1)
    envelope_changed = replace(
        first,
        generated_at=first.generated_at + timedelta(days=1),
        record_set=RecordSet(SCOREFORM_ACADEMIC_RESULT_RECORD_SET_ID, 7),
    )
    assert manifests_have_same_publication_content(first, envelope_changed)
    assert not manifests_have_same_publication_content(
        first, _with_source_hash(envelope_changed, assignment="d" * 64)
    )
    assert not manifests_have_same_publication_content(
        first, _with_source_hash(envelope_changed, results="e" * 64)
    )


def test_exact_noop_reuses_the_original_revision_and_exact_bytes() -> None:
    predecessor = _manifest(2)
    candidate = replace(
        predecessor,
        generated_at=predecessor.generated_at + timedelta(days=2),
        record_set=RecordSet(SCOREFORM_ACADEMIC_RESULT_RECORD_SET_ID, 99),
    )
    exact_bytes = _bytes(predecessor)
    plan = plan_manifest_revision(
        candidate,
        predecessor_manifest=predecessor,
        predecessor_manifest_bytes=exact_bytes,
        allocated_revisions=(1, 2),
    )
    assert plan.disposition is ManifestRevisionDisposition.REUSE_EXISTING
    assert plan.reason is ManifestRevisionReason.EXACT_REPLAY
    assert plan.revision == 2
    assert plan.existing_manifest_bytes is exact_bytes
    assert plan.reuse_existing_bytes
    assert not plan.new_immutable_revision_required


def test_noop_requires_matching_canonical_existing_bytes() -> None:
    predecessor = _manifest(1)
    with pytest.raises(ManifestRevisionReplayConflictError):
        plan_manifest_revision(
            predecessor,
            predecessor_manifest=predecessor,
            predecessor_manifest_bytes=None,
            allocated_revisions=(1,),
        )
    with pytest.raises(ManifestRevisionReplayConflictError):
        plan_manifest_revision(
            predecessor,
            predecessor_manifest=predecessor,
            predecessor_manifest_bytes=_bytes(_manifest(2)),
            allocated_revisions=(1,),
        )


@pytest.mark.parametrize("source_field", ["assignment", "results"])
def test_native_source_hash_change_creates_successor(source_field: str) -> None:
    predecessor = _manifest(1)
    successor = _with_source_hash(
        _manifest(2),
        assignment="d" * 64 if source_field == "assignment" else None,
        results="e" * 64 if source_field == "results" else None,
    )
    plan = _plan_successor(predecessor, successor)
    assert plan.disposition is ManifestRevisionDisposition.CREATE_SUCCESSOR
    assert plan.reason is ManifestRevisionReason.NATIVE_SOURCE_CHANGED
    assert plan.revision == 2


def test_new_student_and_new_attempt_are_append_preserved() -> None:
    predecessor = _manifest(1)
    additional = replace(
        predecessor.students[1],
        student_id="student_gamma",
    )
    new_student_successor = replace(
        _with_source_hash(_manifest(2), results="d" * 64),
        students=predecessor.students + (additional,),
    )
    transition = validate_manifest_revision_transition(
        predecessor, new_student_successor
    )
    assert transition.added_students == ("student_gamma",)
    assert transition.added_attempts[0].student_id == "student_gamma"

    attempt_successor = _with_appended_attempt(
        _with_source_hash(_manifest(2), results="e" * 64)
    )
    plan = _plan_successor(predecessor, attempt_successor)
    assert plan.reason is ManifestRevisionReason.ATTEMPT_HISTORY_APPENDED


@pytest.mark.parametrize(
    "assignment_change",
    [
        lambda assignment: replace(assignment, title="Corrected title"),
        lambda assignment: replace(
            assignment, standards_profile_id="corrected_profile"
        ),
        lambda assignment: replace(
            assignment,
            questions=(
                replace(assignment.questions[0], standard_ids=("new_standard",)),
            )
            + assignment.questions[1:],
        ),
    ],
)
def test_allowed_assignment_metadata_changes_create_successor(
    assignment_change,
) -> None:
    predecessor = _manifest(1)
    successor = replace(
        _with_source_hash(_manifest(2), assignment="d" * 64),
        assignment=assignment_change(predecessor.assignment),
    )
    plan = _plan_successor(predecessor, successor)
    assert plan.reason is ManifestRevisionReason.ASSIGNMENT_METADATA_CHANGED


def test_historical_reversion_allocates_a_new_greater_revision() -> None:
    historical = _manifest(1)
    predecessor = replace(
        _with_source_hash(_manifest(2), assignment="d" * 64),
        assignment=replace(historical.assignment, title="Temporary title"),
    )
    successor = _manifest(3)
    plan = plan_manifest_revision(
        successor,
        predecessor_manifest=predecessor,
        allocated_revisions=(1, 2),
        historical_manifests=(historical,),
    )
    assert plan.revision == 3
    assert plan.reason is ManifestRevisionReason.HISTORICAL_REVERSION


def test_explicit_republication_after_withdrawal_creates_successor() -> None:
    predecessor = _manifest(3)
    successor = _manifest(4)
    plan = plan_manifest_revision(
        successor,
        predecessor_manifest=predecessor,
        allocated_revisions=(1, 2, 3),
        republish_after_withdrawal=True,
    )
    assert plan.disposition is ManifestRevisionDisposition.CREATE_SUCCESSOR
    assert plan.reason is ManifestRevisionReason.REPUBLICATION_AFTER_WITHDRAWAL
    assert plan.revision == 4


def test_allocated_revision_cannot_be_reused_for_changed_content() -> None:
    predecessor = _manifest(2)
    contradictory = _with_source_hash(_manifest(2), results="d" * 64)
    with pytest.raises(ManifestRevisionReplayConflictError):
        plan_manifest_revision(
            contradictory,
            predecessor_manifest=predecessor,
            allocated_revisions=(1, 2),
        )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: replace(value, students=value.students[1:]),
        lambda value: replace(
            value,
            students=(
                replace(value.students[0], attempts=value.students[0].attempts[:-1]),
            )
            + value.students[1:],
        ),
        lambda value: replace(
            value,
            students=(
                replace(
                    value.students[0],
                    attempts=(value.students[0].attempts[0],)
                    + (
                        replace(value.students[0].attempts[1], attempt_number=3),
                    ),
                ),
            )
            + value.students[1:],
        ),
        lambda value: _mutate_first_attempt_score(value),
        lambda value: _mutate_first_attempt(
            value,
            "responses",
            (
                replace(
                    value.students[0].attempts[0].responses[0],
                    selected_answer="B",
                ),
            )
            + value.students[0].attempts[0].responses[1:],
        ),
        lambda value: _mutate_first_attempt(
            value,
            "recorded_at",
            value.students[0].attempts[0].recorded_at + timedelta(seconds=1),
        ),
        lambda value: _mutate_first_attempt(
            value,
            "provenance",
            replace(
                value.students[0].attempts[0].provenance,
                source_sha256="f" * 64,
            ),
        ),
    ],
)
def test_prior_attempt_history_cannot_be_removed_renumbered_or_mutated(
    mutate,
) -> None:
    predecessor = _manifest(1)
    successor = replace(mutate(_manifest(2)), source_snapshot=_with_source_hash(_manifest(2), results="d" * 64).source_snapshot)
    with pytest.raises(ManifestRevisionTransitionError):
        validate_manifest_revision_transition(predecessor, successor)


def _mutate_first_attempt(
    value: AcademicResultManifest, field: str, replacement: object
) -> AcademicResultManifest:
    first = value.students[0]
    changed = replace(
        first.attempts[0], **cast(Any, {field: replacement})
    )
    return replace(
        value,
        students=(replace(first, attempts=(changed,) + first.attempts[1:]),)
        + value.students[1:],
    )


def _mutate_first_attempt_score(value: AcademicResultManifest) -> AcademicResultManifest:
    attempt = value.students[0].attempts[0]
    responses = (
        replace(attempt.responses[0], selected_answer="B", correct=False),
    ) + attempt.responses[1:]
    changed = replace(attempt, points_earned=1, responses=responses)
    return replace(
        value,
        students=(
            replace(
                value.students[0], attempts=(changed,) + value.students[0].attempts[1:]
            ),
        )
        + value.students[1:],
    )


def test_changed_correctness_and_result_origin_are_in_place_mutations() -> None:
    predecessor = _manifest(1)
    response = predecessor.students[1].attempts[0].responses[0]
    changed_responses = (
        replace(response, correct=False),
    ) + predecessor.students[1].attempts[0].responses[1:]
    changed_student = replace(
        predecessor.students[1],
        attempts=(
            replace(
                predecessor.students[1].attempts[0],
                points_earned=2,
                responses=changed_responses,
            ),
        ),
    )
    changed_correctness = replace(
        _manifest(2), students=(predecessor.students[0], changed_student)
    )
    with pytest.raises(ManifestRevisionTransitionError):
        validate_manifest_revision_transition(predecessor, changed_correctness)

    manual = predecessor.students[1].attempts[0]
    changed_origin = replace(
        _manifest(2),
        students=(
            predecessor.students[0],
            replace(
                predecessor.students[1],
                attempts=(
                    replace(
                        manual,
                        result_origin="scan_review_manual",
                        provenance=predecessor.students[0].attempts[1].provenance,
                    ),
                ),
            ),
        ),
    )
    with pytest.raises(ManifestRevisionTransitionError):
        validate_manifest_revision_transition(predecessor, changed_origin)


def test_new_attempt_cannot_fill_a_historical_numbering_gap() -> None:
    base = _manifest(1)
    student = base.students[0]
    predecessor = replace(
        base,
        students=(
            replace(
                student,
                attempts=(student.attempts[0], replace(student.attempts[1], attempt_number=3)),
            ),
        )
        + base.students[1:],
    )
    inserted = replace(student.attempts[1], attempt_number=2)
    successor = replace(
        _manifest(2),
        students=(
            replace(
                predecessor.students[0],
                attempts=(
                    predecessor.students[0].attempts[0],
                    inserted,
                    predecessor.students[0].attempts[1],
                ),
            ),
        )
        + predecessor.students[1:],
    )
    with pytest.raises(ManifestRevisionTransitionError):
        validate_manifest_revision_transition(predecessor, successor)


def test_structural_assignment_and_series_identity_changes_are_rejected() -> None:
    predecessor = _manifest(1)
    with pytest.raises(ManifestRevisionTransitionError):
        validate_manifest_revision_transition(
            predecessor,
            replace(
                _manifest(2),
                assignment=replace(predecessor.assignment, layout_id="compact_25q_abcd_v1"),
            ),
        )

    other_work = "other_assignment"
    with pytest.raises(ManifestRevisionTransitionError):
        validate_manifest_revision_transition(
            predecessor,
            replace(
                _manifest(2),
                work=WorkReference("scoreform", predecessor.work.class_id, other_work),
                assignment=replace(
                    predecessor.assignment, assignment_id=other_work
                ),
            ),
        )


def _structurally_redefined(value: AcademicResultManifest) -> AcademicResultManifest:
    assignment = replace(
        value.assignment,
        question_count=2,
        total_points=2,
        questions=value.assignment.questions[:2],
    )
    students = []
    for student in value.students:
        attempts = []
        for attempt in student.attempts:
            responses = attempt.responses[:2]
            attempts.append(
                replace(
                    attempt,
                    points_earned=sum(response.correct for response in responses),
                    points_possible=2,
                    responses=responses,
                )
            )
        students.append(replace(student, attempts=tuple(attempts)))
    return replace(value, assignment=assignment, students=tuple(students))


def test_question_count_and_point_model_redefinition_is_rejected() -> None:
    with pytest.raises(ManifestRevisionTransitionError):
        validate_manifest_revision_transition(
            _manifest(1), _structurally_redefined(_manifest(2))
        )


@pytest.mark.parametrize(
    ("target", "field", "replacement"),
    [
        ("work", "module_id", "other_module"),
        ("assignment", "choices", ("A", "B")),
        ("assignment", "total_points", 4),
        ("question", "question_number", 2),
        ("question", "points_possible", 2),
    ],
)
def test_unsupported_or_internally_invalid_structural_changes_are_policy_errors(
    target: str, field: str, replacement: object
) -> None:
    predecessor = _manifest(1)
    successor = _manifest(2)
    subject = {
        "work": successor.work,
        "assignment": successor.assignment,
        "question": successor.assignment.questions[0],
    }[target]
    object.__setattr__(subject, field, replacement)
    with pytest.raises(ScoreFormPublicationRevisionPolicyError):
        validate_manifest_revision_transition(predecessor, successor)
    with pytest.raises(ManifestRevisionTransitionError):
        validate_manifest_revision_transition(
            predecessor,
            replace(_manifest(2), work=WorkReference("scoreform", "other_class", predecessor.work.work_id)),
        )
    with pytest.raises(ManifestRevisionTransitionError):
        validate_manifest_revision_transition(
            predecessor,
            replace(
                _manifest(2),
                record_set=RecordSet("other_results", 2),
            ),
        )


def test_invalid_or_unsupported_manifest_is_wrapped_in_policy_error() -> None:
    candidate = _manifest(1)
    object.__setattr__(candidate, "contract_version", "unsupported")
    with pytest.raises(ScoreFormPublicationRevisionPolicyValidationError):
        plan_manifest_revision(candidate)


def test_supersession_requires_an_explicit_expected_head() -> None:
    predecessor = _manifest(1)
    successor = _with_appended_attempt(_manifest(2))
    requirement = require_publication_supersession(
        predecessor,
        successor,
        expected_current_publication_id="publication_exact_head",
    )
    assert requirement.expected_current_publication_id == "publication_exact_head"
    assert requirement.publication_kind == "academic_result_set"
    assert requirement.predecessor_revision == 1
    assert requirement.successor_revision == 2
    with pytest.raises(ScoreFormPublicationRevisionPolicyValidationError):
        require_publication_supersession(
            predecessor, successor, expected_current_publication_id=""
        )


def test_missing_manifest_recovery_restores_only_digest_matching_exact_bytes() -> None:
    exact_bytes = _bytes(_manifest(1))
    digest = hashlib.sha256(exact_bytes).hexdigest()
    restore = plan_missing_manifest_recovery(
        recorded_sha256=digest, trusted_exact_bytes=exact_bytes
    )
    assert restore.disposition is ManifestRecoveryDisposition.RESTORE_EXACT_BYTES
    assert restore.exact_bytes_to_restore is exact_bytes

    replace_plan = plan_missing_manifest_recovery(
        recorded_sha256=digest, trusted_exact_bytes=None
    )
    assert (
        replace_plan.disposition
        is ManifestRecoveryDisposition.WITHDRAW_AND_CREATE_SUCCESSOR
    )
    assert replace_plan.exact_bytes_to_restore is None
    with pytest.raises(ManifestRecoveryError):
        plan_missing_manifest_recovery(
            recorded_sha256=digest, trusted_exact_bytes=exact_bytes + b"\n"
        )


def test_policy_module_has_no_workspace_or_publication_side_effect_surface() -> None:
    source = Path("scoreform/publication_revision_policy.py").read_text(
        encoding="utf-8"
    )
    forbidden = (
        "scoreform.workspace",
        "assignment.json\"",
        "results.csv\"",
        "publish_manifest_revision",
        "supersede_manifest_revision",
        "withdraw_publication",
        "pds_core.publication",
        "meridian",
        "Path(",
        "open(",
        "os.listdir",
        "glob(",
    )
    assert all(fragment not in source for fragment in forbidden)
