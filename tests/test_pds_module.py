from __future__ import annotations

import inspect

import pytest
from pds_core.module_profiles import (
    ModuleProfile,
    build_module_registry,
    discover_module_profiles,
    validate_module_profile,
)
from pds_core.routing_models import (
    ModuleRecordRef,
    ModuleWorkRef,
    RouteLocator,
    RouteRegistration,
)

from scoreform.module_errors import ScoreFormRegistrationValidationError
from scoreform.pds_module import (
    get_module_profile,
    validate_scoreform_registration,
)
from scoreform.route_handler import handle_scoreform_route


def _registration(**overrides):
    page_id = "pg_" + "2" * 32
    work = ModuleWorkRef("scoreform", "class1", "quiz1")
    locator = RouteLocator("PDS2", work, "rt_" + "1" * 32)
    values = {
        "schema_version": "1",
        "locator": locator,
        "target": ModuleRecordRef(
            "scoreform", "answer_sheet_page", page_id, "1"
        ),
        "created_at": "2026-01-01T00:00:00+00:00",
        "status": "active",
        "human_fallback": (
            "ScoreForm | class=class1 | assignment=quiz1 | student=student1 | "
            f"page=1/2 | page_id={page_id}"
        ),
        "module_details": {
            "issuance_id": "iss_" + "3" * 32,
            "logical_page": 1,
            "total_pages": 2,
        },
    }
    values.update(overrides)
    return RouteRegistration(**values)


def test_profile_is_exact_immutable_and_repeatable():
    assert tuple(inspect.signature(get_module_profile).parameters) == ()
    profile = get_module_profile()
    assert isinstance(profile, ModuleProfile)
    assert validate_module_profile(profile) is profile
    assert profile == get_module_profile()
    assert profile.module_id == "scoreform"
    assert profile.display_name == "ScoreForm"
    assert profile.supported_core_routing_contract_versions == frozenset({"1"})
    assert profile.supported_qr_schemas == frozenset({"PDS2"})
    assert profile.supported_route_registration_schema_versions == frozenset({"1"})
    assert profile.dispatchable_route_statuses == frozenset({"active"})
    assert profile.route_handler is handle_scoreform_route
    assert profile.registration_validator is validate_scoreform_registration


def test_registration_validator_accepts_exact_shape_and_returns_none():
    registration = _registration()
    before = registration.module_details
    assert validate_scoreform_registration(registration) is None
    assert registration.module_details == before


@pytest.mark.parametrize(
    "override",
    [
        {"status": "inactive"},
        {
            "target": ModuleRecordRef(
                "scoreform", "other_record", "pg_" + "2" * 32, "1"
            )
        },
        {"module_details": {"issuance_id": "iss_" + "3" * 32}},
        {
            "module_details": {
                "issuance_id": "iss_" + "3" * 32,
                "logical_page": True,
                "total_pages": 2,
            }
        },
    ],
)
def test_registration_validator_rejects_incompatible_shapes(override):
    with pytest.raises(ScoreFormRegistrationValidationError):
        validate_scoreform_registration(_registration(**override))


def test_registration_validator_requires_actual_model():
    with pytest.raises(ScoreFormRegistrationValidationError):
        validate_scoreform_registration({})  # type: ignore[arg-type]


def test_pyproject_declares_exact_installed_entry_point():
    text = open("pyproject.toml", encoding="utf-8").read()
    assert '[project.entry-points."paper_data_suite.modules"]' in text
    assert 'scoreform = "scoreform.pds_module:get_module_profile"' in text


def test_installed_discovery_builds_scoreform_registry():
    profiles = discover_module_profiles()
    profile = next(item for item in profiles if item.module_id == "scoreform")
    assert profile == get_module_profile()
    assert build_module_registry().require("scoreform") == profile
