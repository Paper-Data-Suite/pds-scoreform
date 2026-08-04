"""Pure producer policy for ScoreForm academic-result publication revisions.

The policy operates only on immutable manifest values, exact bytes supplied by
callers, and primitive publication state.  It performs no filesystem, workspace,
Core registry, publication, withdrawal, or consumer work.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from typing import NoReturn

from scoreform.academic_result_manifest import (
    AcademicResultManifest,
    Attempt,
    ScoreFormAcademicResultManifestError,
    StudentResults,
    manifest_from_json_bytes,
    manifest_to_canonical_json_bytes,
    manifest_to_mapping,
    validate_manifest,
)

SCOREFORM_ACADEMIC_RESULT_RECORD_SET_ID = "academic_results"
SCOREFORM_ACADEMIC_RESULT_PUBLICATION_KIND = "academic_result_set"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ScoreFormPublicationRevisionPolicyError(Exception):
    """Base error for public ScoreForm publication-revision policy failures."""


class ScoreFormPublicationRevisionPolicyValidationError(
    ScoreFormPublicationRevisionPolicyError
):
    """Policy input is malformed or internally inconsistent."""


class ManifestRevisionAllocationError(ScoreFormPublicationRevisionPolicyError):
    """Producer revision state cannot safely allocate the requested revision."""


class ManifestRevisionTransitionError(ScoreFormPublicationRevisionPolicyError):
    """Two manifests cannot be predecessor and successor in one series."""


class ManifestRevisionReplayConflictError(ManifestRevisionTransitionError):
    """A logical revision or its immutable bytes are being reused contradictorily."""


class ManifestRecoveryError(ScoreFormPublicationRevisionPolicyError):
    """Manifest recovery evidence is malformed or contradictory."""


class ManifestRevisionDisposition(str, Enum):
    """Producer action selected for the current authoritative state."""

    REUSE_EXISTING = "reuse_existing"
    CREATE_INITIAL = "create_initial"
    CREATE_SUCCESSOR = "create_successor"


class ManifestRevisionReason(str, Enum):
    """Diagnostic producer reason for a revision plan, never a manifest field."""

    EXACT_REPLAY = "exact_replay"
    INITIAL_PUBLICATION = "initial_publication"
    NATIVE_SOURCE_CHANGED = "native_source_changed"
    ATTEMPT_HISTORY_APPENDED = "attempt_history_appended"
    ASSIGNMENT_METADATA_CHANGED = "assignment_metadata_changed"
    HISTORICAL_REVERSION = "historical_reversion"
    REPUBLICATION_AFTER_WITHDRAWAL = "republication_after_withdrawal"


class ManifestRecoveryDisposition(str, Enum):
    """Permitted response to a missing or altered historical manifest."""

    RESTORE_EXACT_BYTES = "restore_exact_bytes"
    WITHDRAW_AND_CREATE_SUCCESSOR = "withdraw_and_create_successor"


@dataclass(frozen=True, slots=True, order=True)
class ManifestAttemptIdentity:
    """Stable attempt identity within a complete ScoreForm work reference."""

    student_id: str
    attempt_number: int

    def __post_init__(self) -> None:
        _model_text(self.student_id, "student_id")
        _model_positive(self.attempt_number, "attempt_number")


@dataclass(frozen=True, slots=True)
class ManifestRevisionTransition:
    """Validated append-preserving relationship between two manifest revisions."""

    predecessor_revision: int
    successor_revision: int
    added_students: tuple[str, ...]
    added_attempts: tuple[ManifestAttemptIdentity, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "added_students", tuple(self.added_students))
        object.__setattr__(self, "added_attempts", tuple(self.added_attempts))
        before = _model_positive(self.predecessor_revision, "predecessor_revision")
        after = _model_positive(self.successor_revision, "successor_revision")
        if after <= before:
            _validation_error("successor_revision must exceed predecessor_revision.")
        if any(
            not isinstance(student_id, str) or not student_id
            for student_id in self.added_students
        ):
            _validation_error("added_students must contain nonempty identifiers.")
        if self.added_students != tuple(sorted(set(self.added_students))):
            _validation_error("added_students must be unique and sorted.")
        if any(
            not isinstance(identity, ManifestAttemptIdentity)
            for identity in self.added_attempts
        ):
            _validation_error("added_attempts contains the wrong model type.")
        if self.added_attempts != tuple(sorted(set(self.added_attempts))):
            _validation_error("added_attempts must be unique and sorted.")


@dataclass(frozen=True, slots=True)
class ManifestRevisionPlan:
    """Immutable producer decision for later manifest generation workflows."""

    disposition: ManifestRevisionDisposition
    reason: ManifestRevisionReason
    revision: int
    record_set_id: str
    existing_manifest_bytes: bytes | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.disposition, ManifestRevisionDisposition):
            _validation_error("disposition has the wrong enum type.")
        if not isinstance(self.reason, ManifestRevisionReason):
            _validation_error("reason has the wrong enum type.")
        _model_positive(self.revision, "revision")
        if self.record_set_id != SCOREFORM_ACADEMIC_RESULT_RECORD_SET_ID:
            _validation_error("record_set_id is not the production ScoreForm identity.")
        if self.existing_manifest_bytes is not None and not isinstance(
            self.existing_manifest_bytes, bytes
        ):
            _validation_error("existing_manifest_bytes must be immutable bytes.")
        if self.disposition is ManifestRevisionDisposition.REUSE_EXISTING:
            if self.reason is not ManifestRevisionReason.EXACT_REPLAY:
                _validation_error("Replay plans require the exact_replay reason.")
            if not self.existing_manifest_bytes:
                _validation_error("Replay plans require nonempty exact existing bytes.")
            return
        if self.disposition is ManifestRevisionDisposition.CREATE_INITIAL:
            if self.reason is not ManifestRevisionReason.INITIAL_PUBLICATION:
                _validation_error(
                    "Initial plans require the initial_publication reason."
                )
            if self.revision != 1:
                _validation_error("Initial plans must select revision 1.")
            if self.existing_manifest_bytes is not None:
                _validation_error("Initial plans cannot carry existing bytes.")
            return
        allowed_successor_reasons = frozenset(
            {
                ManifestRevisionReason.NATIVE_SOURCE_CHANGED,
                ManifestRevisionReason.ATTEMPT_HISTORY_APPENDED,
                ManifestRevisionReason.ASSIGNMENT_METADATA_CHANGED,
                ManifestRevisionReason.HISTORICAL_REVERSION,
                ManifestRevisionReason.REPUBLICATION_AFTER_WITHDRAWAL,
            }
        )
        if self.reason not in allowed_successor_reasons:
            _validation_error("Successor plans require a successor revision reason.")
        if self.revision <= 1:
            _validation_error("Successor plans must select a revision greater than 1.")
        if self.existing_manifest_bytes is not None:
            _validation_error("Successor plans cannot carry existing bytes.")

    @property
    def reuse_existing_bytes(self) -> bool:
        """Whether the caller must preserve and reuse exact existing bytes."""

        return self.disposition is ManifestRevisionDisposition.REUSE_EXISTING

    @property
    def new_immutable_revision_required(self) -> bool:
        """Whether later generation must durably create new immutable bytes."""

        return self.disposition is not ManifestRevisionDisposition.REUSE_EXISTING


@dataclass(frozen=True, slots=True)
class PublicationSupersessionRequirement:
    """Explicit predecessor requirement to carry into a later Core workflow."""

    expected_current_publication_id: str
    publication_kind: str
    record_set_id: str
    predecessor_revision: int
    successor_revision: int

    def __post_init__(self) -> None:
        _model_text(
            self.expected_current_publication_id,
            "expected_current_publication_id",
        )
        if self.publication_kind != SCOREFORM_ACADEMIC_RESULT_PUBLICATION_KIND:
            _validation_error(
                "publication_kind is not the ScoreForm academic-result kind."
            )
        if self.record_set_id != SCOREFORM_ACADEMIC_RESULT_RECORD_SET_ID:
            _validation_error("record_set_id is not the production ScoreForm identity.")
        before = _model_positive(self.predecessor_revision, "predecessor_revision")
        after = _model_positive(self.successor_revision, "successor_revision")
        if after <= before:
            _validation_error("successor_revision must exceed predecessor_revision.")


@dataclass(frozen=True, slots=True)
class ManifestRecoveryPlan:
    """Pure recovery decision; it performs neither restoration nor withdrawal."""

    disposition: ManifestRecoveryDisposition
    exact_bytes_to_restore: bytes | None

    def __post_init__(self) -> None:
        if not isinstance(self.disposition, ManifestRecoveryDisposition):
            _validation_error("disposition has the wrong recovery enum type.")
        if self.exact_bytes_to_restore is not None and not isinstance(
            self.exact_bytes_to_restore, bytes
        ):
            _validation_error("exact_bytes_to_restore must be immutable bytes.")
        if self.disposition is ManifestRecoveryDisposition.RESTORE_EXACT_BYTES:
            if (
                not isinstance(self.exact_bytes_to_restore, bytes)
                or len(self.exact_bytes_to_restore) == 0
            ):
                _validation_error("Exact restoration requires nonempty bytes.")
            return
        if self.exact_bytes_to_restore is not None:
            _validation_error(
                "Withdrawal-and-successor recovery cannot carry restoration bytes."
            )


def _validation_error(message: str) -> NoReturn:
    raise ScoreFormPublicationRevisionPolicyValidationError(message)


def _model_positive(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        _validation_error(f"{field} must be a positive non-Boolean integer.")
    return value


def _model_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        _validation_error(f"{field} must be nonempty and trimmed.")
    return value


def _validated_manifest(
    manifest: object, field: str
) -> AcademicResultManifest:
    if not isinstance(manifest, AcademicResultManifest):
        _validation_error(f"{field} must be an AcademicResultManifest.")
    try:
        return validate_manifest(manifest)
    except ScoreFormAcademicResultManifestError as error:
        raise ScoreFormPublicationRevisionPolicyValidationError(
            f"{field} is not a valid supported manifest: {error}"
        ) from error


def _production_manifest(
    manifest: object, field: str
) -> AcademicResultManifest:
    value = _validated_manifest(manifest, field)
    if value.record_set.record_set_id != SCOREFORM_ACADEMIC_RESULT_RECORD_SET_ID:
        raise ManifestRevisionTransitionError(
            f"{field} record_set_id must be "
            f"{SCOREFORM_ACADEMIC_RESULT_RECORD_SET_ID!r} for production policy."
        )
    return value


def _positive_revision(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ManifestRevisionAllocationError(
            f"{field} must contain only positive non-Boolean integers."
        )
    return value


def _allocated_revision_tuple(values: Iterable[int]) -> tuple[int, ...]:
    if isinstance(values, (str, bytes, bytearray)):
        raise ManifestRevisionAllocationError(
            "allocated_revisions must be an iterable of positive integers."
        )
    try:
        revisions = tuple(values)
    except TypeError as error:
        raise ManifestRevisionAllocationError(
            "allocated_revisions must be an iterable of positive integers."
        ) from error
    validated = tuple(
        _positive_revision(value, "allocated_revisions") for value in revisions
    )
    if len(set(validated)) != len(validated):
        raise ManifestRevisionAllocationError(
            "allocated_revisions must not contain duplicate revisions."
        )
    return validated


def _publication_content(manifest: AcademicResultManifest) -> dict[str, object]:
    mapping = manifest_to_mapping(manifest)
    del mapping["generated_at"]
    record_set = dict(mapping["record_set"])
    del record_set["revision"]
    mapping["record_set"] = record_set
    return mapping


def manifests_have_same_publication_content(
    first: AcademicResultManifest,
    second: AcademicResultManifest,
) -> bool:
    """Compare all manifest state except ``generated_at`` and revision number."""

    left = _validated_manifest(first, "first")
    right = _validated_manifest(second, "second")
    return _publication_content(left) == _publication_content(right)


def next_record_set_revision(allocated_revisions: Iterable[int]) -> int:
    """Return 1 initially, otherwise one greater than the highest allocation."""

    revisions = _allocated_revision_tuple(allocated_revisions)
    return 1 if not revisions else max(revisions) + 1


def _structural_assignment_value(manifest: AcademicResultManifest) -> tuple[object, ...]:
    assignment = manifest.assignment
    return (
        assignment.assignment_id,
        assignment.question_count,
        assignment.layout_id,
        assignment.choices,
        assignment.total_points,
        tuple(
            (question.question_number, question.points_possible)
            for question in assignment.questions
        ),
    )


def _student_map(manifest: AcademicResultManifest) -> dict[str, StudentResults]:
    return {student.student_id: student for student in manifest.students}


def _attempt_map(student: StudentResults) -> dict[int, Attempt]:
    return {attempt.attempt_number: attempt for attempt in student.attempts}


def validate_manifest_revision_transition(
    predecessor: AcademicResultManifest,
    successor: AcademicResultManifest,
) -> ManifestRevisionTransition:
    """Validate same-series identity, structure, and append-only attempt history."""

    before = _validated_manifest(predecessor, "predecessor")
    after = _validated_manifest(successor, "successor")

    identity_fields = (
        ("record_type", before.record_type, after.record_type),
        ("contract_version", before.contract_version, after.contract_version),
        ("producer_module_id", before.producer_module_id, after.producer_module_id),
        ("work.module_id", before.work.module_id, after.work.module_id),
        ("work.class_id", before.work.class_id, after.work.class_id),
        ("work.work_id", before.work.work_id, after.work.work_id),
        (
            "record_set.record_set_id",
            before.record_set.record_set_id,
            after.record_set.record_set_id,
        ),
    )
    for field, old, new in identity_fields:
        if old != new:
            raise ManifestRevisionTransitionError(
                f"Same-series transition cannot change {field}."
            )
    if after.record_set.revision <= before.record_set.revision:
        raise ManifestRevisionTransitionError(
            "Successor revision must be greater than its predecessor; allocated "
            "revision numbers cannot be reused."
        )
    if _structural_assignment_value(before) != _structural_assignment_value(after):
        raise ManifestRevisionTransitionError(
            "Same-series transition cannot structurally redefine the assignment."
        )

    old_students = _student_map(before)
    new_students = _student_map(after)
    added_students = tuple(sorted(set(new_students) - set(old_students)))
    added_attempts: list[ManifestAttemptIdentity] = []

    for student_id, old_student in old_students.items():
        new_student = new_students.get(student_id)
        if new_student is None:
            raise ManifestRevisionTransitionError(
                f"Previously published student {student_id!r} cannot disappear."
            )
        old_attempts = _attempt_map(old_student)
        new_attempts = _attempt_map(new_student)
        for attempt_number, old_attempt in old_attempts.items():
            new_attempt = new_attempts.get(attempt_number)
            if new_attempt is None:
                raise ManifestRevisionTransitionError(
                    f"Previously published attempt {student_id!r}/"
                    f"{attempt_number} cannot disappear or be renumbered."
                )
            if new_attempt != old_attempt:
                raise ManifestRevisionTransitionError(
                    f"Previously published attempt {student_id!r}/"
                    f"{attempt_number} cannot be rewritten in place."
                )
        greatest_old = max(old_attempts)
        for attempt_number in new_attempts.keys() - old_attempts.keys():
            if attempt_number <= greatest_old:
                raise ManifestRevisionTransitionError(
                    f"New attempt {student_id!r}/{attempt_number} must be greater "
                    "than every previously published attempt for that student."
                )
            added_attempts.append(
                ManifestAttemptIdentity(student_id, attempt_number)
            )

    for student_id in added_students:
        for attempt in new_students[student_id].attempts:
            added_attempts.append(
                ManifestAttemptIdentity(student_id, attempt.attempt_number)
            )

    return ManifestRevisionTransition(
        predecessor_revision=before.record_set.revision,
        successor_revision=after.record_set.revision,
        added_students=added_students,
        added_attempts=tuple(sorted(added_attempts)),
    )


def _validated_existing_bytes(
    manifest: AcademicResultManifest, value: object
) -> bytes:
    if not isinstance(value, bytes) or not value:
        raise ManifestRevisionReplayConflictError(
            "Exact replay requires nonempty immutable existing manifest bytes."
        )
    try:
        decoded = manifest_from_json_bytes(value)
        canonical = manifest_to_canonical_json_bytes(decoded)
    except ScoreFormAcademicResultManifestError as error:
        raise ManifestRevisionReplayConflictError(
            "Existing manifest bytes are not a valid canonical manifest."
        ) from error
    if canonical != value or decoded != manifest:
        raise ManifestRevisionReplayConflictError(
            "Existing manifest bytes contradict the selected logical revision."
        )
    return value


def _plan_reason(
    predecessor: AcademicResultManifest,
    successor: AcademicResultManifest,
    transition: ManifestRevisionTransition,
    historical_manifests: tuple[AcademicResultManifest, ...],
) -> ManifestRevisionReason:
    if any(
        manifests_have_same_publication_content(successor, historical)
        for historical in historical_manifests
        if historical.record_set.revision != predecessor.record_set.revision
    ):
        return ManifestRevisionReason.HISTORICAL_REVERSION
    if transition.added_attempts:
        return ManifestRevisionReason.ATTEMPT_HISTORY_APPENDED
    if predecessor.assignment != successor.assignment:
        return ManifestRevisionReason.ASSIGNMENT_METADATA_CHANGED
    return ManifestRevisionReason.NATIVE_SOURCE_CHANGED


def plan_manifest_revision(
    candidate_manifest: AcademicResultManifest,
    *,
    predecessor_manifest: AcademicResultManifest | None = None,
    predecessor_manifest_bytes: bytes | None = None,
    allocated_revisions: Iterable[int] = (),
    historical_manifests: Iterable[AcademicResultManifest] = (),
    republish_after_withdrawal: bool = False,
) -> ManifestRevisionPlan:
    """Plan exact replay, an initial revision, or an append-safe successor.

    ``candidate_manifest`` represents the complete proposed immutable revision.
    Its revision must be the normal producer allocation for new bytes.  Exact
    replay may supply a candidate that differs only in revision/generated time;
    the returned plan still selects and returns the predecessor's exact bytes.
    """

    candidate = _production_manifest(candidate_manifest, "candidate_manifest")
    revisions = _allocated_revision_tuple(allocated_revisions)
    if not isinstance(republish_after_withdrawal, bool):
        _validation_error("republish_after_withdrawal must be a Boolean.")
    try:
        history = tuple(historical_manifests)
    except TypeError as error:
        raise ScoreFormPublicationRevisionPolicyValidationError(
            "historical_manifests must be an iterable of manifests."
        ) from error
    validated_history = tuple(
        _production_manifest(item, "historical_manifests item") for item in history
    )

    if predecessor_manifest is None:
        if revisions:
            raise ManifestRevisionAllocationError(
                "A series with allocated revisions cannot be planned as initial."
            )
        if predecessor_manifest_bytes is not None or validated_history:
            _validation_error(
                "Initial planning cannot include predecessor bytes or history."
            )
        if republish_after_withdrawal:
            _validation_error(
                "Republication after withdrawal requires a predecessor revision."
            )
        if candidate.record_set.revision != 1:
            raise ManifestRevisionAllocationError(
                "The first durable producer manifest must use revision 1."
            )
        return ManifestRevisionPlan(
            ManifestRevisionDisposition.CREATE_INITIAL,
            ManifestRevisionReason.INITIAL_PUBLICATION,
            1,
            SCOREFORM_ACADEMIC_RESULT_RECORD_SET_ID,
        )

    predecessor = _production_manifest(predecessor_manifest, "predecessor_manifest")
    if predecessor.record_set.revision not in revisions:
        raise ManifestRevisionAllocationError(
            "allocated_revisions must include the predecessor revision."
        )
    if predecessor.record_set.revision != max(revisions):
        raise ManifestRevisionAllocationError(
            "Revision planning must use the greatest allocated producer revision "
            "as its predecessor."
        )

    ordered_history = tuple(
        sorted(validated_history, key=lambda item: item.record_set.revision)
    )
    historical_revisions = tuple(
        historical.record_set.revision for historical in ordered_history
    )
    if len(set(historical_revisions)) != len(historical_revisions):
        raise ManifestRevisionAllocationError(
            "historical_manifests must contain unique revisions."
        )
    for historical in ordered_history:
        if (
            historical.work != predecessor.work
            or historical.record_set.record_set_id
            != predecessor.record_set.record_set_id
        ):
            raise ManifestRevisionTransitionError(
                "Historical manifests must belong to the same complete series."
            )
        if historical.record_set.revision not in revisions:
            raise ManifestRevisionAllocationError(
                "Every historical manifest revision must be allocated."
            )
        if historical.record_set.revision >= predecessor.record_set.revision:
            raise ManifestRevisionAllocationError(
                "Historical manifest revisions must be lower than the predecessor."
            )

    same_content = manifests_have_same_publication_content(candidate, predecessor)
    if same_content and not republish_after_withdrawal:
        existing_bytes = _validated_existing_bytes(
            predecessor, predecessor_manifest_bytes
        )
        return ManifestRevisionPlan(
            ManifestRevisionDisposition.REUSE_EXISTING,
            ManifestRevisionReason.EXACT_REPLAY,
            predecessor.record_set.revision,
            SCOREFORM_ACADEMIC_RESULT_RECORD_SET_ID,
            existing_bytes,
        )

    next_revision = next_record_set_revision(revisions)
    if candidate.record_set.revision in revisions:
        raise ManifestRevisionReplayConflictError(
            "An allocated logical revision cannot be reused for different bytes."
        )
    if candidate.record_set.revision != next_revision:
        raise ManifestRevisionAllocationError(
            f"Normal successor allocation must use revision {next_revision}."
        )
    transition = validate_manifest_revision_transition(predecessor, candidate)
    reason = (
        ManifestRevisionReason.REPUBLICATION_AFTER_WITHDRAWAL
        if republish_after_withdrawal
        else _plan_reason(predecessor, candidate, transition, ordered_history)
    )
    return ManifestRevisionPlan(
        ManifestRevisionDisposition.CREATE_SUCCESSOR,
        reason,
        next_revision,
        SCOREFORM_ACADEMIC_RESULT_RECORD_SET_ID,
    )


def require_publication_supersession(
    predecessor: AcademicResultManifest,
    successor: AcademicResultManifest,
    *,
    expected_current_publication_id: str,
) -> PublicationSupersessionRequirement:
    """Bind a valid successor to one explicit expected Core series head."""

    before = _production_manifest(predecessor, "predecessor")
    after = _production_manifest(successor, "successor")
    validate_manifest_revision_transition(before, after)
    if (
        not isinstance(expected_current_publication_id, str)
        or not expected_current_publication_id
        or expected_current_publication_id != expected_current_publication_id.strip()
    ):
        _validation_error(
            "expected_current_publication_id must be nonempty and trimmed."
        )
    return PublicationSupersessionRequirement(
        expected_current_publication_id,
        SCOREFORM_ACADEMIC_RESULT_PUBLICATION_KIND,
        SCOREFORM_ACADEMIC_RESULT_RECORD_SET_ID,
        before.record_set.revision,
        after.record_set.revision,
    )


def plan_missing_manifest_recovery(
    *, recorded_sha256: str, trusted_exact_bytes: bytes | None
) -> ManifestRecoveryPlan:
    """Select exact restoration or withdrawal plus a later successor.

    A digest match permits restoration of only the supplied exact bytes.  When
    no trusted bytes exist, the old revision remains consumed and different
    reconstruction bytes are never authorized under its path.
    """

    if not isinstance(recorded_sha256, str) or _SHA256.fullmatch(recorded_sha256) is None:
        raise ManifestRecoveryError(
            "recorded_sha256 must be a lowercase SHA-256 digest."
        )
    if trusted_exact_bytes is None:
        return ManifestRecoveryPlan(
            ManifestRecoveryDisposition.WITHDRAW_AND_CREATE_SUCCESSOR, None
        )
    if not isinstance(trusted_exact_bytes, bytes) or not trusted_exact_bytes:
        raise ManifestRecoveryError(
            "trusted_exact_bytes must be nonempty immutable bytes when supplied."
        )
    if hashlib.sha256(trusted_exact_bytes).hexdigest() != recorded_sha256:
        raise ManifestRecoveryError(
            "Trusted recovery bytes do not reproduce the recorded digest."
        )
    return ManifestRecoveryPlan(
        ManifestRecoveryDisposition.RESTORE_EXACT_BYTES, trusted_exact_bytes
    )


__all__ = [
    "SCOREFORM_ACADEMIC_RESULT_PUBLICATION_KIND",
    "SCOREFORM_ACADEMIC_RESULT_RECORD_SET_ID",
    "ManifestAttemptIdentity",
    "ManifestRecoveryDisposition",
    "ManifestRecoveryError",
    "ManifestRecoveryPlan",
    "ManifestRevisionAllocationError",
    "ManifestRevisionDisposition",
    "ManifestRevisionPlan",
    "ManifestRevisionReason",
    "ManifestRevisionReplayConflictError",
    "ManifestRevisionTransition",
    "ManifestRevisionTransitionError",
    "PublicationSupersessionRequirement",
    "ScoreFormPublicationRevisionPolicyError",
    "ScoreFormPublicationRevisionPolicyValidationError",
    "manifests_have_same_publication_content",
    "next_record_set_revision",
    "plan_manifest_revision",
    "plan_missing_manifest_recovery",
    "require_publication_supersession",
    "validate_manifest_revision_transition",
]
