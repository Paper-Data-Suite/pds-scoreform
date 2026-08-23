"""Identity-only recent/active assignment context for ScoreForm issue #188."""

from __future__ import annotations

from pathlib import Path

from scoreform.assignment_context import (
    MAX_RECENT_ASSIGNMENTS,
    AssignmentContextRef,
    AssignmentContextSession,
    resolve_active_assignment_context,
    resolve_assignment_context_ref,
    resolve_recent_assignment_contexts,
)


def _assignment_record(
    class_id: str,
    assignment_id: str,
    *,
    title: str = "Unit Quiz",
) -> dict[str, object]:
    return {
        "class_id": class_id,
        "assignment_id": assignment_id,
        "assignment": {
            "assignment_id": assignment_id,
            "title": title,
        },
        "results_path": f"classes/{class_id}/{assignment_id}/results.csv",
    }


def _install_discovery(
    monkeypatch,
    *,
    class_id: str = "english10_p2",
    assignment_id: str = "unit_quiz",
    title: str = "Unit Quiz",
) -> dict[str, object]:
    record = _assignment_record(class_id, assignment_id, title=title)
    monkeypatch.setattr(
        "scoreform.workflows.discover_class_rosters",
        lambda workspace_root=None: [{"class_id": class_id}],
    )
    monkeypatch.setattr(
        "scoreform.workflows.discover_class_assignments",
        lambda selected_class_id, workspace_root=None: (
            [record] if selected_class_id == class_id else []
        ),
    )
    return record


def test_context_ref_contains_only_exact_identity() -> None:
    ref = AssignmentContextRef("english10_p2", "unit_quiz")

    assert ref.class_id == "english10_p2"
    assert ref.assignment_id == "unit_quiz"
    assert tuple(ref.__slots__) == ("class_id", "assignment_id")


def test_session_starts_empty_and_activation_is_bounded_mru(tmp_path: Path) -> None:
    session = AssignmentContextSession()

    assert session.active is None
    assert session.recent == ()

    refs = [
        AssignmentContextRef("english10_p2", f"quiz_{index}")
        for index in range(MAX_RECENT_ASSIGNMENTS + 2)
    ]
    for ref in refs:
        session.activate(ref, workspace_root=tmp_path)

    assert session.active == refs[-1]
    assert session.recent == tuple(reversed(refs[-MAX_RECENT_ASSIGNMENTS:]))

    session.activate(refs[-3], workspace_root=tmp_path)
    assert session.recent[0] == refs[-3]
    assert session.recent.count(refs[-3]) == 1


def test_clear_active_and_recent_are_independent(tmp_path: Path) -> None:
    session = AssignmentContextSession()
    ref = AssignmentContextRef("english10_p2", "unit_quiz")
    session.activate(ref, workspace_root=tmp_path)

    session.clear_recent()
    assert session.active == ref
    assert session.recent == ()

    session.clear_active()
    assert session.active is None


def test_workspace_change_clears_active_and_recent(tmp_path: Path) -> None:
    first = tmp_path / "workspace-one"
    second = tmp_path / "workspace-two"
    session = AssignmentContextSession()
    ref = AssignmentContextRef("english10_p2", "unit_quiz")
    session.activate(ref, workspace_root=first)

    assert session.bind_workspace(second) is True
    assert session.active is None
    assert session.recent == ()


def test_valid_context_is_reloaded_from_current_canonical_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    current = _install_discovery(monkeypatch, title="Renamed Unit Quiz")
    session = AssignmentContextSession()
    ref = AssignmentContextRef("english10_p2", "unit_quiz")
    session.activate(ref, workspace_root=tmp_path)

    resolved = resolve_active_assignment_context(session, workspace_root=tmp_path)

    assert resolved is not None
    assert resolved.is_valid
    assert resolved.record is current
    assert resolved.record["assignment"]["title"] == "Renamed Unit Quiz"
    assert session.active == ref


def test_missing_assignment_fails_closed_and_prunes_context(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "scoreform.workflows.discover_class_rosters",
        lambda workspace_root=None: [{"class_id": "english10_p2"}],
    )
    monkeypatch.setattr(
        "scoreform.workflows.discover_class_assignments",
        lambda class_id, workspace_root=None: [],
    )
    session = AssignmentContextSession()
    ref = AssignmentContextRef("english10_p2", "unit_quiz")
    session.activate(ref, workspace_root=tmp_path)

    resolved = resolve_active_assignment_context(session, workspace_root=tmp_path)

    assert resolved is not None
    assert not resolved.is_valid
    assert "no longer available" in (resolved.stale_reason or "")
    assert session.active is None
    assert session.recent == ()


def test_workspace_mismatch_never_reinterprets_same_ids(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _install_discovery(monkeypatch)
    session = AssignmentContextSession()
    ref = AssignmentContextRef("english10_p2", "unit_quiz")
    session.activate(ref, workspace_root=tmp_path / "one")

    resolved = resolve_assignment_context_ref(
        session,
        ref,
        workspace_root=tmp_path / "two",
    )

    assert not resolved.is_valid
    assert resolved.workspace_changed
    assert "workspace changed" in (resolved.stale_reason or "").lower()
    assert session.active is None
    assert session.recent == ()


def test_recent_resolution_prunes_only_stale_entries(
    tmp_path: Path,
    monkeypatch,
) -> None:
    valid = _assignment_record("english10_p2", "valid_quiz")
    monkeypatch.setattr(
        "scoreform.workflows.discover_class_rosters",
        lambda workspace_root=None: [{"class_id": "english10_p2"}],
    )
    monkeypatch.setattr(
        "scoreform.workflows.discover_class_assignments",
        lambda class_id, workspace_root=None: [valid],
    )
    session = AssignmentContextSession()
    stale = AssignmentContextRef("english10_p2", "stale_quiz")
    current = AssignmentContextRef("english10_p2", "valid_quiz")
    session.activate(stale, workspace_root=tmp_path)
    session.activate(current, workspace_root=tmp_path)

    resolved = resolve_recent_assignment_contexts(session, workspace_root=tmp_path)

    assert [item.ref for item in resolved] == [current]
    assert session.recent == (current,)
