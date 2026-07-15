"""Assignment creation is available on module-qualified storage."""

from scoreform import assignment_workflows


def test_assignment_creation_reports_missing_rosters(monkeypatch) -> None:
    monkeypatch.setattr(assignment_workflows, "discover_class_rosters", lambda: [])

    assert assignment_workflows.prompt_create_assignment() == 1
