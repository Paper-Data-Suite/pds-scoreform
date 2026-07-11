import json

import pytest
from pds_core.standards import (
    StandardDefinition,
    StandardsLibrary,
    StandardsProfile,
    load_workspace_standard_usage_events,
    load_workspace_standards_library,
    standards_library_to_dict,
    write_workspace_standards_library,
)
from pds_core.standards_selection import StandardSelectionItem

from scoreform import assignment, assignment_workflows, standards_workflows, workflows


def make_standard(
    standard_id="njsls-ela:RL.CR.11-12.1",
    code="RL.CR.11-12.1",
    source="NJSLS-ELA",
    short_name="Close Reading Evidence",
):
    return StandardDefinition(
        standard_id=standard_id,
        code=code,
        source=source,
        short_name=short_name,
        description="Cite textual evidence.",
        subject="English Language Arts",
        course="English 12",
        domain="Reading Literature",
        available_modules=("pds-scoreform",),
    )


def create_roster(tmp_path):
    workflows.write_roster_csv(
        str(tmp_path / "classes" / "test_class" / "roster.csv"),
        "test_class",
        "1",
        [{"student_id": "1001", "last_name": "Doe", "first_name": "Jane"}],
    )


def assignment_path(tmp_path, assignment_id="standards_assignment"):
    return (
        tmp_path
        / "classes"
        / "test_class"
        / "assignments"
        / assignment_id
        / "assignment.json"
    )


def test_initialize_empty_standards_alignment():
    assert standards_workflows.initialize_empty_standards_alignment(3) == {
        "1": [],
        "2": [],
        "3": [],
    }


@pytest.mark.parametrize("selection", ["", " ", "1,", "x", "1-2", "0", "4"])
def test_parse_question_selection_rejects_invalid_values(selection):
    with pytest.raises(ValueError):
        standards_workflows.parse_question_selection(selection, 3)


def test_parse_question_selection_accepts_commas_and_deduplicates():
    assert standards_workflows.parse_question_selection(" 2,1,2 ", 3) == (2, 1)


def _selection_item(standard_id):
    return StandardSelectionItem(
        standard_id=standard_id,
        label=standard_id,
        code=standard_id,
        short_name=standard_id,
        source="Test",
    )


def test_parse_standard_selection_supports_multiple_standards():
    available = (_selection_item("standard:a"), _selection_item("standard:b"))
    assert standards_workflows.parse_standard_selection("2,1", available) == (
        "standard:b",
        "standard:a",
    )


@pytest.mark.parametrize("selection", ["", "1,1", "0", "3", "x", "1,"])
def test_parse_standard_selection_rejects_invalid_values(selection):
    available = (_selection_item("standard:a"), _selection_item("standard:b"))
    with pytest.raises(ValueError):
        standards_workflows.parse_standard_selection(selection, available)


def test_attach_multiple_standards_to_multiple_questions():
    assert standards_workflows.attach_standards_to_questions(
        {"1": ["standard:a"]},
        standard_ids=("standard:a", "standard:b"),
        question_numbers=(1, 2),
        question_count=2,
    ) == {
        "1": ["standard:a", "standard:b"],
        "2": ["standard:a", "standard:b"],
    }


def test_attach_standard_to_questions_prevents_duplicates_and_allows_multiple():
    aligned = standards_workflows.attach_standard_to_questions(
        {"1": ["local:evidence"], "2": []},
        standard_id="local:evidence",
        question_numbers=(1, 2),
        question_count=3,
    )
    aligned = standards_workflows.attach_standard_to_questions(
        aligned,
        standard_id="njsls-ela:RL.CR.11-12.1",
        question_numbers=(1,),
        question_count=3,
    )

    assert aligned == {
        "1": ["local:evidence", "njsls-ela:RL.CR.11-12.1"],
        "2": ["local:evidence"],
        "3": [],
    }


def test_workflows_keeps_standards_helper_compatibility_exports():
    assert (
        workflows.initialize_empty_standards_alignment
        is standards_workflows.initialize_empty_standards_alignment
    )
    assert workflows.parse_question_selection is standards_workflows.parse_question_selection
    assert (
        workflows.attach_standard_to_questions
        is standards_workflows.attach_standard_to_questions
    )
    assert (
        workflows.format_standard_for_selection
        is standards_workflows.format_standard_for_selection
    )


def test_prompt_create_assignment_skip_standards_writes_empty_alignment_without_library_write(
    tmp_path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    create_roster(tmp_path)

    def fail_write(*_args, **_kwargs):
        raise AssertionError("standards library should not be written")

    responses = iter([
        "1",
        "Standards Assignment",
        "standards_assignment",
        "2",
        "A",
        "B",
        "1",
    ])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(responses))

    assert assignment_workflows.prompt_create_assignment() == 0

    saved = json.loads(assignment_path(tmp_path).read_text(encoding="utf-8"))
    assert saved["standards"] == {"1": [], "2": []}
    assert not (tmp_path / "standards").exists()


def test_prompt_create_assignment_attaches_existing_standards_without_modifying_library(
    tmp_path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    create_roster(tmp_path)
    library = StandardsLibrary(
        standards=(
            make_standard(
                "local-writing:evidence_explanation",
                "evidence_explanation",
                "Local Writing Rubric",
                "Evidence Explanation",
            ),
            make_standard(),
        ),
        profiles=(StandardsProfile(
            profile_id="english12_profile",
            standards=(
                "local-writing:evidence_explanation",
                "njsls-ela:RL.CR.11-12.1",
            ),
        ),),
    )
    write_workspace_standards_library(tmp_path, library)
    before = standards_library_to_dict(load_workspace_standards_library(tmp_path))

    responses = iter([
        "1",
        "Standards Assignment",
        "standards_assignment",
        "3",
        "A",
        "B",
        "C",
        "2",
        "1",
        "1",
        "1,2",
        "1,2",
        "4",
    ])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(responses))

    assert assignment_workflows.prompt_create_assignment() == 0

    saved = json.loads(assignment_path(tmp_path).read_text(encoding="utf-8"))
    assert saved["standards_profile_id"] == "english12_profile"
    assert saved["standards"] == {
        "1": [
            "local-writing:evidence_explanation",
            "njsls-ela:RL.CR.11-12.1",
        ],
        "2": [
            "local-writing:evidence_explanation",
            "njsls-ela:RL.CR.11-12.1",
        ],
        "3": [],
    }
    assert standards_library_to_dict(load_workspace_standards_library(tmp_path)) == before
    assert load_workspace_standard_usage_events(tmp_path, "2025-2026", "test_class") == ()

    loaded = assignment.load_assignment(str(assignment_path(tmp_path)))
    assert loaded["standards"]["1"] == [
        "local-writing:evidence_explanation",
        "njsls-ela:RL.CR.11-12.1",
    ]


def test_prompt_create_assignment_does_not_offer_shared_standard_authoring(
    tmp_path,
    monkeypatch,
    capsys,
):
    monkeypatch.chdir(tmp_path)
    create_roster(tmp_path)
    responses = iter([
        "1",
        "Standards Assignment",
        "standards_assignment",
        "2",
        "A",
        "B",
        "1",
    ])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(responses))

    assert assignment_workflows.prompt_create_assignment() == 0

    saved = json.loads(assignment_path(tmp_path).read_text(encoding="utf-8"))
    assert saved["standards"] == {"1": [], "2": []}
    output = capsys.readouterr().out
    assert "Enter a new shared standard" not in output
    assert "Select a PDS Core standards profile" in output
    assert not (tmp_path / "standards").exists()


def test_attach_existing_empty_library_returns_to_menu_and_can_skip(
    tmp_path,
    monkeypatch,
    capsys,
):
    monkeypatch.chdir(tmp_path)
    create_roster(tmp_path)
    responses = iter([
        "1",
        "Standards Assignment",
        "standards_assignment",
        "1",
        "A",
        "2",
        "1",
    ])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(responses))

    assert assignment_workflows.prompt_create_assignment() == 0

    output = capsys.readouterr().out
    assert "No PDS Core standards profiles found." in output
    saved = json.loads(assignment_path(tmp_path).read_text(encoding="utf-8"))
    assert saved["standards"] == {"1": []}
