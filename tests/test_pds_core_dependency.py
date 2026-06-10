"""Tests for the local pds-core development dependency."""

from __future__ import annotations

from pds_core.identifiers import validate_identifier
from pds_core.workspace import ensure_workspace_root, resolve_workspace_root


def test_pds_core_dependency_is_available() -> None:
    assert validate_identifier("english9_p2") == "english9_p2"
    assert callable(ensure_workspace_root)
    assert callable(resolve_workspace_root)
