"""Interim boundary coverage for assignment creation migration issue #139."""

import pytest

from scoreform import assignment_workflows
from scoreform.migration import ScoreFormMigrationPendingError


def test_assignment_creation_stops_before_standards_or_storage_writes() -> None:
    with pytest.raises(ScoreFormMigrationPendingError, match=r"#139"):
        assignment_workflows.prompt_create_assignment()
