"""Side-effect-free installed Core module profile and registration validator."""

from __future__ import annotations

import re
from typing import NoReturn

from pds_core.identifiers import IdentifierValidationError, validate_identifier
from pds_core.module_profiles import ModuleProfile, validate_module_profile
from pds_core.routing_models import (
    PDS2_SCHEMA,
    ROUTE_REGISTRATION_SCHEMA_VERSION,
    RouteRegistration,
    RoutingModelError,
    validate_route_registration,
)

from scoreform.answer_sheet_records import (
    AnswerSheetRecordError,
    validate_issuance_id,
    validate_page_id,
)
from scoreform.module_errors import ScoreFormRegistrationValidationError
from scoreform.pds_contract import (
    ANSWER_SHEET_PAGE_CONTRACT_VERSION,
    ANSWER_SHEET_PAGE_RECORD_KIND,
    DISPATCHABLE_ROUTE_STATUSES,
    SCOREFORM_DISPLAY_NAME,
    SCOREFORM_MODULE_ID,
    SUPPORTED_CORE_ROUTING_CONTRACT_VERSIONS,
    SUPPORTED_QR_SCHEMAS,
    SUPPORTED_ROUTE_REGISTRATION_SCHEMA_VERSIONS,
)

_MODULE_DETAIL_KEYS = frozenset({"issuance_id", "logical_page", "total_pages"})
_FALLBACK_PATTERN = re.compile(
    r"^ScoreForm \| class=([^| ]+) \| assignment=([^| ]+) \| "
    r"student=([^| ]+) \| page=([0-9]+)/([0-9]+) \| page_id=([^| ]+)$"
)


def _registration_failure(
    message: str, error: Exception | None = None
) -> NoReturn:
    failure = ScoreFormRegistrationValidationError(message)
    if error is None:
        raise failure
    raise failure from error


def validate_scoreform_registration(registration: RouteRegistration, /) -> None:
    """Purely require the exact ScoreForm answer-sheet route structure."""
    if not isinstance(registration, RouteRegistration):
        _registration_failure("registration must be a RouteRegistration.")
    try:
        validate_route_registration(registration)
    except (RoutingModelError, TypeError, ValueError) as error:
        _registration_failure("registration is not a valid Core routing model.", error)

    locator = registration.locator
    target = registration.target
    if registration.schema_version != ROUTE_REGISTRATION_SCHEMA_VERSION:
        _registration_failure('registration.schema_version must be "1".')
    if locator.schema != PDS2_SCHEMA:
        _registration_failure("registration.locator.schema must be PDS2.")
    if locator.module_id != SCOREFORM_MODULE_ID:
        _registration_failure(
            'registration.locator.module_id must be "scoreform".'
        )
    if registration.status != "active":
        _registration_failure('registration.status must be "active".')
    if target.module_id != SCOREFORM_MODULE_ID:
        _registration_failure('registration.target.module_id must be "scoreform".')
    if target.record_kind != ANSWER_SHEET_PAGE_RECORD_KIND:
        _registration_failure(
            'registration.target.record_kind must be "answer_sheet_page".'
        )
    if target.contract_version != ANSWER_SHEET_PAGE_CONTRACT_VERSION:
        _registration_failure('registration.target.contract_version must be "1".')
    try:
        validate_page_id(target.record_id)
    except AnswerSheetRecordError as error:
        _registration_failure("registration.target.record_id is not a page_id.", error)

    details = registration.module_details
    if frozenset(details) != _MODULE_DETAIL_KEYS:
        _registration_failure(
            "registration.module_details must contain exactly issuance_id, "
            "logical_page, and total_pages."
        )
    try:
        validate_issuance_id(details["issuance_id"])
    except AnswerSheetRecordError as error:
        _registration_failure("module_details.issuance_id is invalid.", error)
    for field_name in ("logical_page", "total_pages"):
        value = details[field_name]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            _registration_failure(
                f"module_details.{field_name} must be an integer greater than or equal to one."
            )
    logical_page = details["logical_page"]
    total_pages = details["total_pages"]
    assert isinstance(logical_page, int) and isinstance(total_pages, int)
    if logical_page > total_pages:
        _registration_failure(
            "module_details.logical_page must not exceed total_pages."
        )

    match = _FALLBACK_PATTERN.fullmatch(registration.human_fallback)
    if match is None:
        _registration_failure(
            "human_fallback does not use the exact ScoreForm page grammar."
        )
    class_id, assignment_id, student_id, logical, total, page_id = match.groups()
    try:
        validate_identifier(class_id, "fallback class_id")
        validate_identifier(assignment_id, "fallback assignment_id")
        validate_identifier(student_id, "fallback student_id")
        validate_page_id(page_id)
    except (IdentifierValidationError, AnswerSheetRecordError) as error:
        _registration_failure("human_fallback contains an unsafe identity.", error)
    if class_id != locator.class_id:
        _registration_failure("human_fallback class does not match the locator.")
    if assignment_id != locator.work_id:
        _registration_failure("human_fallback assignment does not match the locator.")
    if page_id != target.record_id:
        _registration_failure("human_fallback page_id does not match the target.")
    if int(logical) != logical_page or int(total) != total_pages:
        _registration_failure(
            "human_fallback page values do not match module_details."
        )
    return None


def get_module_profile() -> ModuleProfile:
    """Return ScoreForm's immutable installed Core 0.5 module profile."""
    from scoreform.route_handler import handle_scoreform_route

    return validate_module_profile(
        ModuleProfile(
            module_id=SCOREFORM_MODULE_ID,
            display_name=SCOREFORM_DISPLAY_NAME,
            supported_core_routing_contract_versions=(
                SUPPORTED_CORE_ROUTING_CONTRACT_VERSIONS
            ),
            supported_qr_schemas=SUPPORTED_QR_SCHEMAS,
            supported_route_registration_schema_versions=(
                SUPPORTED_ROUTE_REGISTRATION_SCHEMA_VERSIONS
            ),
            dispatchable_route_statuses=DISPATCHABLE_ROUTE_STATUSES,
            route_handler=handle_scoreform_route,
            registration_validator=validate_scoreform_registration,
        )
    )
