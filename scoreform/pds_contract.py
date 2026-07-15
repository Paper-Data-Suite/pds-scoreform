"""Stable ScoreForm-owned constants for the PDS2 integration boundary.

This module is intentionally side-effect free. Later migration issues will use
these values to define module profiles, page records, route registrations, and
dispatch behavior.
"""

from pds_core.module_profiles import CORE_ROUTING_CONTRACT_VERSION
from pds_core.routing_models import (
    PDS2_SCHEMA,
    ROUTE_REGISTRATION_SCHEMA_VERSION,
)

SCOREFORM_MODULE_ID = "scoreform"
SCOREFORM_DISPLAY_NAME = "ScoreForm"
ANSWER_SHEET_PAGE_RECORD_KIND = "answer_sheet_page"
ANSWER_SHEET_PAGE_CONTRACT_VERSION = "1"

SUPPORTED_CORE_ROUTING_CONTRACT_VERSIONS = frozenset(
    {CORE_ROUTING_CONTRACT_VERSION}
)
SUPPORTED_QR_SCHEMAS = frozenset({PDS2_SCHEMA})
SUPPORTED_ROUTE_REGISTRATION_SCHEMA_VERSIONS = frozenset(
    {ROUTE_REGISTRATION_SCHEMA_VERSION}
)
