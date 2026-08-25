"""Read-only planning for ScoreForm's guided result-publication workflow."""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from pds_core.academic_work_registrations import (
    AcademicWorkIntent,
    AcademicWorkRegistration,
    AcademicWorkRegistrationLifecycle,
)
from pds_core.registry_services import AcademicWorkRegistrationRequest
from pds_core.routing_models import ModuleWorkRef

from scoreform.academic_result_manifest_generation import (
    AcademicResultManifestGenerationContext,
    ScoreFormManifestGenerationConflictError,
    ScoreFormManifestGenerationError,
    ScoreFormManifestGenerationIntegrityError,
    ScoreFormManifestGenerationNotFoundError,
    ScoreFormManifestGenerationPartialSuccessError,
    ScoreFormManifestGenerationValidationError,
    ScoreFormManifestGenerationWriteError,
    StoredAcademicResultManifest,
    generate_academic_result_manifest,
    load_academic_result_manifest_generation_context,
    load_academic_result_manifest_revision,
)
from scoreform.academic_result_publication import (
    ScoreFormAcademicResultPublicationConflictError,
    ScoreFormAcademicResultPublicationError,
    ScoreFormAcademicResultPublicationIntegrityError,
    ScoreFormAcademicResultPublicationNotFoundError,
    ScoreFormAcademicResultPublicationPartialSuccessError,
    ScoreFormAcademicResultPublicationValidationError,
    ScoreFormAcademicResultPublicationWriteError,
    ScoreFormPublicationSeriesState,
    load_scoreform_publication_series_status,
    publish_scoreform_academic_results,
    supersede_scoreform_academic_results,
)
from scoreform.academic_work_registration import (
    SCOREFORM_ACADEMIC_WORK_KIND,
    ScoreFormAcademicWorkRegistrationConflictError,
    ScoreFormAcademicWorkRegistrationError,
    ScoreFormAcademicWorkRegistrationIntegrityError,
    ScoreFormAcademicWorkRegistrationNotFoundError,
    ScoreFormAcademicWorkRegistrationPartialSuccessError,
    ScoreFormAcademicWorkRegistrationValidationError,
    ScoreFormAcademicWorkRegistrationWriteError,
    build_scoreform_academic_work_registration_request,
    load_current_scoreform_academic_work_registration,
    load_managed_assignment_registration_context,
    register_scoreform_academic_work,
)
from scoreform.pds_contract import SCOREFORM_ACADEMIC_WORK_CONTRACT_VERSION
from scoreform.publication_revision_policy import (
    ManifestRevisionDisposition,
    ManifestRevisionReason,
)


class ShareResultsNextStep(str, Enum):
    """One safe next stage for the ordinary guided publication journey."""

    NOT_READY = "not_ready"
    REGISTER = "register"
    GENERATE_MANIFEST = "generate_manifest"
    PUBLISH_FIRST = "publish_first"
    ALREADY_CURRENT = "already_current"
    SUPERSEDE = "supersede"
    WITHDRAWN_HEAD_REQUIRES_EXACT_RECOVERY = (
        "withdrawn_head_requires_exact_recovery"
    )
    REPAIR_REQUIRED = "repair_required"


class ScoreFormShareResultsPlanningError(Exception):
    """The selected managed assignment could not be planned safely."""


@dataclass(frozen=True, slots=True)
class ShareResultsReadiness:
    """Privacy-minimized snapshot of canonical publication readiness."""

    work: ModuleWorkRef
    title: str
    result_student_count: int
    result_attempt_count: int
    registration_revision: int | None
    academic_intent: str | None
    registration_lifecycle: str | None
    producer_head_revision: int | None
    producer_head_is_current: bool
    core_head_publication_id: str | None
    core_head_revision: int | None
    core_head_withdrawn: bool
    catalog_available: bool
    next_step: ShareResultsNextStep
    blocking_reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.work, ModuleWorkRef):
            raise TypeError("work must be a ModuleWorkRef.")
        if not isinstance(self.title, str) or not self.title.strip():
            raise ValueError("title must be nonempty.")
        for name in ("result_student_count", "result_attempt_count"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise TypeError(f"{name} must be a nonnegative integer.")
        if self.result_student_count == 0 and self.result_attempt_count != 0:
            raise ValueError("attempts cannot exist without represented students.")
        for name in (
            "registration_revision",
            "producer_head_revision",
            "core_head_revision",
        ):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 1
            ):
                raise TypeError(f"{name} must be a positive integer or None.")
        for name in ("academic_intent", "registration_lifecycle"):
            value = getattr(self, name)
            if value is not None and (
                not isinstance(value, str) or not value.strip()
            ):
                raise TypeError(f"{name} must be a nonempty string or None.")
        registration_absent = self.registration_revision is None
        if (self.academic_intent is None) != registration_absent or (
            self.registration_lifecycle is None
        ) != registration_absent:
            raise ValueError(
                "registration metadata presence must agree with its revision."
            )
        if (self.core_head_publication_id is None) != (
            self.core_head_revision is None
        ):
            raise ValueError(
                "Core head publication ID and revision must appear together."
            )
        if self.core_head_publication_id is not None and (
            not isinstance(self.core_head_publication_id, str)
            or not self.core_head_publication_id.strip()
        ):
            raise TypeError("core_head_publication_id must be nonempty or None.")
        for name in (
            "producer_head_is_current",
            "core_head_withdrawn",
            "catalog_available",
        ):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} must be Boolean.")
        if not isinstance(self.next_step, ShareResultsNextStep):
            raise TypeError("next_step must be a ShareResultsNextStep.")

        blocked = {
            ShareResultsNextStep.NOT_READY,
            ShareResultsNextStep.WITHDRAWN_HEAD_REQUIRES_EXACT_RECOVERY,
            ShareResultsNextStep.REPAIR_REQUIRED,
        }
        if self.next_step in blocked:
            if (
                not isinstance(self.blocking_reason, str)
                or not self.blocking_reason.strip()
            ):
                raise ValueError("blocked plans require a blocking_reason.")
        elif self.blocking_reason is not None:
            raise ValueError("actionable plans must not carry a blocking_reason.")

        if self.next_step is ShareResultsNextStep.REGISTER:
            if self.registration_revision is not None:
                raise ValueError("register plans require absent current registration.")
        if self.next_step is ShareResultsNextStep.GENERATE_MANIFEST:
            if self.registration_revision is None:
                raise ValueError(
                    "manifest generation follows a ready current registration."
                )
        if self.next_step is ShareResultsNextStep.PUBLISH_FIRST:
            if (
                self.registration_revision is None
                or not self.producer_head_is_current
                or self.producer_head_revision is None
                or self.core_head_revision is not None
            ):
                raise ValueError("first-publication plan is internally inconsistent.")
        if self.next_step is ShareResultsNextStep.ALREADY_CURRENT:
            if (
                self.registration_revision is None
                or not self.producer_head_is_current
                or self.producer_head_revision is None
                or self.core_head_revision != self.producer_head_revision
                or self.core_head_withdrawn
                or not self.catalog_available
            ):
                raise ValueError("already-current plan is internally inconsistent.")
        if self.next_step is ShareResultsNextStep.SUPERSEDE:
            if (
                self.registration_revision is None
                or not self.producer_head_is_current
                or self.producer_head_revision is None
                or self.core_head_revision is None
                or self.core_head_publication_id is None
                or self.producer_head_revision <= self.core_head_revision
                or self.core_head_withdrawn
            ):
                raise ValueError("supersession plan is internally inconsistent.")

    @property
    def results_ready(self) -> bool:
        """Whether validated native result history contains any attempts."""

        return self.result_attempt_count > 0

    @property
    def expected_current_publication_id(self) -> str | None:
        """Exact optimistic-concurrency predecessor for a supersession."""

        if self.next_step is ShareResultsNextStep.SUPERSEDE:
            return self.core_head_publication_id
        return None


_NO_RESULTS = (
    "No publishable ScoreForm results are available for this assignment."
)
_RESULTS_REPAIR = (
    "ScoreForm result evidence could not be validated safely. "
    "Review the exact result and manifest state before sharing."
)
_REGISTRATION_REPAIR = (
    "Academic Work Registration state could not be validated safely. "
    "Review the exact registration state before sharing."
)
_PUBLICATION_REPAIR = (
    "Publication state could not be validated safely. "
    "Review the exact publication state before sharing."
)
_MISSING_NATIVE_AFTER_HISTORY = (
    "Current ScoreForm result evidence is missing or empty even though "
    "immutable publication history already exists. Exact recovery is required."
)
_WITHDRAWN_HEAD = (
    "The current Core publication is withdrawn. Use the exact publication "
    "workflow to review republish-after-withdrawal before sharing again."
)
_CATALOG_REPAIR = (
    "The current publication is intact, but Core's derived publication catalog "
    "is unavailable. Rebuild or inspect the exact publication state first."
)


def _positive_revision(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ScoreFormShareResultsPlanningError(
            "Canonical publication state returned an invalid revision."
        )
    return value


def _producer_matches_native_sources(
    producer_head: StoredAcademicResultManifest | None,
    generation_context: AcademicResultManifestGenerationContext,
) -> bool:
    if producer_head is None:
        return False
    source = producer_head.manifest.source_snapshot
    return (
        source.assignment.sha256 == generation_context.assignment_source.sha256
        and source.results_history.sha256
        == generation_context.results_source.sha256
    )


def _core_head_matches_manifest(
    series: ScoreFormPublicationSeriesState,
    stored: StoredAcademicResultManifest,
) -> bool:
    head = series.core_head
    if head is None:
        return True
    return (
        head.record_set_revision == stored.revision
        and head.manifest_path == stored.relative_path
        and head.manifest_digest == stored.sha256
    )


def plan_share_results_readiness(
    workspace_root: str | Path,
    class_id: str,
    assignment_id: str,
) -> ShareResultsReadiness:
    """Read canonical state and choose one safe next guided publication stage.

    The function is intentionally side-effect free.  It never registers work,
    creates a manifest, publishes, supersedes, withdraws, or rebuilds a catalog.
    """

    root = Path(workspace_root)
    try:
        managed = load_managed_assignment_registration_context(
            root,
            class_id,
            assignment_id,
        )
    except ScoreFormAcademicWorkRegistrationError as error:
        raise ScoreFormShareResultsPlanningError(
            "The selected managed assignment could not be validated safely."
        ) from error

    work = managed.work
    title = managed.title
    student_count = 0
    attempt_count = 0
    generation_context: AcademicResultManifestGenerationContext | None = None
    native_results_missing = False

    try:
        generation_context = load_academic_result_manifest_generation_context(
            root,
            work,
        )
    except ScoreFormManifestGenerationNotFoundError:
        results_path = managed.work_root / "results.csv"
        try:
            native_results_missing = (
                not results_path.is_symlink() and not results_path.exists()
            )
        except OSError:
            native_results_missing = False
        if not native_results_missing:
            return ShareResultsReadiness(
                work=work,
                title=title,
                result_student_count=0,
                result_attempt_count=0,
                registration_revision=None,
                academic_intent=None,
                registration_lifecycle=None,
                producer_head_revision=None,
                producer_head_is_current=False,
                core_head_publication_id=None,
                core_head_revision=None,
                core_head_withdrawn=False,
                catalog_available=False,
                next_step=ShareResultsNextStep.REPAIR_REQUIRED,
                blocking_reason=_RESULTS_REPAIR,
            )
    except ScoreFormManifestGenerationError:
        return ShareResultsReadiness(
            work=work,
            title=title,
            result_student_count=0,
            result_attempt_count=0,
            registration_revision=None,
            academic_intent=None,
            registration_lifecycle=None,
            producer_head_revision=None,
            producer_head_is_current=False,
            core_head_publication_id=None,
            core_head_revision=None,
            core_head_withdrawn=False,
            catalog_available=False,
            next_step=ShareResultsNextStep.REPAIR_REQUIRED,
            blocking_reason=_RESULTS_REPAIR,
        )

    if generation_context is not None:
        student_count = len(generation_context.students)
        attempt_count = sum(
            len(student.attempts) for student in generation_context.students
        )

    try:
        registration = load_current_scoreform_academic_work_registration(
            root,
            class_id,
            assignment_id,
        )
    except ScoreFormAcademicWorkRegistrationError:
        return ShareResultsReadiness(
            work=work,
            title=title,
            result_student_count=student_count,
            result_attempt_count=attempt_count,
            registration_revision=None,
            academic_intent=None,
            registration_lifecycle=None,
            producer_head_revision=None,
            producer_head_is_current=False,
            core_head_publication_id=None,
            core_head_revision=None,
            core_head_withdrawn=False,
            catalog_available=False,
            next_step=ShareResultsNextStep.REPAIR_REQUIRED,
            blocking_reason=_REGISTRATION_REPAIR,
        )

    registration_revision = (
        None
        if registration is None
        else _positive_revision(registration.registration_revision)
    )
    academic_intent = (
        None if registration is None else str(registration.academic_intent)
    )
    registration_lifecycle = (
        None if registration is None else str(registration.lifecycle)
    )

    try:
        series = load_scoreform_publication_series_status(
            root,
            class_id,
            assignment_id,
        )
    except ScoreFormAcademicResultPublicationError:
        return ShareResultsReadiness(
            work=work,
            title=title,
            result_student_count=student_count,
            result_attempt_count=attempt_count,
            registration_revision=registration_revision,
            academic_intent=academic_intent,
            registration_lifecycle=registration_lifecycle,
            producer_head_revision=None,
            producer_head_is_current=False,
            core_head_publication_id=None,
            core_head_revision=None,
            core_head_withdrawn=False,
            catalog_available=False,
            next_step=ShareResultsNextStep.REPAIR_REQUIRED,
            blocking_reason=_PUBLICATION_REPAIR,
        )

    producer_head_revision = (
        None
        if series.producer_head is None
        else _positive_revision(series.producer_head.revision)
    )
    core_head_publication_id = (
        None if series.core_head is None else series.core_head.publication_id
    )
    core_head_revision = (
        None
        if series.core_head is None
        else _positive_revision(series.core_head.record_set_revision)
    )
    core_head_withdrawn = series.core_head_withdrawal is not None
    catalog_available = series.derived_catalog_available

    producer_head_is_current = (
        generation_context is not None
        and _producer_matches_native_sources(
            series.producer_head,
            generation_context,
        )
    )

    def state(
        next_step: ShareResultsNextStep,
        *,
        reason: str | None = None,
    ) -> ShareResultsReadiness:
        return ShareResultsReadiness(
            work=work,
            title=title,
            result_student_count=student_count,
            result_attempt_count=attempt_count,
            registration_revision=registration_revision,
            academic_intent=academic_intent,
            registration_lifecycle=registration_lifecycle,
            producer_head_revision=producer_head_revision,
            producer_head_is_current=producer_head_is_current,
            core_head_publication_id=core_head_publication_id,
            core_head_revision=core_head_revision,
            core_head_withdrawn=core_head_withdrawn,
            catalog_available=catalog_available,
            next_step=next_step,
            blocking_reason=reason,
        )

    if generation_context is None or attempt_count == 0:
        if series.producer_head is not None or series.core_head is not None:
            return state(
                ShareResultsNextStep.REPAIR_REQUIRED,
                reason=_MISSING_NATIVE_AFTER_HISTORY,
            )
        return state(ShareResultsNextStep.NOT_READY, reason=_NO_RESULTS)

    if series.core_head is not None:
        if registration is None or series.producer_head is None:
            return state(
                ShareResultsNextStep.REPAIR_REQUIRED,
                reason=_PUBLICATION_REPAIR,
            )
        try:
            historical = load_academic_result_manifest_revision(
                root,
                work,
                series.core_head.record_set_revision,
            )
        except ScoreFormManifestGenerationError:
            return state(
                ShareResultsNextStep.REPAIR_REQUIRED,
                reason=_PUBLICATION_REPAIR,
            )
        if not _core_head_matches_manifest(series, historical):
            return state(
                ShareResultsNextStep.REPAIR_REQUIRED,
                reason=_PUBLICATION_REPAIR,
            )

    if core_head_withdrawn:
        return state(
            ShareResultsNextStep.WITHDRAWN_HEAD_REQUIRES_EXACT_RECOVERY,
            reason=_WITHDRAWN_HEAD,
        )

    if registration is None:
        return state(ShareResultsNextStep.REGISTER)

    if not producer_head_is_current:
        return state(ShareResultsNextStep.GENERATE_MANIFEST)

    if series.producer_head is None:
        return state(
            ShareResultsNextStep.REPAIR_REQUIRED,
            reason=_PUBLICATION_REPAIR,
        )

    if series.core_head is None:
        return state(ShareResultsNextStep.PUBLISH_FIRST)

    if core_head_revision is None or producer_head_revision is None:
        return state(
            ShareResultsNextStep.REPAIR_REQUIRED,
            reason=_PUBLICATION_REPAIR,
        )

    if core_head_revision > producer_head_revision:
        return state(
            ShareResultsNextStep.REPAIR_REQUIRED,
            reason=_PUBLICATION_REPAIR,
        )

    if core_head_revision == producer_head_revision:
        if not catalog_available:
            return state(
                ShareResultsNextStep.REPAIR_REQUIRED,
                reason=_CATALOG_REPAIR,
            )
        return state(ShareResultsNextStep.ALREADY_CURRENT)

    return state(ShareResultsNextStep.SUPERSEDE)


class ScoreFormShareResultsRegistrationError(Exception):
    """Base error for the guided registration stage."""


class ScoreFormShareResultsRegistrationNotReadyError(
    ScoreFormShareResultsRegistrationError
):
    """Canonical readiness does not permit a new registration."""


class ScoreFormShareResultsRegistrationConflictError(
    ScoreFormShareResultsRegistrationError
):
    """State changed after preview or a different registration now exists."""


class ScoreFormShareResultsRegistrationWriteError(
    ScoreFormShareResultsRegistrationError
):
    """The exact registration service could not complete safely."""


@dataclass(frozen=True, slots=True)
class ShareResultsRegistrationPreview:
    """Exact read-only registration request shown before ``REGISTER``."""

    request: AcademicWorkRegistrationRequest

    def __post_init__(self) -> None:
        if not isinstance(self.request, AcademicWorkRegistrationRequest):
            raise TypeError("request must be an AcademicWorkRegistrationRequest.")
        if self.request.work.module_id != "scoreform":
            raise ValueError("registration preview must target ScoreForm work.")
        if (
            self.request.producer_contract_version
            != SCOREFORM_ACADEMIC_WORK_CONTRACT_VERSION
        ):
            raise ValueError(
                "registration preview has the wrong ScoreForm producer contract."
            )
        if self.request.work_kind != SCOREFORM_ACADEMIC_WORK_KIND:
            raise ValueError("registration preview has the wrong work kind.")

    @property
    def work(self) -> ModuleWorkRef:
        return self.request.work

    @property
    def title(self) -> str:
        return self.request.title

    @property
    def academic_intent(self) -> AcademicWorkIntent:
        return self.request.academic_intent

    @property
    def lifecycle(self) -> AcademicWorkRegistrationLifecycle:
        return self.request.lifecycle


@dataclass(frozen=True, slots=True)
class ShareResultsRegistrationCommitResult:
    """Verified durable result of the guided registration commit."""

    disposition: str
    registration: AcademicWorkRegistration

    def __post_init__(self) -> None:
        if self.disposition not in {"created", "existing"}:
            raise ValueError("registration disposition must be created or existing.")
        revision = getattr(self.registration, "registration_revision", None)
        if (
            isinstance(revision, bool)
            or not isinstance(revision, int)
            or revision < 1
        ):
            raise TypeError(
                "registration must expose a positive registration revision."
            )


@dataclass(frozen=True, slots=True)
class ShareResultsRegistrationRecovery:
    """Privacy-bounded projection of a Core registration partial success."""

    durable_registration_revision: int | None
    current_selected: bool | None
    guidance: str

    def __post_init__(self) -> None:
        if self.durable_registration_revision is not None and (
            isinstance(self.durable_registration_revision, bool)
            or not isinstance(self.durable_registration_revision, int)
            or self.durable_registration_revision < 1
        ):
            raise TypeError(
                "durable_registration_revision must be positive or None."
            )
        if self.current_selected is not None and not isinstance(
            self.current_selected, bool
        ):
            raise TypeError("current_selected must be Boolean or None.")
        if not isinstance(self.guidance, str) or not self.guidance.strip():
            raise ValueError("guidance must be nonempty.")


class ScoreFormShareResultsRegistrationPartialSuccessError(
    ScoreFormShareResultsRegistrationError
):
    """Registration may be durable; canonical state must be reloaded."""

    def __init__(
        self,
        recovery: ShareResultsRegistrationRecovery,
    ) -> None:
        super().__init__(
            "Academic Work Registration may already be durable; "
            "reload exact registration state before retrying."
        )
        self.recovery = recovery


def _registration_matches_request(
    registration: AcademicWorkRegistration,
    request: AcademicWorkRegistrationRequest,
) -> bool:
    return (
        registration.work == request.work
        and registration.producer_contract_version
        == request.producer_contract_version
        and registration.title == request.title
        and registration.work_kind == request.work_kind
        and registration.academic_intent == request.academic_intent
        and registration.lifecycle == request.lifecycle
        and registration.source_records == request.source_records
    )


def _registration_recovery(
    error: ScoreFormAcademicWorkRegistrationPartialSuccessError,
) -> ShareResultsRegistrationRecovery:
    state = error.state
    registration = state.registration
    revision = (
        None
        if registration is None
        else getattr(registration, "registration_revision", None)
    )
    if revision is not None and (
        isinstance(revision, bool)
        or not isinstance(revision, int)
        or revision < 1
    ):
        revision = None
    if state.current_selected is True:
        guidance = (
            "Core reports that the new Academic Work Registration is current. "
            "Reload the assignment's exact registration state before continuing."
        )
    elif state.current_selected is False:
        guidance = (
            "A registration revision may be durable but is not confirmed as the "
            "current selection. Inspect exact registration state before continuing."
        )
    else:
        guidance = (
            "Registration durability or current selection is uncertain. "
            "Reload exact registration state before retrying."
        )
    return ShareResultsRegistrationRecovery(
        durable_registration_revision=revision,
        current_selected=state.current_selected,
        guidance=guidance,
    )


def prepare_share_results_registration(
    workspace_root: str | Path,
    class_id: str,
    assignment_id: str,
    *,
    academic_intent: AcademicWorkIntent,
    lifecycle: AcademicWorkRegistrationLifecycle,
) -> ShareResultsRegistrationPreview:
    """Build the exact read-only request for an absent registration."""

    readiness = plan_share_results_readiness(
        workspace_root,
        class_id,
        assignment_id,
    )
    if readiness.next_step is not ShareResultsNextStep.REGISTER:
        raise ScoreFormShareResultsRegistrationNotReadyError(
            "The selected assignment is not ready for a new Academic Work "
            "Registration. Reload guided readiness before continuing."
        )
    try:
        context = load_managed_assignment_registration_context(
            workspace_root,
            class_id,
            assignment_id,
        )
        request = build_scoreform_academic_work_registration_request(
            context,
            academic_intent=academic_intent,
            lifecycle=lifecycle,
        )
    except ScoreFormAcademicWorkRegistrationError as error:
        raise ScoreFormShareResultsRegistrationNotReadyError(
            "The Academic Work Registration preview could not be built safely."
        ) from error
    except (TypeError, ValueError) as error:
        raise ScoreFormShareResultsRegistrationNotReadyError(
            "The Academic Work Registration choices are invalid."
        ) from error
    return ShareResultsRegistrationPreview(request=request)


def commit_share_results_registration(
    workspace_root: str | Path,
    preview: ShareResultsRegistrationPreview,
) -> ShareResultsRegistrationCommitResult:
    """Commit exactly the previewed registration, never an implicit update."""

    if not isinstance(preview, ShareResultsRegistrationPreview):
        raise TypeError("preview must be a ShareResultsRegistrationPreview.")

    work = preview.work
    try:
        context = load_managed_assignment_registration_context(
            workspace_root,
            work.class_id,
            work.work_id,
        )
        current_request = build_scoreform_academic_work_registration_request(
            context,
            academic_intent=preview.request.academic_intent,
            lifecycle=preview.request.lifecycle,
        )
    except ScoreFormAcademicWorkRegistrationError as error:
        raise ScoreFormShareResultsRegistrationConflictError(
            "Managed assignment state changed after the registration preview. "
            "Review a fresh preview before committing."
        ) from error
    except (TypeError, ValueError) as error:
        raise ScoreFormShareResultsRegistrationConflictError(
            "Registration inputs no longer match the preview."
        ) from error

    if current_request != preview.request:
        raise ScoreFormShareResultsRegistrationConflictError(
            "Managed assignment state changed after the registration preview. "
            "Review a fresh preview before committing."
        )

    try:
        current = load_current_scoreform_academic_work_registration(
            workspace_root,
            work.class_id,
            work.work_id,
        )
    except ScoreFormAcademicWorkRegistrationError as error:
        raise ScoreFormShareResultsRegistrationWriteError(
            "Current Academic Work Registration state could not be loaded safely."
        ) from error

    if current is not None:
        if not _registration_matches_request(current, preview.request):
            raise ScoreFormShareResultsRegistrationConflictError(
                "A different Academic Work Registration is now current. "
                "The guided workflow will not update it implicitly."
            )
        return ShareResultsRegistrationCommitResult(
            disposition="existing",
            registration=current,
        )

    try:
        result = register_scoreform_academic_work(
            workspace_root,
            work.class_id,
            work.work_id,
            academic_intent=preview.request.academic_intent,
            lifecycle=preview.request.lifecycle,
        )
    except ScoreFormAcademicWorkRegistrationPartialSuccessError as error:
        wrapped = ScoreFormShareResultsRegistrationPartialSuccessError(
            _registration_recovery(error)
        )
        raise wrapped from error
    except ScoreFormAcademicWorkRegistrationConflictError as error:
        raise ScoreFormShareResultsRegistrationConflictError(
            "Registration state changed during commit. Reload exact state "
            "before deciding again."
        ) from error
    except (
        ScoreFormAcademicWorkRegistrationValidationError,
        ScoreFormAcademicWorkRegistrationNotFoundError,
    ) as error:
        raise ScoreFormShareResultsRegistrationConflictError(
            "Managed assignment or registration inputs changed during commit."
        ) from error
    except (
        ScoreFormAcademicWorkRegistrationIntegrityError,
        ScoreFormAcademicWorkRegistrationWriteError,
    ) as error:
        raise ScoreFormShareResultsRegistrationWriteError(
            "Academic Work Registration could not be completed safely."
        ) from error

    if not _registration_matches_request(result.registration, preview.request):
        raise ScoreFormShareResultsRegistrationWriteError(
            "The registration service result does not match the confirmed preview."
        )
    if result.disposition not in {"created", "existing"}:
        raise ScoreFormShareResultsRegistrationWriteError(
            "The registration service returned an unsupported disposition."
        )
    return ShareResultsRegistrationCommitResult(
        disposition=result.disposition,
        registration=result.registration,
    )


class ScoreFormShareResultsManifestError(Exception):
    """Base error for the guided immutable-manifest stage."""


class ScoreFormShareResultsManifestNotReadyError(ScoreFormShareResultsManifestError):
    """Canonical readiness does not permit a manifest-generation commit."""


class ScoreFormShareResultsManifestConflictError(ScoreFormShareResultsManifestError):
    """Canonical state changed after preview and must be reviewed again."""


class ScoreFormShareResultsManifestRepairRequiredError(
    ScoreFormShareResultsManifestError
):
    """Existing producer evidence cannot be interpreted safely."""


class ScoreFormShareResultsManifestWriteError(ScoreFormShareResultsManifestError):
    """Immutable producer evidence could not be completed safely."""


@dataclass(frozen=True, slots=True)
class ShareResultsManifestPreview:
    """Read-only ``GENERATE`` boundary; it never allocates a revision."""

    work: ModuleWorkRef
    title: str
    registration_revision: int
    producer_head_revision_before: int | None

    def __post_init__(self) -> None:
        if not isinstance(self.work, ModuleWorkRef):
            raise TypeError("work must be a ModuleWorkRef.")
        if not isinstance(self.title, str) or not self.title.strip():
            raise ValueError("title must be nonempty.")
        if (
            isinstance(self.registration_revision, bool)
            or not isinstance(self.registration_revision, int)
            or self.registration_revision < 1
        ):
            raise TypeError("registration_revision must be positive.")
        if self.producer_head_revision_before is not None and (
            isinstance(self.producer_head_revision_before, bool)
            or not isinstance(self.producer_head_revision_before, int)
            or self.producer_head_revision_before < 1
        ):
            raise TypeError(
                "producer_head_revision_before must be positive or None."
            )


@dataclass(frozen=True, slots=True)
class ShareResultsManifestCommitResult:
    """Privacy-bounded exact result returned after one generator call."""

    work: ModuleWorkRef
    disposition: ManifestRevisionDisposition
    reason: ManifestRevisionReason
    revision: int
    relative_path: str
    sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.work, ModuleWorkRef):
            raise TypeError("work must be a ModuleWorkRef.")
        if not isinstance(self.disposition, ManifestRevisionDisposition):
            raise TypeError(
                "disposition must be a ManifestRevisionDisposition."
            )
        if not isinstance(self.reason, ManifestRevisionReason):
            raise TypeError("reason must be a ManifestRevisionReason.")
        if (
            isinstance(self.revision, bool)
            or not isinstance(self.revision, int)
            or self.revision < 1
        ):
            raise TypeError("revision must be positive.")
        if (
            not isinstance(self.relative_path, str)
            or not self.relative_path.strip()
        ):
            raise TypeError("relative_path must be nonempty.")
        if (
            not isinstance(self.sha256, str)
            or len(self.sha256) != 64
            or any(character not in "0123456789abcdef" for character in self.sha256)
        ):
            raise TypeError("sha256 must be lowercase SHA-256.")

    @property
    def created_new_revision(self) -> bool:
        """Whether this commit created new immutable producer bytes."""

        return self.disposition is not ManifestRevisionDisposition.REUSE_EXISTING


@dataclass(frozen=True, slots=True)
class ShareResultsManifestRecovery:
    """Bounded projection of a durable manifest-generation partial success."""

    work: ModuleWorkRef
    revision: int
    relative_path: str
    expected_sha256: str | None
    durable_file_exists: bool
    lock_cleanup_issue: bool
    guidance: str

    def __post_init__(self) -> None:
        if not isinstance(self.work, ModuleWorkRef):
            raise TypeError("work must be a ModuleWorkRef.")
        if (
            isinstance(self.revision, bool)
            or not isinstance(self.revision, int)
            or self.revision < 1
        ):
            raise TypeError("revision must be positive.")
        if (
            not isinstance(self.relative_path, str)
            or not self.relative_path.strip()
        ):
            raise TypeError("relative_path must be nonempty.")
        if self.expected_sha256 is not None and (
            not isinstance(self.expected_sha256, str)
            or len(self.expected_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in self.expected_sha256
            )
        ):
            raise TypeError("expected_sha256 must be lowercase SHA-256 or None.")
        if not isinstance(self.durable_file_exists, bool):
            raise TypeError("durable_file_exists must be Boolean.")
        if not isinstance(self.lock_cleanup_issue, bool):
            raise TypeError("lock_cleanup_issue must be Boolean.")
        if not isinstance(self.guidance, str) or not self.guidance.strip():
            raise ValueError("guidance must be nonempty.")


class ScoreFormShareResultsManifestPartialSuccessError(
    ScoreFormShareResultsManifestError
):
    """A manifest revision may be durable; do not retry automatically."""

    def __init__(self, recovery: ShareResultsManifestRecovery) -> None:
        super().__init__(
            "An immutable Academic Result Manifest may already be durable; "
            "reload exact manifest state before retrying or publishing."
        )
        self.recovery = recovery


def _manifest_partial_success_recovery(
    error: ScoreFormManifestGenerationPartialSuccessError,
) -> ShareResultsManifestRecovery:
    state = error.state
    if state.durable_file_exists:
        guidance = (
            "The manifest file is reported durable, but final verification or "
            "cleanup did not complete. Reload exact manifest history before "
            "continuing; do not generate again automatically."
        )
    else:
        guidance = (
            "Manifest completion is uncertain. Reload exact immutable manifest "
            "history before continuing; do not generate again automatically."
        )
    return ShareResultsManifestRecovery(
        work=state.work,
        revision=state.revision,
        relative_path=state.relative_path,
        expected_sha256=state.expected_sha256,
        durable_file_exists=state.durable_file_exists,
        lock_cleanup_issue=state.lock_cleanup_failure is not None,
        guidance=guidance,
    )


def prepare_share_results_manifest(
    workspace_root: str | Path,
    class_id: str,
    assignment_id: str,
) -> ShareResultsManifestPreview:
    """Prepare the read-only ``GENERATE`` boundary without allocating a revision."""

    readiness = plan_share_results_readiness(
        workspace_root,
        class_id,
        assignment_id,
    )
    if readiness.next_step is not ShareResultsNextStep.GENERATE_MANIFEST:
        raise ScoreFormShareResultsManifestNotReadyError(
            "The selected assignment does not currently require a new or replayed "
            "Academic Result Manifest. Reload guided readiness before continuing."
        )
    if readiness.registration_revision is None:
        raise ScoreFormShareResultsManifestNotReadyError(
            "Academic Work Registration must be ready before manifest generation."
        )
    return ShareResultsManifestPreview(
        work=readiness.work,
        title=readiness.title,
        registration_revision=readiness.registration_revision,
        producer_head_revision_before=readiness.producer_head_revision,
    )


def _require_manifest_preview_still_current(
    workspace_root: str | Path,
    preview: ShareResultsManifestPreview,
) -> ShareResultsReadiness:
    readiness = plan_share_results_readiness(
        workspace_root,
        preview.work.class_id,
        preview.work.work_id,
    )
    if readiness.next_step is not ShareResultsNextStep.GENERATE_MANIFEST:
        raise ScoreFormShareResultsManifestConflictError(
            "Publication readiness changed after the manifest preview. "
            "Review fresh canonical state before generating."
        )
    if (
        readiness.work != preview.work
        or readiness.title != preview.title
        or readiness.registration_revision != preview.registration_revision
        or readiness.producer_head_revision
        != preview.producer_head_revision_before
    ):
        raise ScoreFormShareResultsManifestConflictError(
            "Assignment, registration, or producer-manifest state changed after "
            "the manifest preview. Review a fresh preview before generating."
        )
    return readiness


def commit_share_results_manifest(
    workspace_root: str | Path,
    preview: ShareResultsManifestPreview,
) -> ShareResultsManifestCommitResult:
    """Call the existing immutable generator exactly once after ``GENERATE``."""

    if not isinstance(preview, ShareResultsManifestPreview):
        raise TypeError("preview must be a ShareResultsManifestPreview.")

    _require_manifest_preview_still_current(workspace_root, preview)

    try:
        result = generate_academic_result_manifest(
            workspace_root,
            preview.work.class_id,
            preview.work.work_id,
        )
    except ScoreFormManifestGenerationPartialSuccessError as error:
        wrapped = ScoreFormShareResultsManifestPartialSuccessError(
            _manifest_partial_success_recovery(error)
        )
        raise wrapped from error
    except ScoreFormManifestGenerationConflictError as error:
        raise ScoreFormShareResultsManifestConflictError(
            "Manifest state changed during generation. Reload exact immutable "
            "history before deciding again."
        ) from error
    except (
        ScoreFormManifestGenerationValidationError,
        ScoreFormManifestGenerationNotFoundError,
    ) as error:
        raise ScoreFormShareResultsManifestConflictError(
            "Managed assignment or result evidence changed during generation. "
            "Reload guided readiness before trying again."
        ) from error
    except ScoreFormManifestGenerationIntegrityError as error:
        raise ScoreFormShareResultsManifestRepairRequiredError(
            "Existing producer evidence failed integrity validation. "
            "Inspect exact manifest/result state before continuing."
        ) from error
    except ScoreFormManifestGenerationWriteError as error:
        raise ScoreFormShareResultsManifestWriteError(
            "The immutable Academic Result Manifest could not be completed safely."
        ) from error
    except ScoreFormManifestGenerationError as error:
        raise ScoreFormShareResultsManifestWriteError(
            "Academic Result Manifest generation failed safely."
        ) from error

    manifest_work = ModuleWorkRef(
        result.manifest.work.module_id,
        result.manifest.work.class_id,
        result.manifest.work.work_id,
    )
    if manifest_work != preview.work:
        raise ScoreFormShareResultsManifestWriteError(
            "The manifest generator returned evidence for the wrong work identity."
        )

    return ShareResultsManifestCommitResult(
        work=manifest_work,
        disposition=result.disposition,
        reason=result.reason,
        revision=result.revision,
        relative_path=result.relative_path,
        sha256=result.sha256,
    )

class ShareResultsPublicationAction(str, Enum):
    """Teacher-facing publication decision after manifest readiness."""

    PUBLISH_FIRST = "publish_first"
    ALREADY_CURRENT = "already_current"


class ScoreFormShareResultsPublicationError(Exception):
    """Base error for guided first-publication/current-state handling."""


class ScoreFormShareResultsPublicationNotReadyError(
    ScoreFormShareResultsPublicationError
):
    """Canonical state is not a first-publication/current-state journey."""


class ScoreFormShareResultsPublicationConflictError(
    ScoreFormShareResultsPublicationError
):
    """Canonical publication state changed after teacher preview."""


class ScoreFormShareResultsPublicationRepairRequiredError(
    ScoreFormShareResultsPublicationError
):
    """Canonical or producer publication evidence requires exact inspection."""


class ScoreFormShareResultsPublicationWriteError(
    ScoreFormShareResultsPublicationError
):
    """The exact Core publication service could not complete safely."""


@dataclass(frozen=True, slots=True)
class ShareResultsPublicationPreview:
    """Exact read-only ``PUBLISH`` or already-current decision."""

    work: ModuleWorkRef
    title: str
    action: ShareResultsPublicationAction
    manifest_revision: int
    current_publication_id: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.work, ModuleWorkRef):
            raise TypeError("work must be a ModuleWorkRef.")
        if not isinstance(self.title, str) or not self.title.strip():
            raise ValueError("title must be nonempty.")
        if not isinstance(self.action, ShareResultsPublicationAction):
            raise TypeError("action must be a ShareResultsPublicationAction.")
        if (
            isinstance(self.manifest_revision, bool)
            or not isinstance(self.manifest_revision, int)
            or self.manifest_revision < 1
        ):
            raise TypeError("manifest_revision must be positive.")
        if self.action is ShareResultsPublicationAction.PUBLISH_FIRST:
            if self.current_publication_id is not None:
                raise ValueError(
                    "first-publication preview cannot have a current publication."
                )
        elif (
            not isinstance(self.current_publication_id, str)
            or not self.current_publication_id.strip()
        ):
            raise ValueError(
                "already-current preview requires the exact current publication ID."
            )

    @property
    def requires_commit(self) -> bool:
        return self.action is ShareResultsPublicationAction.PUBLISH_FIRST


@dataclass(frozen=True, slots=True)
class ShareResultsPublicationOutcome:
    """Verified canonical publication state available for Meridian consumption."""

    work: ModuleWorkRef
    disposition: str
    publication_id: str
    manifest_revision: int
    previous_publication_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.work, ModuleWorkRef):
            raise TypeError("work must be a ModuleWorkRef.")
        if self.disposition not in {"created", "existing", "already_current"}:
            raise ValueError("publication disposition is unsupported.")
        if not isinstance(self.publication_id, str) or not self.publication_id.strip():
            raise TypeError("publication_id must be nonempty.")
        if (
            isinstance(self.manifest_revision, bool)
            or not isinstance(self.manifest_revision, int)
            or self.manifest_revision < 1
        ):
            raise TypeError("manifest_revision must be positive.")
        if self.previous_publication_id is not None and (
            not isinstance(self.previous_publication_id, str)
            or not self.previous_publication_id.strip()
        ):
            raise TypeError("previous_publication_id must be nonempty or None.")

    @property
    def available_for_meridian_consumption(self) -> bool:
        """This describes Core publication readiness, not Meridian ingestion."""

        return True


@dataclass(frozen=True, slots=True)
class ShareResultsPublicationRecovery:
    """Bounded durable-state projection for publication recovery."""

    operation: str
    canonical_state: str
    publication_id: str | None
    manifest_revision: int | None
    catalog_rebuild_attempted: bool
    catalog_replacement_completed: bool
    catalog_verification_completed: bool
    guidance: str

    def __post_init__(self) -> None:
        if not isinstance(self.operation, str) or not self.operation.strip():
            raise ValueError("operation must be nonempty.")
        if self.canonical_state not in {"uncertain", "confirmed"}:
            raise ValueError("canonical_state must be uncertain or confirmed.")
        if self.publication_id is not None and (
            not isinstance(self.publication_id, str)
            or not self.publication_id.strip()
        ):
            raise TypeError("publication_id must be nonempty or None.")
        if self.manifest_revision is not None and (
            isinstance(self.manifest_revision, bool)
            or not isinstance(self.manifest_revision, int)
            or self.manifest_revision < 1
        ):
            raise TypeError("manifest_revision must be positive or None.")
        for name in (
            "catalog_rebuild_attempted",
            "catalog_replacement_completed",
            "catalog_verification_completed",
        ):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} must be Boolean.")
        if not isinstance(self.guidance, str) or not self.guidance.strip():
            raise ValueError("guidance must be nonempty.")


class ScoreFormShareResultsPublicationPartialSuccessError(
    ScoreFormShareResultsPublicationError
):
    """Core publication may already be durable; never blindly retry."""

    def __init__(self, recovery: ShareResultsPublicationRecovery) -> None:
        super().__init__(
            "Core publication may already be durable; reload exact publication "
            "state before retrying or continuing."
        )
        self.recovery = recovery


class ScoreFormShareResultsPublicationPostCommitStateError(
    ScoreFormShareResultsPublicationError
):
    """The service returned success but final canonical state changed afterward."""

    def __init__(
        self,
        *,
        publication_id: str,
        manifest_revision: int,
    ) -> None:
        super().__init__(
            "Publication completed, but final canonical state changed before the "
            "guided workflow could confirm it. Reload exact publication state."
        )
        self.publication_id = publication_id
        self.manifest_revision = manifest_revision


def _publication_partial_success_recovery(
    error: ScoreFormAcademicResultPublicationPartialSuccessError,
) -> ShareResultsPublicationRecovery:
    state = error.state
    publication = state.publication
    manifest = state.manifest
    publication_id = (
        None
        if publication is None
        else getattr(publication, "publication_id", None)
    )
    manifest_revision = (
        getattr(publication, "record_set_revision", None)
        if publication is not None
        else (
            None
            if manifest is None
            else getattr(manifest, "revision", None)
        )
    )
    guidance = state.recommended_next_action
    if not isinstance(guidance, str) or not guidance.strip():
        guidance = "Reload exact publication state before retrying or continuing."
    return ShareResultsPublicationRecovery(
        operation=state.operation,
        canonical_state=state.canonical_state,
        publication_id=publication_id,
        manifest_revision=manifest_revision,
        catalog_rebuild_attempted=state.catalog_rebuild_attempted,
        catalog_replacement_completed=state.catalog_replacement_completed,
        catalog_verification_completed=state.catalog_verification_completed,
        guidance=guidance,
    )


def prepare_share_results_publication(
    workspace_root: str | Path,
    class_id: str,
    assignment_id: str,
) -> ShareResultsPublicationPreview:
    """Prepare first-publication or already-current state without writing."""

    readiness = plan_share_results_readiness(
        workspace_root,
        class_id,
        assignment_id,
    )
    if readiness.next_step not in {
        ShareResultsNextStep.PUBLISH_FIRST,
        ShareResultsNextStep.ALREADY_CURRENT,
    }:
        raise ScoreFormShareResultsPublicationNotReadyError(
            "The selected assignment is not in a first-publication or "
            "already-current state. Reload guided readiness before continuing."
        )
    if readiness.producer_head_revision is None:
        raise ScoreFormShareResultsPublicationNotReadyError(
            "An exact producer manifest revision is required before publication."
        )

    if readiness.next_step is ShareResultsNextStep.PUBLISH_FIRST:
        return ShareResultsPublicationPreview(
            work=readiness.work,
            title=readiness.title,
            action=ShareResultsPublicationAction.PUBLISH_FIRST,
            manifest_revision=readiness.producer_head_revision,
            current_publication_id=None,
        )

    if readiness.core_head_publication_id is None:
        raise ScoreFormShareResultsPublicationNotReadyError(
            "Already-current state requires an exact Core publication identity."
        )
    return ShareResultsPublicationPreview(
        work=readiness.work,
        title=readiness.title,
        action=ShareResultsPublicationAction.ALREADY_CURRENT,
        manifest_revision=readiness.producer_head_revision,
        current_publication_id=readiness.core_head_publication_id,
    )


def _require_publication_preview_still_current(
    workspace_root: str | Path,
    preview: ShareResultsPublicationPreview,
) -> ShareResultsReadiness:
    readiness = plan_share_results_readiness(
        workspace_root,
        preview.work.class_id,
        preview.work.work_id,
    )
    expected_step = (
        ShareResultsNextStep.PUBLISH_FIRST
        if preview.action is ShareResultsPublicationAction.PUBLISH_FIRST
        else ShareResultsNextStep.ALREADY_CURRENT
    )
    if readiness.next_step is not expected_step:
        raise ScoreFormShareResultsPublicationConflictError(
            "Publication readiness changed after the teacher preview. "
            "Review fresh canonical state before deciding again."
        )
    if (
        readiness.work != preview.work
        or readiness.title != preview.title
        or readiness.producer_head_revision != preview.manifest_revision
        or readiness.core_head_publication_id != preview.current_publication_id
    ):
        raise ScoreFormShareResultsPublicationConflictError(
            "Producer or Core publication identity changed after the preview. "
            "Review fresh canonical state before deciding again."
        )
    return readiness


def _already_current_outcome(
    preview: ShareResultsPublicationPreview,
) -> ShareResultsPublicationOutcome:
    publication_id = preview.current_publication_id
    if publication_id is None:
        raise ScoreFormShareResultsPublicationRepairRequiredError(
            "Already-current state lost its exact publication identity."
        )
    return ShareResultsPublicationOutcome(
        work=preview.work,
        disposition="already_current",
        publication_id=publication_id,
        manifest_revision=preview.manifest_revision,
    )


def _verify_first_publication_final_state(
    workspace_root: str | Path,
    *,
    preview: ShareResultsPublicationPreview,
    publication_id: str,
) -> None:
    try:
        state = load_scoreform_publication_series_status(
            workspace_root,
            preview.work.class_id,
            preview.work.work_id,
        )
    except ScoreFormAcademicResultPublicationError as error:
        raise ScoreFormShareResultsPublicationPostCommitStateError(
            publication_id=publication_id,
            manifest_revision=preview.manifest_revision,
        ) from error

    head = state.core_head
    if (
        head is None
        or head.publication_id != publication_id
        or head.record_set_revision != preview.manifest_revision
        or state.core_head_withdrawal is not None
        or state.current_selectable_publication != head
        or not state.derived_catalog_available
    ):
        raise ScoreFormShareResultsPublicationPostCommitStateError(
            publication_id=publication_id,
            manifest_revision=preview.manifest_revision,
        )


def commit_share_results_publication(
    workspace_root: str | Path,
    preview: ShareResultsPublicationPreview,
) -> ShareResultsPublicationOutcome:
    """Commit exact first publication or return an already-current no-op."""

    if not isinstance(preview, ShareResultsPublicationPreview):
        raise TypeError("preview must be a ShareResultsPublicationPreview.")

    _require_publication_preview_still_current(workspace_root, preview)

    if preview.action is ShareResultsPublicationAction.ALREADY_CURRENT:
        return _already_current_outcome(preview)

    try:
        result = publish_scoreform_academic_results(
            workspace_root,
            preview.work.class_id,
            preview.work.work_id,
            manifest_revision=preview.manifest_revision,
        )
    except ScoreFormAcademicResultPublicationPartialSuccessError as error:
        wrapped = ScoreFormShareResultsPublicationPartialSuccessError(
            _publication_partial_success_recovery(error)
        )
        raise wrapped from error
    except (
        ScoreFormAcademicResultPublicationConflictError,
        ScoreFormAcademicResultPublicationNotFoundError,
        ScoreFormAcademicResultPublicationValidationError,
    ) as error:
        raise ScoreFormShareResultsPublicationConflictError(
            "Publication state changed during commit. Reload exact state "
            "before deciding again."
        ) from error
    except ScoreFormAcademicResultPublicationIntegrityError as error:
        raise ScoreFormShareResultsPublicationRepairRequiredError(
            "Canonical publication state failed integrity validation. "
            "Inspect exact publication state before continuing."
        ) from error
    except ScoreFormAcademicResultPublicationWriteError as error:
        raise ScoreFormShareResultsPublicationWriteError(
            "The first Core publication could not be completed safely."
        ) from error
    except ScoreFormAcademicResultPublicationError as error:
        raise ScoreFormShareResultsPublicationWriteError(
            "The first Core publication failed safely."
        ) from error

    if result.operation != "publish":
        raise ScoreFormShareResultsPublicationWriteError(
            "The publication service returned the wrong operation."
        )
    if result.disposition not in {"created", "existing"}:
        raise ScoreFormShareResultsPublicationWriteError(
            "The publication service returned an unsupported disposition."
        )
    publication = result.publication
    if (
        publication.work != preview.work
        or publication.record_set_revision != preview.manifest_revision
        or result.withdrawal is not None
    ):
        raise ScoreFormShareResultsPublicationWriteError(
            "The publication service result does not match the confirmed preview."
        )

    _verify_first_publication_final_state(
        workspace_root,
        preview=preview,
        publication_id=publication.publication_id,
    )
    return ShareResultsPublicationOutcome(
        work=preview.work,
        disposition=result.disposition,
        publication_id=publication.publication_id,
        manifest_revision=preview.manifest_revision,
    )


@dataclass(frozen=True, slots=True)
class ShareResultsSupersessionPreview:
    """Exact read-only ``SUPERSEDE`` boundary."""

    work: ModuleWorkRef
    title: str
    predecessor_publication_id: str
    predecessor_manifest_revision: int
    successor_manifest_revision: int

    def __post_init__(self) -> None:
        if not isinstance(self.work, ModuleWorkRef):
            raise TypeError("work must be a ModuleWorkRef.")
        if not isinstance(self.title, str) or not self.title.strip():
            raise ValueError("title must be nonempty.")
        if (
            not isinstance(self.predecessor_publication_id, str)
            or not self.predecessor_publication_id.strip()
        ):
            raise TypeError("predecessor_publication_id must be nonempty.")
        for name in (
            "predecessor_manifest_revision",
            "successor_manifest_revision",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise TypeError(f"{name} must be positive.")
        if self.successor_manifest_revision <= self.predecessor_manifest_revision:
            raise ValueError(
                "successor_manifest_revision must be greater than its predecessor."
            )

    @property
    def expected_current_publication_id(self) -> str:
        """Exact optimistic-concurrency predecessor passed to Core."""

        return self.predecessor_publication_id


def prepare_share_results_supersession(
    workspace_root: str | Path,
    class_id: str,
    assignment_id: str,
) -> ShareResultsSupersessionPreview:
    """Resolve the exact canonical predecessor without asking the teacher to type it."""

    readiness = plan_share_results_readiness(
        workspace_root,
        class_id,
        assignment_id,
    )
    if readiness.next_step is not ShareResultsNextStep.SUPERSEDE:
        raise ScoreFormShareResultsPublicationNotReadyError(
            "The selected assignment is not ready for exact supersession. "
            "Reload guided readiness before continuing."
        )
    predecessor_id = readiness.core_head_publication_id
    predecessor_revision = readiness.core_head_revision
    successor_revision = readiness.producer_head_revision
    if (
        predecessor_id is None
        or predecessor_revision is None
        or successor_revision is None
    ):
        raise ScoreFormShareResultsPublicationNotReadyError(
            "Exact predecessor and successor publication identities are required."
        )
    return ShareResultsSupersessionPreview(
        work=readiness.work,
        title=readiness.title,
        predecessor_publication_id=predecessor_id,
        predecessor_manifest_revision=predecessor_revision,
        successor_manifest_revision=successor_revision,
    )


def _require_supersession_preview_still_current(
    workspace_root: str | Path,
    preview: ShareResultsSupersessionPreview,
) -> ShareResultsReadiness:
    readiness = plan_share_results_readiness(
        workspace_root,
        preview.work.class_id,
        preview.work.work_id,
    )
    if readiness.next_step is not ShareResultsNextStep.SUPERSEDE:
        raise ScoreFormShareResultsPublicationConflictError(
            "Publication state changed after the supersession preview. "
            "Review the new canonical head before deciding again."
        )
    if (
        readiness.work != preview.work
        or readiness.title != preview.title
        or readiness.core_head_publication_id
        != preview.predecessor_publication_id
        or readiness.core_head_revision
        != preview.predecessor_manifest_revision
        or readiness.producer_head_revision
        != preview.successor_manifest_revision
    ):
        raise ScoreFormShareResultsPublicationConflictError(
            "The exact predecessor or successor changed after the supersession "
            "preview. A fresh teacher confirmation is required."
        )
    return readiness


def _verify_supersession_final_state(
    workspace_root: str | Path,
    *,
    preview: ShareResultsSupersessionPreview,
    publication_id: str,
) -> None:
    try:
        state = load_scoreform_publication_series_status(
            workspace_root,
            preview.work.class_id,
            preview.work.work_id,
        )
    except ScoreFormAcademicResultPublicationError as error:
        raise ScoreFormShareResultsPublicationPostCommitStateError(
            publication_id=publication_id,
            manifest_revision=preview.successor_manifest_revision,
        ) from error

    head = state.core_head
    predecessor = next(
        (
            publication
            for publication in state.publications
            if publication.publication_id
            == preview.predecessor_publication_id
        ),
        None,
    )
    if (
        head is None
        or head.publication_id != publication_id
        or head.record_set_revision != preview.successor_manifest_revision
        or head.supersedes_publication_id
        != preview.predecessor_publication_id
        or state.core_head_withdrawal is not None
        or state.current_selectable_publication != head
        or not state.derived_catalog_available
        or predecessor is None
        or predecessor.record_set_revision
        != preview.predecessor_manifest_revision
    ):
        raise ScoreFormShareResultsPublicationPostCommitStateError(
            publication_id=publication_id,
            manifest_revision=preview.successor_manifest_revision,
        )


def commit_share_results_supersession(
    workspace_root: str | Path,
    preview: ShareResultsSupersessionPreview,
) -> ShareResultsPublicationOutcome:
    """Commit one exact supersession without substituting a changed Core head."""

    if not isinstance(preview, ShareResultsSupersessionPreview):
        raise TypeError("preview must be a ShareResultsSupersessionPreview.")

    _require_supersession_preview_still_current(workspace_root, preview)

    try:
        result = supersede_scoreform_academic_results(
            workspace_root,
            preview.work.class_id,
            preview.work.work_id,
            manifest_revision=preview.successor_manifest_revision,
            expected_current_publication_id=(
                preview.expected_current_publication_id
            ),
        )
    except ScoreFormAcademicResultPublicationPartialSuccessError as error:
        wrapped = ScoreFormShareResultsPublicationPartialSuccessError(
            _publication_partial_success_recovery(error)
        )
        raise wrapped from error
    except (
        ScoreFormAcademicResultPublicationConflictError,
        ScoreFormAcademicResultPublicationNotFoundError,
        ScoreFormAcademicResultPublicationValidationError,
    ) as error:
        raise ScoreFormShareResultsPublicationConflictError(
            "The canonical publication head changed during supersession. "
            "Nothing will be substituted automatically; reload exact state "
            "and obtain a fresh teacher confirmation."
        ) from error
    except ScoreFormAcademicResultPublicationIntegrityError as error:
        raise ScoreFormShareResultsPublicationRepairRequiredError(
            "Canonical supersession state failed integrity validation. "
            "Inspect exact publication history before continuing."
        ) from error
    except ScoreFormAcademicResultPublicationWriteError as error:
        raise ScoreFormShareResultsPublicationWriteError(
            "Exact Core supersession could not be completed safely."
        ) from error
    except ScoreFormAcademicResultPublicationError as error:
        raise ScoreFormShareResultsPublicationWriteError(
            "Exact Core supersession failed safely."
        ) from error

    if result.operation != "supersede":
        raise ScoreFormShareResultsPublicationWriteError(
            "The publication service returned the wrong operation."
        )
    if result.disposition not in {"created", "existing"}:
        raise ScoreFormShareResultsPublicationWriteError(
            "The supersession service returned an unsupported disposition."
        )
    publication = result.publication
    if (
        publication.work != preview.work
        or publication.record_set_revision
        != preview.successor_manifest_revision
        or publication.supersedes_publication_id
        != preview.predecessor_publication_id
        or result.withdrawal is not None
    ):
        raise ScoreFormShareResultsPublicationWriteError(
            "The supersession result does not match the confirmed predecessor "
            "and successor."
        )

    requirement = result.supersession_requirement
    if (
        requirement is None
        or requirement.expected_current_publication_id
        != preview.predecessor_publication_id
        or requirement.predecessor_revision
        != preview.predecessor_manifest_revision
        or requirement.successor_revision
        != preview.successor_manifest_revision
    ):
        raise ScoreFormShareResultsPublicationWriteError(
            "The supersession service requirement does not match the teacher "
            "confirmed exact transition."
        )

    _verify_supersession_final_state(
        workspace_root,
        preview=preview,
        publication_id=publication.publication_id,
    )
    return ShareResultsPublicationOutcome(
        work=preview.work,
        disposition=result.disposition,
        publication_id=publication.publication_id,
        manifest_revision=preview.successor_manifest_revision,
        previous_publication_id=preview.predecessor_publication_id,
    )
