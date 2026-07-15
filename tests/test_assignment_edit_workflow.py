"""Interim boundary coverage for assignment storage migration issue #139."""

import pytest

from scoreform import assignment_workflows
from scoreform.migration import ScoreFormMigrationPendingError


def test_assignment_edit_discovery_stops_at_storage_migration_boundary(monkeypatch) -> None:
    monkeypatch.setattr(
        assignment_workflows,
        "discover_class_rosters",
        lambda: [{"class_id": "class1"}],
    )
    monkeypatch.setattr("builtins.input", lambda _prompt="": "1")

    with pytest.raises(ScoreFormMigrationPendingError, match=r"#139"):
        assignment_workflows.prompt_edit_assignment()
