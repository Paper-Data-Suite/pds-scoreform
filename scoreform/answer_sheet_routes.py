"""PDS2 route planning and persistence for managed answer-sheet pages.

The page record is ScoreForm's authority.  Core route registrations are an
immutable index to that record; ``human_fallback`` and ``module_details`` are
bounded diagnostics and never routing authority.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from pds_core.pds2 import parse_pds2_payload, serialize_pds2_payload
from pds_core.route_ids import generate_route_id
from pds_core.route_registrations import (
    load_route_registration,
    write_route_registration,
)
from pds_core.routes import route_registration_path
from pds_core.routing_models import (
    PDS2_SCHEMA,
    ROUTE_REGISTRATION_SCHEMA_VERSION,
    ModuleWorkRef,
    RouteLocator,
    RouteRegistration,
    RoutingModelError,
    validate_module_work_ref,
    validate_route_locator,
    validate_route_registration,
)

from scoreform.answer_sheet_persistence import (
    AnswerSheetPersistenceError,
    load_answer_sheet_page,
    load_answer_sheet_record_set,
)
from scoreform.answer_sheet_records import (
    AnswerSheetPage,
    AnswerSheetRecordError,
    AnswerSheetRecordSet,
    answer_sheet_page_target,
    validate_answer_sheet_page,
    validate_answer_sheet_record_set,
)
from scoreform.pds_contract import SCOREFORM_MODULE_ID

RouteIdGenerator = Callable[[], str]
_ROUTE_ID_PATTERN = re.compile(r"^rt_[0-9a-f]{32}$")
_MODULE_DETAIL_KEYS = frozenset({"issuance_id", "logical_page", "total_pages"})


class AnswerSheetRouteError(Exception):
    """Base class for typed answer-sheet route failures."""


class AnswerSheetRouteValidationError(AnswerSheetRouteError, ValueError):
    """Raised when a route model violates the ScoreForm route contract."""


class AnswerSheetRoutePlanningError(AnswerSheetRouteError):
    """Raised when a complete route set cannot be planned."""


class AnswerSheetRouteCollisionError(AnswerSheetRoutePlanningError):
    """Raised when a route identity or canonical route path already exists."""


class AnswerSheetRoutePersistenceError(AnswerSheetRouteError):
    """Raised when Core cannot durably persist a planned registration."""


class AnswerSheetRouteIntegrityError(AnswerSheetRoutePersistenceError):
    """Raised when persisted ScoreForm or Core data differs from its plan."""


class AnswerSheetGenerationOrchestrationError(AnswerSheetRouteError):
    """Base error used by the managed generation service."""


@dataclass(frozen=True, slots=True)
class AnswerSheetPageRoute:
    """One pure, validated route plan for one immutable physical page."""

    page: AnswerSheetPage
    locator: RouteLocator
    registration: RouteRegistration
    payload_text: str


@dataclass(frozen=True, slots=True)
class RegisteredAnswerSheetPageRoute:
    """A route that was persisted and reloaded from its canonical Core path."""

    route: AnswerSheetPageRoute
    registration_path: Path

    @property
    def page(self) -> AnswerSheetPage:
        return self.route.page

    @property
    def locator(self) -> RouteLocator:
        return self.route.locator

    @property
    def registration(self) -> RouteRegistration:
        return self.route.registration

    @property
    def payload_text(self) -> str:
        return self.route.payload_text


@dataclass(frozen=True, slots=True)
class PersistedAnswerSheetRouteSet:
    """Ordered registrations created and verified for one issuance."""

    routes: tuple[RegisteredAnswerSheetPageRoute, ...]

    @property
    def registration_paths(self) -> tuple[Path, ...]:
        return tuple(route.registration_path for route in self.routes)


def validate_route_id(value: object) -> str:
    """Require Core's non-semantic 128-bit route ID representation."""
    if not isinstance(value, str) or not _ROUTE_ID_PATTERN.fullmatch(value):
        raise AnswerSheetRouteValidationError(
            "route_id must be rt_ followed by 32 lowercase hexadecimal characters."
        )
    return value


def _validated_work(work_ref: ModuleWorkRef) -> ModuleWorkRef:
    try:
        work = validate_module_work_ref(work_ref)
    except (RoutingModelError, TypeError, ValueError) as error:
        raise AnswerSheetRouteValidationError("Invalid ModuleWorkRef.") from error
    if work.module_id != SCOREFORM_MODULE_ID:
        raise AnswerSheetRouteValidationError(
            'ModuleWorkRef.module_id must be "scoreform".'
        )
    return work


def answer_sheet_human_fallback(page: AnswerSheetPage) -> str:
    """Return stable diagnostic text that is deliberately outside the QR."""
    validate_answer_sheet_page(page)
    value = (
        f"ScoreForm | class={page.class_id} | assignment={page.assignment_id} | "
        f"student={page.student_id} | page={page.logical_page}/{page.total_pages} | "
        f"page_id={page.page_id}"
    )
    if value != value.strip() or any(ord(character) < 32 for character in value):
        raise AnswerSheetRouteValidationError(
            "human_fallback must be a trimmed single line without control characters."
        )
    return value


def answer_sheet_module_details(page: AnswerSheetPage) -> dict[str, object]:
    """Return the exact ScoreForm v1 diagnostic details for a page route."""
    validate_answer_sheet_page(page)
    return {
        "issuance_id": page.issuance_id,
        "logical_page": page.logical_page,
        "total_pages": page.total_pages,
    }


def _validate_module_details(page: AnswerSheetPage, value: object) -> None:
    if not isinstance(value, dict) or frozenset(value) != _MODULE_DETAIL_KEYS:
        raise AnswerSheetRouteValidationError(
            "registration.module_details must use exactly issuance_id, logical_page, "
            "and total_pages."
        )
    if value["issuance_id"] != page.issuance_id:
        raise AnswerSheetRouteValidationError("module_details.issuance_id mismatch.")
    for field_name in ("logical_page", "total_pages"):
        field = value[field_name]
        if isinstance(field, bool) or not isinstance(field, int):
            raise AnswerSheetRouteValidationError(
                f"module_details.{field_name} must be an integer, not a boolean."
            )
        if field != getattr(page, field_name):
            raise AnswerSheetRouteValidationError(
                f"module_details.{field_name} mismatch."
            )


def validate_answer_sheet_page_route(
    value: AnswerSheetPageRoute,
) -> AnswerSheetPageRoute:
    """Cross-validate the complete pure route model."""
    if not isinstance(value, AnswerSheetPageRoute):
        raise AnswerSheetRouteValidationError(
            "page route has the wrong model type."
        )
    try:
        page = validate_answer_sheet_page(value.page)
        locator = validate_route_locator(value.locator)
        registration = validate_route_registration(value.registration)
    except (AnswerSheetRecordError, RoutingModelError, TypeError, ValueError) as error:
        raise AnswerSheetRouteValidationError(str(error)) from error
    if locator.schema != PDS2_SCHEMA:
        raise AnswerSheetRouteValidationError("locator.schema must be PDS2.")
    if locator.module_id != SCOREFORM_MODULE_ID:
        raise AnswerSheetRouteValidationError("locator.module_id must be scoreform.")
    if (locator.class_id, locator.work_id) != (
        page.class_id,
        page.assignment_id,
    ):
        raise AnswerSheetRouteValidationError("Locator work does not match page work.")
    validate_route_id(locator.route_id)
    if registration.locator != locator:
        raise AnswerSheetRouteValidationError(
            "Registration locator does not exactly match the planned locator."
        )
    if registration.target != answer_sheet_page_target(page):
        raise AnswerSheetRouteValidationError(
            "Registration target does not exactly identify the page record."
        )
    if registration.schema_version != ROUTE_REGISTRATION_SCHEMA_VERSION:
        raise AnswerSheetRouteValidationError(
            "Registration schema version is not Core's current version."
        )
    if registration.status != "active":
        raise AnswerSheetRouteValidationError("Registration status must be active.")
    if registration.created_at != page.created_at:
        raise AnswerSheetRouteValidationError(
            "Registration creation time must match page creation time."
        )
    if registration.human_fallback != answer_sheet_human_fallback(page):
        raise AnswerSheetRouteValidationError("human_fallback does not match the page.")
    _validate_module_details(page, registration.module_details)
    try:
        parsed = parse_pds2_payload(value.payload_text)
        canonical = serialize_pds2_payload(locator)
    except Exception as error:
        raise AnswerSheetRouteValidationError("Invalid PDS2 payload.") from error
    if parsed != locator or value.payload_text != canonical:
        raise AnswerSheetRouteValidationError(
            "Payload must be the exact canonical serialization of the locator."
        )
    return value


def build_answer_sheet_page_route(
    work_ref: ModuleWorkRef,
    page: AnswerSheetPage,
    *,
    route_id: str | None = None,
    route_id_generator: RouteIdGenerator = generate_route_id,
) -> AnswerSheetPageRoute:
    """Purely build one PDS2 route and Core registration for one page."""
    work = _validated_work(work_ref)
    try:
        page = validate_answer_sheet_page(page)
    except AnswerSheetRecordError as error:
        raise AnswerSheetRouteValidationError(str(error)) from error
    if (page.class_id, page.assignment_id) != (work.class_id, work.work_id):
        raise AnswerSheetRouteValidationError("Page does not match ModuleWorkRef.")
    selected_route_id = validate_route_id(
        route_id_generator() if route_id is None else route_id
    )
    try:
        locator = RouteLocator(PDS2_SCHEMA, work, selected_route_id)
        registration = RouteRegistration(
            schema_version=ROUTE_REGISTRATION_SCHEMA_VERSION,
            locator=locator,
            target=answer_sheet_page_target(page),
            created_at=page.created_at,
            status="active",
            human_fallback=answer_sheet_human_fallback(page),
            module_details=answer_sheet_module_details(page),
        )
        route = AnswerSheetPageRoute(
            page=page,
            locator=locator,
            registration=registration,
            payload_text=serialize_pds2_payload(locator),
        )
    except (RoutingModelError, ValueError, TypeError) as error:
        raise AnswerSheetRouteValidationError(str(error)) from error
    return validate_answer_sheet_page_route(route)


def validate_answer_sheet_route_set(
    record_set: AnswerSheetRecordSet,
    routes: Sequence[AnswerSheetPageRoute],
) -> tuple[AnswerSheetPageRoute, ...]:
    """Require a complete ordered one-to-one route set for a prepared issuance."""
    try:
        record_set = validate_answer_sheet_record_set(record_set)
    except AnswerSheetRecordError as error:
        raise AnswerSheetRoutePlanningError(str(error)) from error
    if record_set.issuance.lifecycle.status != "prepared":
        raise AnswerSheetRoutePlanningError("Route planning requires a prepared issuance.")
    planned = tuple(routes)
    if len(planned) != len(record_set.pages):
        raise AnswerSheetRoutePlanningError("Exactly one route is required per page.")
    for route in planned:
        validate_answer_sheet_page_route(route)
    if tuple(route.page for route in planned) != record_set.pages:
        raise AnswerSheetRoutePlanningError(
            "Route order and page membership must match the issuance."
        )
    route_ids = tuple(route.locator.route_id for route in planned)
    page_ids = tuple(route.page.page_id for route in planned)
    locators = tuple(route.locator for route in planned)
    targets = tuple(route.registration.target for route in planned)
    if len(set(route_ids)) != len(route_ids):
        raise AnswerSheetRouteCollisionError("Route set contains duplicate route IDs.")
    if len(set(page_ids)) != len(page_ids):
        raise AnswerSheetRouteCollisionError("Route set contains duplicate page IDs.")
    if len(set(locators)) != len(locators):
        raise AnswerSheetRouteCollisionError("Route set contains duplicate locators.")
    if len(set(targets)) != len(targets):
        raise AnswerSheetRouteCollisionError("Route set contains duplicate targets.")
    return planned


def plan_answer_sheet_route_set(
    work_ref: ModuleWorkRef,
    record_set: AnswerSheetRecordSet,
    *,
    route_id_generator: RouteIdGenerator = generate_route_id,
) -> tuple[AnswerSheetPageRoute, ...]:
    """Purely plan one ordered route per issuance page."""
    work = _validated_work(work_ref)
    try:
        record_set = validate_answer_sheet_record_set(record_set)
    except AnswerSheetRecordError as error:
        raise AnswerSheetRoutePlanningError(str(error)) from error
    if (record_set.issuance.class_id, record_set.issuance.assignment_id) != (
        work.class_id,
        work.work_id,
    ):
        raise AnswerSheetRoutePlanningError("Record set does not match ModuleWorkRef.")
    routes = tuple(
        build_answer_sheet_page_route(
            work, page, route_id_generator=route_id_generator
        )
        for page in record_set.pages
    )
    return validate_answer_sheet_route_set(record_set, routes)


def _reject_route_collection_types(
    workspace_root: str | Path, routes: Sequence[AnswerSheetPageRoute]
) -> tuple[Path, ...]:
    root = Path(workspace_root)
    paths = tuple(route_registration_path(root, route.locator) for route in routes)
    route_directories = {path.parent for path in paths}
    for routes_dir in route_directories:
        if routes_dir.is_symlink():
            raise AnswerSheetRoutePersistenceError(
                f"Symlinked Core routes directory is not allowed: {routes_dir}"
            )
        if routes_dir.exists() and not routes_dir.is_dir():
            raise AnswerSheetRoutePersistenceError(
                f"Core routes path is not a directory: {routes_dir}"
            )
    if len(set(paths)) != len(paths):
        raise AnswerSheetRouteCollisionError(
            "Registration destinations are not unique."
        )
    for path in paths:
        parent = path.parent
        while parent != root and parent != parent.parent:
            if parent.is_symlink():
                raise AnswerSheetRoutePersistenceError(
                    f"Symlinked route-registration directory is not allowed: {parent}"
                )
            if parent.exists() and not parent.is_dir():
                raise AnswerSheetRoutePersistenceError(
                    f"Route-registration parent is not a directory: {parent}"
                )
            parent = parent.parent
        if path.exists() or path.is_symlink():
            raise AnswerSheetRouteCollisionError(
                f"Route registration already exists: {path}"
            )
    return paths


def preflight_answer_sheet_route_destinations(
    workspace_root: str | Path,
    routes: Sequence[AnswerSheetPageRoute],
) -> tuple[Path, ...]:
    """Public collision/type preflight usable before page-record persistence."""
    planned = tuple(validate_answer_sheet_page_route(route) for route in routes)
    return _reject_route_collection_types(workspace_root, planned)


def preflight_answer_sheet_route_set(
    workspace_root: str | Path,
    work_ref: ModuleWorkRef,
    record_set: AnswerSheetRecordSet,
    routes: Sequence[AnswerSheetPageRoute],
) -> tuple[Path, ...]:
    """Verify all page/issuance sources and destinations before any route write."""
    work = _validated_work(work_ref)
    planned = validate_answer_sheet_route_set(record_set, routes)
    paths = _reject_route_collection_types(workspace_root, planned)
    try:
        loaded_set = load_answer_sheet_record_set(
            workspace_root, work, record_set.issuance.issuance_id
        )
    except AnswerSheetPersistenceError as error:
        raise AnswerSheetRouteIntegrityError(
            "The complete issuance must be persisted before route registration."
        ) from error
    if loaded_set != record_set:
        raise AnswerSheetRouteIntegrityError(
            "Persisted issuance does not equal the planned record set."
        )
    if loaded_set.issuance.lifecycle.status != "prepared" or (
        loaded_set.issuance.lifecycle.revision != 1
    ):
        raise AnswerSheetRouteIntegrityError(
            "Route registration requires prepared issuance revision 1."
        )
    for route in planned:
        try:
            loaded_page = load_answer_sheet_page(
                workspace_root, work, route.page.page_id
            )
        except AnswerSheetPersistenceError as error:
            raise AnswerSheetRouteIntegrityError(
                f"Target page is not loadable: {route.page.page_id}"
            ) from error
        if loaded_page != route.page:
            raise AnswerSheetRouteIntegrityError(
                f"Target page differs from plan: {route.page.page_id}"
            )
    return paths


def persist_answer_sheet_route_set(
    workspace_root: str | Path,
    work_ref: ModuleWorkRef,
    record_set: AnswerSheetRecordSet,
    routes: Sequence[AnswerSheetPageRoute],
) -> PersistedAnswerSheetRouteSet:
    """Persist with Core only, reloading every immutable registration exactly."""
    planned = validate_answer_sheet_route_set(record_set, routes)
    expected_paths = preflight_answer_sheet_route_set(
        workspace_root, work_ref, record_set, planned
    )
    persisted: list[RegisteredAnswerSheetPageRoute] = []
    for route, expected_path in zip(planned, expected_paths, strict=True):
        try:
            created_path = write_route_registration(
                workspace_root, route.registration
            )
            loaded = load_route_registration(workspace_root, route.locator)
        except Exception as error:
            current_path = route_registration_path(workspace_root, route.locator)
            created_paths = tuple(
                [
                    *(item.registration_path for item in persisted),
                    *((current_path,) if current_path.is_file() else ()),
                ]
            )
            failure = AnswerSheetRoutePersistenceError(
                "Route registration failed for page "
                f"{route.page.page_id}: {error}. Created registrations: "
                f"{', '.join(map(str, created_paths)) or 'none'}."
            )
            setattr(failure, "created_paths", created_paths)
            setattr(failure, "verified_routes", tuple(persisted))
            setattr(failure, "failed_page_id", route.page.page_id)
            raise failure from error
        if created_path != expected_path or loaded != route.registration:
            created_paths = tuple(
                [*(item.registration_path for item in persisted), created_path]
            )
            failure = AnswerSheetRouteIntegrityError(
                f"Persisted registration failed integrity verification for page "
                f"{route.page.page_id}."
            )
            setattr(failure, "created_paths", created_paths)
            setattr(failure, "verified_routes", tuple(persisted))
            setattr(failure, "failed_page_id", route.page.page_id)
            raise failure
        persisted.append(RegisteredAnswerSheetPageRoute(route, created_path))
    return PersistedAnswerSheetRouteSet(tuple(persisted))


# Compatibility aliases use explicit route-set terminology expected by callers.
build_answer_sheet_route_set = plan_answer_sheet_route_set
write_answer_sheet_route_set = persist_answer_sheet_route_set
