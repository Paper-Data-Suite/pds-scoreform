from __future__ import annotations

import json
from pathlib import Path

import pytest
from pds_core.standards import StandardDefinition, StandardsLibrary, StandardsProfile

from scoreform import assignment_workflows
from scoreform.assignment_bulk_entry import BulkAnswerKey
from scoreform.assignment_bulk_ui import (
    print_complete_assignment_preview,
    prompt_answer_key_entry,
    prompt_standards_bulk_entry,
)
from scoreform.work_paths import scoreform_work_paths

STANDARD_ID = "nj_ela_2023_rl_cr_9_10_1"
PROFILE_ID = "english10_2023_njsls"


def _library() -> StandardsLibrary:
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


def _assignment(answer: str = "A") -> dict[str, object]:
    return {
        "assignment_id": "quiz",
        "title": "Quiz",
        "question_count": 1,
        "choices": ["A", "B", "C", "D"],
        "layout_id": "standard_15q_abcd_v1",
        "answer_key": {"1": answer},
        "standards": {"1": []},
    }


def test_per_question_entry_treats_b_as_answer_data(monkeypatch) -> None:
    responses = iter(["4", "B", "USE"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    result = prompt_answer_key_entry(
        question_count=1,
        choices=["A", "B", "C", "D"],
    )

    assert result == BulkAnswerKey(("B",))


def test_free_form_answer_entry_requires_back_word_to_cancel(monkeypatch) -> None:
    responses = iter(["1", "BACK"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    assert (
        prompt_answer_key_entry(
            question_count=1,
            choices=["A", "B", "C", "D"],
        )
        is None
    )


def test_bulk_alignment_previews_and_stages_full_coverage(monkeypatch, capsys) -> None:
    responses = iter(["1", "1", f"1 = {STANDARD_ID}; 2 = -", "USE"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    result = prompt_standards_bulk_entry(
        question_count=2,
        standards_library=_library(),
        forced_method="text",
    )

    assert result is not None
    assert result.standards_profile_id == PROFILE_ID
    assert result.by_question == ((STANDARD_ID,), ())
    output = capsys.readouterr().out
    assert "Q1:" in output
    assert "Q2: (unaligned)" in output


def test_complete_assignment_preview_never_truncates_questions(capsys) -> None:
    assignment = {
        "assignment_id": "long_quiz",
        "title": "Long Quiz",
        "question_count": 20,
        "choices": ["A", "B", "C", "D"],
        "layout_id": "standard_15q_abcd_v1",
        "answer_key": {str(i): "A" for i in range(1, 21)},
        "standards": {str(i): [] for i in range(1, 21)},
    }

    print_complete_assignment_preview(assignment, class_ids=("english10_p2",))

    output = capsys.readouterr().out
    assert "Q1: A" in output
    assert "Q20: A" in output
    assert "Q20: (unaligned)" in output


def test_creation_cancel_at_final_preview_writes_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    classes = [{"class_id": "english10_p2", "roster": {"students": []}}]
    monkeypatch.setattr(assignment_workflows, "discover_class_rosters", lambda: classes)
    monkeypatch.setattr(
        assignment_workflows.workspace,
        "get_scoreform_workspace_root",
        lambda: tmp_path,
    )
    monkeypatch.setattr(assignment_workflows, "clear_screen", lambda: None)
    monkeypatch.setattr(
        assignment_workflows,
        "prompt_answer_key_entry",
        lambda **_kwargs: BulkAnswerKey(("B",)),
    )
    monkeypatch.setattr(
        assignment_workflows,
        "_prompt_standards_alignment_choice",
        lambda _root, _count: (None, {"1": []}),
    )
    responses = iter(["1", "Quiz", "", "", "1", "BACK"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    assert assignment_workflows.prompt_create_assignment() == 0

    paths = scoreform_work_paths(tmp_path, "english10_p2", "quiz")
    assert not paths.work_root.exists()


def test_creation_accepts_b_as_title_and_saves_only_after_explicit_save(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    classes = [{"class_id": "english10_p2", "roster": {"students": []}}]
    monkeypatch.setattr(assignment_workflows, "discover_class_rosters", lambda: classes)
    monkeypatch.setattr(
        assignment_workflows.workspace,
        "get_scoreform_workspace_root",
        lambda: tmp_path,
    )
    monkeypatch.setattr(assignment_workflows, "clear_screen", lambda: None)
    monkeypatch.setattr(
        assignment_workflows,
        "prompt_answer_key_entry",
        lambda **_kwargs: BulkAnswerKey(("B",)),
    )
    monkeypatch.setattr(
        assignment_workflows,
        "_prompt_standards_alignment_choice",
        lambda _root, _count: (None, {"1": []}),
    )
    responses = iter(["1", "B", "", "", "1", "SAVE"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    assert assignment_workflows.prompt_create_assignment() == 0

    paths = scoreform_work_paths(tmp_path, "english10_p2", "b")
    persisted = json.loads(paths.assignment_path.read_text(encoding="utf-8"))
    assert persisted["title"] == "B"
    assert persisted["answer_key"] == {"1": "B"}


def test_existing_assignment_bulk_key_save_uses_guarded_atomic_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    paths = scoreform_work_paths(tmp_path, "english10_p2", "quiz")
    paths.work_root.mkdir(parents=True)
    paths.assignment_path.write_text(
        json.dumps(_assignment(), indent=2) + "\n",
        encoding="utf-8",
    )
    records = [
        {
            "assignment_id": "quiz",
            "assignment_path": paths.assignment_path,
            "assignment": _assignment(),
        }
    ]
    monkeypatch.setattr(
        assignment_workflows,
        "discover_class_rosters",
        lambda: [{"class_id": "english10_p2"}],
    )
    monkeypatch.setattr(
        assignment_workflows,
        "discover_class_assignments",
        lambda _class_id: records,
    )
    monkeypatch.setattr(
        assignment_workflows.workspace,
        "get_scoreform_workspace_root",
        lambda: tmp_path,
    )
    monkeypatch.setattr(assignment_workflows, "clear_screen", lambda: None)
    monkeypatch.setattr(
        assignment_workflows,
        "_load_optional_selection_library",
        lambda _root: None,
    )
    monkeypatch.setattr(
        assignment_workflows,
        "prompt_answer_key_entry",
        lambda **_kwargs: BulkAnswerKey(("B",)),
    )
    responses = iter(["1", "1", "2", "1", "5", "SAVE"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    assert assignment_workflows.prompt_edit_assignment() == 0

    persisted = json.loads(paths.assignment_path.read_text(encoding="utf-8"))
    assert persisted["answer_key"] == {"1": "B"}
    assert "Q1: B" in capsys.readouterr().out


def test_creation_overwrite_uses_guarded_replacement_and_preserves_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = scoreform_work_paths(tmp_path, "english10_p2", "quiz")
    paths.work_root.mkdir(parents=True)
    paths.assignment_path.write_text(
        json.dumps(_assignment("A"), indent=2) + "\n",
        encoding="utf-8",
    )
    paths.results_path.write_text("synthetic historical result\n", encoding="utf-8")
    classes = [{"class_id": "english10_p2", "roster": {"students": []}}]
    monkeypatch.setattr(assignment_workflows, "discover_class_rosters", lambda: classes)
    monkeypatch.setattr(
        assignment_workflows.workspace,
        "get_scoreform_workspace_root",
        lambda: tmp_path,
    )
    monkeypatch.setattr(assignment_workflows, "clear_screen", lambda: None)
    monkeypatch.setattr(
        assignment_workflows,
        "_load_optional_selection_library",
        lambda _root: None,
    )
    monkeypatch.setattr(
        assignment_workflows,
        "prompt_answer_key_entry",
        lambda **_kwargs: BulkAnswerKey(("B",)),
    )
    monkeypatch.setattr(
        assignment_workflows,
        "_prompt_standards_alignment_choice",
        lambda _root, _count: (None, {"1": []}),
    )
    responses = iter(["1", "Quiz", "", "", "1", "SAVE", "yes"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    assert assignment_workflows.prompt_create_assignment() == 0

    persisted = json.loads(paths.assignment_path.read_text(encoding="utf-8"))
    assert persisted["answer_key"] == {"1": "B"}
    assert paths.results_path.read_text(encoding="utf-8") == (
        "synthetic historical result\n"
    )
