"""Tests for the local pds-core development dependency."""

from __future__ import annotations

from pds_core.identifiers import validate_identifier
from pds_core.module_operations import (
    MODULE_OPERATIONS_CONTRACT_VERSION,
    MODULE_OPERATIONS_ENTRY_POINT_GROUP,
    ModuleAttentionReport,
    ModuleOperationsProfile,
)
from pds_core.workspace import (
    WorkspaceRootError,
    WorkspaceStatus,
    clear_saved_workspace_root,
    ensure_workspace_root,
    get_default_workspace_root,
    get_workspace_config_path,
    inspect_workspace_root,
    resolve_workspace_root,
    save_workspace_root,
)


def test_pds_core_dependency_is_available() -> None:
    assert validate_identifier("english9_p2") == "english9_p2"
    assert MODULE_OPERATIONS_CONTRACT_VERSION == "1"
    assert (
        MODULE_OPERATIONS_ENTRY_POINT_GROUP
        == "paper_data_suite.module_operations"
    )
    assert ModuleAttentionReport.__module__ == "pds_core.module_operations"
    assert ModuleOperationsProfile.__module__ == "pds_core.module_operations"
    assert WorkspaceStatus.__module__ == "pds_core.workspace"
    assert issubclass(WorkspaceRootError, Exception)
    assert callable(clear_saved_workspace_root)
    assert callable(ensure_workspace_root)
    assert callable(get_default_workspace_root)
    assert callable(get_workspace_config_path)
    assert callable(inspect_workspace_root)
    assert callable(resolve_workspace_root)
    assert callable(save_workspace_root)
