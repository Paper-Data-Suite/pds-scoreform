"""Plain-paper assignment discovery uses ScoreForm work storage."""

from scoreform import workflows


def test_manual_entry_assignment_discovery_is_empty_without_creating_storage(tmp_path) -> None:
    assert workflows.discover_class_assignments(
        "class1", workspace_root=tmp_path
    ) == []
    assert list(tmp_path.iterdir()) == []
