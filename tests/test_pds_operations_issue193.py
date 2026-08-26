"""Issue #193 Slice 1 module-operations provider foundation tests."""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

from pds_core.module_operations import (
    MODULE_OPERATIONS_CONTRACT_VERSION,
    ModuleOperationsRequest,
    invoke_module_attention,
    invoke_module_readiness,
    validate_module_operations_profile,
)

from scoreform.attention_provider import evaluate_scoreform_attention
from scoreform.pds_operations import get_module_operations_profile


def test_project_declares_core_floor_and_operations_entry_point() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]
    assert "pds-core>=0.6.2,<0.7" in project["dependencies"]
    assert "pds-core>=0.6,<0.7" not in project["dependencies"]

    entry_points = project["entry-points"]
    assert entry_points["paper_data_suite.module_operations"] == {
        "scoreform": "scoreform.pds_operations:get_module_operations_profile"
    }


def test_scoreform_operations_profile_exposes_attention_and_readiness_and_is_valid() -> None:
    first = validate_module_operations_profile(get_module_operations_profile())
    second = validate_module_operations_profile(get_module_operations_profile())

    assert first == second
    assert first.module_id == "scoreform"
    assert first.supported_core_operations_contract_versions == frozenset(
        {MODULE_OPERATIONS_CONTRACT_VERSION}
    )
    assert first.attention_provider is not None
    assert first.readiness_provider is not None


def test_operations_profile_does_not_import_deep_capability_implementations() -> None:
    preserved = {
        name: sys.modules.pop(name, None)
        for name in (
            "scoreform.attention_provider",
            "scoreform.readiness_provider",
        )
    }
    try:
        from scoreform import pds_operations

        profile = pds_operations.get_module_operations_profile()

        assert profile.attention_provider is not None
        assert profile.readiness_provider is not None
        assert "scoreform.attention_provider" not in sys.modules
        assert "scoreform.readiness_provider" not in sys.modules
    finally:
        for name, module in preserved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


def test_missing_workspace_is_unavailable_without_implicit_resolution() -> None:
    report = evaluate_scoreform_attention(ModuleOperationsRequest())

    assert report.evaluation == "unavailable"
    assert report.summaries == ()
    assert len(report.notices) == 1
    assert report.notices[0].code == "scoreform_attention_unavailable"
    assert (
        report.notices[0].summary
        == "ScoreForm attention requires an explicit workspace."
    )


def test_absent_explicit_workspace_is_unavailable_and_not_created(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "must-remain-absent"

    report = evaluate_scoreform_attention(
        ModuleOperationsRequest(workspace_root=missing)
    )

    assert report.evaluation == "unavailable"
    assert report.summaries == ()
    assert not missing.exists()


def test_existing_empty_workspace_is_truthful_evaluated_empty(
    tmp_path: Path,
) -> None:
    before = tuple(tmp_path.iterdir())

    report = evaluate_scoreform_attention(
        ModuleOperationsRequest(workspace_root=tmp_path)
    )

    assert report.evaluation == "evaluated"
    assert report.summaries == ()
    assert report.notices == ()
    assert tuple(tmp_path.iterdir()) == before


def test_core_invocation_accepts_initial_scoreform_attention_report(
    tmp_path: Path,
) -> None:
    profile = get_module_operations_profile()
    request = ModuleOperationsRequest(workspace_root=tmp_path)

    result = invoke_module_attention(profile, request)

    assert result.code == "module_operations.evaluated"
    assert result.provider_call_attempted is True
    assert result.provider_call_succeeded is True
    assert result.result_validation == "passed"
    assert result.report is not None
    assert result.report.evaluation == "evaluated"


def test_core_invocation_accepts_initial_scoreform_readiness_report(
    tmp_path: Path,
) -> None:
    profile = get_module_operations_profile()
    request = ModuleOperationsRequest(workspace_root=tmp_path)

    result = invoke_module_readiness(profile, request)

    assert result.code == "module_operations.evaluated"
    assert result.provider_call_attempted is True
    assert result.provider_call_succeeded is True
    assert result.result_validation == "passed"
    assert result.report is not None
    assert result.report.evaluation == "evaluated"
    assert result.report.ready is True
