"""Immutable installed Core publication compatibility metadata for ScoreForm."""

from pds_core.publication_compatibility import (
    PublicationContractSupport,
    PublicationProducerProfile,
    validate_publication_producer_profile,
)
from pds_core.publication_records import PUBLICATION_RECORD_SCHEMA_VERSION

from scoreform.pds_contract import (
    ACADEMIC_RESULT_MANIFEST_CONTRACT_VERSION,
    SCOREFORM_ACADEMIC_WORK_CONTRACT_VERSION,
    SCOREFORM_DISPLAY_NAME,
    SCOREFORM_MODULE_ID,
)


def get_publication_producer_profile() -> PublicationProducerProfile:
    """Return ScoreForm's validated, metadata-only publication profile."""
    return validate_publication_producer_profile(
        PublicationProducerProfile(
            module_id=SCOREFORM_MODULE_ID,
            display_name=SCOREFORM_DISPLAY_NAME,
            supported_core_publication_schema_versions=frozenset(
                {PUBLICATION_RECORD_SCHEMA_VERSION}
            ),
            supported_academic_work_contract_versions=frozenset(
                {SCOREFORM_ACADEMIC_WORK_CONTRACT_VERSION}
            ),
            publication_contracts=(
                PublicationContractSupport(
                    publication_kind="academic_result_set",
                    manifest_contract_versions=frozenset(
                        {ACADEMIC_RESULT_MANIFEST_CONTRACT_VERSION}
                    ),
                    supported_capabilities=frozenset(
                        {"points", "question_evidence", "multiple_attempts"}
                    ),
                    source_record_contracts=(),
                    allows_missing_source_record=True,
                ),
            ),
        )
    )
