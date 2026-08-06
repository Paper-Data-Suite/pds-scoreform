"""Stable ScoreForm-owned constants for installed Core integration boundaries.

This side-effect-free module defines shared identities used by the routing,
Academic Work, manifest, and publication compatibility contracts.
"""

from pds_core.module_profiles import CORE_ROUTING_CONTRACT_VERSION
from pds_core.routing_models import (
    PDS2_SCHEMA,
    ROUTE_REGISTRATION_SCHEMA_VERSION,
)

SCOREFORM_MODULE_ID = "scoreform"
SCOREFORM_DISPLAY_NAME = "ScoreForm"
SCOREFORM_ACADEMIC_WORK_CONTRACT_VERSION = "scoreform_academic_work_v1"
ACADEMIC_RESULT_MANIFEST_CONTRACT_VERSION = (
    "scoreform_academic_result_manifest_v1"
)
ANSWER_SHEET_PAGE_RECORD_KIND = "answer_sheet_page"
ANSWER_SHEET_PAGE_CONTRACT_VERSION = "1"

SUPPORTED_CORE_ROUTING_CONTRACT_VERSIONS = frozenset(
    {CORE_ROUTING_CONTRACT_VERSION}
)
SUPPORTED_QR_SCHEMAS = frozenset({PDS2_SCHEMA})
SUPPORTED_ROUTE_REGISTRATION_SCHEMA_VERSIONS = frozenset(
    {ROUTE_REGISTRATION_SCHEMA_VERSION}
)
DISPATCHABLE_ROUTE_STATUSES = frozenset({"active"})
