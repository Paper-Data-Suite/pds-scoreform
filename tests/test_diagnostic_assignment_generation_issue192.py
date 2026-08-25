"""Issue #192 Slice 2d assignment/generation diagnostic contracts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pds_core.routes import class_roster_path

import scoreform.assignment_copying as copying
import scoreform.diagnostic_events as diagnostics
import scoreform.multi_class_generation as generation
from scoreform.answer_sheet_generation import (
    AnswerSheetArtifactResult,
    AnswerSheetGenerationResult,
)
from scoreform.multi_class_generation import GenerationTargetRef
from scoreform.work_paths import scoreform_work_paths


def _codes(root: Path) -> list[str]:
    return [
        event.code
        for event in diagnostics.list_diagnostic_events(
            root,
            limit=diagnostics.MAX_EVENT_LIST_LIMIT,
        ).events
    ]


def _assignment(assignment_id: str) -> dict[str, object]:
    return {
        "assignment_id": assignment_id,
        "title": "PRIVATE-ASSIGNMENT-TITLE",
        "question_count": 1,
        "choices": ["A", "B", "C", "D"],
        "layout_id": "standard_15q_abcd_v1",
        "answer_key": {"1": "A"},
        "standards": {"1": []},
    }


def _write_roster(root: Path, class_id: str) -> None:
    path = class_roster_path(root, class_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            (
                "class_id,student_id,last_name,first_name,period",
                f"{class_id},student_private_1001,Private,Student,2",
            )
        )
        + "\n",
        encoding="utf-8",
    )


def _write_assignment(root: Path, class_id: str, assignment_id: str) -> None:
    paths = scoreform_work_paths(root, class_id, assignment_id)
    paths.work_root.mkdir(parents=True, exist_ok=True)
    paths.assignment_path.write_text(
        json.dumps(_assignment(assignment_id)) + "\n",
        encoding="utf-8",
    )


def test_verified_assignment_copy_records_target_without_content(
    tmp_path: Path,
) -> None:
    _write_assignment(tmp_path, "source_class", "unit_quiz")
    _write_roster(tmp_path, "target_class")
    source = copying.load_assignment_copy_source(
        tmp_path, "source_class", "unit_quiz"
    )
    plan = copying.plan_assignment_copy(
        tmp_path,
        source,
        target_class_ids=("target_class",),
        target_assignment_id="unit_quiz_copy",
    )

    result = copying.commit_assignment_copy(tmp_path, plan)

    assert result.complete
    assert _codes(tmp_path).count("assignment_copy_verified") == 1
    event = next(
        item
        for item in diagnostics.list_diagnostic_events(tmp_path).events
        if item.code == "assignment_copy_verified"
    )
    assert (event.class_id, event.assignment_id) == (
        "target_class",
        "unit_quiz_copy",
    )
    raw = diagnostics.diagnostic_event_path(
        tmp_path, event.event_id
    ).read_text(encoding="utf-8")
    assert "student_private_1001" not in raw
    assert "PRIVATE-ASSIGNMENT-TITLE" not in raw
    assert '"answer_key"' not in raw


def test_stale_assignment_copy_conflict_is_preserved_and_bounded(
    tmp_path: Path,
) -> None:
    _write_assignment(tmp_path, "source_class", "unit_quiz")
    _write_roster(tmp_path, "target_class")
    source = copying.load_assignment_copy_source(
        tmp_path, "source_class", "unit_quiz"
    )
    plan = copying.plan_assignment_copy(
        tmp_path,
        source,
        target_class_ids=("target_class",),
        target_assignment_id="unit_quiz_copy",
    )
    source.assignment_path.write_text(
        json.dumps(
            {
                **_assignment("unit_quiz"),
                "title": "PRIVATE-CHANGED-AFTER-PREVIEW",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(copying.AssignmentCopyConflictError):
        copying.commit_assignment_copy(tmp_path, plan)

    event = diagnostics.list_diagnostic_events(tmp_path).events[0]
    assert event.code == "assignment_copy_conflict"
    assert event.outcome == "blocked"
    raw = diagnostics.diagnostic_event_path(
        tmp_path, event.event_id
    ).read_text(encoding="utf-8")
    assert "PRIVATE-CHANGED-AFTER-PREVIEW" not in raw


def test_assignment_copy_success_survives_diagnostic_storage_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_assignment(tmp_path, "source_class", "unit_quiz")
    _write_roster(tmp_path, "target_class")
    source = copying.load_assignment_copy_source(
        tmp_path, "source_class", "unit_quiz"
    )
    plan = copying.plan_assignment_copy(
        tmp_path,
        source,
        target_class_ids=("target_class",),
        target_assignment_id="unit_quiz_copy",
    )

    def fail_record(*_args: object, **_kwargs: object) -> object:
        raise diagnostics.DiagnosticEventStorageError("diagnostics unavailable")

    monkeypatch.setattr(diagnostics, "record_diagnostic_event", fail_record)
    result = copying.commit_assignment_copy(tmp_path, plan)

    assert result.complete
    assert plan.targets[0].assignment_path.is_file()


@pytest.fixture(autouse=True)
def _skip_generation_dependency_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        generation,
        "preflight_generation_dependencies",
        lambda: None,
    )


def _write_generation_target(
    root: Path,
    class_id: str,
    assignment_id: str = "unit_quiz",
) -> None:
    _write_roster(root, class_id)
    _write_assignment(root, class_id, assignment_id)


def _generation_result(
    generation_id: str,
    *,
    success: bool,
    installed: bool,
) -> AnswerSheetGenerationResult:
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
        failure_stage=None if success else "predecessor_supersession",
        error=None if success else "PRIVATE-STUDENT-SENTINEL",
    )
    return AnswerSheetGenerationResult(generation_id, (artifact,))


def test_generation_success_is_target_level_not_student_activity(
    tmp_path: Path,
) -> None:
    _write_generation_target(tmp_path, "english10_p2")
    plan = generation.plan_multi_class_generation(
        tmp_path,
        (GenerationTargetRef("english10_p2", "unit_quiz"),),
    )

    result = generation.execute_multi_class_generation(
        plan,
        target_executor=lambda _root, _target, generation_id: _generation_result(
            generation_id,
            success=True,
            installed=True,
        ),
    )

    assert result.success
    event = diagnostics.list_diagnostic_events(tmp_path).events[0]
    assert event.code == "generation_verified"
    assert (event.class_id, event.assignment_id) == (
        "english10_p2",
        "unit_quiz",
    )
    raw = diagnostics.diagnostic_event_path(
        tmp_path, event.event_id
    ).read_text(encoding="utf-8")
    assert "student_private_1001" not in raw
    assert "PRIVATE-ASSIGNMENT-TITLE" not in raw


def test_generation_partial_success_is_bounded(
    tmp_path: Path,
) -> None:
    _write_generation_target(tmp_path, "english10_p2")
    plan = generation.plan_multi_class_generation(
        tmp_path,
        (GenerationTargetRef("english10_p2", "unit_quiz"),),
    )

    result = generation.execute_multi_class_generation(
        plan,
        target_executor=lambda _root, _target, generation_id: _generation_result(
            generation_id,
            success=False,
            installed=True,
        ),
    )

    assert result.partial_success_count == 1
    event = diagnostics.list_diagnostic_events(tmp_path).events[0]
    assert event.code == "generation_partial_success"
    assert event.outcome == "partial_success"
    raw = diagnostics.diagnostic_event_path(
        tmp_path, event.event_id
    ).read_text(encoding="utf-8")
    assert "PRIVATE-STUDENT-SENTINEL" not in raw


def test_blocked_generation_attempt_records_preflight_without_mutation(
    tmp_path: Path,
) -> None:
    plan = generation.plan_multi_class_generation(
        tmp_path,
        (GenerationTargetRef("english10_p2", "missing_quiz"),),
    )
    calls: list[str] = []

    with pytest.raises(generation.MultiClassGenerationPlanNotReadyError):
        generation.execute_multi_class_generation(
            plan,
            target_executor=lambda _root, target, _generation_id: calls.append(
                target.target.class_id
            ),
        )

    assert calls == []
    event = diagnostics.list_diagnostic_events(tmp_path).events[0]
    assert event.code == "generation_preflight_failed"
    assert event.outcome == "blocked"


def test_generation_success_survives_diagnostic_storage_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_generation_target(tmp_path, "english10_p2")
    plan = generation.plan_multi_class_generation(
        tmp_path,
        (GenerationTargetRef("english10_p2", "unit_quiz"),),
    )

    def fail_record(*_args: object, **_kwargs: object) -> object:
        raise diagnostics.DiagnosticEventStorageError("diagnostics unavailable")

    monkeypatch.setattr(diagnostics, "record_diagnostic_event", fail_record)
    result = generation.execute_multi_class_generation(
        plan,
        target_executor=lambda _root, _target, generation_id: _generation_result(
            generation_id,
            success=True,
            installed=True,
        ),
    )

    assert result.success
