from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pds_core.routes import class_roster_path
from pds_core.standards import StandardDefinition, StandardsLibrary, StandardsProfile

from scoreform.assignment_copying import (
    AssignmentCopyConflictError,
    AssignmentCopyNotFoundError,
    AssignmentCopyValidationError,
    build_assignment_copy_candidate,
    load_assignment_copy_source,
    plan_assignment_copy,
)
from scoreform.work_paths import scoreform_work_paths


def _standards_library() -> StandardsLibrary:
    return StandardsLibrary(
        standards=(
            StandardDefinition(
                standard_id="nj_ela_2023_rl_cr_9_10_1",
                code="RL.CR.9-10.1",
                source="NJSLS-ELA 2023",
                short_name="Close Reading Evidence",
                description="Cite strong and thorough textual evidence.",
            ),
        ),
        profiles=(
            StandardsProfile(
                profile_id="english10_2023_njsls",
                standards=("nj_ela_2023_rl_cr_9_10_1",),
            ),
        ),
    )


def _assignment(
    assignment_id: str = "unit_1_quiz",
    *,
    with_standards: bool = False,
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
        assignment["standards_profile_id"] = "english10_2023_njsls"
        assignment["standards"] = {
            "1": ["nj_ela_2023_rl_cr_9_10_1"],
            "2": [],
            "3": [],
        }
    return assignment


def _write_roster(
    root: Path,
    class_id: str,
    *,
    periods: tuple[str, ...] = ("2", "2"),
) -> Path:
    path = class_roster_path(root, class_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        "class_id,student_id,last_name,first_name,period",
        *[
            f"{class_id},student_{index},Student{index},Synthetic,{period}"
            for index, period in enumerate(periods, start=1)
        ],
    ]
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def _write_source(
    root: Path,
    class_id: str = "english10_p2",
    assignment_id: str = "unit_1_quiz",
    *,
    assignment: dict[str, object] | None = None,
) -> tuple[Path, bytes]:
    paths = scoreform_work_paths(root, class_id, assignment_id)
    paths.work_root.mkdir(parents=True, exist_ok=True)
    payload = _assignment(assignment_id) if assignment is None else assignment
    data = (json.dumps(payload, indent=2) + "\n").encode("utf-8")
    paths.assignment_path.write_bytes(data)
    return paths.assignment_path, data


def test_load_source_captures_exact_bytes_digest_and_allowlisted_definition(
    tmp_path: Path,
) -> None:
    assignment = _assignment()
    assignment["future_noncopyable_field"] = {"state": "must not propagate"}
    path, data = _write_source(tmp_path, assignment=assignment)

    source = load_assignment_copy_source(
        tmp_path,
        "english10_p2",
        "unit_1_quiz",
    )

    assert source.assignment_path == path
    assert source.assignment_bytes == data
    assert source.assignment_sha256 == hashlib.sha256(data).hexdigest()
    assert source.definition.assignment_id == "unit_1_quiz"
    assert source.definition.answer_key == ((1, "A"), (2, "B"), (3, "C"))
    assert source.definition.standards_profile_id is None

    candidate = build_assignment_copy_candidate(
        source,
        target_assignment_id="unit_1_quiz_copy",
    )
    assert "future_noncopyable_field" not in candidate


def test_source_duplicate_json_keys_are_rejected(tmp_path: Path) -> None:
    paths = scoreform_work_paths(tmp_path, "english10_p2", "unit_1_quiz")
    paths.work_root.mkdir(parents=True)
    paths.assignment_path.write_text(
        """{
  "assignment_id": "unit_1_quiz",
  "assignment_id": "other",
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

    with pytest.raises(AssignmentCopyValidationError, match="duplicate object key"):
        load_assignment_copy_source(
            tmp_path,
            "english10_p2",
            "unit_1_quiz",
        )


def test_source_identity_must_match_canonical_work_path(tmp_path: Path) -> None:
    _write_source(
        tmp_path,
        assignment=_assignment("different_assignment"),
    )

    with pytest.raises(AssignmentCopyValidationError, match="managed work identity"):
        load_assignment_copy_source(
            tmp_path,
            "english10_p2",
            "unit_1_quiz",
        )


def test_source_with_standards_requires_current_library(tmp_path: Path) -> None:
    _write_source(
        tmp_path,
        assignment=_assignment(with_standards=True),
    )

    with pytest.raises(AssignmentCopyValidationError, match="standards library"):
        load_assignment_copy_source(
            tmp_path,
            "english10_p2",
            "unit_1_quiz",
        )


def test_source_standards_are_revalidated_against_current_core_library(
    tmp_path: Path,
) -> None:
    assignment = _assignment(with_standards=True)
    assignment["standards_profile_id"] = "missing_profile"
    _write_source(tmp_path, assignment=assignment)

    with pytest.raises(AssignmentCopyValidationError, match="not currently valid"):
        load_assignment_copy_source(
            tmp_path,
            "english10_p2",
            "unit_1_quiz",
            standards_library=_standards_library(),
        )


def test_candidate_is_positive_allowlist_and_independent_copy(tmp_path: Path) -> None:
    _write_source(
        tmp_path,
        assignment=_assignment(with_standards=True),
    )
    source = load_assignment_copy_source(
        tmp_path,
        "english10_p2",
        "unit_1_quiz",
        standards_library=_standards_library(),
    )

    first = build_assignment_copy_candidate(
        source,
        target_assignment_id="unit_1_quiz_makeup",
        title="Unit 1 Quiz - Makeup",
    )
    second = build_assignment_copy_candidate(
        source,
        target_assignment_id="unit_1_quiz_period4",
    )

    assert set(first) == {
        "assignment_id",
        "title",
        "question_count",
        "choices",
        "layout_id",
        "answer_key",
        "standards",
        "standards_profile_id",
    }
    assert first["assignment_id"] == "unit_1_quiz_makeup"
    assert first["title"] == "Unit 1 Quiz - Makeup"
    assert second["title"] == "Unit 1 Quiz"

    assert isinstance(first["choices"], list)
    first["choices"].append("TEST_ONLY")
    assert second["choices"] == ["A", "B", "C", "D"]

    assert isinstance(first["standards"], dict)
    first["standards"]["1"].append("test_only")
    assert second["standards"]["1"] == ["nj_ela_2023_rl_cr_9_10_1"]
    assert source.definition.standards == (
        (1, ("nj_ela_2023_rl_cr_9_10_1",)),
        (2, ()),
        (3, ()),
    )


def test_plan_multiple_targets_preserves_selection_order_and_roster_summary(
    tmp_path: Path,
) -> None:
    _write_source(tmp_path)
    _write_roster(tmp_path, "english10_p4", periods=("4", "4"))
    _write_roster(tmp_path, "english10_p6", periods=("6", "7"))
    source = load_assignment_copy_source(
        tmp_path,
        "english10_p2",
        "unit_1_quiz",
    )

    plan = plan_assignment_copy(
        tmp_path,
        source,
        target_class_ids=("english10_p6", "english10_p4"),
        target_assignment_id="unit_1_quiz",
    )

    assert [target.work.class_id for target in plan.targets] == [
        "english10_p6",
        "english10_p4",
    ]
    assert plan.targets[0].roster.student_count == 2
    assert plan.targets[0].roster.periods == ("6", "7")
    assert plan.targets[1].roster.periods == ("4",)

    for target in plan.targets:
        assert not target.work_root.exists()


def test_plan_rejects_duplicate_target_class(tmp_path: Path) -> None:
    _write_source(tmp_path)
    _write_roster(tmp_path, "english10_p4")
    source = load_assignment_copy_source(
        tmp_path,
        "english10_p2",
        "unit_1_quiz",
    )

    with pytest.raises(AssignmentCopyValidationError, match="more than once"):
        plan_assignment_copy(
            tmp_path,
            source,
            target_class_ids=("english10_p4", "english10_p4"),
            target_assignment_id="unit_1_quiz",
        )


def test_plan_rejects_exact_source_as_its_own_target(tmp_path: Path) -> None:
    _write_source(tmp_path)
    _write_roster(tmp_path, "english10_p2")
    source = load_assignment_copy_source(
        tmp_path,
        "english10_p2",
        "unit_1_quiz",
    )

    with pytest.raises(AssignmentCopyConflictError, match="own copy target"):
        plan_assignment_copy(
            tmp_path,
            source,
            target_class_ids=("english10_p2",),
            target_assignment_id="unit_1_quiz",
        )


def test_plan_allows_same_class_with_different_assignment_id(tmp_path: Path) -> None:
    _write_source(tmp_path)
    _write_roster(tmp_path, "english10_p2")
    source = load_assignment_copy_source(
        tmp_path,
        "english10_p2",
        "unit_1_quiz",
    )

    plan = plan_assignment_copy(
        tmp_path,
        source,
        target_class_ids=("english10_p2",),
        target_assignment_id="unit_1_quiz_makeup",
    )

    assert plan.targets[0].work.class_id == "english10_p2"
    assert plan.targets[0].work.work_id == "unit_1_quiz_makeup"
    assert not plan.targets[0].work_root.exists()


def test_plan_requires_valid_target_core_roster(tmp_path: Path) -> None:
    _write_source(tmp_path)
    source = load_assignment_copy_source(
        tmp_path,
        "english10_p2",
        "unit_1_quiz",
    )

    with pytest.raises(AssignmentCopyNotFoundError, match="valid Core roster"):
        plan_assignment_copy(
            tmp_path,
            source,
            target_class_ids=("english10_p4",),
            target_assignment_id="unit_1_quiz",
        )


def test_plan_is_non_mutating_even_when_source_has_operational_descendants(
    tmp_path: Path,
) -> None:
    source_path, _ = _write_source(tmp_path)
    source_paths = scoreform_work_paths(tmp_path, "english10_p2", "unit_1_quiz")
    source_paths.results_path.write_text("synthetic result history\n", encoding="utf-8")
    source_paths.templates_dir.mkdir()
    (source_paths.templates_dir / "old.pdf").write_bytes(b"synthetic-pdf")
    _write_roster(tmp_path, "english10_p4")

    source = load_assignment_copy_source(
        tmp_path,
        "english10_p2",
        "unit_1_quiz",
    )
    before = source_path.read_bytes()

    plan = plan_assignment_copy(
        tmp_path,
        source,
        target_class_ids=("english10_p4",),
        target_assignment_id="unit_1_quiz",
    )

    target = plan.targets[0]
    assert not target.work_root.exists()
    assert source_path.read_bytes() == before
    assert source_paths.results_path.read_text(encoding="utf-8") == (
        "synthetic result history\n"
    )
    assert (source_paths.templates_dir / "old.pdf").read_bytes() == b"synthetic-pdf"


def test_invalid_target_assignment_id_is_rejected_without_creating_state(
    tmp_path: Path,
) -> None:
    _write_source(tmp_path)
    _write_roster(tmp_path, "english10_p4")
    source = load_assignment_copy_source(
        tmp_path,
        "english10_p2",
        "unit_1_quiz",
    )

    with pytest.raises(AssignmentCopyValidationError):
        plan_assignment_copy(
            tmp_path,
            source,
            target_class_ids=("english10_p4",),
            target_assignment_id="../unsafe",
        )

    assert not (tmp_path / "classes" / "english10_p4" / "modules").exists()


def test_plan_rejects_any_existing_target_work_root(tmp_path: Path) -> None:
    _write_source(tmp_path)
    _write_roster(tmp_path, "english10_p4")
    target = scoreform_work_paths(tmp_path, "english10_p4", "unit_1_quiz")
    target.work_root.mkdir(parents=True)
    (target.work_root / "results.csv").write_text(
        "synthetic stale state\n",
        encoding="utf-8",
    )
    source = load_assignment_copy_source(
        tmp_path,
        "english10_p2",
        "unit_1_quiz",
    )

    with pytest.raises(AssignmentCopyConflictError, match="work root already exists"):
        plan_assignment_copy(
            tmp_path,
            source,
            target_class_ids=("english10_p4",),
            target_assignment_id="unit_1_quiz",
        )

    assert (target.work_root / "results.csv").read_text(encoding="utf-8") == (
        "synthetic stale state\n"
    )


def test_multi_target_known_collision_blocks_every_target_before_write(
    tmp_path: Path,
) -> None:
    _write_source(tmp_path)
    _write_roster(tmp_path, "english10_p4")
    _write_roster(tmp_path, "english10_p6")
    collided = scoreform_work_paths(tmp_path, "english10_p6", "unit_1_quiz")
    collided.work_root.mkdir(parents=True)
    first = scoreform_work_paths(tmp_path, "english10_p4", "unit_1_quiz")
    source = load_assignment_copy_source(
        tmp_path,
        "english10_p2",
        "unit_1_quiz",
    )

    with pytest.raises(AssignmentCopyConflictError, match="work root already exists"):
        plan_assignment_copy(
            tmp_path,
            source,
            target_class_ids=("english10_p4", "english10_p6"),
            target_assignment_id="unit_1_quiz",
        )

    assert not first.work_root.exists()


def test_commit_creates_fresh_layout_and_assignment_only(tmp_path: Path) -> None:
    from scoreform.assignment_copying import commit_assignment_copy

    _write_source(tmp_path)
    _write_roster(tmp_path, "english10_p4", periods=("4", "4"))
    source = load_assignment_copy_source(
        tmp_path,
        "english10_p2",
        "unit_1_quiz",
    )
    plan = plan_assignment_copy(
        tmp_path,
        source,
        target_class_ids=("english10_p4",),
        target_assignment_id="unit_1_quiz",
    )

    result = commit_assignment_copy(tmp_path, plan)

    assert result.complete is True
    assert len(result.created) == 1
    assert result.failures == ()
    assert result.not_attempted == ()

    target = scoreform_work_paths(tmp_path, "english10_p4", "unit_1_quiz")
    assert target.assignment_path.is_file()
    assert (target.work_root / "templates").is_dir()
    assert (target.work_root / "templates" / "individual").is_dir()
    assert (target.work_root / "scans").is_dir()
    assert (target.work_root / "debug").is_dir()
    assert not target.results_path.exists()
    assert not target.answer_sheets_dir.exists()
    assert not target.exports_dir.exists()
    assert not (target.work_root / "routes").exists()

    persisted = json.loads(target.assignment_path.read_text(encoding="utf-8"))
    assert persisted["assignment_id"] == "unit_1_quiz"
    assert persisted["answer_key"] == {"1": "A", "2": "B", "3": "C"}


def test_commit_rejects_stale_source_before_any_target_write(tmp_path: Path) -> None:
    from scoreform.assignment_copying import commit_assignment_copy

    source_path, _ = _write_source(tmp_path)
    _write_roster(tmp_path, "english10_p4")
    source = load_assignment_copy_source(
        tmp_path,
        "english10_p2",
        "unit_1_quiz",
    )
    plan = plan_assignment_copy(
        tmp_path,
        source,
        target_class_ids=("english10_p4",),
        target_assignment_id="unit_1_quiz",
    )

    changed = _assignment()
    changed["title"] = "Changed After Preview"
    source_path.write_text(json.dumps(changed), encoding="utf-8")

    with pytest.raises(AssignmentCopyConflictError, match="changed after the copy preview"):
        commit_assignment_copy(tmp_path, plan)

    assert not plan.targets[0].work_root.exists()


def test_commit_rejects_stale_target_before_any_target_write(tmp_path: Path) -> None:
    from scoreform.assignment_copying import commit_assignment_copy

    _write_source(tmp_path)
    _write_roster(tmp_path, "english10_p4")
    _write_roster(tmp_path, "english10_p6")
    source = load_assignment_copy_source(
        tmp_path,
        "english10_p2",
        "unit_1_quiz",
    )
    plan = plan_assignment_copy(
        tmp_path,
        source,
        target_class_ids=("english10_p4", "english10_p6"),
        target_assignment_id="unit_1_quiz",
    )

    plan.targets[1].work_root.mkdir(parents=True)
    marker = plan.targets[1].work_root / "keep.txt"
    marker.write_text("appeared after preview", encoding="utf-8")

    with pytest.raises(AssignmentCopyConflictError, match="work root already exists"):
        commit_assignment_copy(tmp_path, plan)

    assert not plan.targets[0].work_root.exists()
    assert marker.read_text(encoding="utf-8") == "appeared after preview"


def test_commit_rejects_roster_change_after_preview(tmp_path: Path) -> None:
    from scoreform.assignment_copying import commit_assignment_copy

    _write_source(tmp_path)
    roster_path = _write_roster(tmp_path, "english10_p4", periods=("4", "4"))
    source = load_assignment_copy_source(
        tmp_path,
        "english10_p2",
        "unit_1_quiz",
    )
    plan = plan_assignment_copy(
        tmp_path,
        source,
        target_class_ids=("english10_p4",),
        target_assignment_id="unit_1_quiz",
    )

    roster_path.write_text(
        "\n".join(
            [
                "class_id,student_id,last_name,first_name,period",
                "english10_p4,student_1,Student1,Synthetic,4",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(AssignmentCopyConflictError, match="context changed after preview"):
        commit_assignment_copy(tmp_path, plan)

    assert not plan.targets[0].work_root.exists()


def test_commit_rejects_candidate_mutation_after_preview(tmp_path: Path) -> None:
    from scoreform.assignment_copying import commit_assignment_copy

    _write_source(tmp_path)
    _write_roster(tmp_path, "english10_p4")
    source = load_assignment_copy_source(
        tmp_path,
        "english10_p2",
        "unit_1_quiz",
    )
    plan = plan_assignment_copy(
        tmp_path,
        source,
        target_class_ids=("english10_p4",),
        target_assignment_id="unit_1_quiz",
    )

    plan.candidate["title"] = "Mutated After Preview"

    with pytest.raises(AssignmentCopyConflictError, match="candidate changed after preview"):
        commit_assignment_copy(tmp_path, plan)

    assert not plan.targets[0].work_root.exists()


def test_runtime_partial_success_keeps_success_and_stops_future_targets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scoreform.assignment_copying as assignment_copying
    from scoreform.assignment_copying import AssignmentCopyWriteError

    _write_source(tmp_path)
    for class_id, period in (
        ("english10_p4", "4"),
        ("english10_p6", "6"),
        ("english10_p7", "7"),
    ):
        _write_roster(tmp_path, class_id, periods=(period, period))

    source = load_assignment_copy_source(
        tmp_path,
        "english10_p2",
        "unit_1_quiz",
    )
    plan = plan_assignment_copy(
        tmp_path,
        source,
        target_class_ids=("english10_p4", "english10_p6", "english10_p7"),
        target_assignment_id="unit_1_quiz",
    )

    real_persist = assignment_copying._persist_assignment_copy_target
    calls = 0

    def fail_second(workspace_root, target, candidate):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise AssignmentCopyWriteError("synthetic injected write failure")
        return real_persist(workspace_root, target, candidate)

    monkeypatch.setattr(
        assignment_copying,
        "_persist_assignment_copy_target",
        fail_second,
    )

    result = assignment_copying.commit_assignment_copy(tmp_path, plan)

    assert result.complete is False
    assert [item.work.class_id for item in result.created] == ["english10_p4"]
    assert len(result.failures) == 1
    assert result.failures[0].target.work.class_id == "english10_p6"
    assert "synthetic injected write failure" in result.failures[0].message
    assert [item.work.class_id for item in result.not_attempted] == ["english10_p7"]

    first = scoreform_work_paths(tmp_path, "english10_p4", "unit_1_quiz")
    second = scoreform_work_paths(tmp_path, "english10_p6", "unit_1_quiz")
    third = scoreform_work_paths(tmp_path, "english10_p7", "unit_1_quiz")
    assert first.assignment_path.is_file()
    assert not second.work_root.exists()
    assert not third.work_root.exists()


def test_persistence_race_does_not_overwrite_appearing_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scoreform.assignment_copying as assignment_copying

    _write_source(tmp_path)
    _write_roster(tmp_path, "english10_p4")
    source = load_assignment_copy_source(
        tmp_path,
        "english10_p2",
        "unit_1_quiz",
    )
    plan = plan_assignment_copy(
        tmp_path,
        source,
        target_class_ids=("english10_p4",),
        target_assignment_id="unit_1_quiz",
    )

    real_ensure = assignment_copying._ensure_target_parent_directories

    def create_racing_target(workspace_root, target):
        created = real_ensure(workspace_root, target)
        target.work_root.mkdir()
        marker = target.work_root / "external.txt"
        marker.write_text("external", encoding="utf-8")
        return created

    monkeypatch.setattr(
        assignment_copying,
        "_ensure_target_parent_directories",
        create_racing_target,
    )

    result = assignment_copying.commit_assignment_copy(tmp_path, plan)

    assert result.complete is False
    assert result.created == ()
    assert len(result.failures) == 1
    marker = plan.targets[0].work_root / "external.txt"
    assert marker.read_text(encoding="utf-8") == "external"
    assert not plan.targets[0].assignment_path.exists()

def test_source_rejects_symlinked_ancestor_in_canonical_path_chain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_source(tmp_path)
    paths = scoreform_work_paths(tmp_path, "english10_p2", "unit_1_quiz")
    linked_ancestor = paths.work_root.parent

    original_is_symlink = Path.is_symlink

    def report_one_link(path: Path) -> bool:
        if path == linked_ancestor:
            return True
        return original_is_symlink(path)

    monkeypatch.setattr(Path, "is_symlink", report_one_link)

    with pytest.raises(
        AssignmentCopyValidationError,
        match="Source path chain contains a symbolic link",
    ):
        load_assignment_copy_source(
            tmp_path,
            "english10_p2",
            "unit_1_quiz",
        )

