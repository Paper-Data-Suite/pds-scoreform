"""Manual-entry result routing waits for module-qualified storage (#139)."""

import pytest

from scoreform.migration import ScoreFormMigrationPendingError
from scoreform.results import export_routed_results


def test_manual_entry_routed_export_stops_before_writing(tmp_path) -> None:
    with pytest.raises(ScoreFormMigrationPendingError, match=r"#139 and #143"):
        export_routed_results([{"class_id": "class1", "assignment_id": "quiz"}], tmp_path)

    assert list(tmp_path.iterdir()) == []
