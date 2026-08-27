"""Regression coverage for the physical scan-review menu defect found in #195."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import scoreform.menu_scan_review as menu_review


@pytest.mark.parametrize(
    "action",
    (
        "rescan_needed",
        "cannot_route",
        "mixed_assignment",
        "defer",
    ),
)
def test_nonmanual_review_actions_do_not_submit_observed_identity_as_teacher_override(
    tmp_path,
    monkeypatch,
    action: str,
) -> None:
    """Diagnostic identity is context, not a teacher identity override."""

    item = SimpleNamespace(
        failure_id="failure_physical_missing_page",
        status="unresolved",
        class_id="physical_copy_class",
        assignment_id="physical_source_quiz",
        student_id="physical_copy_student",
        route_locator=None,
        target=None,
        retained_source_path=(
            "scans/source/2026-08-27/physical_copy_class_packet_page1_only.pdf"
        ),
    )
    captured: dict[str, object] = {}
    expected = object()

    def resolve(
        root,
        failure_id,
        selected_action,
        **kwargs,
    ):
        assert root == tmp_path
        assert failure_id == item.failure_id
        assert selected_action == action
        captured.update(kwargs)
        return expected

    monkeypatch.setattr(menu_review, "clear_screen", lambda: None)
    monkeypatch.setattr(menu_review, "print_menu_header", lambda _title: None)
    monkeypatch.setattr(menu_review, "resolve_scan_review_item", resolve)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "WRITE")

    assert menu_review._perform_action(tmp_path, item, action) is expected

    assert captured["class_id"] is None
    assert captured["assignment_id"] is None
    assert captured["student_id"] is None
    assert captured["answers"] is None
    assert captured["route_payload"] is None


def test_manual_review_action_still_submits_teacher_verified_identity(
    tmp_path,
    monkeypatch,
) -> None:
    """The nonmanual fix must not remove identity from manual recovery."""

    item = SimpleNamespace(
        failure_id="failure_manual",
        status="unresolved",
        class_id="observed_class",
        assignment_id="observed_quiz",
        student_id="observed_student",
        route_locator=None,
        target=None,
        retained_source_path="scans/source/2026-08-27/manual.pdf",
    )
    assignment = {
        "question_count": 1,
        "answer_key": {"1": "A"},
    }
    captured: dict[str, object] = {}
    expected = object()

    monkeypatch.setattr(menu_review, "clear_screen", lambda: None)
    monkeypatch.setattr(menu_review, "print_menu_header", lambda _title: None)
    monkeypatch.setattr(
        menu_review,
        "_prompt_identity",
        lambda _item: ("teacher_class", "teacher_quiz", "teacher_student"),
    )
    monkeypatch.setattr(
        menu_review,
        "_prompt_manual_answers",
        lambda *_args: {1: "A"},
    )
    monkeypatch.setattr(menu_review, "load_assignment", lambda _path: assignment)

    def resolve(
        root,
        failure_id,
        selected_action,
        **kwargs,
    ):
        assert root == tmp_path
        assert failure_id == item.failure_id
        assert selected_action == "manual_entry"
        captured.update(kwargs)
        return expected

    monkeypatch.setattr(menu_review, "resolve_scan_review_item", resolve)

    responses = iter(("", "", "WRITE"))
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    assert menu_review._perform_action(tmp_path, item, "manual_entry") is expected

    assert captured["class_id"] == "teacher_class"
    assert captured["assignment_id"] == "teacher_quiz"
    assert captured["student_id"] == "teacher_student"
    assert captured["answers"] == {1: "A"}
