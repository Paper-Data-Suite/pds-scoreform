import json

import pytest
from pds_core.standards import (
    StandardDefinition,
    StandardsLibrary,
    load_workspace_standard_usage_events,
    load_workspace_standards_library,
    standards_library_to_dict,
    write_workspace_standards_library,
)

from scoreform import assignment, workflows


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
    assert workflows.initialize_empty_standards_alignment(3) == {
        "1": [],
        "2": [],
        "3": [],
    }


@pytest.mark.parametrize("selection", ["", " ", "1,", "x", "1-2", "0", "4"])
def test_parse_question_selection_rejects_invalid_values(selection):
    with pytest.raises(ValueError):
        workflows.parse_question_selection(selection, 3)


def test_parse_question_selection_accepts_commas_and_deduplicates():
    assert workflows.parse_question_selection(" 2,1,2 ", 3) == (2, 1)


def test_attach_standard_to_questions_prevents_duplicates_and_allows_multiple():
    aligned = workflows.attach_standard_to_questions(
        {"1": ["local:evidence"], "2": []},
        standard_id="local:evidence",
        question_numbers=(1, 2),
        question_count=3,
    )
    aligned = workflows.attach_standard_to_questions(
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


def test_prompt_create_assignment_skip_standards_writes_empty_alignment_without_library_write(
    tmp_path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    create_roster(tmp_path)

    def fail_write(*_args, **_kwargs):
        raise AssertionError("standards library should not be written")

    monkeypatch.setattr(workflows, "write_workspace_standards_library", fail_write)
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

    assert workflows.prompt_create_assignment() == 0

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
        )
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
        "1,2",
        "2",
        "1",
        "",
    ])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(responses))

    assert workflows.prompt_create_assignment() == 0

    saved = json.loads(assignment_path(tmp_path).read_text(encoding="utf-8"))
    assert saved["standards"] == {
        "1": [
            "local-writing:evidence_explanation",
            "njsls-ela:RL.CR.11-12.1",
        ],
        "2": ["local-writing:evidence_explanation"],
        "3": [],
    }
    assert standards_library_to_dict(load_workspace_standards_library(tmp_path)) == before
    assert load_workspace_standard_usage_events(tmp_path, "2025-2026", "test_class") == ()

    loaded = assignment.load_assignment(str(assignment_path(tmp_path)))
    assert loaded["standards"]["1"] == [
        "local-writing:evidence_explanation",
        "njsls-ela:RL.CR.11-12.1",
    ]


def test_prompt_create_assignment_creates_shared_standard_then_attaches_id_only(
    tmp_path,
    monkeypatch,
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
        "3",
        "local-writing:evidence_explanation",
        "evidence_explanation",
        "Local Writing Rubric",
        "Evidence Explanation",
        "Explain how evidence supports a claim.",
        "English Language Arts",
        "English 12",
        "11-12",
        "Writing",
        "English Language Arts, Writing",
        "evidence, explanation",
        "",
        "1,2",
    ])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(responses))

    assert workflows.prompt_create_assignment() == 0

    saved = json.loads(assignment_path(tmp_path).read_text(encoding="utf-8"))
    assert saved["standards"] == {
        "1": ["local-writing:evidence_explanation"],
        "2": ["local-writing:evidence_explanation"],
    }

    library = load_workspace_standards_library(tmp_path)
    definition = library.standards[0]
    assert definition.standard_id == "local-writing:evidence_explanation"
    assert definition.active is True
    assert "pds-scoreform" in definition.available_modules
    assert saved["standards"]["1"] == [definition.standard_id]
    assert load_workspace_standard_usage_events(tmp_path, "2025-2026", "test_class") == ()


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

    assert workflows.prompt_create_assignment() == 0

    output = capsys.readouterr().out
    assert "No shared standards exist yet." in output
    saved = json.loads(assignment_path(tmp_path).read_text(encoding="utf-8"))
    assert saved["standards"] == {"1": []}
