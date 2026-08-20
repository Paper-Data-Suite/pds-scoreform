from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
from pds_core.standards import StandardDefinition, StandardsLibrary, StandardsProfile

from scoreform.assignment_bulk_entry import BulkAnswerKey, BulkStandardsAlignment
from scoreform.assignment_bulk_mutation import (
    AssignmentBulkMutationConflictError,
    AssignmentBulkMutationValidationError,
    AssignmentBulkMutationWriteError,
    build_assignment_bulk_candidate,
    commit_assignment_bulk_mutation,
    load_assignment_bulk_snapshot,
    plan_assignment_bulk_mutation,
)
from scoreform.work_paths import scoreform_work_paths

STANDARD_ID = "nj_ela_2023_rl_cr_9_10_1"
PROFILE_ID = "english10_2023_njsls"


def _standards_library() -> StandardsLibrary:
    return StandardsLibrary(
        standards=(
            StandardDefinition(
                standard_id=STANDARD_ID,
                code="RL.CR.9-10.1",
                source="NJSLS-ELA 2023",
                short_name="Close Reading Evidence",
                description="Cite strong and thorough textual evidence.",
            ),
        ),
        profiles=(
            StandardsProfile(
                profile_id=PROFILE_ID,
                standards=(STANDARD_ID,),
            ),
        ),
    )


def _empty_standards_library() -> StandardsLibrary:
    return StandardsLibrary(standards=(), profiles=())


def _assignment(
    assignment_id: str = "unit_1_quiz",
    *,
    with_standards: bool = False,
    extra: bool = False,
) -> dict[str, object]:
    assignment: dict[str, object] = {
        "assignment_id": assignment_id,
        "title": "Unit 1 Quiz",
        "question_count": 3,
        "choices": ["A", "B", "C", "D"],
        "layout_id": "standard_15q_abcd_v1",
        "answer_key": {"1": "A", "2": "B", "3": "C"},
        "standards": {"1": [], "2": [], "3": []},
    }
    if with_standards:
        assignment["standards_profile_id"] = PROFILE_ID
        assignment["standards"] = {
            "1": [STANDARD_ID],
            "2": [],
            "3": [],
        }
    if extra:
        assignment["future_nonbulk_field"] = {
            "synthetic": True,
            "nested": [1, 2, 3],
        }
    return assignment


def _write_assignment(
    root: Path,
    *,
    class_id: str = "english10_p2",
    assignment_id: str = "unit_1_quiz",
    assignment: dict[str, object] | None = None,
) -> tuple[Path, bytes]:
    paths = scoreform_work_paths(root, class_id, assignment_id)
    paths.work_root.mkdir(parents=True, exist_ok=True)
    payload = _assignment(assignment_id) if assignment is None else assignment
    data = (json.dumps(payload, indent=2) + "\n").encode("utf-8")
    paths.assignment_path.write_bytes(data)
    return paths.assignment_path, data


def _answer_key(*answers: str) -> BulkAnswerKey:
    return BulkAnswerKey(tuple(answers))


def _alignment(
    *rows: tuple[str, ...],
    profile_id: str | None = PROFILE_ID,
) -> BulkStandardsAlignment:
    return BulkStandardsAlignment(
        standards_profile_id=profile_id,
        by_question=tuple(rows),
    )


def _assert_no_temp_files(path: Path) -> None:
    leftovers = tuple(path.parent.glob(f".{path.name}.*.tmp"))
    assert leftovers == ()


def test_snapshot_captures_exact_bytes_digest_and_preserved_payload(
    tmp_path: Path,
) -> None:
    path, data = _write_assignment(tmp_path, assignment=_assignment(extra=True))

    snapshot = load_assignment_bulk_snapshot(
        tmp_path,
        "english10_p2",
        "unit_1_quiz",
    )

    assert snapshot.assignment_path == path
    assert snapshot.assignment_bytes == data
    assert snapshot.assignment_sha256 == hashlib.sha256(data).hexdigest()
    assert snapshot.assignment["assignment_id"] == "unit_1_quiz"
    assert snapshot.payload["future_nonbulk_field"] == {
        "synthetic": True,
        "nested": [1, 2, 3],
    }


def test_snapshot_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    paths = scoreform_work_paths(tmp_path, "english10_p2", "unit_1_quiz")
    paths.work_root.mkdir(parents=True)
    paths.assignment_path.write_text(
        """{
  "assignment_id": "unit_1_quiz",
  "assignment_id": "different",
  "title": "Unit 1 Quiz",
  "question_count": 1,
  "choices": ["A", "B", "C", "D"],
  "layout_id": "standard_15q_abcd_v1",
  "answer_key": {"1": "A"},
  "standards": {"1": []}
}
""",
        encoding="utf-8",
    )

    with pytest.raises(
        AssignmentBulkMutationValidationError,
        match="duplicate object key",
    ):
        load_assignment_bulk_snapshot(
            tmp_path,
            "english10_p2",
            "unit_1_quiz",
        )


def test_snapshot_rejects_nonfinite_json_constant(tmp_path: Path) -> None:
    path, _ = _write_assignment(tmp_path)
    text = path.read_text(encoding="utf-8").replace(
        '"question_count": 3',
        '"question_count": NaN',
    )
    path.write_text(text, encoding="utf-8")

    with pytest.raises(
        AssignmentBulkMutationValidationError,
        match="nonfinite",
    ):
        load_assignment_bulk_snapshot(
            tmp_path,
            "english10_p2",
            "unit_1_quiz",
        )


def test_snapshot_identity_must_match_canonical_work_path(tmp_path: Path) -> None:
    _write_assignment(
        tmp_path,
        assignment=_assignment("different_assignment"),
    )

    with pytest.raises(
        AssignmentBulkMutationValidationError,
        match="managed work identity",
    ):
        load_assignment_bulk_snapshot(
            tmp_path,
            "english10_p2",
            "unit_1_quiz",
        )


def test_snapshot_with_standards_requires_current_library(tmp_path: Path) -> None:
    _write_assignment(
        tmp_path,
        assignment=_assignment(with_standards=True),
    )

    with pytest.raises(
        AssignmentBulkMutationValidationError,
        match="current Core standards library",
    ):
        load_assignment_bulk_snapshot(
            tmp_path,
            "english10_p2",
            "unit_1_quiz",
        )


def test_snapshot_revalidates_standards_against_current_core_library(
    tmp_path: Path,
) -> None:
    _write_assignment(
        tmp_path,
        assignment=_assignment(with_standards=True),
    )

    with pytest.raises(
        AssignmentBulkMutationValidationError,
        match="not currently valid",
    ):
        load_assignment_bulk_snapshot(
            tmp_path,
            "english10_p2",
            "unit_1_quiz",
            standards_library=_empty_standards_library(),
        )


def test_snapshot_rejects_assignment_file_symlink(tmp_path: Path) -> None:
    path, _ = _write_assignment(tmp_path)
    target = path.with_name("target.json")
    target.write_bytes(path.read_bytes())
    path.unlink()
    try:
        path.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("Symbolic links are unavailable in this environment.")

    with pytest.raises(
        AssignmentBulkMutationValidationError,
        match="symbolic link",
    ):
        load_assignment_bulk_snapshot(
            tmp_path,
            "english10_p2",
            "unit_1_quiz",
        )


def test_snapshot_rejects_symlink_in_assignment_parent_chain(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    target_paths = scoreform_work_paths(
        outside,
        "english10_p2",
        "unit_1_quiz",
    )
    target_paths.work_root.mkdir(parents=True)
    target_paths.assignment_path.write_text(
        json.dumps(_assignment(), indent=2) + "\n",
        encoding="utf-8",
    )

    class_root = tmp_path / "classes" / "english10_p2"
    class_root.parent.mkdir(parents=True)
    try:
        class_root.symlink_to(outside / "classes" / "english10_p2", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Directory symbolic links are unavailable in this environment.")

    with pytest.raises(
        AssignmentBulkMutationValidationError,
        match="symbolic link",
    ):
        load_assignment_bulk_snapshot(
            tmp_path,
            "english10_p2",
            "unit_1_quiz",
        )


def test_build_answer_key_candidate_preserves_all_unrelated_data(
    tmp_path: Path,
) -> None:
    _write_assignment(tmp_path, assignment=_assignment(extra=True))
    snapshot = load_assignment_bulk_snapshot(
        tmp_path,
        "english10_p2",
        "unit_1_quiz",
    )

    payload, assignment = build_assignment_bulk_candidate(
        snapshot,
        answer_key=_answer_key("D", "C", "B"),
    )

    assert payload["answer_key"] == {"1": "D", "2": "C", "3": "B"}
    assert assignment["answer_key"] == {1: "D", 2: "C", 3: "B"}
    assert payload["title"] == snapshot.payload["title"]
    assert payload["question_count"] == snapshot.payload["question_count"]
    assert payload["choices"] == snapshot.payload["choices"]
    assert payload["layout_id"] == snapshot.payload["layout_id"]
    assert payload["future_nonbulk_field"] == snapshot.payload["future_nonbulk_field"]
    assert payload["standards"] == snapshot.payload["standards"]


def test_build_alignment_candidate_replaces_full_alignment(tmp_path: Path) -> None:
    _write_assignment(tmp_path)
    snapshot = load_assignment_bulk_snapshot(
        tmp_path,
        "english10_p2",
        "unit_1_quiz",
    )

    payload, assignment = build_assignment_bulk_candidate(
        snapshot,
        standards_alignment=_alignment((STANDARD_ID,), (), (STANDARD_ID,)),
        standards_library=_standards_library(),
    )

    assert payload["standards_profile_id"] == PROFILE_ID
    assert payload["standards"] == {
        "1": [STANDARD_ID],
        "2": [],
        "3": [STANDARD_ID],
    }
    assert assignment["standards_profile_id"] == PROFILE_ID


def test_all_unaligned_replacement_removes_profile_id(tmp_path: Path) -> None:
    _write_assignment(
        tmp_path,
        assignment=_assignment(with_standards=True),
    )
    library = _standards_library()
    snapshot = load_assignment_bulk_snapshot(
        tmp_path,
        "english10_p2",
        "unit_1_quiz",
        standards_library=library,
    )

    payload, assignment = build_assignment_bulk_candidate(
        snapshot,
        standards_alignment=_alignment((), (), (), profile_id=None),
        standards_library=library,
    )

    assert "standards_profile_id" not in payload
    assert "standards_profile_id" not in assignment
    assert payload["standards"] == {"1": [], "2": [], "3": []}


def test_build_rejects_answer_key_with_wrong_question_count(tmp_path: Path) -> None:
    _write_assignment(tmp_path)
    snapshot = load_assignment_bulk_snapshot(
        tmp_path,
        "english10_p2",
        "unit_1_quiz",
    )

    with pytest.raises(
        AssignmentBulkMutationValidationError,
        match="question count",
    ):
        build_assignment_bulk_candidate(
            snapshot,
            answer_key=_answer_key("A", "B"),
        )


def test_build_rejects_answer_choice_outside_assignment_choices(tmp_path: Path) -> None:
    _write_assignment(tmp_path)
    snapshot = load_assignment_bulk_snapshot(
        tmp_path,
        "english10_p2",
        "unit_1_quiz",
    )

    with pytest.raises(
        AssignmentBulkMutationValidationError,
        match="choice not allowed",
    ):
        build_assignment_bulk_candidate(
            snapshot,
            answer_key=_answer_key("A", "B", "E"),
        )


def test_build_requires_at_least_one_bulk_replacement(tmp_path: Path) -> None:
    _write_assignment(tmp_path)
    snapshot = load_assignment_bulk_snapshot(
        tmp_path,
        "english10_p2",
        "unit_1_quiz",
    )

    with pytest.raises(
        AssignmentBulkMutationValidationError,
        match="requires an answer key or standards alignment",
    ):
        build_assignment_bulk_candidate(snapshot)


def test_build_aligned_candidate_requires_current_standards_library(
    tmp_path: Path,
) -> None:
    _write_assignment(tmp_path)
    snapshot = load_assignment_bulk_snapshot(
        tmp_path,
        "english10_p2",
        "unit_1_quiz",
    )

    with pytest.raises(
        AssignmentBulkMutationValidationError,
        match="current Core standards library",
    ):
        build_assignment_bulk_candidate(
            snapshot,
            standards_alignment=_alignment((STANDARD_ID,), (), ()),
        )


def test_plan_is_non_mutating_and_contains_exact_candidate_digest(
    tmp_path: Path,
) -> None:
    path, before = _write_assignment(tmp_path, assignment=_assignment(extra=True))
    snapshot = load_assignment_bulk_snapshot(
        tmp_path,
        "english10_p2",
        "unit_1_quiz",
    )

    plan = plan_assignment_bulk_mutation(
        snapshot,
        answer_key=_answer_key("D", "D", "D"),
    )

    assert path.read_bytes() == before
    assert plan.snapshot.assignment_bytes == before
    assert plan.candidate_sha256 == hashlib.sha256(plan.candidate_bytes).hexdigest()
    assert plan.candidate_payload["future_nonbulk_field"] == (
        snapshot.payload["future_nonbulk_field"]
    )
    _assert_no_temp_files(path)


def test_candidate_mutation_after_preview_is_detected(tmp_path: Path) -> None:
    path, before = _write_assignment(tmp_path)
    snapshot = load_assignment_bulk_snapshot(
        tmp_path,
        "english10_p2",
        "unit_1_quiz",
    )
    plan = plan_assignment_bulk_mutation(
        snapshot,
        answer_key=_answer_key("D", "D", "D"),
    )
    plan.candidate_payload["title"] = "Tampered"

    with pytest.raises(
        AssignmentBulkMutationValidationError,
        match="cannot change 'title'",
    ):
        commit_assignment_bulk_mutation(tmp_path, plan)

    assert path.read_bytes() == before
    _assert_no_temp_files(path)


def test_stale_assignment_bytes_abort_without_overwrite(tmp_path: Path) -> None:
    path, _ = _write_assignment(tmp_path)
    snapshot = load_assignment_bulk_snapshot(
        tmp_path,
        "english10_p2",
        "unit_1_quiz",
    )
    plan = plan_assignment_bulk_mutation(
        snapshot,
        answer_key=_answer_key("D", "D", "D"),
    )
    externally_changed = (json.dumps(_assignment(), separators=(",", ":")) + "\n").encode(
        "utf-8"
    )
    path.write_bytes(externally_changed)

    with pytest.raises(
        AssignmentBulkMutationConflictError,
        match="changed after preview",
    ):
        commit_assignment_bulk_mutation(tmp_path, plan)

    assert path.read_bytes() == externally_changed
    _assert_no_temp_files(path)


def test_deleted_assignment_after_preview_aborts_without_recreation(
    tmp_path: Path,
) -> None:
    path, _ = _write_assignment(tmp_path)
    snapshot = load_assignment_bulk_snapshot(
        tmp_path,
        "english10_p2",
        "unit_1_quiz",
    )
    plan = plan_assignment_bulk_mutation(
        snapshot,
        answer_key=_answer_key("D", "D", "D"),
    )
    path.unlink()

    with pytest.raises(
        AssignmentBulkMutationConflictError,
        match="became unavailable",
    ):
        commit_assignment_bulk_mutation(tmp_path, plan)

    assert not path.exists()
    _assert_no_temp_files(path)


def test_assignment_becoming_symlink_after_preview_aborts(tmp_path: Path) -> None:
    path, before = _write_assignment(tmp_path)
    snapshot = load_assignment_bulk_snapshot(
        tmp_path,
        "english10_p2",
        "unit_1_quiz",
    )
    plan = plan_assignment_bulk_mutation(
        snapshot,
        answer_key=_answer_key("D", "D", "D"),
    )
    target = path.with_name("external.json")
    target.write_bytes(before)
    path.unlink()
    try:
        path.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("Symbolic links are unavailable in this environment.")

    with pytest.raises(
        AssignmentBulkMutationConflictError,
        match="became unsafe or invalid",
    ):
        commit_assignment_bulk_mutation(tmp_path, plan)

    assert path.is_symlink()
    assert target.read_bytes() == before


def test_atomic_commit_replaces_only_assignment_definition(tmp_path: Path) -> None:
    path, before = _write_assignment(tmp_path, assignment=_assignment(extra=True))
    paths = scoreform_work_paths(tmp_path, "english10_p2", "unit_1_quiz")
    paths.results_path.write_text("synthetic historical result\n", encoding="utf-8")
    paths.templates_dir.mkdir()
    template = paths.templates_dir / "existing.pdf"
    template.write_bytes(b"synthetic-pdf")
    sentinel = paths.work_root / "unrelated.txt"
    sentinel.write_text("unchanged\n", encoding="utf-8")

    snapshot = load_assignment_bulk_snapshot(
        tmp_path,
        "english10_p2",
        "unit_1_quiz",
    )
    plan = plan_assignment_bulk_mutation(
        snapshot,
        answer_key=_answer_key("D", "C", "B"),
    )
    persisted = commit_assignment_bulk_mutation(tmp_path, plan)

    assert path.read_bytes() != before
    assert path.read_bytes() == plan.candidate_bytes
    assert persisted.assignment_sha256 == plan.candidate_sha256
    assert persisted.assignment["answer_key"] == {1: "D", 2: "C", 3: "B"}
    assert persisted.payload["future_nonbulk_field"] == (
        snapshot.payload["future_nonbulk_field"]
    )
    assert paths.results_path.read_text(encoding="utf-8") == (
        "synthetic historical result\n"
    )
    assert template.read_bytes() == b"synthetic-pdf"
    assert sentinel.read_text(encoding="utf-8") == "unchanged\n"
    _assert_no_temp_files(path)


def test_atomic_commit_can_stage_key_and_alignment_together(tmp_path: Path) -> None:
    path, _ = _write_assignment(tmp_path)
    library = _standards_library()
    snapshot = load_assignment_bulk_snapshot(
        tmp_path,
        "english10_p2",
        "unit_1_quiz",
    )
    plan = plan_assignment_bulk_mutation(
        snapshot,
        answer_key=_answer_key("B", "B", "B"),
        standards_alignment=_alignment((STANDARD_ID,), (), (STANDARD_ID,)),
        standards_library=library,
    )

    persisted = commit_assignment_bulk_mutation(
        tmp_path,
        plan,
        standards_library=library,
    )

    assert persisted.assignment["answer_key"] == {1: "B", 2: "B", 3: "B"}
    assert persisted.assignment["standards_profile_id"] == PROFILE_ID
    assert persisted.assignment["standards"] == {
        "1": [STANDARD_ID],
        "2": [],
        "3": [STANDARD_ID],
    }
    assert path.read_bytes() == plan.candidate_bytes


def test_commit_revalidates_candidate_standards_before_writing(tmp_path: Path) -> None:
    path, before = _write_assignment(tmp_path)
    good_library = _standards_library()
    snapshot = load_assignment_bulk_snapshot(
        tmp_path,
        "english10_p2",
        "unit_1_quiz",
    )
    plan = plan_assignment_bulk_mutation(
        snapshot,
        standards_alignment=_alignment((STANDARD_ID,), (), ()),
        standards_library=good_library,
    )

    with pytest.raises(
        AssignmentBulkMutationValidationError,
        match="not currently valid",
    ):
        commit_assignment_bulk_mutation(
            tmp_path,
            plan,
            standards_library=_empty_standards_library(),
        )

    assert path.read_bytes() == before
    _assert_no_temp_files(path)


def test_replace_failure_leaves_original_and_cleans_temp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path, before = _write_assignment(tmp_path)
    snapshot = load_assignment_bulk_snapshot(
        tmp_path,
        "english10_p2",
        "unit_1_quiz",
    )
    plan = plan_assignment_bulk_mutation(
        snapshot,
        answer_key=_answer_key("D", "D", "D"),
    )

    def fail_replace(source: str | bytes | os.PathLike[str], destination: object) -> None:
        raise OSError("synthetic replace failure")

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(
        AssignmentBulkMutationWriteError,
        match="synthetic replace failure",
    ):
        commit_assignment_bulk_mutation(tmp_path, plan)

    assert path.read_bytes() == before
    _assert_no_temp_files(path)


def test_temp_validation_failure_leaves_original_and_cleans_temp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scoreform.assignment_bulk_mutation as mutation

    path, before = _write_assignment(tmp_path)
    snapshot = load_assignment_bulk_snapshot(
        tmp_path,
        "english10_p2",
        "unit_1_quiz",
    )
    plan = plan_assignment_bulk_mutation(
        snapshot,
        answer_key=_answer_key("D", "D", "D"),
    )

    def fail_temp_validation(*args: object, **kwargs: object) -> None:
        raise AssignmentBulkMutationWriteError("synthetic temp validation failure")

    monkeypatch.setattr(
        mutation,
        "_validate_temporary_candidate",
        fail_temp_validation,
    )

    with pytest.raises(
        AssignmentBulkMutationWriteError,
        match="synthetic temp validation failure",
    ):
        commit_assignment_bulk_mutation(tmp_path, plan)

    assert path.read_bytes() == before
    _assert_no_temp_files(path)


def test_plan_from_other_workspace_cannot_be_committed(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    other_root = tmp_path / "other"
    path, before = _write_assignment(source_root)
    _write_assignment(other_root)
    snapshot = load_assignment_bulk_snapshot(
        source_root,
        "english10_p2",
        "unit_1_quiz",
    )
    plan = plan_assignment_bulk_mutation(
        snapshot,
        answer_key=_answer_key("D", "D", "D"),
    )

    with pytest.raises(
        AssignmentBulkMutationConflictError,
        match="does not match this workspace",
    ):
        commit_assignment_bulk_mutation(other_root, plan)

    assert path.read_bytes() == before


def test_nonbulk_payload_tampering_cannot_be_hidden_in_replacement(
    tmp_path: Path,
) -> None:
    path, before = _write_assignment(tmp_path, assignment=_assignment(extra=True))
    snapshot = load_assignment_bulk_snapshot(
        tmp_path,
        "english10_p2",
        "unit_1_quiz",
    )
    plan = plan_assignment_bulk_mutation(
        snapshot,
        answer_key=_answer_key("D", "D", "D"),
    )
    plan.candidate_payload["future_nonbulk_field"] = {"synthetic": False}

    with pytest.raises(
        AssignmentBulkMutationValidationError,
        match="cannot change 'future_nonbulk_field'",
    ):
        commit_assignment_bulk_mutation(tmp_path, plan)

    assert path.read_bytes() == before


def test_commit_revalidates_original_snapshot_immediately_before_replace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scoreform.assignment_bulk_mutation as mutation

    path, before = _write_assignment(tmp_path)
    snapshot = load_assignment_bulk_snapshot(
        tmp_path,
        "english10_p2",
        "unit_1_quiz",
    )
    plan = plan_assignment_bulk_mutation(
        snapshot,
        answer_key=_answer_key("D", "D", "D"),
    )
    original_temp_validation = mutation._validate_temporary_candidate

    def change_source_during_temp_validation(*args: object, **kwargs: object) -> None:
        original_temp_validation(*args, **kwargs)
        changed = json.loads(before.decode("utf-8"))
        changed["title"] = "External concurrent edit"
        path.write_text(json.dumps(changed, indent=2) + "\n", encoding="utf-8")

    monkeypatch.setattr(
        mutation,
        "_validate_temporary_candidate",
        change_source_during_temp_validation,
    )

    with pytest.raises(
        AssignmentBulkMutationConflictError,
        match="changed after preview",
    ):
        commit_assignment_bulk_mutation(tmp_path, plan)

    current = json.loads(path.read_text(encoding="utf-8"))
    assert current["title"] == "External concurrent edit"
    _assert_no_temp_files(path)


def test_key_only_edit_preserves_and_revalidates_existing_standards(
    tmp_path: Path,
) -> None:
    library = _standards_library()
    path, _ = _write_assignment(
        tmp_path,
        assignment=_assignment(with_standards=True),
    )
    snapshot = load_assignment_bulk_snapshot(
        tmp_path,
        "english10_p2",
        "unit_1_quiz",
        standards_library=library,
    )
    plan = plan_assignment_bulk_mutation(
        snapshot,
        answer_key=_answer_key("C", "C", "C"),
        standards_library=library,
    )

    persisted = commit_assignment_bulk_mutation(
        tmp_path,
        plan,
        standards_library=library,
    )

    assert persisted.assignment["answer_key"] == {1: "C", 2: "C", 3: "C"}
    assert persisted.assignment["standards_profile_id"] == PROFILE_ID
    assert persisted.assignment["standards"] == snapshot.assignment["standards"]
    assert path.read_bytes() == plan.candidate_bytes


def test_build_rejects_alignment_with_wrong_question_count(tmp_path: Path) -> None:
    _write_assignment(tmp_path)
    snapshot = load_assignment_bulk_snapshot(
        tmp_path,
        "english10_p2",
        "unit_1_quiz",
    )

    with pytest.raises(
        AssignmentBulkMutationValidationError,
        match="question count",
    ):
        build_assignment_bulk_candidate(
            snapshot,
            standards_alignment=_alignment((STANDARD_ID,), ()),
            standards_library=_standards_library(),
        )


def test_temp_byte_tampering_is_detected_before_replace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scoreform.assignment_bulk_mutation as mutation

    path, before = _write_assignment(tmp_path)
    snapshot = load_assignment_bulk_snapshot(
        tmp_path,
        "english10_p2",
        "unit_1_quiz",
    )
    plan = plan_assignment_bulk_mutation(
        snapshot,
        answer_key=_answer_key("D", "D", "D"),
    )
    original_temp_validation = mutation._validate_temporary_candidate

    def tamper_then_validate(temp_path: Path, **kwargs: object) -> None:
        temp_path.write_bytes(temp_path.read_bytes() + b" ")
        original_temp_validation(temp_path, **kwargs)

    monkeypatch.setattr(
        mutation,
        "_validate_temporary_candidate",
        tamper_then_validate,
    )

    with pytest.raises(
        AssignmentBulkMutationWriteError,
        match="bytes changed",
    ):
        commit_assignment_bulk_mutation(tmp_path, plan)

    assert path.read_bytes() == before
    _assert_no_temp_files(path)
