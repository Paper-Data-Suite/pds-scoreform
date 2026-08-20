from __future__ import annotations

import json
from pathlib import Path

import pytest

from scoreform.assignment_bulk_mutation import (
    AssignmentBulkMutationValidationError,
    commit_assignment_bulk_mutation,
    load_assignment_bulk_snapshot,
    plan_assignment_staged_replacement,
)
from scoreform.work_paths import scoreform_work_paths


def _assignment(*, extra: bool = False) -> dict[str, object]:
    value: dict[str, object] = {
        "assignment_id": "unit_quiz",
        "title": "Original title",
        "question_count": 3,
        "choices": ["A", "B", "C", "D"],
        "layout_id": "standard_15q_abcd_v1",
        "answer_key": {"1": "A", "2": "B", "3": "C"},
        "standards": {"1": [], "2": [], "3": []},
    }
    if extra:
        value["future_field"] = {"preserve": [1, 2, 3]}
    return value


def _write(root: Path, *, extra: bool = False) -> Path:
    paths = scoreform_work_paths(root, "english10_p2", "unit_quiz")
    paths.work_root.mkdir(parents=True)
    paths.assignment_path.write_text(
        json.dumps(_assignment(extra=extra), indent=2) + "\n",
        encoding="utf-8",
    )
    return paths.assignment_path


def _staged(snapshot) -> dict[str, object]:
    assignment = snapshot.assignment
    return {
        "assignment_id": assignment["assignment_id"],
        "title": assignment["title"],
        "question_count": assignment["question_count"],
        "choices": list(assignment["choices"]),
        "layout_id": assignment["layout_id"],
        "answer_key": {
            str(question): answer
            for question, answer in assignment["answer_key"].items()
        },
        "standards": {
            str(question): list(values)
            for question, values in assignment["standards"].items()
        },
    }


def test_staged_replacement_allows_title_and_bulk_fields_together(tmp_path: Path) -> None:
    _write(tmp_path, extra=True)
    snapshot = load_assignment_bulk_snapshot(
        tmp_path,
        "english10_p2",
        "unit_quiz",
    )
    staged = _staged(snapshot)
    staged["title"] = "Revised title"
    staged["answer_key"] = {"1": "D", "2": "C", "3": "B"}

    plan = plan_assignment_staged_replacement(snapshot, staged)

    assert plan.candidate_payload["title"] == "Revised title"
    assert plan.candidate_payload["answer_key"] == {"1": "D", "2": "C", "3": "B"}
    assert plan.candidate_payload["future_field"] == {"preserve": [1, 2, 3]}


def test_staged_replacement_rejects_immutable_assignment_fields(tmp_path: Path) -> None:
    _write(tmp_path)
    snapshot = load_assignment_bulk_snapshot(
        tmp_path,
        "english10_p2",
        "unit_quiz",
    )
    staged = _staged(snapshot)
    staged["question_count"] = 2
    staged["answer_key"] = {"1": "A", "2": "B"}
    staged["standards"] = {"1": [], "2": []}

    with pytest.raises(
        AssignmentBulkMutationValidationError,
        match="immutable field 'question_count'",
    ):
        plan_assignment_staged_replacement(snapshot, staged)


def test_staged_replacement_commit_is_one_atomic_candidate(tmp_path: Path) -> None:
    path = _write(tmp_path, extra=True)
    snapshot = load_assignment_bulk_snapshot(
        tmp_path,
        "english10_p2",
        "unit_quiz",
    )
    staged = _staged(snapshot)
    staged["title"] = "Revised title"
    staged["answer_key"] = {"1": "D", "2": "D", "3": "D"}
    plan = plan_assignment_staged_replacement(snapshot, staged)

    persisted = commit_assignment_bulk_mutation(tmp_path, plan)

    assert persisted.assignment["title"] == "Revised title"
    assert persisted.assignment["answer_key"] == {1: "D", 2: "D", 3: "D"}
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["future_field"] == {"preserve": [1, 2, 3]}


def test_staged_replacement_commit_rejects_stale_source(tmp_path: Path) -> None:
    path = _write(tmp_path)
    snapshot = load_assignment_bulk_snapshot(
        tmp_path,
        "english10_p2",
        "unit_quiz",
    )
    staged = _staged(snapshot)
    staged["title"] = "Revised title"
    plan = plan_assignment_staged_replacement(snapshot, staged)

    external = _assignment()
    external["title"] = "External title"
    path.write_text(json.dumps(external, indent=2) + "\n", encoding="utf-8")

    from scoreform.assignment_bulk_mutation import AssignmentBulkMutationConflictError

    with pytest.raises(AssignmentBulkMutationConflictError, match="changed after preview"):
        commit_assignment_bulk_mutation(tmp_path, plan)

    assert json.loads(path.read_text(encoding="utf-8"))["title"] == "External title"
