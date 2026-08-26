"""Installed ScoreForm module-operations profile for Core v1."""

from __future__ import annotations

from pds_core.module_operations import (
    MODULE_OPERATIONS_CONTRACT_VERSION,
    ModuleAttentionReport,
    ModuleOperationsProfile,
    ModuleOperationsRequest,
    ModuleReadinessReport,
    validate_module_operations_profile,
)

from scoreform.pds_contract import SCOREFORM_MODULE_ID


def evaluate_scoreform_attention(
    request: ModuleOperationsRequest,
    /,
) -> ModuleAttentionReport:
    """Lazily evaluate ScoreForm-owned attention for one neutral Core request."""
    from scoreform.attention_provider import (
        evaluate_scoreform_attention as _evaluate,
    )

    return _evaluate(request)


def evaluate_scoreform_readiness(
    request: ModuleOperationsRequest,
    /,
) -> ModuleReadinessReport:
    """Lazily evaluate ScoreForm-owned readiness for one neutral Core request."""
    from scoreform.readiness_provider import (
        evaluate_scoreform_readiness as _evaluate,
    )

    return _evaluate(request)


def get_module_operations_profile() -> ModuleOperationsProfile:
    """Return ScoreForm's validated Core v1 operations profile."""
    return validate_module_operations_profile(
        ModuleOperationsProfile(
            module_id=SCOREFORM_MODULE_ID,
            supported_core_operations_contract_versions=frozenset(
                {MODULE_OPERATIONS_CONTRACT_VERSION}
            ),
            readiness_provider=evaluate_scoreform_readiness,
            attention_provider=evaluate_scoreform_attention,
        )
    )


__all__ = [
    "evaluate_scoreform_attention",
    "evaluate_scoreform_readiness",
    "get_module_operations_profile",
]
