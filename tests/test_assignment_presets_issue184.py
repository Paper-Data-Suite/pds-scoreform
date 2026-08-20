from __future__ import annotations

import json
from pathlib import Path

import pytest
from pds_core.routes import class_roster_path
from pds_core.standards import StandardDefinition, StandardsLibrary, StandardsProfile

from scoreform.assignment_presets import (
    PRESET_COLLECTION_RELATIVE,
    AssignmentPresetConflictError,
    AssignmentPresetNotFoundError,
    AssignmentPresetValidationError,
    assignment_preset_collection_dir,
    assignment_preset_from_json_bytes,
    assignment_preset_path,
    build_assignment_from_preset,
    build_assignment_preset,
    build_assignment_preset_from_source,
    commit_assignment_preset_application,
    commit_assignment_preset_from_assignment,
    commit_assignment_preset_mutation,
    discover_assignment_presets,
    load_assignment_preset,
    plan_assignment_preset_application,
    plan_create_assignment_preset,
    plan_create_assignment_preset_from_assignment,
    plan_delete_assignment_preset,
    plan_update_assignment_preset,
    validate_assignment_preset_data,
)


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


def _preset(
    preset_id: str = "short_quiz",
    *,
    with_standards: bool = False,
) -> dict[str, object]:
    preset: dict[str, object] = {
        "schema_version": 1,
        "module": "scoreform",
        "record_type": "assignment_setup_preset",
        "preset_id": preset_id,
        "label": "Short Quiz",
        "question_count": 3,
        "choices": ["A", "B", "C", "D"],
        "layout_id": "standard_15q_abcd_v1",
        "answer_key": {"1": "A", "2": "B", "3": "C"},
        "standards": {"1": [], "2": [], "3": []},
    }
    if with_standards:
        preset["standards_profile_id"] = "english10_2023_njsls"
        preset["standards"] = {
            "1": ["nj_ela_2023_rl_cr_9_10_1"],
            "2": [],
            "3": [],
        }
    return preset


def _persist_raw(root: Path, preset: dict[str, object]) -> Path:
    path = assignment_preset_path(root, str(preset["preset_id"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(preset, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def test_canonical_preset_path_is_workspace_level_and_class_independent(
    tmp_path: Path,
) -> None:
    collection = assignment_preset_collection_dir(tmp_path)
    path = assignment_preset_path(tmp_path, "short_quiz")

    assert collection == tmp_path / PRESET_COLLECTION_RELATIVE
    assert path == collection / "short_quiz.json"
    assert "classes" not in path.parts


def test_build_preset_normalizes_independent_setup_data() -> None:
    answer_key = {"1": "a", "2": "b", "3": "c"}
    standards = {"1": [], "2": [], "3": []}

    preset = build_assignment_preset(
        preset_id="short_quiz",
        label="  Short Quiz  ",
        question_count=3,
        choices=["A", "B", "C", "D"],
        layout_id="standard_15q_abcd_v1",
        answer_key=answer_key,
        standards=standards,
    )

    assert preset["label"] == "Short Quiz"
    assert preset["answer_key"] == {"1": "A", "2": "B", "3": "C"}
    answer_key["1"] = "D"
    standards["1"].append("later_change")
    assert preset["answer_key"] == {"1": "A", "2": "B", "3": "C"}
    assert preset["standards"] == {"1": [], "2": [], "3": []}


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("schema_version", 2, "schema_version"),
        ("module", "other", "module"),
        ("record_type", "assignment", "record_type"),
        ("preset_id", "../unsafe", "preset_id"),
        ("label", "   ", "label"),
    ],
)
def test_preset_contract_rejects_invalid_identity_fields(
    field: str,
    value: object,
    match: str,
) -> None:
    data = _preset()
    data[field] = value

    with pytest.raises(AssignmentPresetValidationError, match=match):
        validate_assignment_preset_data(data)


def test_preset_contract_rejects_unknown_top_level_fields() -> None:
    data = _preset()
    data["student_id"] = "must_not_be_stored"

    with pytest.raises(
        AssignmentPresetValidationError,
        match="unknown top-level field",
    ):
        validate_assignment_preset_data(data)


def test_strict_bytes_reject_duplicate_object_key() -> None:
    data = b'''{
  "schema_version": 1,
  "module": "scoreform",
  "record_type": "assignment_setup_preset",
  "preset_id": "short_quiz",
  "label": "Short Quiz",
  "question_count": 1,
  "choices": ["A", "B", "C", "D"],
  "layout_id": "standard_15q_abcd_v1",
  "answer_key": {"1": "A", "1": "B"},
  "standards": {"1": []}
}
'''

    with pytest.raises(AssignmentPresetValidationError, match="duplicate object key"):
        assignment_preset_from_json_bytes(data)


def test_strict_bytes_reject_nonfinite_constant() -> None:
    data = json.dumps(_preset()).replace(
        '"question_count": 3',
        '"question_count": NaN',
    ).encode()

    with pytest.raises(AssignmentPresetValidationError, match="nonfinite"):
        assignment_preset_from_json_bytes(data)


def test_standards_preset_requires_current_library_when_mutating() -> None:
    with pytest.raises(
        AssignmentPresetValidationError,
        match="standards library",
    ):
        build_assignment_preset(
            preset_id="aligned_quiz",
            label="Aligned Quiz",
            question_count=3,
            choices=["A", "B", "C", "D"],
            layout_id="standard_15q_abcd_v1",
            answer_key={"1": "A", "2": "B", "3": "C"},
            standards={
                "1": ["nj_ela_2023_rl_cr_9_10_1"],
                "2": [],
                "3": [],
            },
            standards_profile_id="english10_2023_njsls",
        )


def test_standards_preset_validates_against_current_core_library() -> None:
    preset = build_assignment_preset(
        preset_id="aligned_quiz",
        label="Aligned Quiz",
        question_count=3,
        choices=["A", "B", "C", "D"],
        layout_id="standard_15q_abcd_v1",
        answer_key={"1": "A", "2": "B", "3": "C"},
        standards={
            "1": ["nj_ela_2023_rl_cr_9_10_1"],
            "2": [],
            "3": [],
        },
        standards_profile_id="english10_2023_njsls",
        standards_library=_standards_library(),
    )

    assert preset["standards_profile_id"] == "english10_2023_njsls"


def test_create_plan_is_non_mutating(tmp_path: Path) -> None:
    plan = plan_create_assignment_preset(tmp_path, _preset())

    assert plan.operation == "create"
    assert plan.path == assignment_preset_path(tmp_path, "short_quiz")
    assert not assignment_preset_collection_dir(tmp_path).exists()


def test_commit_create_persists_exact_canonical_preset(tmp_path: Path) -> None:
    plan = plan_create_assignment_preset(tmp_path, _preset())
    snapshot = commit_assignment_preset_mutation(tmp_path, plan)

    assert snapshot is not None
    assert snapshot.preset_id == "short_quiz"
    assert snapshot.path == assignment_preset_path(tmp_path, "short_quiz")
    assert snapshot.preset == validate_assignment_preset_data(_preset())
    assert load_assignment_preset(tmp_path, "short_quiz").preset == snapshot.preset


def test_create_collision_never_overwrites_existing_preset(tmp_path: Path) -> None:
    existing = _persist_raw(tmp_path, _preset())
    before = existing.read_bytes()

    with pytest.raises(AssignmentPresetConflictError, match="already exists"):
        plan_create_assignment_preset(tmp_path, _preset())

    assert existing.read_bytes() == before


def test_create_commit_detects_destination_appearing_after_preview(
    tmp_path: Path,
) -> None:
    plan = plan_create_assignment_preset(tmp_path, _preset())
    path = _persist_raw(tmp_path, _preset())
    before = path.read_bytes()

    with pytest.raises(AssignmentPresetConflictError, match="appeared after preview"):
        commit_assignment_preset_mutation(tmp_path, plan)

    assert path.read_bytes() == before


def test_update_is_guarded_by_exact_reviewed_snapshot(tmp_path: Path) -> None:
    _persist_raw(tmp_path, _preset())
    replacement = _preset()
    replacement["label"] = "Updated Short Quiz"
    plan = plan_update_assignment_preset(
        tmp_path,
        "short_quiz",
        replacement,
    )

    changed = _preset()
    changed["label"] = "Concurrent Change"
    _persist_raw(tmp_path, changed)

    with pytest.raises(AssignmentPresetConflictError, match="changed after preview"):
        commit_assignment_preset_mutation(tmp_path, plan)

    current = load_assignment_preset(tmp_path, "short_quiz")
    assert current.preset["label"] == "Concurrent Change"


def test_update_replaces_only_selected_preset(tmp_path: Path) -> None:
    _persist_raw(tmp_path, _preset())
    sibling = _preset("other_quiz")
    sibling["label"] = "Other Quiz"
    sibling_path = _persist_raw(tmp_path, sibling)
    sibling_before = sibling_path.read_bytes()

    replacement = _preset()
    replacement["label"] = "Updated Short Quiz"
    plan = plan_update_assignment_preset(
        tmp_path,
        "short_quiz",
        replacement,
    )
    snapshot = commit_assignment_preset_mutation(tmp_path, plan)

    assert snapshot is not None
    assert snapshot.preset["label"] == "Updated Short Quiz"
    assert sibling_path.read_bytes() == sibling_before


def test_update_cannot_change_preset_identity(tmp_path: Path) -> None:
    _persist_raw(tmp_path, _preset())
    replacement = _preset("different_id")

    with pytest.raises(AssignmentPresetValidationError, match="must match"):
        plan_update_assignment_preset(
            tmp_path,
            "short_quiz",
            replacement,
        )


def test_delete_plan_is_guarded_by_exact_reviewed_snapshot(tmp_path: Path) -> None:
    _persist_raw(tmp_path, _preset())
    plan = plan_delete_assignment_preset(tmp_path, "short_quiz")

    changed = _preset()
    changed["label"] = "Concurrent Change"
    path = _persist_raw(tmp_path, changed)

    with pytest.raises(AssignmentPresetConflictError, match="changed after preview"):
        commit_assignment_preset_mutation(tmp_path, plan)

    assert path.is_file()


def test_delete_removes_only_exact_selected_preset(tmp_path: Path) -> None:
    selected = _persist_raw(tmp_path, _preset())
    sibling = _preset("other_quiz")
    sibling["label"] = "Other Quiz"
    sibling_path = _persist_raw(tmp_path, sibling)
    sibling_before = sibling_path.read_bytes()

    plan = plan_delete_assignment_preset(tmp_path, "short_quiz")
    result = commit_assignment_preset_mutation(tmp_path, plan)

    assert result is None
    assert not selected.exists()
    assert sibling_path.read_bytes() == sibling_before


def test_discovery_keeps_valid_siblings_when_one_entry_is_corrupt(
    tmp_path: Path,
) -> None:
    _persist_raw(tmp_path, _preset())
    corrupt = assignment_preset_collection_dir(tmp_path) / "broken.json"
    corrupt.write_text("{not json", encoding="utf-8")

    discovery = discover_assignment_presets(tmp_path)

    assert [item.preset_id for item in discovery.presets] == ["short_quiz"]
    assert len(discovery.issues) == 1
    assert discovery.issues[0].path == corrupt


def test_discovery_is_deterministic_by_canonical_filename(tmp_path: Path) -> None:
    for preset_id in ("z_quiz", "a_quiz", "m_quiz"):
        preset = _preset(preset_id)
        preset["label"] = preset_id
        _persist_raw(tmp_path, preset)

    discovery = discover_assignment_presets(tmp_path)

    assert [item.preset_id for item in discovery.presets] == [
        "a_quiz",
        "m_quiz",
        "z_quiz",
    ]


def test_collection_symlink_state_is_rejected_without_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collection = assignment_preset_collection_dir(tmp_path)
    linked_ancestor = collection.parent
    linked_ancestor.mkdir(parents=True)

    original_is_symlink = Path.is_symlink

    def report_one_link(path: Path) -> bool:
        if path == linked_ancestor:
            return True
        return original_is_symlink(path)

    monkeypatch.setattr(Path, "is_symlink", report_one_link)

    with pytest.raises(
        AssignmentPresetValidationError,
        match="symbolic link",
    ):
        plan_create_assignment_preset(tmp_path, _preset())

    assert not collection.exists()


def test_preset_filename_identity_must_match_record_identity(tmp_path: Path) -> None:
    path = assignment_preset_path(tmp_path, "short_quiz")
    path.parent.mkdir(parents=True)
    wrong = _preset("other_quiz")
    path.write_text(json.dumps(wrong), encoding="utf-8")

    with pytest.raises(AssignmentPresetValidationError, match="canonical filename"):
        load_assignment_preset(tmp_path, "short_quiz")

def _source_assignment(
    assignment_id: str = "source_quiz",
    *,
    with_standards: bool = False,
) -> dict[str, object]:
    assignment: dict[str, object] = {
        "assignment_id": assignment_id,
        "title": "Source Quiz",
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


def _write_source_assignment(
    root: Path,
    *,
    class_id: str = "english10_p2",
    assignment_id: str = "source_quiz",
    with_standards: bool = False,
) -> tuple[Path, Path]:
    from scoreform.work_paths import scoreform_work_paths

    paths = scoreform_work_paths(root, class_id, assignment_id)
    paths.work_root.mkdir(parents=True)
    assignment = _source_assignment(
        assignment_id,
        with_standards=with_standards,
    )
    paths.assignment_path.write_text(
        json.dumps(assignment, indent=2) + "\n",
        encoding="utf-8",
    )
    return paths.work_root, paths.assignment_path


def test_assignment_source_projection_uses_only_preset_allowlist(
    tmp_path: Path,
) -> None:
    _write_source_assignment(tmp_path)
    plan = plan_create_assignment_preset_from_assignment(
        tmp_path,
        source_class_id="english10_p2",
        source_assignment_id="source_quiz",
        preset_id="short_quiz",
    )

    preset = plan.mutation.candidate
    assert preset is not None
    assert preset == {
        "schema_version": 1,
        "module": "scoreform",
        "record_type": "assignment_setup_preset",
        "preset_id": "short_quiz",
        "label": "Source Quiz",
        "question_count": 3,
        "choices": ["A", "B", "C", "D"],
        "layout_id": "standard_15q_abcd_v1",
        "answer_key": {"1": "A", "2": "B", "3": "C"},
        "standards": {"1": [], "2": [], "3": []},
    }
    assert "assignment_id" not in preset
    assert "class_id" not in preset
    assert "title" not in preset


def test_assignment_source_projection_accepts_independent_label(
    tmp_path: Path,
) -> None:
    _write_source_assignment(tmp_path)
    plan = plan_create_assignment_preset_from_assignment(
        tmp_path,
        source_class_id="english10_p2",
        source_assignment_id="source_quiz",
        preset_id="exit_ticket",
        label="Reusable Exit Ticket",
    )

    assert plan.mutation.candidate is not None
    assert plan.mutation.candidate["label"] == "Reusable Exit Ticket"
    assert plan.source.definition.title == "Source Quiz"


def test_assignment_to_preset_plan_does_not_create_storage_or_read_descendants(
    tmp_path: Path,
) -> None:
    work_root, _assignment_path = _write_source_assignment(tmp_path)
    (work_root / "results.csv").write_text("not,a,valid,result\n", encoding="utf-8")
    nested = work_root / "scans" / "private_history"
    nested.mkdir(parents=True)
    (nested / "opaque.bin").write_bytes(b"\x00\xffsource-history")

    plan = plan_create_assignment_preset_from_assignment(
        tmp_path,
        source_class_id="english10_p2",
        source_assignment_id="source_quiz",
        preset_id="short_quiz",
    )

    assert plan.mutation.operation == "create"
    assert not assignment_preset_collection_dir(tmp_path).exists()


def test_assignment_to_preset_commit_preserves_source_and_creates_only_preset(
    tmp_path: Path,
) -> None:
    work_root, assignment_path = _write_source_assignment(tmp_path)
    source_before = assignment_path.read_bytes()
    operational = work_root / "results.csv"
    operational.write_bytes(b"student_id,score\nsynthetic,1\n")
    operational_before = operational.read_bytes()

    plan = plan_create_assignment_preset_from_assignment(
        tmp_path,
        source_class_id="english10_p2",
        source_assignment_id="source_quiz",
        preset_id="short_quiz",
    )
    snapshot = commit_assignment_preset_from_assignment(tmp_path, plan)

    assert snapshot.preset_id == "short_quiz"
    assert assignment_path.read_bytes() == source_before
    assert operational.read_bytes() == operational_before
    assert list(assignment_preset_collection_dir(tmp_path).iterdir()) == [
        assignment_preset_path(tmp_path, "short_quiz")
    ]


def test_assignment_to_preset_commit_rejects_source_bytes_changed_after_preview(
    tmp_path: Path,
) -> None:
    _work_root, assignment_path = _write_source_assignment(tmp_path)
    plan = plan_create_assignment_preset_from_assignment(
        tmp_path,
        source_class_id="english10_p2",
        source_assignment_id="source_quiz",
        preset_id="short_quiz",
    )

    changed = _source_assignment()
    changed["title"] = "Changed After Preview"
    assignment_path.write_text(
        json.dumps(changed, indent=2) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(AssignmentPresetConflictError, match="changed after preview"):
        commit_assignment_preset_from_assignment(tmp_path, plan)

    assert not assignment_preset_collection_dir(tmp_path).exists()


def test_assignment_to_preset_commit_rejects_source_removed_after_preview(
    tmp_path: Path,
) -> None:
    _work_root, assignment_path = _write_source_assignment(tmp_path)
    plan = plan_create_assignment_preset_from_assignment(
        tmp_path,
        source_class_id="english10_p2",
        source_assignment_id="source_quiz",
        preset_id="short_quiz",
    )
    assignment_path.unlink()

    with pytest.raises(
        AssignmentPresetConflictError,
        match="changed or became unsafe",
    ):
        commit_assignment_preset_from_assignment(tmp_path, plan)

    assert not assignment_preset_collection_dir(tmp_path).exists()


@pytest.mark.parametrize("link_target", ["ancestor", "assignment"])
def test_assignment_to_preset_commit_rejects_post_preview_link_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    link_target: str,
) -> None:
    work_root, assignment_path = _write_source_assignment(tmp_path)
    plan = plan_create_assignment_preset_from_assignment(
        tmp_path,
        source_class_id="english10_p2",
        source_assignment_id="source_quiz",
        preset_id="short_quiz",
    )

    linked_path = work_root.parent if link_target == "ancestor" else assignment_path
    original_is_symlink = Path.is_symlink

    def report_new_link(path: Path) -> bool:
        if path == linked_path:
            return True
        return original_is_symlink(path)

    monkeypatch.setattr(Path, "is_symlink", report_new_link)

    with pytest.raises(
        AssignmentPresetConflictError,
        match="changed or became unsafe",
    ):
        commit_assignment_preset_from_assignment(tmp_path, plan)

    assert not assignment_preset_collection_dir(tmp_path).exists()


def test_assignment_to_preset_revalidates_current_standards_at_commit(
    tmp_path: Path,
) -> None:
    _write_source_assignment(tmp_path, with_standards=True)
    library = _standards_library()
    plan = plan_create_assignment_preset_from_assignment(
        tmp_path,
        source_class_id="english10_p2",
        source_assignment_id="source_quiz",
        preset_id="aligned_quiz",
        standards_library=library,
    )

    empty_library = StandardsLibrary(standards=(), profiles=())
    with pytest.raises(
        AssignmentPresetConflictError,
        match="changed or became unsafe",
    ):
        commit_assignment_preset_from_assignment(
            tmp_path,
            plan,
            standards_library=empty_library,
        )

    assert not assignment_preset_collection_dir(tmp_path).exists()


def test_build_assignment_preset_from_source_copies_nested_values_independently(
    tmp_path: Path,
) -> None:
    _write_source_assignment(tmp_path)
    plan = plan_create_assignment_preset_from_assignment(
        tmp_path,
        source_class_id="english10_p2",
        source_assignment_id="source_quiz",
        preset_id="short_quiz",
    )
    preset = build_assignment_preset_from_source(
        plan.source,
        preset_id="second_preset",
    )

    preset_key = preset["answer_key"]
    preset_standards = preset["standards"]
    assert isinstance(preset_key, dict)
    assert isinstance(preset_standards, dict)
    preset_key["1"] = "D"
    preset_standards["1"] = ["changed"]

    assert dict(plan.source.definition.answer_key)[1] == "A"
    assert dict(plan.source.definition.standards)[1] == ()

def _write_target_roster(
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


def test_build_assignment_from_preset_is_normal_assignment_and_independent() -> None:
    preset = _preset()
    candidate = build_assignment_from_preset(
        preset,
        target_assignment_id="unit_2_quiz",
        title="Unit 2 Quiz",
    )

    assert candidate["assignment_id"] == "unit_2_quiz"
    assert candidate["title"] == "Unit 2 Quiz"
    assert candidate["question_count"] == 3
    assert candidate["answer_key"] == {1: "A", 2: "B", 3: "C"}
    assert candidate["standards"] == {"1": [], "2": [], "3": []}

    candidate_key = candidate["answer_key"]
    assert isinstance(candidate_key, dict)
    candidate_key[1] = "D"
    assert preset["answer_key"] == {"1": "A", "2": "B", "3": "C"}


def test_preset_application_plan_is_non_mutating_and_privacy_minimal(
    tmp_path: Path,
) -> None:
    _persist_raw(tmp_path, _preset())
    roster_path = _write_target_roster(
        tmp_path,
        "english10_p4",
        periods=("4", "4"),
    )
    roster_before = roster_path.read_bytes()

    plan = plan_assignment_preset_application(
        tmp_path,
        preset_id="short_quiz",
        target_class_ids=["english10_p4"],
        target_assignment_id="unit_2_quiz",
        title="Unit 2 Quiz",
    )

    assert plan.preset.preset_id == "short_quiz"
    assert plan.candidate["assignment_id"] == "unit_2_quiz"
    assert len(plan.targets) == 1
    target = plan.targets[0]
    assert target.work.class_id == "english10_p4"
    assert target.work.work_id == "unit_2_quiz"
    assert target.roster.student_count == 2
    assert target.roster.periods == ("4",)
    assert not target.work_root.exists()
    assert roster_path.read_bytes() == roster_before


def test_preset_application_preserves_target_selection_order(
    tmp_path: Path,
) -> None:
    _persist_raw(tmp_path, _preset())
    for class_id in ("english10_p6", "english10_p2", "english10_p4"):
        _write_target_roster(tmp_path, class_id)

    plan = plan_assignment_preset_application(
        tmp_path,
        preset_id="short_quiz",
        target_class_ids=["english10_p6", "english10_p2", "english10_p4"],
        target_assignment_id="common_quiz",
        title="Common Quiz",
    )

    assert [target.work.class_id for target in plan.targets] == [
        "english10_p6",
        "english10_p2",
        "english10_p4",
    ]
    assert {target.work.work_id for target in plan.targets} == {"common_quiz"}


def test_preset_application_rejects_duplicate_target_class_before_writes(
    tmp_path: Path,
) -> None:
    _persist_raw(tmp_path, _preset())
    _write_target_roster(tmp_path, "english10_p4")

    with pytest.raises(
        AssignmentPresetValidationError,
        match="selected more than once",
    ):
        plan_assignment_preset_application(
            tmp_path,
            preset_id="short_quiz",
            target_class_ids=["english10_p4", "english10_p4"],
            target_assignment_id="unit_2_quiz",
            title="Unit 2 Quiz",
        )


def test_preset_application_requires_current_valid_target_roster(
    tmp_path: Path,
) -> None:
    _persist_raw(tmp_path, _preset())

    with pytest.raises(
        AssignmentPresetNotFoundError,
        match="valid Core roster",
    ):
        plan_assignment_preset_application(
            tmp_path,
            preset_id="short_quiz",
            target_class_ids=["missing_class"],
            target_assignment_id="unit_2_quiz",
            title="Unit 2 Quiz",
        )


def test_preset_application_rejects_existing_target_work_root(
    tmp_path: Path,
) -> None:
    _persist_raw(tmp_path, _preset())
    _write_target_roster(tmp_path, "english10_p4")

    from scoreform.work_paths import scoreform_work_paths

    paths = scoreform_work_paths(tmp_path, "english10_p4", "unit_2_quiz")
    paths.work_root.mkdir(parents=True)

    with pytest.raises(
        AssignmentPresetConflictError,
        match="work root already exists",
    ):
        plan_assignment_preset_application(
            tmp_path,
            preset_id="short_quiz",
            target_class_ids=["english10_p4"],
            target_assignment_id="unit_2_quiz",
            title="Unit 2 Quiz",
        )


def test_preset_application_rejects_stale_standards_before_target_mutation(
    tmp_path: Path,
) -> None:
    _persist_raw(tmp_path, _preset(with_standards=True))
    _write_target_roster(tmp_path, "english10_p4")
    empty_library = StandardsLibrary(standards=(), profiles=())

    with pytest.raises(
        AssignmentPresetValidationError,
        match="not currently valid",
    ):
        plan_assignment_preset_application(
            tmp_path,
            preset_id="short_quiz",
            target_class_ids=["english10_p4"],
            target_assignment_id="unit_2_quiz",
            title="Unit 2 Quiz",
            standards_library=empty_library,
        )


def test_preset_application_requires_explicit_valid_assignment_title(
    tmp_path: Path,
) -> None:
    _persist_raw(tmp_path, _preset())
    _write_target_roster(tmp_path, "english10_p4")

    with pytest.raises(
        AssignmentPresetValidationError,
        match="title",
    ):
        plan_assignment_preset_application(
            tmp_path,
            preset_id="short_quiz",
            target_class_ids=["english10_p4"],
            target_assignment_id="unit_2_quiz",
            title="   ",
        )


def test_preset_application_candidate_mutation_does_not_mutate_snapshot(
    tmp_path: Path,
) -> None:
    _persist_raw(tmp_path, _preset())
    _write_target_roster(tmp_path, "english10_p4")

    plan = plan_assignment_preset_application(
        tmp_path,
        preset_id="short_quiz",
        target_class_ids=["english10_p4"],
        target_assignment_id="unit_2_quiz",
        title="Unit 2 Quiz",
    )

    candidate_key = plan.candidate["answer_key"]
    assert isinstance(candidate_key, dict)
    candidate_key[1] = "D"

    assert plan.preset.preset["answer_key"] == {
        "1": "A",
        "2": "B",
        "3": "C",
    }

def test_preset_application_commit_creates_fresh_verified_assignment_only(
    tmp_path: Path,
) -> None:
    _persist_raw(tmp_path, _preset())
    roster_path = _write_target_roster(tmp_path, "english10_p4")
    roster_before = roster_path.read_bytes()

    plan = plan_assignment_preset_application(
        tmp_path,
        preset_id="short_quiz",
        target_class_ids=["english10_p4"],
        target_assignment_id="unit_2_quiz",
        title="Unit 2 Quiz",
    )
    result = commit_assignment_preset_application(tmp_path, plan)

    assert result.complete is True
    assert len(result.created) == 1
    target = plan.targets[0]
    assert result.created[0].work == target.work
    assert result.created[0].assignment_path == target.assignment_path
    assert target.assignment_path.is_file()
    assert roster_path.read_bytes() == roster_before
    assert sorted(
        path.relative_to(target.work_root).as_posix()
        for path in target.work_root.rglob("*")
    ) == [
        "assignment.json",
        "debug",
        "scans",
        "templates",
        "templates/individual",
    ]


def test_preset_application_commit_rejects_preset_change_before_any_write(
    tmp_path: Path,
) -> None:
    preset_path = _persist_raw(tmp_path, _preset())
    _write_target_roster(tmp_path, "english10_p4")
    plan = plan_assignment_preset_application(
        tmp_path,
        preset_id="short_quiz",
        target_class_ids=["english10_p4"],
        target_assignment_id="unit_2_quiz",
        title="Unit 2 Quiz",
    )

    changed = _preset()
    changed["label"] = "Changed After Preview"
    preset_path.write_text(json.dumps(changed), encoding="utf-8")

    with pytest.raises(AssignmentPresetConflictError, match="changed after preview"):
        commit_assignment_preset_application(tmp_path, plan)

    assert not plan.targets[0].work_root.exists()


def test_preset_application_commit_rejects_preset_link_change_before_any_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preset_path = _persist_raw(tmp_path, _preset())
    _write_target_roster(tmp_path, "english10_p4")
    plan = plan_assignment_preset_application(
        tmp_path,
        preset_id="short_quiz",
        target_class_ids=["english10_p4"],
        target_assignment_id="unit_2_quiz",
        title="Unit 2 Quiz",
    )

    original_is_symlink = Path.is_symlink

    def report_new_link(path: Path) -> bool:
        if path == preset_path:
            return True
        return original_is_symlink(path)

    monkeypatch.setattr(Path, "is_symlink", report_new_link)

    with pytest.raises(
        AssignmentPresetConflictError,
        match="changed or became unsafe",
    ):
        commit_assignment_preset_application(tmp_path, plan)

    assert not plan.targets[0].work_root.exists()


def test_preset_application_commit_rejects_candidate_change_after_preview(
    tmp_path: Path,
) -> None:
    _persist_raw(tmp_path, _preset())
    _write_target_roster(tmp_path, "english10_p4")
    plan = plan_assignment_preset_application(
        tmp_path,
        preset_id="short_quiz",
        target_class_ids=["english10_p4"],
        target_assignment_id="unit_2_quiz",
        title="Unit 2 Quiz",
    )

    plan.candidate["title"] = "Mutated Without Replan"

    with pytest.raises(
        AssignmentPresetConflictError,
        match="changed after preview",
    ):
        commit_assignment_preset_application(tmp_path, plan)

    assert not plan.targets[0].work_root.exists()


def test_preset_application_commit_rejects_roster_change_before_any_write(
    tmp_path: Path,
) -> None:
    _persist_raw(tmp_path, _preset())
    _write_target_roster(tmp_path, "english10_p4", periods=("4", "4"))
    plan = plan_assignment_preset_application(
        tmp_path,
        preset_id="short_quiz",
        target_class_ids=["english10_p4"],
        target_assignment_id="unit_2_quiz",
        title="Unit 2 Quiz",
    )

    _write_target_roster(tmp_path, "english10_p4", periods=("5", "5"))

    with pytest.raises(
        AssignmentPresetConflictError,
        match="context changed after preview",
    ):
        commit_assignment_preset_application(tmp_path, plan)

    assert not plan.targets[0].work_root.exists()


def test_preset_application_commit_preflights_all_targets_before_first_write(
    tmp_path: Path,
) -> None:
    _persist_raw(tmp_path, _preset())
    for class_id in ("english10_p2", "english10_p4"):
        _write_target_roster(tmp_path, class_id)

    plan = plan_assignment_preset_application(
        tmp_path,
        preset_id="short_quiz",
        target_class_ids=["english10_p2", "english10_p4"],
        target_assignment_id="common_quiz",
        title="Common Quiz",
    )
    plan.targets[1].work_root.mkdir(parents=True)

    with pytest.raises(
        AssignmentPresetConflictError,
        match="work root already exists",
    ):
        commit_assignment_preset_application(tmp_path, plan)

    assert not plan.targets[0].work_root.exists()


def test_preset_application_runtime_failure_reports_partial_success_truthfully(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scoreform.assignment_presets as preset_module

    _persist_raw(tmp_path, _preset())
    for class_id in ("english10_p2", "english10_p4", "english10_p6"):
        _write_target_roster(tmp_path, class_id)

    plan = plan_assignment_preset_application(
        tmp_path,
        preset_id="short_quiz",
        target_class_ids=["english10_p2", "english10_p4", "english10_p6"],
        target_assignment_id="common_quiz",
        title="Common Quiz",
    )

    original_persist = preset_module._persist_preset_application_target

    def fail_second(
        workspace_root: str | Path,
        target: object,
        candidate: dict[str, object],
    ) -> object:
        if target == plan.targets[1]:
            raise preset_module.AssignmentPresetApplicationWriteError(
                "synthetic second-target failure"
            )
        return original_persist(workspace_root, target, candidate)

    monkeypatch.setattr(
        preset_module,
        "_persist_preset_application_target",
        fail_second,
    )

    result = commit_assignment_preset_application(tmp_path, plan)

    assert result.complete is False
    assert [item.work for item in result.created] == [plan.targets[0].work]
    assert len(result.failures) == 1
    assert result.failures[0].target == plan.targets[1]
    assert "synthetic second-target failure" in result.failures[0].message
    assert result.not_attempted == (plan.targets[2],)
    assert plan.targets[0].assignment_path.is_file()
    assert not plan.targets[2].work_root.exists()


def test_preset_deletion_after_application_does_not_change_created_assignment(
    tmp_path: Path,
) -> None:
    _persist_raw(tmp_path, _preset())
    _write_target_roster(tmp_path, "english10_p4")
    plan = plan_assignment_preset_application(
        tmp_path,
        preset_id="short_quiz",
        target_class_ids=["english10_p4"],
        target_assignment_id="unit_2_quiz",
        title="Unit 2 Quiz",
    )
    result = commit_assignment_preset_application(tmp_path, plan)
    assignment_path = result.created[0].assignment_path
    assignment_before = assignment_path.read_bytes()

    delete_plan = plan_delete_assignment_preset(tmp_path, "short_quiz")
    commit_assignment_preset_mutation(tmp_path, delete_plan)

    assert not assignment_preset_path(tmp_path, "short_quiz").exists()
    assert assignment_path.read_bytes() == assignment_before


def test_preset_application_revalidates_current_standards_at_commit(
    tmp_path: Path,
) -> None:
    _persist_raw(tmp_path, _preset(with_standards=True))
    _write_target_roster(tmp_path, "english10_p4")
    library = _standards_library()
    plan = plan_assignment_preset_application(
        tmp_path,
        preset_id="short_quiz",
        target_class_ids=["english10_p4"],
        target_assignment_id="aligned_quiz",
        title="Aligned Quiz",
        standards_library=library,
    )

    empty_library = StandardsLibrary(standards=(), profiles=())
    with pytest.raises(
        AssignmentPresetConflictError,
        match="changed or became unsafe",
    ):
        commit_assignment_preset_application(
            tmp_path,
            plan,
            standards_library=empty_library,
        )

    assert not plan.targets[0].work_root.exists()
