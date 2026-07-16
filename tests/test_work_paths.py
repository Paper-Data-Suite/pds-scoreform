from __future__ import annotations

import json
from pathlib import Path

import pytest
from pds_core.routes import module_work_dir
from pds_core.routing_models import ModuleWorkRef

from scoreform.folders import setup_assignment_folder
from scoreform.work_paths import (
    initialize_managed_work_layout,
    scoreform_work_paths,
    scoreform_work_ref,
)
from scoreform.workflows import discover_class_assignments


def _assignment(assignment_id="quiz", title="Quiz"):
    return {
        "assignment_id": assignment_id,
        "title": title,
        "question_count": 1,
        "choices": ["A", "B", "C", "D"],
        "layout_id": "standard_15q_abcd_v1",
        "answer_key": {"1": "A"},
        "standards": {"1": []},
    }


def _roster(class_id="class1", first_name="Jane"):
    return {
        "class_id": class_id,
        "students": [
            {
                "student_id": "1001",
                "last_name": "Doe",
                "first_name": first_name,
                "period": "1",
            }
        ],
    }


def test_paths_are_module_qualified_pure_and_isolated(tmp_path):
    paths = scoreform_work_paths(tmp_path, "class1", "quiz")

    assert paths.work_ref == ModuleWorkRef("scoreform", "class1", "quiz")
    assert scoreform_work_ref("class1", "quiz").work_id == "quiz"
    assert paths.work_root == (
        tmp_path / "classes" / "class1" / "modules" / "scoreform" / "work" / "quiz"
    )
    assert paths.roster_path == tmp_path / "classes" / "class1" / "roster.csv"
    assert paths.assignment_path == paths.work_root / "assignment.json"
    assert paths.individual_templates_dir == paths.work_root / "templates" / "individual"
    assert paths.class_packet_path == paths.work_root / "templates" / "class_packet.pdf"
    assert paths.results_path == paths.work_root / "results.csv"
    for descendant in (
        paths.assignment_path,
        paths.templates_dir,
        paths.individual_templates_dir,
        paths.class_packet_path,
        paths.scans_dir,
        paths.results_path,
        paths.debug_dir,
    ):
        assert descendant.is_relative_to(paths.work_root)
    assert list(tmp_path.iterdir()) == []

    other = module_work_dir(tmp_path, ModuleWorkRef("quillan", "class1", "quiz"))
    assert other != paths.work_root


@pytest.mark.parametrize("class_id,assignment_id", [("../class", "quiz"), ("class1", "../quiz")])
def test_unsafe_identity_fails_without_mutation(tmp_path, class_id, assignment_id):
    with pytest.raises(ValueError):
        scoreform_work_paths(tmp_path, class_id, assignment_id)
    assert list(tmp_path.iterdir()) == []


def test_layout_initializer_is_idempotent_and_does_not_create_artifacts(tmp_path):
    paths = scoreform_work_paths(tmp_path, "class1", "quiz")
    assert initialize_managed_work_layout(paths) is paths
    assert initialize_managed_work_layout(paths) is paths

    assert paths.templates_dir.is_dir()
    assert paths.individual_templates_dir.is_dir()
    assert paths.scans_dir.is_dir()
    assert paths.debug_dir.is_dir()
    assert not paths.results_path.exists()
    assert not paths.class_packet_path.exists()
    assert not (paths.work_root / "routes").exists()


def test_layout_wrong_type_preflight_does_not_replace_or_partially_create(tmp_path):
    paths = scoreform_work_paths(tmp_path, "class1", "quiz")
    paths.work_root.mkdir(parents=True)
    paths.templates_dir.write_text("keep", encoding="utf-8")

    with pytest.raises(FileExistsError):
        initialize_managed_work_layout(paths)

    assert paths.templates_dir.read_text(encoding="utf-8") == "keep"
    assert not paths.scans_dir.exists()
    assert not paths.debug_dir.exists()


def test_setup_reuses_equivalent_records_and_rejects_collisions(tmp_path):
    paths = scoreform_work_paths(tmp_path, "class1", "quiz")
    sibling = module_work_dir(tmp_path, ModuleWorkRef("quillan", "class1", "quiz"))
    sibling.mkdir(parents=True)
    marker = sibling / "keep.txt"
    marker.write_text("other module", encoding="utf-8")

    first = setup_assignment_folder(
        _roster(),
        _assignment(),
        workspace_root=tmp_path,
    )
    assert first is not None
    assert first["work_ref"] == paths.work_ref
    original_roster = paths.roster_path.read_text(encoding="utf-8")
    original_assignment = paths.assignment_path.read_text(encoding="utf-8")

    assert setup_assignment_folder(
        _roster(), _assignment(), workspace_root=tmp_path
    ) is not None
    assert setup_assignment_folder(
        _roster(first_name="Janet"), _assignment(), workspace_root=tmp_path
    ) is None
    assert setup_assignment_folder(
        _roster(), _assignment(title="Changed"), workspace_root=tmp_path
    ) is None

    assert paths.roster_path.read_text(encoding="utf-8") == original_roster
    assert paths.assignment_path.read_text(encoding="utf-8") == original_assignment
    assert marker.read_text(encoding="utf-8") == "other module"

    new_work = scoreform_work_paths(tmp_path, "class1", "new_quiz")
    assert setup_assignment_folder(
        _roster(first_name="Janet"),
        _assignment("new_quiz"),
        workspace_root=tmp_path,
    ) is None
    assert not new_work.work_root.exists()


def test_discovery_is_direct_scoreform_only_and_ignores_unqualified_roots(tmp_path, capsys):
    setup_assignment_folder(_roster(), _assignment("z_quiz"), workspace_root=tmp_path)
    setup_assignment_folder(_roster(), _assignment("a_quiz"), workspace_root=tmp_path)

    malformed = scoreform_work_paths(tmp_path, "class1", "bad")
    malformed.work_root.mkdir(parents=True)
    malformed.assignment_path.write_text("{bad json", encoding="utf-8")
    mismatch = scoreform_work_paths(tmp_path, "class1", "folder_id")
    mismatch.work_root.mkdir(parents=True)
    mismatch.assignment_path.write_text(json.dumps(_assignment("other_id")), encoding="utf-8")
    nested = scoreform_work_paths(tmp_path, "class1", "container")
    nested.work_root.mkdir(parents=True)
    nested_assignment = nested.work_root / "nested" / "assignment.json"
    nested_assignment.parent.mkdir()
    nested_assignment.write_text(json.dumps(_assignment("nested")), encoding="utf-8")

    unqualified = tmp_path / "classes" / "class1" / "assignments" / "old_quiz"
    unqualified.mkdir(parents=True)
    unqualified_assignment = unqualified / "assignment.json"
    original = json.dumps(_assignment("old_quiz")).encode()
    unqualified_assignment.write_bytes(original)
    sibling = module_work_dir(tmp_path, ModuleWorkRef("quillan", "class1", "same"))
    sibling.mkdir(parents=True)
    (sibling / "assignment.json").write_text(json.dumps(_assignment("same")), encoding="utf-8")

    discovered = discover_class_assignments("class1", workspace_root=tmp_path)

    assert [record["assignment_id"] for record in discovered] == ["a_quiz", "z_quiz"]
    assert all(record["work_ref"].module_id == "scoreform" for record in discovered)
    assert all(record["results_path"].endswith("results.csv") for record in discovered)
    assert unqualified_assignment.read_bytes() == original
    assert "mismatched assignment_id" in capsys.readouterr().out


def test_discovery_of_absent_collection_is_empty_and_nonmutating(tmp_path):
    assert discover_class_assignments("class1", workspace_root=tmp_path) == []
    assert list(tmp_path.iterdir()) == []


def test_active_python_does_not_reconstruct_unqualified_assignment_roots():
    package_dir = Path(__file__).parents[1] / "scoreform"
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in package_dir.glob("*.py")
    )

    assert '/ "assignments"' not in source
    assert "joinpath(\"assignments\"" not in source
    assert "classes/<class_id>/assignments/<assignment_id>" not in source
