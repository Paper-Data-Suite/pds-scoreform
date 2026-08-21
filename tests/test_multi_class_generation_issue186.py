from __future__ import annotations

import json
from pathlib import Path

import pytest

from scoreform import multi_class_generation as multi
from scoreform.answer_sheet_generation import (
    AnswerSheetArtifactResult,
    AnswerSheetGenerationResult,
)
from scoreform.answer_sheet_persistence import load_answer_sheet_issuance
from scoreform.multi_class_generation import (
    GenerationTargetRef,
    MultiClassGenerationGlobalExecutionError,
    MultiClassGenerationPlanNotReadyError,
    MultiClassGenerationStalePlanError,
    MultiClassGenerationValidationError,
    execute_multi_class_generation,
    plan_multi_class_generation,
    revalidate_multi_class_generation_plan,
)
from scoreform.work_paths import scoreform_work_paths


@pytest.fixture(autouse=True)
def _skip_dependency_import_preflight(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(multi, "preflight_generation_dependencies", lambda: None)


def _assignment(
    assignment_id: str,
    *,
    title: str = "Unit Quiz",
    question_count: int = 3,
    layout_id: str = "standard_15q_abcd_v1",
) -> dict[str, object]:
    answers = ["A", "B", "C", "D"]
    return {
        "assignment_id": assignment_id,
        "title": title,
        "question_count": question_count,
        "choices": ["A", "B", "C", "D"],
        "layout_id": layout_id,
        "answer_key": {
            str(question): answers[(question - 1) % len(answers)]
            for question in range(1, question_count + 1)
        },
        "standards": {
            str(question): [] for question in range(1, question_count + 1)
        },
    }


def _write_target(
    root: Path,
    class_id: str,
    assignment_id: str,
    *,
    student_count: int = 2,
    question_count: int = 3,
    layout_id: str = "standard_15q_abcd_v1",
    title: str = "Unit Quiz",
) -> None:
    paths = scoreform_work_paths(root, class_id, assignment_id)
    paths.roster_path.parent.mkdir(parents=True, exist_ok=True)
    roster_rows = [
        "class_id,student_id,last_name,first_name,period",
        *[
            f"{class_id},student_{index},Student{index},Synthetic,{index}"
            for index in range(1, student_count + 1)
        ],
    ]
    paths.roster_path.write_text("\n".join(roster_rows) + "\n", encoding="utf-8")
    paths.work_root.mkdir(parents=True, exist_ok=True)
    paths.assignment_path.write_text(
        json.dumps(
            _assignment(
                assignment_id,
                title=title,
                question_count=question_count,
                layout_id=layout_id,
            ),
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _tree_snapshot(root: Path) -> tuple[tuple[str, str, bytes | None], ...]:
    records: list[tuple[str, str, bytes | None]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(root).as_posix()
        if path.is_file():
            records.append((relative, "file", path.read_bytes()))
        elif path.is_dir():
            records.append((relative, "dir", None))
        else:
            records.append((relative, "other", None))
    return tuple(records)


def test_two_class_plan_is_complete_ordered_and_read_only(tmp_path: Path) -> None:
    _write_target(
        tmp_path,
        "english10_p2",
        "unit_2_quiz",
        student_count=2,
        question_count=16,
    )
    _write_target(
        tmp_path,
        "english10_p4",
        "unit_2_quiz",
        student_count=3,
        question_count=26,
        layout_id="compact_25q_abcd_v1",
    )
    before = _tree_snapshot(tmp_path)

    plan = plan_multi_class_generation(
        tmp_path,
        (
            GenerationTargetRef("english10_p4", "unit_2_quiz"),
            GenerationTargetRef("english10_p2", "unit_2_quiz"),
        ),
    )

    assert _tree_snapshot(tmp_path) == before
    assert plan.ready
    assert [target.target.class_id for target in plan.targets] == [
        "english10_p4",
        "english10_p2",
    ]

    p4, p2 = plan.targets
    assert p4.title == "Unit Quiz"
    assert p4.layout_id == "compact_25q_abcd_v1"
    assert p4.question_count == 26
    assert p4.student_count == 3
    assert p4.pages_per_student == 2
    assert p4.individual_pdf_count == 3
    assert p4.individual_physical_page_count == 6
    assert p4.class_packet_pdf_count == 1
    assert p4.class_packet_physical_page_count == 6
    assert p4.total_pdf_artifact_count == 4
    assert p4.total_physical_page_count == 12
    assert p4.expected_route_count == 12
    assert p4.generation_state == "initial"
    assert p4.current_predecessor_count == 0

    assert p2.layout_id == "standard_15q_abcd_v1"
    assert p2.question_count == 16
    assert p2.student_count == 2
    assert p2.pages_per_student == 2
    assert p2.total_pdf_artifact_count == 3
    assert p2.total_physical_page_count == 8
    assert p2.expected_route_count == 8

    assert p4.work_paths is not None
    assert p4.work_paths.class_packet_path == (
        tmp_path
        / "classes"
        / "english10_p4"
        / "modules"
        / "scoreform"
        / "work"
        / "unit_2_quiz"
        / "templates"
        / "class_packet.pdf"
    )


def test_plan_does_not_require_cross_target_definition_equality(tmp_path: Path) -> None:
    _write_target(
        tmp_path,
        "english10_p2",
        "unit_2_quiz",
        student_count=1,
        question_count=3,
        title="Three Question Quiz",
    )
    _write_target(
        tmp_path,
        "english10_p4",
        "different_quiz",
        student_count=4,
        question_count=30,
        layout_id="compact_25q_abcd_v1",
        title="Different Quiz",
    )

    plan = plan_multi_class_generation(
        tmp_path,
        (
            GenerationTargetRef("english10_p2", "unit_2_quiz"),
            GenerationTargetRef("english10_p4", "different_quiz"),
        ),
    )

    assert plan.ready
    assert plan.targets[0].title == "Three Question Quiz"
    assert plan.targets[1].title == "Different Quiz"
    assert plan.targets[0].layout_id != plan.targets[1].layout_id


def test_duplicate_exact_target_is_rejected_before_inspection(tmp_path: Path) -> None:
    target = GenerationTargetRef("english10_p2", "unit_2_quiz")

    with pytest.raises(MultiClassGenerationValidationError, match="Duplicate"):
        plan_multi_class_generation(tmp_path, (target, target))


def test_empty_target_set_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(MultiClassGenerationValidationError, match="at least one"):
        plan_multi_class_generation(tmp_path, ())


def test_invalid_identity_becomes_bounded_target_diagnostic(tmp_path: Path) -> None:
    plan = plan_multi_class_generation(
        tmp_path,
        (GenerationTargetRef("bad/class", "unit_2_quiz"),),
    )

    assert not plan.ready
    assert plan.targets[0].diagnostics[0].code == "invalid_target_identity"


def test_multiple_independently_blocked_targets_are_all_reported(tmp_path: Path) -> None:
    _write_target(tmp_path, "english10_p4", "unit_2_quiz")
    paths = scoreform_work_paths(tmp_path, "english10_p4", "unit_2_quiz")
    paths.roster_path.write_text(
        "class_id,student_id,last_name,first_name,period\n",
        encoding="utf-8",
    )

    plan = plan_multi_class_generation(
        tmp_path,
        (
            GenerationTargetRef("english10_p2", "missing_quiz"),
            GenerationTargetRef("english10_p4", "unit_2_quiz"),
        ),
    )

    assert not plan.ready
    assert len(plan.blocked_targets) == 2
    assert any(
        diagnostic.code == "assignment_not_ready"
        for diagnostic in plan.targets[0].diagnostics
    )
    assert any(
        diagnostic.code == "roster_not_ready"
        for diagnostic in plan.targets[1].diagnostics
    )


def test_duplicate_assignment_json_keys_fail_closed(tmp_path: Path) -> None:
    _write_target(tmp_path, "english10_p2", "unit_2_quiz")
    paths = scoreform_work_paths(tmp_path, "english10_p2", "unit_2_quiz")
    paths.assignment_path.write_text(
        """{
  "assignment_id": "unit_2_quiz",
  "assignment_id": "other",
  "title": "Unit Quiz",
  "question_count": 1,
  "choices": ["A", "B", "C", "D"],
  "layout_id": "standard_15q_abcd_v1",
  "answer_key": {"1": "A"},
  "standards": {"1": []}
}
""",
        encoding="utf-8",
    )

    plan = plan_multi_class_generation(
        tmp_path,
        (GenerationTargetRef("english10_p2", "unit_2_quiz"),),
    )

    assert not plan.ready
    assignment_errors = [
        diagnostic.message
        for diagnostic in plan.targets[0].diagnostics
        if diagnostic.code == "assignment_not_ready"
    ]
    assert assignment_errors
    assert "duplicate object key" in assignment_errors[0]


def test_assignment_identity_must_match_canonical_work(tmp_path: Path) -> None:
    _write_target(tmp_path, "english10_p2", "unit_2_quiz")
    paths = scoreform_work_paths(tmp_path, "english10_p2", "unit_2_quiz")
    payload = _assignment("other_quiz")
    paths.assignment_path.write_text(
        json.dumps(payload) + "\n",
        encoding="utf-8",
    )

    plan = plan_multi_class_generation(
        tmp_path,
        (GenerationTargetRef("english10_p2", "unit_2_quiz"),),
    )

    assert not plan.ready
    assert any(
        "canonical work identity" in diagnostic.message
        for diagnostic in plan.targets[0].diagnostics
    )


def test_output_path_conflict_is_reported_without_mutation(tmp_path: Path) -> None:
    _write_target(tmp_path, "english10_p2", "unit_2_quiz")
    paths = scoreform_work_paths(tmp_path, "english10_p2", "unit_2_quiz")
    paths.templates_dir.write_text("not a directory\n", encoding="utf-8")
    before = _tree_snapshot(tmp_path)

    plan = plan_multi_class_generation(
        tmp_path,
        (GenerationTargetRef("english10_p2", "unit_2_quiz"),),
    )

    assert _tree_snapshot(tmp_path) == before
    assert not plan.ready
    assert any(
        diagnostic.code == "output_not_ready"
        for diagnostic in plan.targets[0].diagnostics
    )


def test_missing_template_directories_are_not_created_by_plan(tmp_path: Path) -> None:
    _write_target(tmp_path, "english10_p2", "unit_2_quiz")
    paths = scoreform_work_paths(tmp_path, "english10_p2", "unit_2_quiz")
    assert not paths.templates_dir.exists()

    plan = plan_multi_class_generation(
        tmp_path,
        (GenerationTargetRef("english10_p2", "unit_2_quiz"),),
    )

    assert plan.ready
    assert not paths.templates_dir.exists()
    assert not paths.individual_templates_dir.exists()
    assert not paths.answer_sheet_issuances_dir.exists()


def test_assignment_change_after_preview_is_detected(tmp_path: Path) -> None:
    _write_target(tmp_path, "english10_p2", "unit_2_quiz")
    plan = plan_multi_class_generation(
        tmp_path,
        (GenerationTargetRef("english10_p2", "unit_2_quiz"),),
    )
    paths = scoreform_work_paths(tmp_path, "english10_p2", "unit_2_quiz")
    payload = _assignment("unit_2_quiz", title="Changed After Preview")
    paths.assignment_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    freshness = revalidate_multi_class_generation_plan(plan)

    assert not freshness.fresh
    assert any(
        diagnostic.code == "assignment_changed"
        for diagnostic in freshness.diagnostics
    )


def test_roster_change_after_preview_is_detected(tmp_path: Path) -> None:
    _write_target(tmp_path, "english10_p2", "unit_2_quiz", student_count=1)
    plan = plan_multi_class_generation(
        tmp_path,
        (GenerationTargetRef("english10_p2", "unit_2_quiz"),),
    )
    paths = scoreform_work_paths(tmp_path, "english10_p2", "unit_2_quiz")
    paths.roster_path.write_text(
        "\n".join(
            (
                "class_id,student_id,last_name,first_name,period",
                "english10_p2,student_1,One,Synthetic,2",
                "english10_p2,student_2,Two,Synthetic,2",
            )
        )
        + "\n",
        encoding="utf-8",
    )

    freshness = revalidate_multi_class_generation_plan(plan)

    assert not freshness.fresh
    assert any(
        diagnostic.code == "roster_changed" for diagnostic in freshness.diagnostics
    )
    assert freshness.current_plan.targets[0].student_count == 2


def test_issuance_collection_change_after_preview_requires_replan(tmp_path: Path) -> None:
    _write_target(tmp_path, "english10_p2", "unit_2_quiz")
    plan = plan_multi_class_generation(
        tmp_path,
        (GenerationTargetRef("english10_p2", "unit_2_quiz"),),
    )
    assert plan.ready
    paths = scoreform_work_paths(tmp_path, "english10_p2", "unit_2_quiz")
    paths.answer_sheet_issuances_dir.mkdir(parents=True)
    (paths.answer_sheet_issuances_dir / "iss_invalid.json").write_text(
        "{}\n",
        encoding="utf-8",
    )

    freshness = revalidate_multi_class_generation_plan(plan)

    assert not freshness.fresh
    assert any(
        diagnostic.code == "issuance_state_changed"
        for diagnostic in freshness.diagnostics
    )
    assert any(
        diagnostic.code == "target_now_blocked"
        for diagnostic in freshness.diagnostics
    )


def test_revalidation_of_unchanged_ready_plan_is_fresh(tmp_path: Path) -> None:
    _write_target(tmp_path, "english10_p2", "unit_2_quiz")
    _write_target(tmp_path, "english10_p4", "unit_2_quiz")
    plan = plan_multi_class_generation(
        tmp_path,
        (
            GenerationTargetRef("english10_p2", "unit_2_quiz"),
            GenerationTargetRef("english10_p4", "unit_2_quiz"),
        ),
    )

    freshness = revalidate_multi_class_generation_plan(plan)

    assert freshness.fresh
    assert freshness.diagnostics == ()
    assert freshness.current_plan.ready



def _fake_generation_result(
    generation_id: str,
    *,
    success: bool = True,
    installed: bool | None = None,
    stage: str | None = None,
    error: str | None = None,
) -> AnswerSheetGenerationResult:
    if installed is None:
        installed = success
    artifact = AnswerSheetArtifactResult(
        generation_id=generation_id,
        artifact_id="art_" + "1" * 32,
        output_path="synthetic.pdf",
        output_kind="individual_pdf",
        success=success,
        student_count=1,
        issuance_count=1,
        physical_page_count=1,
        issuance_ids=("iss_" + "2" * 32,),
        page_ids=("pg_" + "3" * 32,),
        route_ids=("rt_" + "4" * 32,),
        planned_route_count=1,
        created_route_count=1 if installed else 0,
        verified_route_count=1 if installed else 0,
        installed=installed,
        replaced_previous_output=False,
        predecessor_count=0,
        superseded_predecessor_count=0,
        failure_stage=stage,
        error=error,
    )
    return AnswerSheetGenerationResult(generation_id, (artifact,))


def _three_target_plan(tmp_path: Path):
    for period in ("p2", "p4", "p6"):
        _write_target(tmp_path, f"english10_{period}", "unit_2_quiz", student_count=1)
    return plan_multi_class_generation(
        tmp_path,
        tuple(
            GenerationTargetRef(f"english10_{period}", "unit_2_quiz")
            for period in ("p2", "p4", "p6")
        ),
    )


def test_execute_refuses_blocked_plan_before_target_execution(tmp_path: Path) -> None:
    plan = plan_multi_class_generation(
        tmp_path,
        (GenerationTargetRef("english10_p2", "missing_quiz"),),
    )
    calls: list[str] = []

    def executor(root, target, generation_id):
        calls.append(target.target.class_id)
        return _fake_generation_result(generation_id)

    with pytest.raises(MultiClassGenerationPlanNotReadyError):
        execute_multi_class_generation(plan, target_executor=executor)

    assert calls == []


def test_execute_refuses_stale_complete_plan_before_first_target(tmp_path: Path) -> None:
    plan = _three_target_plan(tmp_path)
    paths = scoreform_work_paths(tmp_path, "english10_p4", "unit_2_quiz")
    paths.assignment_path.write_text(
        json.dumps(_assignment("unit_2_quiz", title="Changed")) + "\n",
        encoding="utf-8",
    )
    calls: list[str] = []

    def executor(root, target, generation_id):
        calls.append(target.target.class_id)
        return _fake_generation_result(generation_id)

    with pytest.raises(MultiClassGenerationStalePlanError) as caught:
        execute_multi_class_generation(plan, target_executor=executor)

    assert calls == []
    assert any(
        item.target.class_id == "english10_p4" and item.code == "assignment_changed"
        for item in caught.value.freshness.diagnostics
    )


def test_execute_preserves_reviewed_order_and_one_generation_context(tmp_path: Path) -> None:
    plan = _three_target_plan(tmp_path)
    calls: list[tuple[str, str]] = []

    def executor(root, target, generation_id):
        calls.append((target.target.class_id, generation_id))
        return _fake_generation_result(generation_id)

    result = execute_multi_class_generation(plan, target_executor=executor)

    assert result.success
    assert [class_id for class_id, _generation_id in calls] == [
        "english10_p2",
        "english10_p4",
        "english10_p6",
    ]
    assert {generation_id for _class_id, generation_id in calls} == {
        result.generation_id
    }
    assert [item.status for item in result.outcomes] == [
        "clean_success",
        "clean_success",
        "clean_success",
    ]
    assert result.clean_success_count == 3
    assert result.partial_success_count == 0
    assert result.failed_count == 0
    assert result.not_attempted_count == 0


def test_target_local_failed_result_does_not_block_later_independent_target(
    tmp_path: Path,
) -> None:
    plan = _three_target_plan(tmp_path)
    calls: list[str] = []

    def executor(root, target, generation_id):
        calls.append(target.target.class_id)
        if target.target.class_id == "english10_p4":
            return _fake_generation_result(
                generation_id,
                success=False,
                installed=False,
                stage="pdf_rendering",
                error="simulated target-local render failure",
            )
        return _fake_generation_result(generation_id)

    result = execute_multi_class_generation(plan, target_executor=executor)

    assert calls == ["english10_p2", "english10_p4", "english10_p6"]
    assert [item.status for item in result.outcomes] == [
        "clean_success",
        "failed",
        "clean_success",
    ]
    assert not result.success
    assert result.clean_success_count == 2
    assert result.failed_count == 1
    assert result.outcomes[1].failure_stage == "pdf_rendering"


def test_installed_failed_result_is_reported_as_partial_and_batch_continues(
    tmp_path: Path,
) -> None:
    plan = _three_target_plan(tmp_path)
    calls: list[str] = []

    def executor(root, target, generation_id):
        calls.append(target.target.class_id)
        if target.target.class_id == "english10_p4":
            return _fake_generation_result(
                generation_id,
                success=False,
                installed=True,
                stage="predecessor_supersession",
                error="simulated supersession failure",
            )
        return _fake_generation_result(generation_id)

    result = execute_multi_class_generation(plan, target_executor=executor)

    assert calls == ["english10_p2", "english10_p4", "english10_p6"]
    assert [item.status for item in result.outcomes] == [
        "clean_success",
        "partial",
        "clean_success",
    ]
    assert result.partial_success_count == 1
    assert result.outcomes[1].installed_artifact_count == 1
    assert result.outcomes[1].verified_route_count == 1


def test_target_that_becomes_stale_mid_batch_is_skipped_but_later_target_runs(
    tmp_path: Path,
) -> None:
    plan = _three_target_plan(tmp_path)
    calls: list[str] = []

    def executor(root, target, generation_id):
        calls.append(target.target.class_id)
        if target.target.class_id == "english10_p2":
            paths = scoreform_work_paths(root, "english10_p4", "unit_2_quiz")
            paths.assignment_path.write_text(
                json.dumps(_assignment("unit_2_quiz", title="Changed Mid Batch"))
                + "\n",
                encoding="utf-8",
            )
        return _fake_generation_result(generation_id)

    result = execute_multi_class_generation(plan, target_executor=executor)

    assert calls == ["english10_p2", "english10_p6"]
    assert [item.status for item in result.outcomes] == [
        "clean_success",
        "failed",
        "clean_success",
    ]
    assert result.outcomes[1].failure_stage == "stale_plan"
    assert "assignment.json changed" in (result.outcomes[1].error or "")


def test_global_execution_failure_stops_and_marks_remaining_not_attempted(
    tmp_path: Path,
) -> None:
    plan = _three_target_plan(tmp_path)
    calls: list[str] = []

    def executor(root, target, generation_id):
        calls.append(target.target.class_id)
        if target.target.class_id == "english10_p4":
            raise MultiClassGenerationGlobalExecutionError(
                "simulated shared infrastructure failure"
            )
        return _fake_generation_result(generation_id)

    result = execute_multi_class_generation(plan, target_executor=executor)

    assert calls == ["english10_p2", "english10_p4"]
    assert [item.status for item in result.outcomes] == [
        "clean_success",
        "failed",
        "not_attempted",
    ]
    assert result.outcomes[1].failure_stage == "global_execution"
    assert result.outcomes[2].failure_stage == "batch_aborted"
    assert result.not_attempted_count == 1
    assert not result.success


def test_real_executor_generates_two_targets_with_distinct_physical_identities(
    tmp_path: Path,
) -> None:
    _write_target(tmp_path, "english10_p2", "unit_2_quiz", student_count=1)
    _write_target(tmp_path, "english10_p4", "unit_2_quiz", student_count=1)
    refs = (
        GenerationTargetRef("english10_p2", "unit_2_quiz"),
        GenerationTargetRef("english10_p4", "unit_2_quiz"),
    )
    plan = plan_multi_class_generation(tmp_path, refs)
    assignment_bytes = {
        ref.class_id: scoreform_work_paths(
            tmp_path, ref.class_id, ref.assignment_id
        ).assignment_path.read_bytes()
        for ref in refs
    }
    roster_bytes = {
        ref.class_id: scoreform_work_paths(
            tmp_path, ref.class_id, ref.assignment_id
        ).roster_path.read_bytes()
        for ref in refs
    }

    result = execute_multi_class_generation(plan)

    assert result.success
    all_artifact_ids: set[str] = set()
    all_issuance_ids: set[str] = set()
    all_page_ids: set[str] = set()
    all_route_ids: set[str] = set()
    for ref in refs:
        paths = scoreform_work_paths(tmp_path, ref.class_id, ref.assignment_id)
        assert paths.class_packet_path.is_file()
        assert paths.class_packet_path.stat().st_size > 0
        assert len(tuple(paths.individual_templates_dir.glob("*.pdf"))) == 1
        issuance_ids = {path.stem for path in paths.answer_sheet_issuances_dir.glob("*.json")}
        page_ids = {path.stem for path in paths.answer_sheet_pages_dir.glob("*.json")}
        route_ids = {path.stem for path in (paths.work_root / "routes").glob("*.json")}
        artifact_ids = {
            load_answer_sheet_issuance(
                tmp_path, paths.work_ref, issuance_id
            ).artifact_id
            for issuance_id in issuance_ids
        }
        assert len(artifact_ids) == 2
        assert len(issuance_ids) == 2
        assert len(page_ids) == 2
        assert len(route_ids) == 2
        assert all_artifact_ids.isdisjoint(artifact_ids)
        assert all_issuance_ids.isdisjoint(issuance_ids)
        assert all_page_ids.isdisjoint(page_ids)
        assert all_route_ids.isdisjoint(route_ids)
        all_artifact_ids.update(artifact_ids)
        all_issuance_ids.update(issuance_ids)
        all_page_ids.update(page_ids)
        all_route_ids.update(route_ids)
        assert paths.assignment_path.read_bytes() == assignment_bytes[ref.class_id]
        assert paths.roster_path.read_bytes() == roster_bytes[ref.class_id]

    assert len(all_artifact_ids) == 4
    assert len(all_issuance_ids) == 4
    assert len(all_page_ids) == 4
    assert len(all_route_ids) == 4
    assert result.installed_artifact_count == 4
    assert result.verified_route_count == 4
