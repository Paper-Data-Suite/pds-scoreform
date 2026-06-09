"""Tests for the local pds-core development dependency."""

from __future__ import annotations

from pds_core.identifiers import validate_identifier


def test_pds_core_dependency_is_available() -> None:
    assert validate_identifier("english9_p2") == "english9_p2"