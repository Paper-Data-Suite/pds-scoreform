"""Tests for the local pds-core development dependency."""

from __future__ import annotations

from pds_core.identifiers import validate_identifier
from pds_core.workspace import (
    WorkspaceRootError,
    clear_saved_workspace_root,
    ensure_workspace_root,
    get_default_workspace_root,
    get_workspace_config_path,
    resolve_workspace_root,
    save_workspace_root,
)


def test_pds_core_dependency_is_available() -> None:
    assert validate_identifier("english9_p2") == "english9_p2"
    assert issubclass(WorkspaceRootError, Exception)
    assert callable(clear_saved_workspace_root)
    assert callable(ensure_workspace_root)
    assert callable(get_default_workspace_root)
    assert callable(get_workspace_config_path)
    assert callable(resolve_workspace_root)
    assert callable(save_workspace_root)
