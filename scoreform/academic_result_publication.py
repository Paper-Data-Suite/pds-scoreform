"""Explicit Core publication workflows for ScoreForm academic-result manifests.

ScoreForm owns manifest selection and producer policy.  Core owns every
canonical Publication Record, withdrawal, lock, identifier, timestamp, and the
derived catalog.  This module deliberately contains no JSON or SQLite writer.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, NoReturn, cast

from pds_core.academic_catalog import (
    AcademicCatalogBuildError,
    AcademicCatalogBuildResult,
    AcademicCatalogCompatibilityError,
    AcademicCatalogConflictError,
    AcademicCatalogError,
    AcademicCatalogIntegrityError,
    AcademicCatalogNotFoundError,
    AcademicCatalogReadError,
    AcademicCatalogSourceError,
    AcademicCatalogValidationError,
    CatalogPublication,
    PublicationCatalogQuery,
    load_academic_catalog_metadata,
    query_publication_catalog,
    rebuild_academic_catalog,
)
from pds_core.academic_work_registration_storage import (
    AcademicWorkRegistrationStorageError,
    load_academic_work_registration_revision,
    load_current_academic_work_registration,
)
from pds_core.academic_work_registrations import AcademicWorkRegistration
from pds_core.publication_compatibility import (
    PublicationCompatibilityResult,
    evaluate_publication_compatibility,
)
from pds_core.publication_records import (
    PublicationRecord,
    PublicationRecordError,
    PublicationWithdrawal,
    validate_publication_record_series,
)
from pds_core.publication_storage import (
    PublicationManifestError,
    PublicationManifestIntegrityError,
    PublicationManifestNotFoundError,
    PublicationStorageError,
    list_publication_record_set,
    verify_publication_manifest,
)
from pds_core.registry_services import (
    PublicationManifestRequest,
    PublicationServiceResult,
    PublicationWithdrawalRequest,
    RegistryServiceConflictError,
    RegistryServiceError,
    RegistryServiceIntegrityError,
    RegistryServiceNotFoundError,
    RegistryServicePartialSuccessError,
    RegistryServiceValidationError,
    RegistryServiceWriteError,
    get_canonical_publication_record,
    get_canonical_publication_withdrawal,
    publish_manifest_revision,
    supersede_manifest_revision,
    withdraw_publication,
)
from pds_core.routing_models import ModuleRecordRef, ModuleWorkRef

from scoreform.academic_result_manifest_generation import (
    AcademicResultManifestGenerationResult,
    ScoreFormManifestGenerationError,
    ScoreFormManifestGenerationPartialSuccessError,
    StoredAcademicResultManifest,
    generate_academic_result_manifest,
    list_academic_result_manifest_revisions,
    load_academic_result_manifest_revision,
)
from scoreform.academic_work_registration import (
    SCOREFORM_ACADEMIC_WORK_KIND,
    SCOREFORM_ASSIGNMENT_SOURCE_RECORD_KIND,
)
from scoreform.pds_contract import (
    ACADEMIC_RESULT_MANIFEST_CONTRACT_VERSION,
    SCOREFORM_ACADEMIC_WORK_CONTRACT_VERSION,
    SCOREFORM_MODULE_ID,
)
from scoreform.pds_publication import get_publication_producer_profile
from scoreform.publication_revision_policy import (
    SCOREFORM_ACADEMIC_RESULT_PUBLICATION_KIND,
    SCOREFORM_ACADEMIC_RESULT_RECORD_SET_ID,
    PublicationSupersessionRequirement,
    require_publication_supersession,
)
from scoreform.work_paths import (
    academic_result_manifest_relative_path,
    scoreform_work_ref,
)

SCOREFORM_PUBLICATION_CAPABILITIES = (
    "multiple_attempts",
    "points",
    "question_evidence",
)

WithdrawalManifestVerification = Literal[
    "verified",
    "missing",
    "digest_mismatch_or_unsafe",
    "unreadable",
]
_WITHDRAWAL_MANIFEST_VERIFICATIONS = frozenset(
    {"verified", "missing", "digest_mismatch_or_unsafe", "unreadable"}
)


class ScoreFormAcademicResultPublicationError(Exception):
    """Base error for ScoreForm's publication-management boundary."""


class ScoreFormAcademicResultPublicationValidationError(
    ScoreFormAcademicResultPublicationError, ValueError
):
    """Caller input is malformed or outside ScoreForm's publication series."""


class ScoreFormAcademicResultPublicationNotFoundError(
    ScoreFormAcademicResultPublicationError
):
    """Required producer or canonical state does not exist."""


class ScoreFormAcademicResultPublicationConflictError(
    ScoreFormAcademicResultPublicationError
):
    """Current immutable state conflicts with the requested transition."""


class ScoreFormAcademicResultPublicationIntegrityError(
    ScoreFormAcademicResultPublicationError
):
    """Producer, canonical, or derived state is contradictory."""


class ScoreFormAcademicResultPublicationWriteError(
    ScoreFormAcademicResultPublicationError
):
    """Core could not safely complete a write or catalog operation."""


@dataclass(frozen=True, slots=True)
class PublicationCatalogReconciliation:
    """Full Core catalog rebuild plus the exact reconciled publication row."""

    build: AcademicCatalogBuildResult
    publication: CatalogPublication

    def __post_init__(self) -> None:
        if not isinstance(self.build, AcademicCatalogBuildResult):
            raise TypeError("build must be an AcademicCatalogBuildResult.")
        if not isinstance(self.publication, CatalogPublication):
            raise TypeError("publication must be a CatalogPublication.")


@dataclass(frozen=True, slots=True)
class ScoreFormPublicationSeriesState:
    """Canonical series and optional read-only catalog projection."""

    work: ModuleWorkRef
    publications: tuple[PublicationRecord, ...]
    withdrawals: tuple[PublicationWithdrawal, ...]
    producer_revisions: tuple[int, ...]
    producer_head: StoredAcademicResultManifest | None
    core_head: PublicationRecord | None
    core_head_withdrawal: PublicationWithdrawal | None
    current_selectable_publication: PublicationRecord | None
    derived_catalog_available: bool
    derived_catalog_rows: tuple[CatalogPublication, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.work, ModuleWorkRef):
            raise TypeError("work must be a ModuleWorkRef.")
        object.__setattr__(self, "publications", tuple(self.publications))
        object.__setattr__(self, "withdrawals", tuple(self.withdrawals))
        object.__setattr__(self, "producer_revisions", tuple(self.producer_revisions))
        object.__setattr__(self, "derived_catalog_rows", tuple(self.derived_catalog_rows))
        if any(not isinstance(item, PublicationRecord) for item in self.publications):
            raise TypeError("publications must contain PublicationRecord values.")
        if any(not isinstance(item, PublicationWithdrawal) for item in self.withdrawals):
            raise TypeError("withdrawals must contain PublicationWithdrawal values.")
        if any(isinstance(item, bool) or not isinstance(item, int) or item < 1 for item in self.producer_revisions):
            raise TypeError("producer_revisions must contain positive integers.")
        if self.producer_head is not None and not isinstance(
            self.producer_head, StoredAcademicResultManifest
        ):
            raise TypeError("producer_head must be a StoredAcademicResultManifest or None.")
        for name in ("core_head", "current_selectable_publication"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, PublicationRecord):
                raise TypeError(f"{name} must be a PublicationRecord or None.")
        if self.core_head_withdrawal is not None and not isinstance(
            self.core_head_withdrawal, PublicationWithdrawal
        ):
            raise TypeError("core_head_withdrawal must be a PublicationWithdrawal or None.")
        if not isinstance(self.derived_catalog_available, bool):
            raise TypeError("derived_catalog_available must be Boolean.")
        if any(
            not isinstance(item, CatalogPublication)
            for item in self.derived_catalog_rows
        ):
            raise TypeError(
                "derived_catalog_rows must contain CatalogPublication values."
            )
        if tuple(sorted(set(self.producer_revisions))) != self.producer_revisions:
            raise ValueError(
                "producer_revisions must be unique and strictly ascending."
            )
        if (self.producer_head is None) != (not self.producer_revisions):
            raise ValueError(
                "producer_head presence must agree with producer_revisions."
            )
        if (
            self.producer_head is not None
            and self.producer_head.revision != self.producer_revisions[-1]
        ):
            raise ValueError(
                "producer_head must be the greatest producer revision."
            )
        try:
            validated_series = validate_publication_record_series(self.publications)
        except PublicationRecordError as error:
            raise ValueError("publications do not form a valid Core series.") from error
        for publication in validated_series:
            _validate_scoreform_publication_record(
                publication,
                expected_work=self.work,
            )
        publication_ids = {
            publication.publication_id for publication in self.publications
        }
        withdrawal_ids = tuple(
            withdrawal.publication_id for withdrawal in self.withdrawals
        )
        if len(set(withdrawal_ids)) != len(withdrawal_ids):
            raise ValueError("withdrawals must not contain duplicate publication IDs.")
        if not set(withdrawal_ids).issubset(publication_ids):
            raise ValueError("withdrawals must belong to publications in the series.")
        expected_head = _series_head(self.publications)
        if self.core_head != expected_head:
            raise ValueError("core_head disagrees with the canonical supersession chain.")
        if self.core_head_withdrawal is not None and (
            self.core_head is None
            or self.core_head_withdrawal.publication_id != self.core_head.publication_id
        ):
            raise ValueError("core_head_withdrawal must belong to core_head.")
        expected_selectable = (
            self.core_head
            if self.core_head is not None and self.core_head_withdrawal is None
            else None
        )
        if self.current_selectable_publication != expected_selectable:
            raise ValueError(
                "current_selectable_publication disagrees with Core-head state."
            )

    @property
    def head(self) -> PublicationRecord | None:
        """Compatibility alias for the canonical Core chain head."""
        return self.core_head

    @property
    def producer_head_revision(self) -> int | None:
        return None if self.producer_head is None else self.producer_head.revision

    @property
    def catalog_available(self) -> bool:
        return self.derived_catalog_available

    @property
    def catalog_rows(self) -> tuple[CatalogPublication, ...]:
        return self.derived_catalog_rows


PublicationOperation = Literal[
    "publish", "supersede", "republish_after_withdrawal", "withdraw"
]


@dataclass(frozen=True, slots=True)
class AcademicResultPublicationResult:
    """Verified canonical and derived result of one explicit workflow."""

    operation: PublicationOperation
    disposition: Literal["created", "existing"]
    publication: PublicationRecord
    withdrawal: PublicationWithdrawal | None
    registration: AcademicWorkRegistration
    compatibility: PublicationCompatibilityResult
    catalog: PublicationCatalogReconciliation
    manifest_generation: AcademicResultManifestGenerationResult | None = None
    supersession_requirement: PublicationSupersessionRequirement | None = None

    def __post_init__(self) -> None:
        if self.operation not in {"publish", "supersede", "republish_after_withdrawal"}:
            raise ValueError("operation is invalid for a publication result.")
        if self.disposition not in {"created", "existing"}:
            raise ValueError("disposition must be created or existing.")
        if not isinstance(self.publication, PublicationRecord):
            raise TypeError("publication must be a PublicationRecord.")
        if self.withdrawal is not None and not isinstance(self.withdrawal, PublicationWithdrawal):
            raise TypeError("withdrawal must be a PublicationWithdrawal or None.")
        if not isinstance(self.registration, AcademicWorkRegistration):
            raise TypeError("registration must be an AcademicWorkRegistration.")
        if not isinstance(self.compatibility, PublicationCompatibilityResult):
            raise TypeError("compatibility must be a PublicationCompatibilityResult.")
        if not isinstance(self.catalog, PublicationCatalogReconciliation):
            raise TypeError("catalog must be a PublicationCatalogReconciliation.")
        if self.supersession_requirement is not None and not isinstance(
            self.supersession_requirement, PublicationSupersessionRequirement
        ):
            raise TypeError("supersession_requirement has the wrong type.")


@dataclass(frozen=True, slots=True)
class AcademicResultWithdrawalResult:
    """Verified withdrawal and its rebuilt catalog row."""

    disposition: Literal["created", "existing"]
    publication: PublicationRecord
    withdrawal: PublicationWithdrawal
    catalog: PublicationCatalogReconciliation
    manifest_verification: WithdrawalManifestVerification

    def __post_init__(self) -> None:
        if self.disposition not in {"created", "existing"}:
            raise ValueError("disposition must be created or existing.")
        if not isinstance(self.publication, PublicationRecord):
            raise TypeError("publication must be a PublicationRecord.")
        if not isinstance(self.withdrawal, PublicationWithdrawal):
            raise TypeError("withdrawal must be a PublicationWithdrawal.")
        if not isinstance(self.catalog, PublicationCatalogReconciliation):
            raise TypeError("catalog must be a PublicationCatalogReconciliation.")
        if self.manifest_verification not in _WITHDRAWAL_MANIFEST_VERIFICATIONS:
            raise ValueError("manifest_verification is invalid.")


@dataclass(frozen=True, slots=True)
class PublicationPartialSuccessState:
    """Durable state known after later verification/reconciliation failed."""

    operation: str
    publication: PublicationRecord | None
    withdrawal: PublicationWithdrawal | None
    manifest: StoredAcademicResultManifest | None
    canonical_state: Literal["uncertain", "confirmed"]
    catalog_rebuild_attempted: bool
    catalog_replacement_completed: bool
    catalog_verification_completed: bool
    recommended_next_action: str
    catalog_build: AcademicCatalogBuildResult | None = None
    catalog_error: Exception | None = None
    withdrawal_manifest_verification: WithdrawalManifestVerification | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.operation, str) or not self.operation:
            raise ValueError("operation must be nonempty.")
        if self.publication is not None and not isinstance(self.publication, PublicationRecord):
            raise TypeError("publication must be a PublicationRecord or None.")
        if self.withdrawal is not None and not isinstance(self.withdrawal, PublicationWithdrawal):
            raise TypeError("withdrawal must be a PublicationWithdrawal or None.")
        if self.manifest is not None and not isinstance(self.manifest, StoredAcademicResultManifest):
            raise TypeError("manifest must be a StoredAcademicResultManifest or None.")
        if self.canonical_state not in {"uncertain", "confirmed"}:
            raise ValueError("canonical_state must be uncertain or confirmed.")
        for name in (
            "catalog_rebuild_attempted",
            "catalog_replacement_completed",
            "catalog_verification_completed",
        ):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} must be Boolean.")
        if self.catalog_replacement_completed and not self.catalog_rebuild_attempted:
            raise ValueError("catalog replacement requires a rebuild attempt.")
        if self.catalog_verification_completed and not self.catalog_replacement_completed:
            raise ValueError("catalog verification requires completed replacement.")
        if self.catalog_replacement_completed and self.catalog_build is None:
            raise ValueError(
                "completed catalog replacement requires its build result."
            )
        if self.catalog_build is not None and not isinstance(
            self.catalog_build, AcademicCatalogBuildResult
        ):
            raise TypeError("catalog_build must be an AcademicCatalogBuildResult or None.")
        if self.catalog_error is not None and not isinstance(
            self.catalog_error, Exception
        ):
            raise TypeError("catalog_error must be an Exception or None.")
        if (
            self.withdrawal_manifest_verification is not None
            and self.withdrawal_manifest_verification
            not in _WITHDRAWAL_MANIFEST_VERIFICATIONS
        ):
            raise ValueError("withdrawal_manifest_verification is invalid.")
        if not isinstance(self.recommended_next_action, str) or not self.recommended_next_action:
            raise ValueError("recommended_next_action must be nonempty.")

    @property
    def canonical_state_confirmed(self) -> bool:
        return self.canonical_state == "confirmed"

    @property
    def catalog_installed(self) -> bool:
        return self.catalog_replacement_completed

    @property
    def catalog_verified(self) -> bool:
        return self.catalog_verification_completed


class ScoreFormAcademicResultPublicationPartialSuccessError(
    ScoreFormAcademicResultPublicationError
):
    """Canonical or producer state is durable but later completion failed."""

    def __init__(self, message: str, state: PublicationPartialSuccessState) -> None:
        super().__init__(message)
        self.state = state


def _work(class_id: str, assignment_id: str) -> ModuleWorkRef:
    try:
        return scoreform_work_ref(class_id, assignment_id)
    except (TypeError, ValueError) as error:
        raise ScoreFormAcademicResultPublicationValidationError(str(error)) from error


def _validate_scoreform_publication_record(
    publication: PublicationRecord,
    *,
    expected_work: ModuleWorkRef,
) -> PublicationRecord:
    if not isinstance(publication, PublicationRecord):
        raise ScoreFormAcademicResultPublicationIntegrityError(
            "Canonical publication has the wrong model type."
        )
    try:
        expected_path = academic_result_manifest_relative_path(
            expected_work,
            publication.record_set_revision,
        )
    except (TypeError, ValueError) as error:
        raise ScoreFormAcademicResultPublicationIntegrityError(
            "Canonical publication has an invalid producer revision."
        ) from error
    if (
        publication.work != expected_work
        or publication.publication_kind
        != SCOREFORM_ACADEMIC_RESULT_PUBLICATION_KIND
        or publication.record_set_id != SCOREFORM_ACADEMIC_RESULT_RECORD_SET_ID
        or publication.source_record is not None
        or publication.manifest_contract_version
        != ACADEMIC_RESULT_MANIFEST_CONTRACT_VERSION
        or publication.capabilities != SCOREFORM_PUBLICATION_CAPABILITIES
        or publication.manifest_path != expected_path
    ):
        raise ScoreFormAcademicResultPublicationIntegrityError(
            "Canonical publication contradicts ScoreForm's exact production contract."
        )
    return publication


def _series_head(records: tuple[PublicationRecord, ...]) -> PublicationRecord | None:
    try:
        series = validate_publication_record_series(records)
    except PublicationRecordError as error:
        raise ScoreFormAcademicResultPublicationIntegrityError(str(error)) from error
    if not series:
        return None
    superseded = {
        item.supersedes_publication_id
        for item in series
        if item.supersedes_publication_id is not None
    }
    heads = tuple(item for item in series if item.publication_id not in superseded)
    if len(heads) != 1:
        raise ScoreFormAcademicResultPublicationIntegrityError(
            "Canonical publication series does not have exactly one head."
        )
    return heads[0]


def _load_series(root: str | Path, work: ModuleWorkRef) -> tuple[PublicationRecord, ...]:
    try:
        records = cast(
            tuple[PublicationRecord, ...],
            list_publication_record_set(
                root,
                work,
                SCOREFORM_ACADEMIC_RESULT_PUBLICATION_KIND,
                SCOREFORM_ACADEMIC_RESULT_RECORD_SET_ID,
            ),
        )
    except PublicationStorageError as error:
        raise ScoreFormAcademicResultPublicationIntegrityError(str(error)) from error
    for publication in records:
        _validate_scoreform_publication_record(
            publication,
            expected_work=work,
        )
    return records


def _catalog_query(work: ModuleWorkRef) -> PublicationCatalogQuery:
    return PublicationCatalogQuery(
        class_id=work.class_id,
        module_id=work.module_id,
        work_id=work.work_id,
        publication_kind=SCOREFORM_ACADEMIC_RESULT_PUBLICATION_KIND,
        record_set_id=SCOREFORM_ACADEMIC_RESULT_RECORD_SET_ID,
        state="all",
    )


def load_scoreform_publication_series_status(
    workspace_root: str | Path,
    class_id: str,
    assignment_id: str,
) -> ScoreFormPublicationSeriesState:
    """Load canonical series status without creating a missing catalog."""
    work = _work(class_id, assignment_id)
    records = _load_series(workspace_root, work)
    try:
        history = list_academic_result_manifest_revisions(workspace_root, work)
    except ScoreFormManifestGenerationError as error:
        raise ScoreFormAcademicResultPublicationIntegrityError(str(error)) from error
    withdrawals: list[PublicationWithdrawal] = []
    for record in records:
        try:
            item = get_canonical_publication_withdrawal(
                workspace_root, record.publication_id
            )
        except RegistryServiceError as error:
            _raise_registry(error)
        if item is not None:
            withdrawals.append(item)
    try:
        load_academic_catalog_metadata(workspace_root)
        rows = query_publication_catalog(workspace_root, _catalog_query(work))
        available = True
    except AcademicCatalogNotFoundError:
        rows = ()
        available = False
    except AcademicCatalogError as error:
        raise ScoreFormAcademicResultPublicationIntegrityError(str(error)) from error
    core_head = _series_head(records)
    withdrawal_by_id = {item.publication_id: item for item in withdrawals}
    core_head_withdrawal = (
        None if core_head is None else withdrawal_by_id.get(core_head.publication_id)
    )
    return ScoreFormPublicationSeriesState(
        work=work,
        publications=records,
        withdrawals=tuple(withdrawals),
        producer_revisions=tuple(item.revision for item in history),
        producer_head=history[-1] if history else None,
        core_head=core_head,
        core_head_withdrawal=core_head_withdrawal,
        current_selectable_publication=(
            core_head if core_head is not None and core_head_withdrawal is None else None
        ),
        derived_catalog_available=available,
        derived_catalog_rows=rows,
    )


def load_scoreform_publication(
    workspace_root: str | Path,
    class_id: str,
    assignment_id: str,
    publication_id: str,
) -> tuple[PublicationRecord, PublicationWithdrawal | None]:
    """Load one exact canonical publication and require ScoreForm series ownership."""
    work = _work(class_id, assignment_id)
    try:
        publication = get_canonical_publication_record(workspace_root, publication_id)
        withdrawal = get_canonical_publication_withdrawal(workspace_root, publication_id)
    except RegistryServiceError as error:
        _raise_registry(error)
    _validate_scoreform_publication_record(
        publication,
        expected_work=work,
    )
    return publication, withdrawal


def _producer_head(
    root: str | Path, work: ModuleWorkRef, revision: int
) -> StoredAcademicResultManifest:
    try:
        history = list_academic_result_manifest_revisions(root, work)
    except ScoreFormManifestGenerationError as error:
        raise ScoreFormAcademicResultPublicationIntegrityError(str(error)) from error
    if not history:
        raise ScoreFormAcademicResultPublicationNotFoundError(
            "No immutable academic-result manifest exists."
        )
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise ScoreFormAcademicResultPublicationValidationError(
            "manifest_revision must be a positive integer."
        )
    if history[-1].revision != revision:
        raise ScoreFormAcademicResultPublicationConflictError(
            "Selected manifest revision is not the producer head."
        )
    return history[-1]


def _current_registration(
    root: str | Path, work: ModuleWorkRef
) -> AcademicWorkRegistration:
    try:
        registration = load_current_academic_work_registration(root, work)
    except AcademicWorkRegistrationStorageError as error:
        raise ScoreFormAcademicResultPublicationIntegrityError(str(error)) from error
    if registration is None:
        raise ScoreFormAcademicResultPublicationNotFoundError(
            "No current Academic Work Registration exists."
        )
    if not isinstance(registration, AcademicWorkRegistration):
        raise ScoreFormAcademicResultPublicationIntegrityError(
            "Current Academic Work Registration has the wrong model type."
        )
    expected_source = ModuleRecordRef(
        module_id=SCOREFORM_MODULE_ID,
        record_kind=SCOREFORM_ASSIGNMENT_SOURCE_RECORD_KIND,
        record_id=work.work_id,
        contract_version=None,
    )
    if registration.work != work:
        raise ScoreFormAcademicResultPublicationIntegrityError(
            "Current Academic Work Registration has the wrong work identity."
        )
    if (
        registration.producer_contract_version
        != SCOREFORM_ACADEMIC_WORK_CONTRACT_VERSION
    ):
        raise ScoreFormAcademicResultPublicationIntegrityError(
            "Current Academic Work Registration has an unsupported producer contract."
        )
    if registration.work_kind != SCOREFORM_ACADEMIC_WORK_KIND:
        raise ScoreFormAcademicResultPublicationIntegrityError(
            "Current Academic Work Registration has the wrong work kind."
        )
    if registration.source_records != (expected_source,):
        raise ScoreFormAcademicResultPublicationIntegrityError(
            "Current Academic Work Registration has the wrong assignment source."
        )
    if registration.lifecycle == "cancelled":
        raise ScoreFormAcademicResultPublicationConflictError(
            "A cancelled Academic Work Registration cannot be published."
        )
    return registration


def _request(
    stored: StoredAcademicResultManifest,
    registration: AcademicWorkRegistration,
) -> PublicationManifestRequest:
    try:
        return PublicationManifestRequest(
            work=registration.work,
            source_record=None,
            publication_kind=SCOREFORM_ACADEMIC_RESULT_PUBLICATION_KIND,
            capabilities=SCOREFORM_PUBLICATION_CAPABILITIES,
            record_set_id=SCOREFORM_ACADEMIC_RESULT_RECORD_SET_ID,
            record_set_revision=stored.revision,
            manifest_contract_version=ACADEMIC_RESULT_MANIFEST_CONTRACT_VERSION,
            manifest_path=stored.relative_path,
            academic_work_registration_revision=registration.registration_revision,
            expected_manifest_digest=stored.sha256,
        )
    except (RegistryServiceValidationError, TypeError, ValueError) as error:
        raise ScoreFormAcademicResultPublicationValidationError(str(error)) from error


class _CatalogReconciliationFailure(Exception):
    def __init__(
        self,
        error: Exception,
        *,
        build: AcademicCatalogBuildResult | None,
        query_completed: bool,
    ) -> None:
        super().__init__(str(error))
        self.error = error
        self.build = build
        self.query_completed = query_completed


def _raise_catalog(error: AcademicCatalogError) -> NoReturn:
    if isinstance(error, AcademicCatalogValidationError):
        raise ScoreFormAcademicResultPublicationValidationError(str(error)) from error
    if isinstance(error, AcademicCatalogNotFoundError):
        raise ScoreFormAcademicResultPublicationNotFoundError(str(error)) from error
    if isinstance(error, AcademicCatalogConflictError):
        raise ScoreFormAcademicResultPublicationConflictError(str(error)) from error
    if isinstance(
        error,
        (
            AcademicCatalogSourceError,
            AcademicCatalogIntegrityError,
            AcademicCatalogCompatibilityError,
            AcademicCatalogReadError,
        ),
    ):
        raise ScoreFormAcademicResultPublicationIntegrityError(str(error)) from error
    if isinstance(error, AcademicCatalogBuildError):
        raise ScoreFormAcademicResultPublicationWriteError(str(error)) from error
    raise ScoreFormAcademicResultPublicationWriteError(str(error)) from error


def _reconcile_scoreform_publication_catalog(
    workspace_root: str | Path,
    work: ModuleWorkRef,
    publication: PublicationRecord,
    withdrawal: PublicationWithdrawal | None,
) -> PublicationCatalogReconciliation:
    try:
        build = rebuild_academic_catalog(workspace_root)
    except AcademicCatalogError as error:
        raise _CatalogReconciliationFailure(
            error,
            build=None,
            query_completed=False,
        ) from error
    try:
        rows = query_publication_catalog(workspace_root, _catalog_query(work))
    except AcademicCatalogError as error:
        raise _CatalogReconciliationFailure(
            error,
            build=build,
            query_completed=False,
        ) from error
    try:
        matches = tuple(
            row for row in rows if row.publication_id == publication.publication_id
        )
        if len(matches) != 1:
            raise ScoreFormAcademicResultPublicationIntegrityError(
                "Rebuilt catalog does not contain exactly one row for the publication."
            )
        row = matches[0]
        head = _series_head(_load_series(workspace_root, work))
        expected_head = (
            head is not None
            and head.publication_id == publication.publication_id
        )
        expected_withdrawn = withdrawal is not None
        canonical_values = (
            row.work,
            row.source_record,
            row.publication_kind,
            row.capabilities,
            row.record_set_id,
            row.record_set_revision,
            row.manifest_contract_version,
            row.manifest_path,
            row.manifest_digest_algorithm,
            row.manifest_digest,
            row.published_at,
            row.academic_work_registration_revision,
            row.supersedes_publication_id,
        )
        record_values = (
            publication.work,
            publication.source_record,
            publication.publication_kind,
            publication.capabilities,
            publication.record_set_id,
            publication.record_set_revision,
            publication.manifest_contract_version,
            publication.manifest_path,
            publication.manifest_digest_algorithm,
            publication.manifest_digest,
            publication.published_at,
            publication.academic_work_registration_revision,
            publication.supersedes_publication_id,
        )
        if (
            canonical_values != record_values
            or row.is_series_head != expected_head
            or row.is_withdrawn != expected_withdrawn
            or row.withdrawn_at
            != (withdrawal.withdrawn_at if withdrawal else None)
            or row.is_current_selectable
            != (expected_head and not expected_withdrawn)
        ):
            raise ScoreFormAcademicResultPublicationIntegrityError(
                "Rebuilt catalog row disagrees with canonical publication state."
            )
        return PublicationCatalogReconciliation(build=build, publication=row)
    except Exception as error:
        raise _CatalogReconciliationFailure(
            error,
            build=build,
            query_completed=True,
        ) from error


def rebuild_scoreform_publication_catalog(
    workspace_root: str | Path,
    class_id: str,
    assignment_id: str,
    publication_id: str,
) -> PublicationCatalogReconciliation:
    """Rebuild Core's full catalog and reconcile one exact canonical row."""
    work = _work(class_id, assignment_id)
    publication, withdrawal = load_scoreform_publication(
        workspace_root, class_id, assignment_id, publication_id
    )
    try:
        return _reconcile_scoreform_publication_catalog(
            workspace_root,
            work,
            publication,
            withdrawal,
        )
    except _CatalogReconciliationFailure as failure:
        if isinstance(failure.error, AcademicCatalogError):
            _raise_catalog(failure.error)
        if isinstance(
            failure.error,
            ScoreFormAcademicResultPublicationError,
        ):
            raise failure.error from failure
        raise ScoreFormAcademicResultPublicationIntegrityError(
            "Catalog reconciliation failed after Core rebuilt the catalog."
        ) from failure.error


def rebuild_full_academic_catalog(
    workspace_root: str | Path,
) -> AcademicCatalogBuildResult:
    """Explicitly rebuild Core's complete disposable academic catalog."""
    try:
        return rebuild_academic_catalog(workspace_root)
    except AcademicCatalogError as error:
        _raise_catalog(error)


def _verify_publication_result(
    root: str | Path,
    work: ModuleWorkRef,
    service: PublicationServiceResult,
    stored: StoredAcademicResultManifest,
    operation: PublicationOperation,
    *,
    generation: AcademicResultManifestGenerationResult | None = None,
    supersession_requirement: PublicationSupersessionRequirement | None = None,
) -> AcademicResultPublicationResult:
    catalog_attempted = False
    try:
        canonical, withdrawal = load_scoreform_publication(
            root, work.class_id, work.work_id, service.publication.publication_id
        )
        if canonical != service.publication or withdrawal != service.withdrawal:
            raise ScoreFormAcademicResultPublicationIntegrityError(
                "Canonical reload differs from Core's service result."
            )
        series = _load_series(root, work)
        if canonical not in validate_publication_record_series(series):
            raise ScoreFormAcademicResultPublicationIntegrityError(
                "Canonical publication is absent from its revalidated series."
            )
        resolved = verify_publication_manifest(root, canonical)
        if resolved != stored.path.resolve(strict=True):
            raise ScoreFormAcademicResultPublicationIntegrityError(
                "Core resolved a different manifest path."
            )
        revision = canonical.academic_work_registration_revision
        if revision is None:
            raise ScoreFormAcademicResultPublicationIntegrityError(
                "Academic publication has no registration revision."
            )
        registration = load_academic_work_registration_revision(root, work, revision)
        compatibility = evaluate_publication_compatibility(
            canonical, get_publication_producer_profile(), registration
        )
        if not compatibility.compatible or compatibility.codes != ():
            raise ScoreFormAcademicResultPublicationIntegrityError(
                "Publication is incompatible with ScoreForm's producer profile: "
                + ", ".join(compatibility.codes)
            )
        catalog_attempted = True
        try:
            catalog = _reconcile_scoreform_publication_catalog(
                root,
                work,
                canonical,
                withdrawal,
            )
        except _CatalogReconciliationFailure as failure:
            state = PublicationPartialSuccessState(
                operation=operation,
                publication=canonical,
                withdrawal=withdrawal,
                manifest=stored,
                canonical_state="confirmed",
                catalog_rebuild_attempted=True,
                catalog_replacement_completed=failure.build is not None,
                catalog_verification_completed=False,
                recommended_next_action=(
                    "Replay the exact operation or run rebuild-catalog."
                ),
                catalog_build=failure.build,
                catalog_error=failure.error,
            )
            raise ScoreFormAcademicResultPublicationPartialSuccessError(
                "Core publication is durable but catalog reconciliation failed.",
                state,
            ) from failure.error
        return AcademicResultPublicationResult(
            operation=operation,
            disposition=service.disposition,
            publication=canonical,
            withdrawal=withdrawal,
            registration=registration,
            compatibility=compatibility,
            catalog=catalog,
            manifest_generation=generation,
            supersession_requirement=supersession_requirement,
        )
    except ScoreFormAcademicResultPublicationPartialSuccessError:
        raise
    except Exception as error:
        state = PublicationPartialSuccessState(
            operation=operation,
            publication=service.publication,
            withdrawal=service.withdrawal,
            manifest=stored,
            canonical_state="confirmed",
            catalog_rebuild_attempted=catalog_attempted,
            catalog_replacement_completed=False,
            catalog_verification_completed=False,
            recommended_next_action=(
                "Replay the exact operation or run rebuild-catalog."
            ),
            catalog_error=error if catalog_attempted else None,
        )
        raise ScoreFormAcademicResultPublicationPartialSuccessError(
            "Core publication is durable but post-write verification failed.",
            state,
        ) from error


def publish_scoreform_academic_results(
    workspace_root: str | Path,
    class_id: str,
    assignment_id: str,
    *,
    manifest_revision: int,
) -> AcademicResultPublicationResult:
    """Publish the selected producer head, or reconcile its exact replay."""
    work = _work(class_id, assignment_id)
    stored = _producer_head(workspace_root, work, manifest_revision)
    registration = _current_registration(workspace_root, work)
    request = _request(stored, registration)
    try:
        service = publish_manifest_revision(workspace_root, request)
    except RegistryServiceError as error:
        _raise_registry(error, manifest=stored)
    return _verify_publication_result(
        workspace_root, work, service, stored, "publish"
    )


def supersede_scoreform_academic_results(
    workspace_root: str | Path,
    class_id: str,
    assignment_id: str,
    *,
    manifest_revision: int,
    expected_current_publication_id: str,
) -> AcademicResultPublicationResult:
    """Supersede the explicit canonical head with the selected producer head."""
    work = _work(class_id, assignment_id)
    stored = _producer_head(workspace_root, work, manifest_revision)
    registration = _current_registration(workspace_root, work)
    records = _load_series(workspace_root, work)
    logical = tuple(
        item for item in records if item.record_set_revision == stored.revision
    )
    if len(logical) > 1:
        raise ScoreFormAcademicResultPublicationIntegrityError(
            "Canonical logical publication revision is duplicated."
        )
    predecessor_record = next(
        (
            item
            for item in records
            if item.publication_id == expected_current_publication_id
        ),
        None,
    )
    if predecessor_record is None:
        raise ScoreFormAcademicResultPublicationConflictError(
            "Expected publication ID does not belong to the canonical series."
        )
    if not logical:
        head = _series_head(records)
        if head is None:
            raise ScoreFormAcademicResultPublicationNotFoundError(
                "Publication series does not exist."
            )
        if head.publication_id != expected_current_publication_id:
            raise ScoreFormAcademicResultPublicationConflictError(
                "Expected publication ID is not the canonical series head."
            )
        if stored.revision <= head.record_set_revision:
            raise ScoreFormAcademicResultPublicationConflictError(
                "Successor producer revision must be greater than the canonical head revision."
            )
    else:
        replay = logical[0]
        if replay.supersedes_publication_id != expected_current_publication_id:
            raise ScoreFormAcademicResultPublicationIntegrityError(
                "Existing logical revision has a contradictory predecessor."
            )
    try:
        predecessor = load_academic_result_manifest_revision(
            workspace_root, work, predecessor_record.record_set_revision
        )
        requirement = require_publication_supersession(
            predecessor.manifest,
            stored.manifest,
            expected_current_publication_id=expected_current_publication_id,
        )
    except ScoreFormManifestGenerationError as error:
        raise ScoreFormAcademicResultPublicationIntegrityError(str(error)) from error
    except Exception as error:
        raise ScoreFormAcademicResultPublicationConflictError(str(error)) from error
    expected_requirement = (
        expected_current_publication_id,
        SCOREFORM_ACADEMIC_RESULT_PUBLICATION_KIND,
        SCOREFORM_ACADEMIC_RESULT_RECORD_SET_ID,
        predecessor.revision,
        stored.revision,
    )
    actual_requirement = (
        requirement.expected_current_publication_id,
        requirement.publication_kind,
        requirement.record_set_id,
        requirement.predecessor_revision,
        requirement.successor_revision,
    )
    if actual_requirement != expected_requirement:
        raise ScoreFormAcademicResultPublicationIntegrityError(
            "Publication supersession requirement contradicts loaded canonical state."
        )
    request = _request(stored, registration)
    try:
        service = supersede_manifest_revision(
            workspace_root,
            request,
            expected_current_publication_id=requirement.expected_current_publication_id,
        )
    except RegistryServiceError as error:
        _raise_registry(error, manifest=stored)
    return _verify_publication_result(
        workspace_root,
        work,
        service,
        stored,
        "supersede",
        supersession_requirement=requirement,
    )


def republish_scoreform_academic_results_after_withdrawal(
    workspace_root: str | Path,
    class_id: str,
    assignment_id: str,
    *,
    expected_withdrawn_head_publication_id: str,
) -> AcademicResultPublicationResult:
    """Explicitly create/reuse a successor and supersede one withdrawn head."""
    work = _work(class_id, assignment_id)
    records = _load_series(workspace_root, work)
    head = _series_head(records)
    if head is None:
        raise ScoreFormAcademicResultPublicationNotFoundError(
            "Publication series does not exist."
        )
    expected_record = next(
        (
            item
            for item in records
            if item.publication_id == expected_withdrawn_head_publication_id
        ),
        None,
    )
    if expected_record is None:
        raise ScoreFormAcademicResultPublicationConflictError(
            "Expected publication ID does not belong to the canonical series."
        )
    exact_replay = (
        head.publication_id != expected_withdrawn_head_publication_id
        and head.supersedes_publication_id
        == expected_withdrawn_head_publication_id
    )
    if (
        head.publication_id != expected_withdrawn_head_publication_id
        and not exact_replay
    ):
        raise ScoreFormAcademicResultPublicationConflictError(
            "Expected publication ID is not the canonical series head."
        )
    try:
        withdrawn = get_canonical_publication_withdrawal(
            workspace_root, expected_record.publication_id
        )
    except RegistryServiceError as error:
        _raise_registry(error)
    if withdrawn is None:
        raise ScoreFormAcademicResultPublicationConflictError(
            "The exact canonical series head is not withdrawn."
        )
    try:
        history = list_academic_result_manifest_revisions(workspace_root, work)
    except ScoreFormManifestGenerationError as error:
        raise ScoreFormAcademicResultPublicationIntegrityError(str(error)) from error
    if exact_replay:
        if not history or history[-1].revision != head.record_set_revision:
            raise ScoreFormAcademicResultPublicationIntegrityError(
                "Canonical republication replay does not match the producer head."
            )
        stored = history[-1]
        generation = None
    elif history and history[-1].revision > head.record_set_revision:
        stored = history[-1]
        generation = None
    else:
        try:
            generation = generate_academic_result_manifest(
                workspace_root,
                class_id,
                assignment_id,
                republish_after_withdrawal=True,
            )
        except ScoreFormManifestGenerationPartialSuccessError as error:
            raise ScoreFormAcademicResultPublicationPartialSuccessError(
                "A republication manifest is durable but publication did not complete.",
                PublicationPartialSuccessState(
                    operation="republish_after_withdrawal",
                    publication=None,
                    withdrawal=withdrawn,
                    manifest=None,
                    canonical_state="confirmed",
                    catalog_rebuild_attempted=False,
                    catalog_replacement_completed=False,
                    catalog_verification_completed=False,
                    recommended_next_action="Retry republication; the durable producer revision will be reused.",
                ),
            ) from error
        except ScoreFormManifestGenerationError as error:
            raise ScoreFormAcademicResultPublicationWriteError(str(error)) from error
        stored = StoredAcademicResultManifest(
            generation.manifest,
            generation.revision,
            generation.path,
            generation.relative_path,
            generation.content,
            generation.sha256,
        )
    try:
        result = supersede_scoreform_academic_results(
            workspace_root,
            class_id,
            assignment_id,
            manifest_revision=stored.revision,
            expected_current_publication_id=expected_record.publication_id,
        )
    except ScoreFormAcademicResultPublicationPartialSuccessError as error:
        partial = error.state
        raise ScoreFormAcademicResultPublicationPartialSuccessError(
            str(error),
            PublicationPartialSuccessState(
                operation="republish_after_withdrawal",
                publication=partial.publication,
                withdrawal=partial.withdrawal or withdrawn,
                manifest=partial.manifest or stored,
                canonical_state=partial.canonical_state,
                catalog_rebuild_attempted=partial.catalog_rebuild_attempted,
                catalog_replacement_completed=partial.catalog_replacement_completed,
                catalog_verification_completed=partial.catalog_verification_completed,
                recommended_next_action=partial.recommended_next_action,
                catalog_build=partial.catalog_build,
                catalog_error=partial.catalog_error,
                withdrawal_manifest_verification=(
                    partial.withdrawal_manifest_verification
                ),
            ),
        ) from error
    except ScoreFormAcademicResultPublicationError as error:
        if generation is None:
            raise
        raise ScoreFormAcademicResultPublicationPartialSuccessError(
            "A successor manifest is durable but Core publication did not complete.",
            PublicationPartialSuccessState(
                operation="republish_after_withdrawal",
                publication=None,
                withdrawal=withdrawn,
                manifest=stored,
                canonical_state="confirmed",
                catalog_rebuild_attempted=False,
                catalog_replacement_completed=False,
                catalog_verification_completed=False,
                recommended_next_action="Retry republication; the durable producer revision will be reused.",
            ),
        ) from error
    return AcademicResultPublicationResult(
        operation="republish_after_withdrawal",
        disposition=result.disposition,
        publication=result.publication,
        withdrawal=result.withdrawal,
        registration=result.registration,
        compatibility=result.compatibility,
        catalog=result.catalog,
        manifest_generation=generation,
        supersession_requirement=result.supersession_requirement,
    )


def _verify_manifest_for_withdrawal(
    workspace_root: str | Path,
    publication: PublicationRecord,
) -> WithdrawalManifestVerification:
    try:
        verify_publication_manifest(workspace_root, publication)
        return "verified"
    except PublicationManifestNotFoundError:
        return "missing"
    except PublicationManifestIntegrityError:
        return "digest_mismatch_or_unsafe"
    except (PublicationManifestError, OSError):
        return "unreadable"


def withdraw_scoreform_academic_result_publication(
    workspace_root: str | Path,
    class_id: str,
    assignment_id: str,
    *,
    publication_id: str,
    reason: str,
) -> AcademicResultWithdrawalResult:
    """Withdraw one exact publication without rewriting producer evidence."""
    publication, _ = load_scoreform_publication(
        workspace_root, class_id, assignment_id, publication_id
    )
    manifest_verification = _verify_manifest_for_withdrawal(
        workspace_root,
        publication,
    )
    catalog_attempted = False
    try:
        service = withdraw_publication(
            workspace_root,
            PublicationWithdrawalRequest(publication_id=publication_id, reason=reason),
        )
    except RegistryServiceError as error:
        _raise_registry(
            error,
            withdrawal_manifest_verification=manifest_verification,
        )
    try:
        canonical, withdrawal = load_scoreform_publication(
            workspace_root, class_id, assignment_id, publication_id
        )
        if (
            canonical != publication
            or canonical != service.publication
            or withdrawal != service.withdrawal
        ):
            raise ScoreFormAcademicResultPublicationIntegrityError(
                "Canonical withdrawal reload differs from Core's service result."
            )
        validate_publication_record_series(
            _load_series(workspace_root, canonical.work)
        )
        catalog_attempted = True
        try:
            catalog = _reconcile_scoreform_publication_catalog(
                workspace_root,
                canonical.work,
                canonical,
                withdrawal,
            )
        except _CatalogReconciliationFailure as failure:
            state = PublicationPartialSuccessState(
                operation="withdraw",
                publication=canonical,
                withdrawal=withdrawal,
                manifest=None,
                canonical_state="confirmed",
                catalog_rebuild_attempted=True,
                catalog_replacement_completed=failure.build is not None,
                catalog_verification_completed=False,
                recommended_next_action=(
                    "Replay the exact withdrawal or run rebuild-catalog."
                ),
                catalog_build=failure.build,
                catalog_error=failure.error,
                withdrawal_manifest_verification=manifest_verification,
            )
            raise ScoreFormAcademicResultPublicationPartialSuccessError(
                "Core withdrawal is durable but catalog reconciliation failed.",
                state,
            ) from failure.error
        return AcademicResultWithdrawalResult(
            disposition=service.disposition,
            publication=canonical,
            withdrawal=service.withdrawal,
            catalog=catalog,
            manifest_verification=manifest_verification,
        )
    except ScoreFormAcademicResultPublicationPartialSuccessError:
        raise
    except Exception as error:
        state = PublicationPartialSuccessState(
            operation="withdraw",
            publication=service.publication,
            withdrawal=service.withdrawal,
            manifest=None,
            canonical_state="confirmed",
            catalog_rebuild_attempted=catalog_attempted,
            catalog_replacement_completed=False,
            catalog_verification_completed=False,
            recommended_next_action=(
                "Replay the exact withdrawal or run rebuild-catalog."
            ),
            catalog_error=error if catalog_attempted else None,
            withdrawal_manifest_verification=manifest_verification,
        )
        raise ScoreFormAcademicResultPublicationPartialSuccessError(
            "Core withdrawal is durable but post-write verification failed.",
            state,
        ) from error


def _raise_registry(
    error: Exception,
    *,
    manifest: StoredAcademicResultManifest | None = None,
    withdrawal_manifest_verification: WithdrawalManifestVerification | None = None,
) -> NoReturn:
    if isinstance(error, RegistryServicePartialSuccessError):
        core = error.state
        raise ScoreFormAcademicResultPublicationPartialSuccessError(
            str(error),
            PublicationPartialSuccessState(
                operation=core.operation,
                publication=core.publication,
                withdrawal=core.withdrawal,
                manifest=manifest,
                canonical_state="uncertain",
                catalog_rebuild_attempted=False,
                catalog_replacement_completed=False,
                catalog_verification_completed=False,
                recommended_next_action=(
                    "Replay the exact operation to reconcile canonical state."
                ),
                withdrawal_manifest_verification=(
                    withdrawal_manifest_verification
                ),
            ),
        ) from error
    mappings = (
        (RegistryServiceValidationError, ScoreFormAcademicResultPublicationValidationError),
        (RegistryServiceNotFoundError, ScoreFormAcademicResultPublicationNotFoundError),
        (RegistryServiceConflictError, ScoreFormAcademicResultPublicationConflictError),
        (RegistryServiceIntegrityError, ScoreFormAcademicResultPublicationIntegrityError),
        (RegistryServiceWriteError, ScoreFormAcademicResultPublicationWriteError),
    )
    for core_type, local_type in mappings:
        if isinstance(error, core_type):
            raise local_type(str(error)) from error
    raise error


__all__ = [
    "SCOREFORM_PUBLICATION_CAPABILITIES",
    "AcademicResultPublicationResult",
    "AcademicResultWithdrawalResult",
    "WithdrawalManifestVerification",
    "PublicationCatalogReconciliation",
    "PublicationPartialSuccessState",
    "ScoreFormPublicationSeriesState",
    "ScoreFormAcademicResultPublicationError",
    "ScoreFormAcademicResultPublicationValidationError",
    "ScoreFormAcademicResultPublicationNotFoundError",
    "ScoreFormAcademicResultPublicationConflictError",
    "ScoreFormAcademicResultPublicationIntegrityError",
    "ScoreFormAcademicResultPublicationWriteError",
    "ScoreFormAcademicResultPublicationPartialSuccessError",
    "load_scoreform_publication_series_status",
    "load_scoreform_publication",
    "publish_scoreform_academic_results",
    "supersede_scoreform_academic_results",
    "republish_scoreform_academic_results_after_withdrawal",
    "withdraw_scoreform_academic_result_publication",
    "rebuild_scoreform_publication_catalog",
    "rebuild_full_academic_catalog",
]
