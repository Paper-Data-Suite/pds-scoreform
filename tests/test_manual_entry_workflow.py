"""Manual-entry assignment discovery waits for module storage issue #139."""

import pytest

from scoreform import workflows
from scoreform.migration import ScoreFormMigrationPendingError


def test_manual_entry_assignment_discovery_is_gated() -> None:
    with pytest.raises(ScoreFormMigrationPendingError, match=r"#139"):
        workflows.discover_class_assignments("class1")
