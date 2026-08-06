"""ScoreForm-owned Academic Work Registration for managed assignments."""

from __future__ import annotations

import contextlib
import io
from dataclasses import dataclass
from pathlib import Path

from pds_core.academic_work_registration_storage import (
    AcademicWorkRegistrationConflictError as CoreStorageConflictError,
)
from pds_core.academic_work_registration_storage import (
    AcademicWorkRegistrationIntegrityError as CoreStorageIntegrityError,
)
from pds_core.academic_work_registration_storage import (
    AcademicWorkRegistrationNotFoundError as CoreStorageNotFoundError,
)
from pds_core.academic_work_registration_storage import (
    AcademicWorkRegistrationReadError as CoreStorageReadError,
)
from pds_core.academic_work_registration_storage import (
    AcademicWorkRegistrationValidationError as CoreStorageValidationError,
)
from pds_core.academic_work_registration_storage import (
    AcademicWorkRegistrationWriteError as CoreStorageWriteError,
)
from pds_core.academic_work_registration_storage import (
    load_current_academic_work_registration,
)
from pds_core.academic_work_registrations import (
    ACADEMIC_WORK_INTENTS,
    ACADEMIC_WORK_REGISTRATION_LIFECYCLES,
    AcademicWorkIntent,
    AcademicWorkRegistration,
    AcademicWorkRegistrationLifecycle,
    ModuleRecordRef,
    ModuleWorkRef,
)
from pds_core.registry_services import (
    AcademicWorkRegistrationRequest,
    AcademicWorkRegistrationServiceResult,
    RegistryServiceConflictError,
    RegistryServiceIntegrityError,
    RegistryServiceNotFoundError,
    RegistryServicePartialState,
    RegistryServicePartialSuccessError,
    RegistryServiceValidationError,
    RegistryServiceWriteError,
    register_academic_work,
    update_academic_work_registration,
)

from scoreform.assignment import load_assignment
from scoreform.pds_contract import (
    SCOREFORM_ACADEMIC_WORK_CONTRACT_VERSION,
    SCOREFORM_MODULE_ID,
)
from scoreform.work_paths import scoreform_work_paths

SCOREFORM_ACADEMIC_WORK_KIND = "assignment"
SCOREFORM_ASSIGNMENT_SOURCE_RECORD_KIND = "assignment"

SUPPORTED_ACADEMIC_INTENTS: tuple[AcademicWorkIntent, ...] = (
    "formative",
    "summative",
    "diagnostic",
    "practice",
    "feedback_only",
    "reporting_only",
)
SUPPORTED_ACADEMIC_WORK_LIFECYCLES: tuple[
    AcademicWorkRegistrationLifecycle, ...
] = ("planned", "active", "closed", "cancelled")


class ScoreFormAcademicWorkRegistrationError(Exception):
    """Base error for ScoreForm's Academic Work Registration boundary."""


class ScoreFormAcademicWorkRegistrationValidationError(
    ScoreFormAcademicWorkRegistrationError, ValueError
):
    """The caller input or managed assignment is invalid."""


class ScoreFormAcademicWorkRegistrationNotFoundError(
    ScoreFormAcademicWorkRegistrationError
):
    """The requested managed assignment or registration does not exist."""


class ScoreFormAcademicWorkRegistrationConflictError(
    ScoreFormAcademicWorkRegistrationError
):
    """Existing canonical state conflicts with the requested operation."""


class ScoreFormAcademicWorkRegistrationIntegrityError(
    ScoreFormAcademicWorkRegistrationError
):
    """Canonical registry state cannot be reconciled safely."""


class ScoreFormAcademicWorkRegistrationWriteError(
    ScoreFormAcademicWorkRegistrationError
):
    """Core could not durably complete the requested write."""


class ScoreFormAcademicWorkRegistrationPartialSuccessError(
    ScoreFormAcademicWorkRegistrationError
):
    """Core left durable state while completion remained uncertain."""

    def __init__(self, message: str, state: RegistryServicePartialState) -> None:
        super().__init__(message)
        self.state = state


@dataclass(frozen=True, slots=True)
class ManagedAssignmentRegistrationContext:
    """Validated, minimal snapshot needed to build one registration request."""

    work: ModuleWorkRef
    work_root: Path
    assignment_path: Path
    title: str


def load_managed_assignment_registration_context(
    workspace_root: str | Path,
    class_id: str,
    assignment_id: str,
) -> ManagedAssignmentRegistrationContext:
    """Validate and load one existing canonical managed ScoreForm assignment."""
    try:
        paths = scoreform_work_paths(workspace_root, class_id, assignment_id)
    except (TypeError, ValueError) as error:
        raise ScoreFormAcademicWorkRegistrationValidationError(str(error)) from error

    if paths.work_ref.module_id != SCOREFORM_MODULE_ID:
        raise ScoreFormAcademicWorkRegistrationValidationError(
            'work.module_id must be exactly "scoreform".'
        )
    if paths.work_root.is_symlink():
        raise ScoreFormAcademicWorkRegistrationValidationError(
            f"Managed work root must not be a symbolic link: {paths.work_root}"
        )
    if not paths.work_root.exists() or not paths.work_root.is_dir():
        raise ScoreFormAcademicWorkRegistrationNotFoundError(
            f"Managed assignment work root does not exist: {paths.work_root}. "
            "Create or set up the assignment first."
        )
    if paths.assignment_path.is_symlink():
        raise ScoreFormAcademicWorkRegistrationValidationError(
            f"assignment.json must not be a symbolic link: {paths.assignment_path}"
        )
    if not paths.assignment_path.exists() or not paths.assignment_path.is_file():
        raise ScoreFormAcademicWorkRegistrationNotFoundError(
            f"Managed assignment.json does not exist: {paths.assignment_path}"
        )

    diagnostics = io.StringIO()
    with contextlib.redirect_stdout(diagnostics):
        assignment = load_assignment(paths.assignment_path)
    if assignment is None:
        detail = diagnostics.getvalue().strip()
        message = f"Managed assignment.json is invalid: {paths.assignment_path}"
        if detail:
            message = f"{message}: {detail}"
        raise ScoreFormAcademicWorkRegistrationValidationError(message)
    if assignment["assignment_id"] != paths.work_ref.work_id:
        raise ScoreFormAcademicWorkRegistrationValidationError(
            "assignment.json assignment_id does not match its managed work directory."
        )

    return ManagedAssignmentRegistrationContext(
        work=paths.work_ref,
        work_root=paths.work_root,
        assignment_path=paths.assignment_path,
        title=assignment["title"],
    )


def build_scoreform_academic_work_registration_request(
    context: ManagedAssignmentRegistrationContext,
    *,
    academic_intent: AcademicWorkIntent,
    lifecycle: AcademicWorkRegistrationLifecycle,
) -> AcademicWorkRegistrationRequest:
    """Purely map a validated ScoreForm assignment context to Core's request."""
    if not isinstance(context, ManagedAssignmentRegistrationContext):
        raise ScoreFormAcademicWorkRegistrationValidationError(
            "context must be a ManagedAssignmentRegistrationContext."
        )
    work = context.work
    if getattr(work, "module_id", None) != SCOREFORM_MODULE_ID:
        raise ScoreFormAcademicWorkRegistrationValidationError(
            'work.module_id must be exactly "scoreform".'
        )
    if academic_intent not in ACADEMIC_WORK_INTENTS:
        raise ScoreFormAcademicWorkRegistrationValidationError(
            f"academic_intent must be one of: {', '.join(ACADEMIC_WORK_INTENTS)}."
        )
    if lifecycle not in ACADEMIC_WORK_REGISTRATION_LIFECYCLES:
        raise ScoreFormAcademicWorkRegistrationValidationError(
            "lifecycle must be one of: "
            f"{', '.join(ACADEMIC_WORK_REGISTRATION_LIFECYCLES)}."
        )
    try:
        return AcademicWorkRegistrationRequest(
            work=work,
            producer_contract_version=SCOREFORM_ACADEMIC_WORK_CONTRACT_VERSION,
            title=context.title,
            work_kind=SCOREFORM_ACADEMIC_WORK_KIND,
            academic_intent=academic_intent,
            lifecycle=lifecycle,
            source_records=(
                ModuleRecordRef(
                    module_id=SCOREFORM_MODULE_ID,
                    record_kind=SCOREFORM_ASSIGNMENT_SOURCE_RECORD_KIND,
                    record_id=work.work_id,
                    contract_version=None,
                ),
            ),
        )
    except (RegistryServiceValidationError, TypeError, ValueError) as error:
        raise ScoreFormAcademicWorkRegistrationValidationError(str(error)) from error


def load_current_scoreform_academic_work_registration(
    workspace_root: str | Path,
    class_id: str,
    assignment_id: str,
) -> AcademicWorkRegistration | None:
    """Load Core's explicit current selection for one ScoreForm assignment."""
    context = load_managed_assignment_registration_context(
        workspace_root, class_id, assignment_id
    )
    try:
        return load_current_academic_work_registration(workspace_root, context.work)
    except CoreStorageValidationError as error:
        raise ScoreFormAcademicWorkRegistrationValidationError(str(error)) from error
    except CoreStorageNotFoundError as error:
        raise ScoreFormAcademicWorkRegistrationNotFoundError(str(error)) from error
    except CoreStorageConflictError as error:
        raise ScoreFormAcademicWorkRegistrationConflictError(str(error)) from error
    except CoreStorageIntegrityError as error:
        raise ScoreFormAcademicWorkRegistrationIntegrityError(str(error)) from error
    except CoreStorageWriteError as error:
        raise ScoreFormAcademicWorkRegistrationWriteError(str(error)) from error
    except CoreStorageReadError as error:
        raise ScoreFormAcademicWorkRegistrationIntegrityError(str(error)) from error


def register_scoreform_academic_work(
    workspace_root: str | Path,
    class_id: str,
    assignment_id: str,
    *,
    academic_intent: AcademicWorkIntent,
    lifecycle: AcademicWorkRegistrationLifecycle,
) -> AcademicWorkRegistrationServiceResult:
    """Create revision 1 or return Core's exact existing registration."""
    context = load_managed_assignment_registration_context(
        workspace_root, class_id, assignment_id
    )
    request = build_scoreform_academic_work_registration_request(
        context, academic_intent=academic_intent, lifecycle=lifecycle
    )
    try:
        result = register_academic_work(workspace_root, request)
    except Exception as error:
        _raise_normalized_service_error(error)
    if result.disposition not in {"created", "existing"}:
        raise ScoreFormAcademicWorkRegistrationIntegrityError(
            f"Core returned unexpected registration disposition: {result.disposition}."
        )
    if result.disposition == "created" and result.registration.registration_revision != 1:
        raise ScoreFormAcademicWorkRegistrationIntegrityError(
            "Initial registration did not create revision 1."
        )
    _verify_current(workspace_root, context, result.registration)
    return result


def update_scoreform_academic_work_registration(
    workspace_root: str | Path,
    class_id: str,
    assignment_id: str,
    *,
    academic_intent: AcademicWorkIntent,
    lifecycle: AcademicWorkRegistrationLifecycle,
    expected_current_revision: int,
) -> AcademicWorkRegistrationServiceResult:
    """Update registration metadata with Core's optimistic revision check."""
    if (
        isinstance(expected_current_revision, bool)
        or not isinstance(expected_current_revision, int)
        or expected_current_revision < 1
    ):
        raise ScoreFormAcademicWorkRegistrationValidationError(
            "expected_current_revision must be a positive integer."
        )
    context = load_managed_assignment_registration_context(
        workspace_root, class_id, assignment_id
    )
    request = build_scoreform_academic_work_registration_request(
        context, academic_intent=academic_intent, lifecycle=lifecycle
    )
    try:
        result = update_academic_work_registration(
            workspace_root,
            request,
            expected_current_revision=expected_current_revision,
        )
    except Exception as error:
        _raise_normalized_service_error(error)
    if result.disposition not in {"updated", "existing"}:
        raise ScoreFormAcademicWorkRegistrationIntegrityError(
            f"Core returned unexpected update disposition: {result.disposition}."
        )
    _verify_current(workspace_root, context, result.registration)
    return result


def _verify_current(
    workspace_root: str | Path,
    context: ManagedAssignmentRegistrationContext,
    expected: AcademicWorkRegistration,
) -> None:
    try:
        current = load_current_academic_work_registration(workspace_root, context.work)
    except Exception as error:
        _raise_normalized_storage_error(error)
    if current != expected:
        raise ScoreFormAcademicWorkRegistrationIntegrityError(
            "Core's current registration does not equal the service result."
        )


def _raise_normalized_service_error(error: Exception) -> None:
    if isinstance(error, RegistryServicePartialSuccessError):
        raise ScoreFormAcademicWorkRegistrationPartialSuccessError(
            str(error), error.state
        ) from error
    mappings = (
        (RegistryServiceValidationError, ScoreFormAcademicWorkRegistrationValidationError),
        (RegistryServiceNotFoundError, ScoreFormAcademicWorkRegistrationNotFoundError),
        (RegistryServiceConflictError, ScoreFormAcademicWorkRegistrationConflictError),
        (RegistryServiceIntegrityError, ScoreFormAcademicWorkRegistrationIntegrityError),
        (RegistryServiceWriteError, ScoreFormAcademicWorkRegistrationWriteError),
    )
    for core_type, scoreform_type in mappings:
        if isinstance(error, core_type):
            raise scoreform_type(str(error)) from error
    raise error


def _raise_normalized_storage_error(error: Exception) -> None:
    mappings = (
        (CoreStorageValidationError, ScoreFormAcademicWorkRegistrationValidationError),
        (CoreStorageNotFoundError, ScoreFormAcademicWorkRegistrationNotFoundError),
        (CoreStorageConflictError, ScoreFormAcademicWorkRegistrationConflictError),
        (CoreStorageIntegrityError, ScoreFormAcademicWorkRegistrationIntegrityError),
        (CoreStorageWriteError, ScoreFormAcademicWorkRegistrationWriteError),
        (CoreStorageReadError, ScoreFormAcademicWorkRegistrationIntegrityError),
    )
    for core_type, scoreform_type in mappings:
        if isinstance(error, core_type):
            raise scoreform_type(str(error)) from error
    raise error
