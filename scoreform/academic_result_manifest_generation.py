"""Immutable workspace generation for ScoreForm Academic Result Manifest v1."""

from __future__ import annotations

import datetime as dt
import hashlib
import os
import stat
from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from pds_core.routing_models import ModuleWorkRef, validate_module_work_ref
from pds_core.standards import load_workspace_standards_library

from scoreform.academic_result_manifest import (
    CONTRACT_VERSION,
    PRODUCER_MODULE_ID,
    RECORD_TYPE,
    ROUTED_RESULTS_SCHEMA_VERSION,
    AcademicResultManifest,
    AssignmentSnapshot,
    AssignmentSourceSnapshot,
    Attempt,
    AttemptProvenance,
    Pds2ScanProvenance,
    PlainPaperManualProvenance,
    Question,
    RecordSet,
    Response,
    ResultsHistorySourceSnapshot,
    ReviewReference,
    ScanReviewManualProvenance,
    SourceSnapshot,
    StudentResults,
    WorkReference,
    manifest_from_json_bytes,
    manifest_to_canonical_json_bytes,
)
from scoreform.assignment import (
    assignment_from_json_bytes,
    validate_assignment_standard_alignments,
)
from scoreform.page_scoring import ScoredAnswer
from scoreform.pds_contract import SCOREFORM_MODULE_ID
from scoreform.publication_revision_policy import (
    SCOREFORM_ACADEMIC_RESULT_RECORD_SET_ID,
    ManifestRevisionDisposition,
    ManifestRevisionReason,
    next_record_set_revision,
    plan_manifest_revision,
)
from scoreform.results import (
    ScoreFormRoutedResultHistoryRow,
    routed_results_history_from_csv_bytes,
)
from scoreform.retained_page import (
    validate_canonical_retained_source_relative_path,
)
from scoreform.work_paths import (
    academic_result_manifest_relative_path,
    academic_result_manifest_revision_path,
    scoreform_work_paths,
    scoreform_work_ref,
)


class ScoreFormManifestGenerationError(Exception):
    """Base error for manifest generation and storage."""


class ScoreFormManifestGenerationValidationError(ScoreFormManifestGenerationError):
    """Generation inputs or native content are invalid."""


class ScoreFormManifestGenerationNotFoundError(ScoreFormManifestGenerationError):
    """Required managed state does not exist."""


class ScoreFormManifestGenerationConflictError(ScoreFormManifestGenerationError):
    """A concurrent operation or immutable target conflicts."""


class ScoreFormManifestGenerationIntegrityError(ScoreFormManifestGenerationError):
    """Durable or retained evidence contradicts its recorded identity."""


class ScoreFormManifestGenerationWriteError(ScoreFormManifestGenerationError):
    """Immutable storage could not be completed safely."""


@dataclass(frozen=True, slots=True)
class ManifestGenerationPartialSuccessState:
    operation: str
    work: ModuleWorkRef
    revision: int
    path: Path
    relative_path: str
    expected_sha256: str | None
    durable_file_exists: bool
    cleanup_failure: str | None = None


class ScoreFormManifestGenerationPartialSuccessError(
    ScoreFormManifestGenerationWriteError
):
    """A revision is durable but final verification or cleanup failed."""

    def __init__(self, message: str, state: ManifestGenerationPartialSuccessState):
        super().__init__(message)
        self.state = state


class _DurableRevisionWriteError(Exception):
    """Internal signal that file durability preceded a later write-stage failure."""


@dataclass(frozen=True, slots=True)
class NativeFileByteSnapshot:
    relative_path: str
    path: Path
    content: bytes
    sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.relative_path, str) or not self.relative_path:
            raise ScoreFormManifestGenerationValidationError(
                "Native snapshot relative_path must be nonempty."
            )
        if not isinstance(self.path, Path) or not isinstance(self.content, bytes):
            raise ScoreFormManifestGenerationValidationError(
                "Native snapshot path or content has the wrong type."
            )
        if self.sha256 != hashlib.sha256(self.content).hexdigest():
            raise ScoreFormManifestGenerationIntegrityError(
                "Native snapshot digest disagrees with its exact bytes."
            )


@dataclass(frozen=True, slots=True)
class AcademicResultManifestGenerationContext:
    work: ModuleWorkRef
    assignment_source: NativeFileByteSnapshot
    results_source: NativeFileByteSnapshot
    assignment: AssignmentSnapshot
    students: tuple[StudentResults, ...]

    def __post_init__(self) -> None:
        validate_module_work_ref(self.work)
        if self.work.module_id != SCOREFORM_MODULE_ID:
            raise ScoreFormManifestGenerationValidationError(
                'work.module_id must be "scoreform".'
            )
        if not isinstance(self.assignment_source, NativeFileByteSnapshot) or not isinstance(
            self.results_source, NativeFileByteSnapshot
        ):
            raise ScoreFormManifestGenerationValidationError(
                "Generation sources have the wrong model type."
            )
        object.__setattr__(self, "students", tuple(self.students))
        if any(not isinstance(item, StudentResults) for item in self.students):
            raise ScoreFormManifestGenerationValidationError(
                "Generation students contain the wrong model type."
            )


@dataclass(frozen=True, slots=True)
class StoredAcademicResultManifest:
    manifest: AcademicResultManifest
    revision: int
    path: Path
    relative_path: str
    content: bytes
    sha256: str

    def __post_init__(self) -> None:
        _validate_stored_value(self)


@dataclass(frozen=True, slots=True)
class AcademicResultManifestGenerationResult:
    disposition: ManifestRevisionDisposition
    reason: ManifestRevisionReason
    manifest: AcademicResultManifest
    revision: int
    path: Path
    relative_path: str
    content: bytes
    sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.disposition, ManifestRevisionDisposition) or not isinstance(
            self.reason, ManifestRevisionReason
        ):
            raise ScoreFormManifestGenerationValidationError(
                "Generation result disposition or reason has the wrong type."
            )
        _validate_stored_value(self)


def _validate_stored_value(value: object) -> None:
    manifest = getattr(value, "manifest", None)
    revision = getattr(value, "revision", None)
    path = getattr(value, "path", None)
    relative_path = getattr(value, "relative_path", None)
    content = getattr(value, "content", None)
    digest = getattr(value, "sha256", None)
    if (
        not isinstance(manifest, AcademicResultManifest)
        or isinstance(revision, bool)
        or not isinstance(revision, int)
        or revision < 1
        or not isinstance(path, Path)
        or not isinstance(relative_path, str)
        or not isinstance(content, bytes)
    ):
        raise ScoreFormManifestGenerationValidationError(
            "Stored manifest value contains invalid typed fields."
        )
    try:
        decoded = manifest_from_json_bytes(content)
        canonical = manifest_to_canonical_json_bytes(decoded)
    except Exception as error:
        raise ScoreFormManifestGenerationIntegrityError(
            "Stored manifest bytes are invalid."
        ) from error
    work = ModuleWorkRef(
        manifest.work.module_id,
        manifest.work.class_id,
        manifest.work.work_id,
    )
    expected_relative = academic_result_manifest_relative_path(work, revision)
    if (
        decoded != manifest
        or canonical != content
        or revision != manifest.record_set.revision
        or digest != hashlib.sha256(content).hexdigest()
        or Path(relative_path).name != f"{revision}.json"
        or path.name != f"{revision}.json"
        or relative_path != expected_relative
    ):
        raise ScoreFormManifestGenerationIntegrityError(
            "Stored manifest fields do not agree."
        )


def _validated_scoreform_work(work_ref: object) -> ModuleWorkRef:
    try:
        work = validate_module_work_ref(work_ref)
    except Exception as error:
        raise ScoreFormManifestGenerationValidationError(
            "work_ref must be a valid ModuleWorkRef."
        ) from error
    if work.module_id != SCOREFORM_MODULE_ID:
        raise ScoreFormManifestGenerationValidationError(
            'work_ref.module_id must be "scoreform".'
        )
    return work


def _snapshot_regular_file(
    path: Path,
    *,
    relative_path: str,
    missing_message: str,
) -> NativeFileByteSnapshot:
    if path.is_symlink():
        raise ScoreFormManifestGenerationValidationError(
            f"{relative_path} must not be a symbolic link."
        )
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError as error:
        raise ScoreFormManifestGenerationNotFoundError(missing_message) from error
    except OSError as error:
        raise ScoreFormManifestGenerationValidationError(
            f"Could not open {relative_path} as exact bytes."
        ) from error
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ScoreFormManifestGenerationValidationError(
                f"{relative_path} must be a regular file."
            )
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
    except OSError as error:
        raise ScoreFormManifestGenerationValidationError(
            f"Could not read stable exact bytes from {relative_path}."
        ) from error
    finally:
        os.close(descriptor)
    if (
        before.st_dev != after.st_dev
        or before.st_ino != after.st_ino
        or before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
    ):
        raise ScoreFormManifestGenerationConflictError(
            f"{relative_path} changed while its snapshot was read."
        )
    content = b"".join(chunks)
    if len(content) != before.st_size:
        raise ScoreFormManifestGenerationConflictError(
            f"{relative_path} changed while its snapshot was read."
        )
    return NativeFileByteSnapshot(
        relative_path=relative_path,
        path=path,
        content=content,
        sha256=hashlib.sha256(content).hexdigest(),
    )


def snapshot_native_file_bytes(
    path: str | Path,
    *,
    relative_path: str,
) -> NativeFileByteSnapshot:
    """Read one exact nonsymlink regular file into an immutable snapshot."""
    return _snapshot_regular_file(
        Path(path),
        relative_path=relative_path,
        missing_message=f"Required native source {relative_path} was not found.",
    )


def verify_native_sources_unchanged(
    assignment_snapshot: NativeFileByteSnapshot,
    results_snapshot: NativeFileByteSnapshot,
) -> None:
    """Re-read both native files and require their exact snapshot bytes."""
    if not isinstance(assignment_snapshot, NativeFileByteSnapshot) or not isinstance(
        results_snapshot, NativeFileByteSnapshot
    ):
        raise ScoreFormManifestGenerationValidationError(
            "Native source verification requires immutable byte snapshots."
        )
    if (
        assignment_snapshot.relative_path != "assignment.json"
        or results_snapshot.relative_path != "results.csv"
        or assignment_snapshot.path.name != "assignment.json"
        or results_snapshot.path.name != "results.csv"
        or assignment_snapshot.path.parent != results_snapshot.path.parent
    ):
        raise ScoreFormManifestGenerationValidationError(
            "Native source snapshots do not identify one canonical managed work root."
        )
    work_root = assignment_snapshot.path.parent
    if work_root.is_symlink() or not work_root.is_dir():
        raise ScoreFormManifestGenerationConflictError(
            "Managed work root changed before final native-source verification."
        )
    try:
        resolved_work_root = work_root.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise ScoreFormManifestGenerationConflictError(
            "Managed work root changed before final native-source verification."
        ) from error
    for original in (assignment_snapshot, results_snapshot):
        try:
            current = snapshot_native_file_bytes(
                original.path,
                relative_path=original.relative_path,
            )
        except ScoreFormManifestGenerationConflictError:
            raise
        except ScoreFormManifestGenerationError as error:
            raise ScoreFormManifestGenerationConflictError(
                f"{original.relative_path} changed before manifest completion."
            ) from error
        try:
            resolved_source = current.path.resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as error:
            raise ScoreFormManifestGenerationConflictError(
                "A native source escaped its managed work root before final verification."
            ) from error
        if resolved_source.parent != resolved_work_root:
            raise ScoreFormManifestGenerationConflictError(
                "A native source escaped its managed work root before final verification."
            )
        if current.content != original.content or current.sha256 != original.sha256:
            raise ScoreFormManifestGenerationConflictError(
                f"{original.relative_path} changed before manifest completion."
            )


def _run_prewrite_verification_hook(
    context: AcademicResultManifestGenerationContext,
) -> None:
    """No-op seam for deterministic tests at the planning/verification boundary."""


def _assignment_snapshot(
    assignment: Mapping[str, object],
    *,
    workspace_root: Path,
    work: ModuleWorkRef,
) -> AssignmentSnapshot:
    assignment_id = assignment.get("assignment_id")
    title = assignment.get("title")
    count = assignment.get("question_count")
    layout_id = assignment.get("layout_id")
    choices_value = assignment.get("choices")
    profile = assignment.get("standards_profile_id")
    standards = assignment.get("standards", {})
    if (
        not isinstance(assignment_id, str)
        or not isinstance(title, str)
        or isinstance(count, bool)
        or not isinstance(count, int)
        or not isinstance(layout_id, str)
        or not isinstance(choices_value, list)
        or any(not isinstance(choice, str) for choice in choices_value)
        or (profile is not None and not isinstance(profile, str))
        or not isinstance(standards, Mapping)
    ):
        raise ScoreFormManifestGenerationValidationError(
            "Validated assignment contains unexpected typed values."
        )
    choices = tuple(choices_value)
    if assignment_id != work.work_id:
        raise ScoreFormManifestGenerationValidationError(
            "Managed work identity disagrees with assignment.json."
        )
    if profile is not None or any(bool(value) for value in standards.values()):
        try:
            alignments = validate_assignment_standard_alignments(
                assignment,
                load_workspace_standards_library(workspace_root),
            )
        except Exception as error:
            raise ScoreFormManifestGenerationValidationError(
                "Assignment standards do not match the current standards library."
            ) from error
    else:
        alignments = {number: () for number in range(1, count + 1)}
    return AssignmentSnapshot(
        assignment_id=assignment_id,
        title=title,
        question_count=count,
        layout_id=layout_id,
        choices=choices,
        total_points=count,
        standards_profile_id=profile,
        questions=tuple(
            Question(number, 1, tuple(alignments[number]))
            for number in range(1, count + 1)
        ),
    )


def _retained_source_digest(
    workspace_root: Path,
    relative_path: str,
    expected_digest: str,
    cache: dict[str, str],
) -> None:
    try:
        validated = validate_canonical_retained_source_relative_path(relative_path)
    except Exception as error:
        raise ScoreFormManifestGenerationValidationError(
            "PDS2 retained_source_path is unsafe or unsupported."
        ) from error
    prior = cache.get(validated)
    if prior is not None:
        if prior != expected_digest:
            raise ScoreFormManifestGenerationIntegrityError(
                "Repeated retained-source path has contradictory digest claims."
            )
        return
    path = workspace_root.joinpath(*validated.split("/"))
    try:
        root = (workspace_root / "scans" / "source").resolve(strict=True)
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError) as error:
        raise ScoreFormManifestGenerationNotFoundError(
            "A retained PDS2 source is missing or outside the retained-source root."
        ) from error
    snapshot = _snapshot_regular_file(
        path,
        relative_path=validated,
        missing_message="A retained PDS2 source was not found.",
    )
    if snapshot.sha256 != expected_digest:
        raise ScoreFormManifestGenerationIntegrityError(
            "Retained PDS2 source bytes do not match the recorded SHA-256."
        )
    cache[validated] = expected_digest


def _response(answer: ScoredAnswer, choices: tuple[str, ...]) -> Response:
    selected = answer.selected_answer
    if selected == "BLANK":
        if answer.correct:
            raise ScoreFormManifestGenerationIntegrityError(
                "A blank historical response cannot be recorded as correct."
            )
        return Response(answer.question_number, "blank", None, False)
    if selected == "AMBIGUOUS":
        if answer.correct:
            raise ScoreFormManifestGenerationIntegrityError(
                "An ambiguous historical response cannot be recorded as correct."
            )
        return Response(answer.question_number, "ambiguous", None, False)
    if selected not in choices:
        raise ScoreFormManifestGenerationValidationError(
            "A historical selected response is not a current assignment choice."
        )
    return Response(answer.question_number, "selected", selected, answer.correct)


def _attempt(
    row: ScoreFormRoutedResultHistoryRow,
    *,
    assignment: AssignmentSnapshot,
    workspace_root: Path,
    retained_cache: dict[str, str],
) -> Attempt:
    result = row.result
    if result.class_id == "" or result.assignment_id == "":
        raise ScoreFormManifestGenerationValidationError(
            "Result history contains an incomplete work identity."
        )
    if result.total_points != assignment.question_count:
        raise ScoreFormManifestGenerationIntegrityError(
            "Existing results cannot be reinterpreted under the changed assignment structure."
        )
    try:
        recorded_at = dt.datetime.fromisoformat(row.scan_timestamp)
    except ValueError as error:
        raise ScoreFormManifestGenerationValidationError(
            "Result history contains an invalid timestamp."
        ) from error
    responses = tuple(_response(answer, assignment.choices) for answer in result.answers)
    if result.result_origin == "pds2_scan":
        assert result.retained_source_relative_path is not None
        assert result.source_sha256 is not None
        _retained_source_digest(
            workspace_root,
            result.retained_source_relative_path,
            result.source_sha256,
            retained_cache,
        )
        assert result.issuance_id is not None
        assert result.generation_id is not None
        assert result.artifact_id is not None
        assert result.source_scan_id is not None
        provenance: AttemptProvenance = Pds2ScanProvenance(
            issuance_id=result.issuance_id,
            generation_id=result.generation_id,
            artifact_id=result.artifact_id,
            page_ids=result.page_ids,
            route_ids=result.route_ids,
            logical_pages=result.logical_pages,
            source_scan_id=result.source_scan_id,
            source_page_numbers=result.source_page_numbers,
            retained_source_path=result.retained_source_relative_path,
            source_sha256=result.source_sha256,
        )
    elif result.result_origin == "plain_paper_manual":
        provenance = PlainPaperManualProvenance()
    else:
        prefix = "scan_review_manual:"
        provenance = ScanReviewManualProvenance(
            ReviewReference(result.source_file[len(prefix) :])
        )
    return Attempt(
        attempt_number=row.attempt_number,
        result_origin=result.result_origin,
        recorded_at=recorded_at,
        points_earned=result.score,
        points_possible=result.total_points,
        responses=responses,
        provenance=provenance,
    )


def _students(
    rows: tuple[ScoreFormRoutedResultHistoryRow, ...],
    *,
    assignment: AssignmentSnapshot,
    work: ModuleWorkRef,
    workspace_root: Path,
) -> tuple[StudentResults, ...]:
    grouped: dict[str, list[Attempt]] = defaultdict(list)
    retained_cache: dict[str, str] = {}
    identities: set[tuple[str, int]] = set()
    for row in rows:
        result = row.result
        if result.class_id != work.class_id or result.assignment_id != work.work_id:
            raise ScoreFormManifestGenerationIntegrityError(
                "Result history mixes work identities."
            )
        identity = (result.student_id, row.attempt_number)
        if identity in identities:
            raise ScoreFormManifestGenerationIntegrityError(
                "Result history repeats a student attempt identity."
            )
        identities.add(identity)
        grouped[result.student_id].append(
            _attempt(
                row,
                assignment=assignment,
                workspace_root=workspace_root,
                retained_cache=retained_cache,
            )
        )
    return tuple(
        StudentResults(student_id, tuple(sorted(attempts, key=lambda item: item.attempt_number)))
        for student_id, attempts in sorted(grouped.items())
    )


def _verify_retained_evidence_unchanged(
    context: AcademicResultManifestGenerationContext,
    *,
    workspace_root: Path,
) -> None:
    """Revalidate exact PDS2 retained bytes immediately before native verification."""
    cache: dict[str, str] = {}
    for student in context.students:
        for attempt in student.attempts:
            provenance = attempt.provenance
            if isinstance(provenance, Pds2ScanProvenance):
                _retained_source_digest(
                    workspace_root,
                    provenance.retained_source_path,
                    provenance.source_sha256,
                    cache,
                )


def load_academic_result_manifest_generation_context(
    workspace_root: str | Path,
    work_ref: ModuleWorkRef,
) -> AcademicResultManifestGenerationContext:
    """Validate managed native sources and return the immutable pure-build context."""
    root = Path(workspace_root)
    work = _validated_scoreform_work(work_ref)
    paths = scoreform_work_paths(root, work.class_id, work.work_id)
    if paths.work_root.is_symlink() or not paths.work_root.is_dir():
        raise ScoreFormManifestGenerationNotFoundError(
            "Managed ScoreForm assignment does not exist."
        )
    try:
        paths.work_root.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, RuntimeError, ValueError) as error:
        raise ScoreFormManifestGenerationValidationError(
            "Managed ScoreForm assignment escapes the workspace."
        ) from error
    assignment_source = snapshot_native_file_bytes(
        paths.assignment_path,
        relative_path="assignment.json",
    )
    results_source = snapshot_native_file_bytes(
        paths.results_path,
        relative_path="results.csv",
    )
    try:
        native_assignment = assignment_from_json_bytes(assignment_source.content)
        result_rows = routed_results_history_from_csv_bytes(results_source.content)
    except ScoreFormManifestGenerationError:
        raise
    except Exception as error:
        raise ScoreFormManifestGenerationValidationError(
            "Native assignment or schema-v2 result history is invalid."
        ) from error
    assignment = _assignment_snapshot(
        native_assignment,
        workspace_root=root,
        work=work,
    )
    students = _students(
        result_rows,
        assignment=assignment,
        work=work,
        workspace_root=root,
    )
    return AcademicResultManifestGenerationContext(
        work=work,
        assignment_source=assignment_source,
        results_source=results_source,
        assignment=assignment,
        students=students,
    )


def build_academic_result_manifest(
    context: AcademicResultManifestGenerationContext,
    *,
    record_set_revision: int,
    generated_at: dt.datetime,
) -> AcademicResultManifest:
    """Purely construct the complete validated manifest from immutable context."""
    if not isinstance(context, AcademicResultManifestGenerationContext):
        raise ScoreFormManifestGenerationValidationError(
            "context has the wrong model type."
        )
    return AcademicResultManifest(
        record_type=RECORD_TYPE,
        contract_version=CONTRACT_VERSION,
        producer_module_id=PRODUCER_MODULE_ID,
        generated_at=generated_at,
        record_set=RecordSet(
            SCOREFORM_ACADEMIC_RESULT_RECORD_SET_ID,
            record_set_revision,
        ),
        work=WorkReference(
            context.work.module_id,
            context.work.class_id,
            context.work.work_id,
        ),
        source_snapshot=SourceSnapshot(
            AssignmentSourceSnapshot(
                context.assignment_source.relative_path,
                context.assignment_source.sha256,
            ),
            ResultsHistorySourceSnapshot(
                context.results_source.relative_path,
                context.results_source.sha256,
                ROUTED_RESULTS_SCHEMA_VERSION,
            ),
        ),
        assignment=context.assignment,
        students=tuple(context.students),
    )


def build_academic_result_manifest_bytes(
    context: AcademicResultManifestGenerationContext,
    *,
    record_set_revision: int,
    generated_at: dt.datetime,
) -> bytes:
    """Purely construct and canonically serialize one manifest revision."""
    return manifest_to_canonical_json_bytes(
        build_academic_result_manifest(
            context,
            record_set_revision=record_set_revision,
            generated_at=generated_at,
        )
    )


def _canonical_revision_name(name: str) -> int | None:
    if not name.endswith(".json"):
        return None
    stem = name[:-5]
    if not stem.isdecimal() or stem == "0" or str(int(stem)) != stem:
        return None
    return int(stem)


def _load_history(
    workspace_root: Path,
    work_ref: ModuleWorkRef,
    *,
    allow_lock: bool,
) -> tuple[StoredAcademicResultManifest, ...]:
    paths = scoreform_work_paths(
        workspace_root, work_ref.class_id, work_ref.work_id
    )
    directory = paths.academic_result_manifests_dir
    if not directory.exists():
        return ()
    if directory.is_symlink() or not directory.is_dir():
        raise ScoreFormManifestGenerationIntegrityError(
            "Academic-result manifest history must be a nonsymlink directory."
        )
    stored: list[StoredAcademicResultManifest] = []
    for entry in sorted(directory.iterdir(), key=lambda item: item.name):
        if allow_lock and entry.name == ".write.lock":
            continue
        revision = _canonical_revision_name(entry.name)
        if revision is None:
            raise ScoreFormManifestGenerationIntegrityError(
                "Manifest history contains an unexpected or noncanonical entry."
            )
        if entry.is_symlink() or not entry.is_file():
            raise ScoreFormManifestGenerationIntegrityError(
                "Manifest revision must be a nonsymlink regular file."
            )
        try:
            content = entry.read_bytes()
            manifest = manifest_from_json_bytes(content)
            canonical = manifest_to_canonical_json_bytes(manifest)
        except Exception as error:
            raise ScoreFormManifestGenerationIntegrityError(
                f"Manifest revision {revision} is invalid."
            ) from error
        if canonical != content:
            raise ScoreFormManifestGenerationIntegrityError(
                f"Manifest revision {revision} does not contain canonical bytes."
            )
        if (
            manifest.record_set.record_set_id
            != SCOREFORM_ACADEMIC_RESULT_RECORD_SET_ID
            or manifest.record_set.revision != revision
            or manifest.work.module_id != work_ref.module_id
            or manifest.work.class_id != work_ref.class_id
            or manifest.work.work_id != work_ref.work_id
        ):
            raise ScoreFormManifestGenerationIntegrityError(
                f"Manifest revision {revision} disagrees with its series or path."
            )
        stored.append(
            StoredAcademicResultManifest(
                manifest=manifest,
                revision=revision,
                path=entry,
                relative_path=academic_result_manifest_relative_path(
                    work_ref, revision
                ),
                content=content,
                sha256=hashlib.sha256(content).hexdigest(),
            )
        )
    revisions = tuple(item.revision for item in stored)
    if len(revisions) != len(set(revisions)):
        raise ScoreFormManifestGenerationIntegrityError(
            "Manifest history contains duplicate revisions."
        )
    return tuple(sorted(stored, key=lambda item: item.revision))


def list_academic_result_manifest_revisions(
    workspace_root: str | Path,
    work_ref: ModuleWorkRef,
) -> tuple[StoredAcademicResultManifest, ...]:
    """Read and strictly validate every durable revision in one series."""
    work = _validated_scoreform_work(work_ref)
    return _load_history(Path(workspace_root), work, allow_lock=False)


def load_academic_result_manifest_revision(
    workspace_root: str | Path,
    work_ref: ModuleWorkRef,
    revision: int,
) -> StoredAcademicResultManifest:
    """Read and validate one exact revision while also validating its history."""
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise ScoreFormManifestGenerationValidationError(
            "revision must be a positive integer."
        )
    for stored in list_academic_result_manifest_revisions(workspace_root, work_ref):
        if stored.revision == revision:
            return stored
    raise ScoreFormManifestGenerationNotFoundError(
        f"Academic-result manifest revision {revision} was not found."
    )


def validate_academic_result_manifest_revision(
    workspace_root: str | Path,
    work_ref: ModuleWorkRef,
    revision: int,
) -> StoredAcademicResultManifest:
    """Read-only validation alias for one exact immutable revision."""
    return load_academic_result_manifest_revision(
        workspace_root, work_ref, revision
    )


def _acquire_lock(directory: Path) -> tuple[int, Path]:
    try:
        work_root = directory.parents[2]
        for candidate in (
            directory.parents[1],
            directory.parent,
            directory,
        ):
            if candidate.is_symlink() or (
                candidate.exists() and not candidate.is_dir()
            ):
                raise ScoreFormManifestGenerationConflictError(
                    "Manifest generation path contains an unsafe filesystem entry."
                )
            candidate.mkdir(exist_ok=True)
        directory.resolve(strict=True).relative_to(work_root.resolve(strict=True))
    except ScoreFormManifestGenerationError:
        raise
    except (OSError, RuntimeError, ValueError) as error:
        raise ScoreFormManifestGenerationWriteError(
            "Could not establish a contained manifest generation directory."
        ) from error
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise ScoreFormManifestGenerationWriteError(
            "Could not create the manifest generation lock directory."
        ) from error
    if directory.is_symlink() or not directory.is_dir():
        raise ScoreFormManifestGenerationConflictError(
            "Manifest generation directory is not a safe directory."
        )
    lock_path = directory / ".write.lock"
    try:
        descriptor = os.open(
            lock_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
            0o600,
        )
    except FileExistsError as error:
        raise ScoreFormManifestGenerationConflictError(
            "Another manifest generation operation holds .write.lock."
        ) from error
    except OSError as error:
        raise ScoreFormManifestGenerationWriteError(
            "Could not create the manifest generation lock."
        ) from error
    return descriptor, lock_path


def _sync_directory(directory: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_new_revision(path: Path, content: bytes) -> None:
    descriptor: int | None = None
    created = False
    durable = False
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
            0o600,
        )
        created = True
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            descriptor = None
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        durable = True
        _sync_directory(path.parent)
    except FileExistsError as error:
        raise ScoreFormManifestGenerationConflictError(
            "The planned immutable manifest revision already exists."
        ) from error
    except Exception as error:
        cleanup_error: OSError | None = None
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if created and not durable:
            try:
                path.unlink()
            except OSError as caught:
                cleanup_error = caught
        if durable:
            raise _DurableRevisionWriteError(
                "Manifest file is durable but containing-directory sync failed."
            ) from error
        write_error = ScoreFormManifestGenerationWriteError(
            "Could not durably create the immutable manifest revision"
            + (
                "; incomplete-file cleanup also failed."
                if cleanup_error is not None
                else "."
            )
        )
        setattr(write_error, "cleanup_failure", cleanup_error)
        raise write_error from error


def _clock_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def generate_academic_result_manifest(
    workspace_root: str | Path,
    class_id: str,
    assignment_id: str,
    *,
    republish_after_withdrawal: bool = False,
    clock: Callable[[], dt.datetime] = _clock_now,
) -> AcademicResultManifestGenerationResult:
    """Generate/replay one revision under the producer-owned exclusive lock."""
    if not isinstance(republish_after_withdrawal, bool):
        raise ScoreFormManifestGenerationValidationError(
            "republish_after_withdrawal must be a Boolean."
        )
    if not callable(clock):
        raise ScoreFormManifestGenerationValidationError("clock must be callable.")
    root = Path(workspace_root)
    try:
        work = scoreform_work_ref(class_id, assignment_id)
        paths = scoreform_work_paths(root, class_id, assignment_id)
    except Exception as error:
        raise ScoreFormManifestGenerationValidationError(
            "class_id and assignment_id must be safe identifiers."
        ) from error
    if paths.work_root.is_symlink() or not paths.work_root.is_dir():
        raise ScoreFormManifestGenerationNotFoundError(
            "Managed ScoreForm assignment does not exist."
        )
    lock_descriptor, lock_path = _acquire_lock(paths.academic_result_manifests_dir)
    operation_error: BaseException | None = None
    durable_path: Path | None = None
    durable_revision: int | None = None
    expected_digest: str | None = None
    try:
        os.close(lock_descriptor)
        history = _load_history(root, work, allow_lock=True)
        revisions = tuple(item.revision for item in history)
        predecessor = history[-1] if history else None
        context = load_academic_result_manifest_generation_context(root, work)
        revision = next_record_set_revision(revisions)
        generated_at = predecessor.manifest.generated_at if predecessor else clock()
        if (
            not isinstance(generated_at, dt.datetime)
            or generated_at.tzinfo is None
            or generated_at.utcoffset() is None
        ):
            raise ScoreFormManifestGenerationValidationError(
                "clock must return a timezone-aware datetime."
            )
        candidate = build_academic_result_manifest(
            context,
            record_set_revision=revision,
            generated_at=generated_at,
        )
        candidate_bytes = manifest_to_canonical_json_bytes(candidate)
        plan = plan_manifest_revision(
            candidate,
            predecessor_manifest=(predecessor.manifest if predecessor else None),
            predecessor_manifest_bytes=(predecessor.content if predecessor else None),
            allocated_revisions=revisions,
            historical_manifests=tuple(item.manifest for item in history[:-1]),
            republish_after_withdrawal=republish_after_withdrawal,
        )
        if plan.disposition is not ManifestRevisionDisposition.REUSE_EXISTING:
            generated_at = clock() if predecessor is not None else generated_at
            if (
                not isinstance(generated_at, dt.datetime)
                or generated_at.tzinfo is None
                or generated_at.utcoffset() is None
            ):
                raise ScoreFormManifestGenerationValidationError(
                    "clock must return a timezone-aware datetime."
                )
        if (
            predecessor is not None
            and plan.disposition is not ManifestRevisionDisposition.REUSE_EXISTING
        ):
            candidate = build_academic_result_manifest(
                context,
                record_set_revision=revision,
                generated_at=generated_at,
            )
            candidate_bytes = manifest_to_canonical_json_bytes(candidate)
            plan = plan_manifest_revision(
                candidate,
                predecessor_manifest=predecessor.manifest,
                predecessor_manifest_bytes=predecessor.content,
                allocated_revisions=revisions,
                historical_manifests=tuple(
                    item.manifest for item in history[:-1]
                ),
                republish_after_withdrawal=republish_after_withdrawal,
            )
        _verify_retained_evidence_unchanged(context, workspace_root=root)
        _run_prewrite_verification_hook(context)
        verify_native_sources_unchanged(
            context.assignment_source,
            context.results_source,
        )
        if plan.disposition is ManifestRevisionDisposition.REUSE_EXISTING:
            assert predecessor is not None
            durable_path = predecessor.path
            durable_revision = predecessor.revision
            expected_digest = predecessor.sha256
            return AcademicResultManifestGenerationResult(
                disposition=plan.disposition,
                reason=plan.reason,
                manifest=predecessor.manifest,
                revision=predecessor.revision,
                path=predecessor.path,
                relative_path=predecessor.relative_path,
                content=predecessor.content,
                sha256=hashlib.sha256(predecessor.content).hexdigest(),
            )
        target = academic_result_manifest_revision_path(root, work, plan.revision)
        relative = academic_result_manifest_relative_path(work, plan.revision)
        expected_digest = hashlib.sha256(candidate_bytes).hexdigest()
        try:
            _write_new_revision(target, candidate_bytes)
        except _DurableRevisionWriteError as error:
            durable_path = target
            durable_revision = plan.revision
            state = ManifestGenerationPartialSuccessState(
                operation="directory_sync",
                work=work,
                revision=plan.revision,
                path=target,
                relative_path=relative,
                expected_sha256=expected_digest,
                durable_file_exists=target.exists(),
            )
            raise ScoreFormManifestGenerationPartialSuccessError(
                "Manifest revision is durable but directory sync failed.", state
            ) from error
        durable_path = target
        durable_revision = plan.revision
        try:
            stored_history = _load_history(root, work, allow_lock=True)
            stored = next(
                item for item in stored_history if item.revision == plan.revision
            )
            if stored.content != candidate_bytes or stored.manifest != candidate:
                raise ScoreFormManifestGenerationIntegrityError(
                    "Durable manifest revision contradicts the generated candidate."
                )
            result_value = AcademicResultManifestGenerationResult(
                disposition=plan.disposition,
                reason=plan.reason,
                manifest=stored.manifest,
                revision=stored.revision,
                path=stored.path,
                relative_path=stored.relative_path,
                content=stored.content,
                sha256=stored.sha256,
            )
        except Exception as error:
            state = ManifestGenerationPartialSuccessState(
                operation="generate",
                work=work,
                revision=plan.revision,
                path=target,
                relative_path=relative,
                expected_sha256=expected_digest,
                durable_file_exists=target.exists(),
            )
            partial = ScoreFormManifestGenerationPartialSuccessError(
                "Manifest revision is durable but final verification failed.", state
            )
            raise partial from error
        return result_value
    except ScoreFormManifestGenerationError as error:
        operation_error = error
        raise
    except Exception as error:
        normalized = ScoreFormManifestGenerationIntegrityError(
            "Manifest generation validation or revision planning failed."
        )
        operation_error = normalized
        raise normalized from error
    except BaseException as error:
        operation_error = error
        raise
    finally:
        try:
            lock_path.unlink()
        except OSError as cleanup_error:
            if operation_error is None:
                if durable_path is not None and durable_revision is not None:
                    state = ManifestGenerationPartialSuccessState(
                        operation="lock_cleanup",
                        work=work,
                        revision=durable_revision,
                        path=durable_path,
                        relative_path=academic_result_manifest_relative_path(
                            work, durable_revision
                        ),
                        expected_sha256=expected_digest,
                        durable_file_exists=durable_path.exists(),
                        cleanup_failure=str(cleanup_error),
                    )
                    raise ScoreFormManifestGenerationPartialSuccessError(
                        "Manifest is durable but generation lock cleanup failed.",
                        state,
                    ) from cleanup_error
                raise ScoreFormManifestGenerationWriteError(
                    "Manifest generation lock cleanup failed."
                ) from cleanup_error
            setattr(operation_error, "lock_cleanup_failure", cleanup_error)


__all__ = [
    "AcademicResultManifestGenerationContext",
    "AcademicResultManifestGenerationResult",
    "ManifestGenerationPartialSuccessState",
    "NativeFileByteSnapshot",
    "ScoreFormManifestGenerationConflictError",
    "ScoreFormManifestGenerationError",
    "ScoreFormManifestGenerationIntegrityError",
    "ScoreFormManifestGenerationNotFoundError",
    "ScoreFormManifestGenerationPartialSuccessError",
    "ScoreFormManifestGenerationValidationError",
    "ScoreFormManifestGenerationWriteError",
    "StoredAcademicResultManifest",
    "build_academic_result_manifest",
    "build_academic_result_manifest_bytes",
    "generate_academic_result_manifest",
    "list_academic_result_manifest_revisions",
    "load_academic_result_manifest_generation_context",
    "load_academic_result_manifest_revision",
    "snapshot_native_file_bytes",
    "verify_native_sources_unchanged",
    "validate_academic_result_manifest_revision",
]
