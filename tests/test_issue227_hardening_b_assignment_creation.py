"""Issue #227 Hardening B: guarded create-only assignment persistence."""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from scoreform import assignment_creation as creation
from scoreform.assignment import load_assignment
from scoreform.work_paths import scoreform_work_paths
from scoreform.workflows import write_assignment_json


def _payload(assignment_id: str = "unit_quiz") -> dict[str, object]:
    return {
        "assignment_id": assignment_id,
        "title": "Unit Quiz",
        "question_count": 2,
        "layout_id": "standard_15q_abcd_v1",
        "choices": ["A", "B", "C", "D"],
        "answer_key": {"1": "A", "2": "B"},
        "standards": {"1": [], "2": []},
    }


def _path(root: Path) -> Path:
    path = scoreform_work_paths(root, "english12_p2", "unit_quiz").assignment_path
    path.parent.mkdir(parents=True)
    return path


def _assert_clean(path: Path) -> None:
    assert not tuple(path.parent.glob(".assignment.json.*.tmp"))


def test_create_install_is_exact_loadable_and_leaves_no_temp(tmp_path: Path) -> None:
    path = _path(tmp_path)
    assert creation.commit_new_assignment(path, _payload()) == path
    assert json.loads(path.read_text(encoding="utf-8"))["assignment_id"] == "unit_quiz"
    assert load_assignment(path)["answer_key"] == {1: "A", 2: "B"}
    assert path.read_bytes().endswith(b"\n")
    _assert_clean(path)


def test_legacy_workflow_return_shape(tmp_path: Path) -> None:
    path = _path(tmp_path)
    assert write_assignment_json(str(path), _payload()) is True
    original = path.read_bytes()
    assert write_assignment_json(str(path), _payload()) is False
    assert path.read_bytes() == original


def test_create_never_overwrites_existing_bytes(tmp_path: Path) -> None:
    path = _path(tmp_path)
    path.write_bytes(b"historic assignment (even if invalid)")
    with pytest.raises(creation.AssignmentCreationConflictError):
        creation.commit_new_assignment(path, _payload())
    assert path.read_bytes() == b"historic assignment (even if invalid)"
    _assert_clean(path)


def test_invalid_payload_fails_before_writing(tmp_path: Path) -> None:
    path = _path(tmp_path)
    candidate = _payload()
    candidate["answer_key"] = {"1": "X", "2": "B"}
    with pytest.raises(creation.AssignmentCreationValidationError):
        creation.commit_new_assignment(path, candidate)
    assert not path.exists()
    _assert_clean(path)


def test_assignment_identity_must_match_managed_work_path(tmp_path: Path) -> None:
    path = _path(tmp_path)
    with pytest.raises(creation.AssignmentCreationValidationError, match="ID"):
        creation.commit_new_assignment(path, _payload("wrong_id"))
    assert not path.exists()


def test_rejects_dangling_symlink_as_existing_target(tmp_path: Path) -> None:
    path = _path(tmp_path)
    try:
        path.symlink_to(path.parent / "nonexistent")
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks unavailable")
    with pytest.raises(creation.AssignmentCreationConflictError):
        creation.commit_new_assignment(path, _payload())
    assert path.is_symlink()
    _assert_clean(path)


def test_rejects_symlinked_parent_without_touching_target(tmp_path: Path) -> None:
    path = _path(tmp_path)
    external = tmp_path / "external"
    external.mkdir()
    path.parent.rmdir()
    try:
        path.parent.symlink_to(external, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Directory symlinks unavailable")
    with pytest.raises(creation.AssignmentCreationValidationError):
        creation.commit_new_assignment(path, _payload())
    assert not tuple(external.iterdir())


def test_staging_fsync_failure_never_creates_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _path(tmp_path)

    def fail_fsync(_descriptor: int) -> None:
        raise OSError("injected fsync failure")

    monkeypatch.setattr(creation.os, "fsync", fail_fsync)
    with pytest.raises(creation.AssignmentCreationWriteError) as caught:
        creation.commit_new_assignment(path, _payload())
    assert not caught.value.partial
    assert not path.exists()
    _assert_clean(path)


def test_staged_payload_mutation_is_detected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _path(tmp_path)
    real_check = creation._validate_staged

    def sabotage(stage: Path, expected: bytes, normalized: dict[str, object]) -> None:
        stage.write_bytes(b"corrupt")
        real_check(stage, expected, normalized)

    monkeypatch.setattr(creation, "_validate_staged", sabotage)
    with pytest.raises(creation.AssignmentCreationWriteError, match="changed"):
        creation.commit_new_assignment(path, _payload())
    assert not path.exists()
    _assert_clean(path)


def test_raced_destination_is_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _path(tmp_path)
    old_check = creation._validate_staged

    def other_writer(stage: Path, expected: bytes, normalized: dict[str, object]) -> None:
        old_check(stage, expected, normalized)
        path.write_bytes(b"concurrent writer")

    monkeypatch.setattr(creation, "_validate_staged", other_writer)
    with pytest.raises(creation.AssignmentCreationConflictError):
        creation.commit_new_assignment(path, _payload())
    assert path.read_bytes() == b"concurrent writer"
    _assert_clean(path)


def test_postpublication_error_never_deletes_successful_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _path(tmp_path)
    real_link = os.link

    def link_then_error(src: Path, dst: Path) -> None:
        real_link(src, dst)
        raise OSError("injected late failure")

    monkeypatch.setattr(creation.os, "link", link_then_error)
    with pytest.raises(creation.AssignmentCreationWriteError) as caught:
        creation.commit_new_assignment(path, _payload())
    assert caught.value.partial
    assert load_assignment(path)["assignment_id"] == "unit_quiz"
    _assert_clean(path)


def test_unsupported_hardlinks_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _path(tmp_path)

    def unsupported(_src: Path, _dst: Path) -> None:
        raise OSError("hardlinks unsupported")

    monkeypatch.setattr(creation.os, "link", unsupported)
    with pytest.raises(creation.AssignmentCreationWriteError, match="hard links") as caught:
        creation.commit_new_assignment(path, _payload())
    assert not caught.value.partial
    assert not path.exists()
    _assert_clean(path)


def test_parallel_creators_get_exactly_one_winner(tmp_path: Path) -> None:
    path = _path(tmp_path)

    def candidate(_i: int) -> str:
        try:
            creation.commit_new_assignment(path, _payload())
            return "created"
        except creation.AssignmentCreationConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(candidate, range(2)))
    assert sorted(results) == ["conflict", "created"]
    assert load_assignment(path)["assignment_id"] == "unit_quiz"
    _assert_clean(path)
