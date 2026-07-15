from dataclasses import replace
from pathlib import Path

import pytest

import scoreform.answer_sheet_generation as generation
import scoreform.answer_sheet_routes as routes_module
import scoreform.generate_workflows as generate_workflows
from scoreform.answer_sheet_generation import (
    AnswerSheetGenerationResult,
    AnswerSheetPredecessorError,
    execute_answer_sheet_artifact,
    plan_answer_sheet_artifact,
)
from scoreform.answer_sheet_persistence import (
    load_answer_sheet_issuance,
    transition_answer_sheet_issuance,
    write_answer_sheet_record_set,
)
from scoreform.answer_sheet_records import build_answer_sheet_record_set
from scoreform.answer_sheet_routes import AnswerSheetRoutePersistenceError
from scoreform.folders import setup_assignment_folder
from scoreform.templates import student_pdf_filename


def _assignment(question_count=10):
    return {
        "assignment_id": "quiz1",
        "title": "Quiz One",
        "question_count": question_count,
        "choices": ["A", "B", "C", "D"],
        "layout_id": "standard_15q_abcd_v1",
        "answer_key": {str(index): "A" for index in range(1, question_count + 1)},
        "standards": {str(index): [] for index in range(1, question_count + 1)},
    }


def _student(student_id="1001", last_name="Doe"):
    return {
        "class_id": "class1",
        "student_id": student_id,
        "last_name": last_name,
        "first_name": "Jane",
        "period": "2",
    }


def _managed(tmp_path, *, students=None):
    selected = students or [_student()]
    assignment = _assignment()
    roster = {"class_id": "class1", "students": selected}
    setup = setup_assignment_folder(roster, assignment, workspace_root=tmp_path)
    assert setup is not None
    return setup["paths"], assignment, roster


def _plan(tmp_path, paths, assignment, students, output, *, generation_digit="1"):
    return plan_answer_sheet_artifact(
        tmp_path,
        paths.work_ref,
        assignment,
        students,
        output,
        output_kind=("individual_pdf" if len(students) == 1 else "class_packet_pdf"),
        generation_id=f"gen_{generation_digit * 32}",
    )


def _fail_cleanup(monkeypatch, temporary_path):
    original = Path.unlink

    def unlink(path, *args, **kwargs):
        if path == temporary_path:
            raise OSError("simulated cleanup failure")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", unlink)


def _assert_cleanup_warning(result, primary):
    assert primary in result.error
    assert any(
        "Temporary artifact cleanup failed" in warning
        and "simulated cleanup failure" in warning
        for warning in result.warnings
    )


def test_planning_cleanup_failure_is_an_exception_note_without_masking_primary(
    tmp_path, monkeypatch
):
    paths, assignment, roster = _managed(tmp_path)
    temporary_path = paths.individual_templates_dir / ".planning.tmp.pdf"
    temporary_path.write_bytes(b"")
    monkeypatch.setattr(
        generation,
        "_preflight_output_destination",
        lambda _path: (temporary_path, False),
    )
    monkeypatch.setattr(
        generation,
        "discover_answer_sheet_issuances",
        lambda *_args: (_ for _ in ()).throw(
            AnswerSheetPredecessorError("primary planning failure")
        ),
    )
    _fail_cleanup(monkeypatch, temporary_path)

    with pytest.raises(AnswerSheetPredecessorError, match="primary planning failure") as caught:
        _plan(
            tmp_path,
            paths,
            assignment,
            (roster["students"][0],),
            paths.individual_templates_dir / "student.pdf",
        )

    assert any(
        "Temporary artifact cleanup failed" in note
        for note in getattr(caught.value, "__notes__", ())
    )


def test_record_failure_cleanup_warning_preserves_primary_stage_and_old_pdf(
    tmp_path, monkeypatch
):
    students = (_student("1001", "Doe"), _student("1002", "Smith"))
    paths, assignment, _roster = _managed(tmp_path, students=list(students))
    output = paths.class_packet_path
    output.write_bytes(b"old-pdf")
    plan = _plan(tmp_path, paths, assignment, students, output)
    original_write = generation.write_answer_sheet_record_set
    writes = 0

    def fail_second_record(*args):
        nonlocal writes
        writes += 1
        if writes == 2:
            raise RuntimeError("primary record failure")
        return original_write(*args)

    monkeypatch.setattr(generation, "write_answer_sheet_record_set", fail_second_record)
    _fail_cleanup(monkeypatch, plan.temporary_path)

    result = execute_answer_sheet_artifact(tmp_path, paths.work_ref, plan)

    assert result.failure_stage == "record_persistence"
    assert result.created_route_count == result.verified_route_count == 0
    assert not result.installed
    assert output.read_bytes() == b"old-pdf"
    first = load_answer_sheet_issuance(
        tmp_path, paths.work_ref, result.issuance_ids[0]
    )
    assert first.lifecycle.status == "cancelled"
    assert len(tuple(paths.answer_sheet_pages_dir.glob("*.json"))) == 1
    _assert_cleanup_warning(result, "primary record failure")


def test_route_failure_cleanup_warning_preserves_primary_and_compensation(
    tmp_path, monkeypatch
):
    paths, assignment, roster = _managed(tmp_path)
    output = paths.individual_templates_dir / "student.pdf"
    output.write_bytes(b"old-pdf")
    plan = _plan(tmp_path, paths, assignment, (roster["students"][0],), output)
    monkeypatch.setattr(
        generation,
        "persist_answer_sheet_route_set",
        lambda *_args: (_ for _ in ()).throw(
            AnswerSheetRoutePersistenceError("primary route failure")
        ),
    )
    _fail_cleanup(monkeypatch, plan.temporary_path)

    result = execute_answer_sheet_artifact(tmp_path, paths.work_ref, plan)

    assert result.failure_stage == "route_persistence"
    assert result.created_route_count == result.verified_route_count == 0
    issuance = load_answer_sheet_issuance(
        tmp_path, paths.work_ref, result.issuance_ids[0]
    )
    assert issuance.lifecycle.status == "cancelled"
    assert output.read_bytes() == b"old-pdf"
    _assert_cleanup_warning(result, "primary route failure")


def test_render_failure_cleanup_warning_keeps_all_routes_and_invalidates(
    tmp_path, monkeypatch
):
    paths, assignment, roster = _managed(tmp_path)
    output = paths.individual_templates_dir / "student.pdf"
    output.write_bytes(b"old-pdf")
    plan = _plan(tmp_path, paths, assignment, (roster["students"][0],), output)
    monkeypatch.setattr(
        generation,
        "render_registered_answer_sheet_pdf",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("primary render failure")),
    )
    _fail_cleanup(monkeypatch, plan.temporary_path)

    result = execute_answer_sheet_artifact(tmp_path, paths.work_ref, plan)

    assert result.failure_stage == "pdf_rendering"
    assert result.created_route_count == result.verified_route_count == 1
    issuance = load_answer_sheet_issuance(
        tmp_path, paths.work_ref, result.issuance_ids[0]
    )
    assert issuance.lifecycle.status == "invalidated"
    assert output.read_bytes() == b"old-pdf"
    _assert_cleanup_warning(result, "primary render failure")


def test_packet_issuance_finalization_failure_invalidates_issued_and_prepared(
    tmp_path, monkeypatch
):
    students = (_student("1001", "Doe"), _student("1002", "Smith"))
    paths, assignment, _roster = _managed(tmp_path, students=list(students))
    output = paths.class_packet_path
    output.write_bytes(b"old-pdf")
    plan = _plan(tmp_path, paths, assignment, students, output, generation_digit="2")
    original_transition = generation.transition_answer_sheet_issuance
    issued_calls = 0

    def fail_second_issued(*args, **kwargs):
        nonlocal issued_calls
        if kwargs.get("new_status") == "issued":
            issued_calls += 1
            if issued_calls == 2:
                raise RuntimeError("primary finalization failure")
        return original_transition(*args, **kwargs)

    monkeypatch.setattr(generation, "transition_answer_sheet_issuance", fail_second_issued)
    _fail_cleanup(monkeypatch, plan.temporary_path)

    result = execute_answer_sheet_artifact(tmp_path, paths.work_ref, plan)

    assert result.failure_stage == "issuance_finalization"
    assert not result.installed
    assert output.read_bytes() == b"old-pdf"
    assert result.created_route_count == result.verified_route_count == 2
    assert all(Path(path).is_file() for path in result.created_registration_paths)
    assert len(tuple(paths.answer_sheet_pages_dir.glob("*.json"))) == 2
    statuses = tuple(
        load_answer_sheet_issuance(tmp_path, paths.work_ref, issuance_id).lifecycle.status
        for issuance_id in result.issuance_ids
    )
    assert statuses == ("invalidated", "invalidated")
    _assert_cleanup_warning(result, "primary finalization failure")


def test_installation_failure_invalidates_issued_and_preserves_old_pdf(
    tmp_path, monkeypatch
):
    paths, assignment, roster = _managed(tmp_path)
    output = paths.individual_templates_dir / "student.pdf"
    output.write_bytes(b"old-pdf")
    plan = _plan(tmp_path, paths, assignment, (roster["students"][0],), output)
    original_replace = generation.os.replace

    def fail_artifact_replace(source, destination):
        if Path(source) == plan.temporary_path and Path(destination) == output:
            raise OSError("primary installation failure")
        return original_replace(source, destination)

    monkeypatch.setattr(generation.os, "replace", fail_artifact_replace)
    _fail_cleanup(monkeypatch, plan.temporary_path)

    result = execute_answer_sheet_artifact(tmp_path, paths.work_ref, plan)

    assert result.failure_stage == "pdf_installation"
    assert not result.installed
    assert result.created_route_count == result.verified_route_count == 1
    assert output.read_bytes() == b"old-pdf"
    issuance = load_answer_sheet_issuance(
        tmp_path, paths.work_ref, result.issuance_ids[0]
    )
    assert issuance.lifecycle.status == "invalidated"
    assert all(Path(path).is_file() for path in result.created_registration_paths)
    assert len(tuple(paths.answer_sheet_pages_dir.glob("*.json"))) == 1
    _assert_cleanup_warning(result, "primary installation failure")


def test_predecessor_supersession_failure_is_installed_partial_and_cli_nonzero(
    tmp_path, monkeypatch, capsys
):
    paths, assignment, roster = _managed(tmp_path)
    student = roster["students"][0]
    output = paths.individual_templates_dir / student_pdf_filename(student)
    first_plan = _plan(tmp_path, paths, assignment, (student,), output)
    first = execute_answer_sheet_artifact(tmp_path, paths.work_ref, first_plan)
    assert first.success
    predecessor_id = first.issuance_ids[0]
    replacement_plan = _plan(
        tmp_path, paths, assignment, (student,), output, generation_digit="3"
    )
    original_transition = generation.transition_answer_sheet_issuance

    def fail_supersession(*args, **kwargs):
        if kwargs.get("new_status") == "superseded":
            raise RuntimeError("primary supersession failure")
        return original_transition(*args, **kwargs)

    monkeypatch.setattr(generation, "transition_answer_sheet_issuance", fail_supersession)
    replacement = execute_answer_sheet_artifact(
        tmp_path, paths.work_ref, replacement_plan
    )
    aggregate = AnswerSheetGenerationResult(replacement.generation_id, (replacement,))

    assert not replacement.success
    assert replacement.installed and replacement.completed and replacement.partial_success
    assert replacement.failed_predecessor_ids == (predecessor_id,)
    assert aggregate.completed_artifact_count == 1
    assert aggregate.installed_artifact_count == 1
    assert aggregate.clean_success_count == 0
    assert aggregate.partial_artifact_count == 1
    assert aggregate.partial_success
    assert output.is_file() and output.stat().st_size > 0
    new_issuance = load_answer_sheet_issuance(
        tmp_path, paths.work_ref, replacement.issuance_ids[0]
    )
    predecessor = load_answer_sheet_issuance(tmp_path, paths.work_ref, predecessor_id)
    assert new_issuance.lifecycle.status == "issued"
    assert predecessor.lifecycle.status == "issued"

    failure = generate_workflows.ManagedAnswerSheetGenerationFailure(aggregate)
    monkeypatch.setattr(
        generate_workflows,
        "regenerate_answer_sheets_for_assignment",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(failure),
    )
    assert generate_workflows.run_regenerate_sheets(
        ["--class-id", "class1", "--assignment-id", "quiz1"]
    ) == 1
    output_text = capsys.readouterr().out
    assert "new PDF was installed" in output_text
    assert "Installed artifacts: 1" in output_text
    assert "Clean-success artifacts: 0" in output_text
    assert "Partial artifacts: 1" in output_text
    assert f"Predecessors not superseded: {predecessor_id}" in output_text


def test_generation_aggregation_distinguishes_installed_partial_and_preinstall_failure(
    tmp_path,
):
    paths, assignment, roster = _managed(tmp_path)
    output = paths.individual_templates_dir / "student.pdf"
    plan = _plan(tmp_path, paths, assignment, (roster["students"][0],), output)
    clean = execute_answer_sheet_artifact(tmp_path, paths.work_ref, plan)
    partial = replace(
        clean,
        success=False,
        failure_stage="predecessor_supersession",
        failed_predecessor_ids=("iss_10000000000000000000000000000000",),
    )
    preinstall = replace(
        clean,
        success=False,
        installed=False,
        failure_stage="pdf_rendering",
        created_route_count=clean.created_route_count,
        verified_route_count=clean.verified_route_count,
    )

    installed_partial = AnswerSheetGenerationResult(
        clean.generation_id, (clean, partial)
    )
    failed_later = AnswerSheetGenerationResult(clean.generation_id, (clean, preinstall))

    assert installed_partial.completed_artifact_count == 2
    assert installed_partial.clean_success_count == 1
    assert installed_partial.partial_artifact_count == 1
    assert installed_partial.physical_page_count == 2
    assert installed_partial.installed_route_count == 2
    assert failed_later.completed_artifact_count == 1
    assert failed_later.failed_before_install_count == 1
    assert failed_later.physical_page_count == 1


def test_run_generate_reports_installed_partial_counts_and_nonzero(
    tmp_path, monkeypatch, capsys
):
    paths, assignment, roster = _managed(tmp_path)
    student = roster["students"][0]
    plan = _plan(
        tmp_path,
        paths,
        assignment,
        (student,),
        paths.individual_templates_dir / "student.pdf",
    )
    clean = execute_answer_sheet_artifact(tmp_path, paths.work_ref, plan)
    partial = replace(
        clean,
        success=False,
        failure_stage="predecessor_supersession",
        error="iss_10000000000000000000000000000000: supersession failed",
        failed_predecessor_ids=("iss_10000000000000000000000000000000",),
    )
    aggregate = AnswerSheetGenerationResult(partial.generation_id, (partial,))
    setup_paths = {
        "paths": paths,
        "class_dir": str(paths.roster_path.parent),
        "assignment_dir": str(paths.work_root),
        "roster_copy": str(paths.roster_path),
        "assignment_copy": str(paths.assignment_path),
    }
    monkeypatch.setattr(generate_workflows, "load_assignment", lambda _path: assignment)
    monkeypatch.setattr(generate_workflows, "load_roster", lambda _path: roster)
    monkeypatch.setattr(
        generate_workflows, "setup_assignment_folder", lambda *_args: setup_paths
    )
    monkeypatch.setattr(
        generate_workflows, "generate_managed_answer_sheets", lambda *_args, **_kwargs: aggregate
    )

    assert generate_workflows.run_generate(
        ["assignment.json", "--rosters", "roster.csv"]
    ) == 1
    output = capsys.readouterr().out
    assert "new PDF was installed" in output
    assert "Output:" in output
    assert "Installed artifacts: 1" in output
    assert "Clean-success artifacts: 0" in output
    assert "Partial artifacts: 1" in output
    assert "Completed earlier artifacts: 0" in output
    assert "Predecessors not superseded: iss_10000000000000000000000000000000" in output


def test_unexpected_planning_exception_is_reported_as_orchestration_not_preflight(
    tmp_path, monkeypatch
):
    paths, assignment, roster = _managed(tmp_path)
    monkeypatch.setattr(
        generation,
        "plan_answer_sheet_artifact",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("unexpected orchestration failure")
        ),
    )

    result = generation.generate_managed_answer_sheets(
        tmp_path,
        paths.work_ref,
        assignment,
        roster,
        individual_dir=paths.individual_templates_dir,
        class_packet_path=paths.class_packet_path,
        student_filename=student_pdf_filename,
    )

    assert not result.success
    assert result.artifacts[-1].failure_stage == "orchestration"
    assert "unexpected orchestration failure" in result.artifacts[-1].error


def test_all_assignment_reporting_includes_earlier_and_installed_partial_counts(
    tmp_path, monkeypatch
):
    paths, assignment, roster = _managed(tmp_path)
    plan = _plan(
        tmp_path,
        paths,
        assignment,
        (roster["students"][0],),
        paths.individual_templates_dir / "student.pdf",
    )
    clean_artifact = execute_answer_sheet_artifact(tmp_path, paths.work_ref, plan)
    clean_generation = AnswerSheetGenerationResult(
        clean_artifact.generation_id, (clean_artifact,)
    )
    partial_artifact = replace(
        clean_artifact,
        success=False,
        failure_stage="predecessor_supersession",
        error="iss_10000000000000000000000000000000: supersession failed",
        failed_predecessor_ids=("iss_10000000000000000000000000000000",),
    )
    partial_generation = AnswerSheetGenerationResult(
        partial_artifact.generation_id, (partial_artifact,)
    )
    first_result = generate_workflows.RegenerateSheetsResult(
        "class1",
        "quiz1",
        1,
        1,
        str(paths.class_packet_path),
        str(paths.templates_dir),
        generation_result=clean_generation,
    )
    roster_marker = tmp_path / "roster-marker.csv"
    roster_marker.write_text("exists", encoding="utf-8")
    monkeypatch.setattr(
        generate_workflows,
        "discover_class_assignments",
        lambda *_args, **_kwargs: (
            {"assignment_id": "quiz1"},
            {"assignment_id": "quiz2"},
        ),
    )
    monkeypatch.setattr(
        generate_workflows, "class_roster_path", lambda *_args: roster_marker
    )
    calls = 0

    def regenerate(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return first_result
        raise generate_workflows.ManagedAnswerSheetGenerationFailure(
            partial_generation
        )

    monkeypatch.setattr(
        generate_workflows, "regenerate_answer_sheets_for_assignment", regenerate
    )

    with pytest.raises(RuntimeError) as caught:
        generate_workflows.regenerate_answer_sheets_for_class(
            "class1", workspace_root=tmp_path
        )

    message = str(caught.value)
    assert "after 1 assignment(s) completed" in message
    assert "Installed artifacts: 2" in message
    assert "Clean-success artifacts: 1" in message
    assert "Partial artifacts: 1" in message
    assert "Completed earlier artifacts: 1" in message


def test_two_issued_predecessors_are_ambiguous_before_new_records_or_routes(tmp_path):
    paths, assignment, roster = _managed(tmp_path)
    student = roster["students"][0]
    for digit in ("4", "5"):
        records = build_answer_sheet_record_set(
            "class1",
            assignment,
            student,
            generation_id=f"gen_{digit * 32}",
            artifact_id=f"art_{digit * 32}",
            output_kind="individual_pdf",
                reason="initial",
                issuance_id=f"iss_{digit * 32}",
                page_ids=(f"pg_{digit * 32}",),
                clock=lambda: "2026-07-15T14:59:00+00:00",
            )
        write_answer_sheet_record_set(tmp_path, paths.work_ref, records)
        transition_answer_sheet_issuance(
            tmp_path,
            paths.work_ref,
            records.issuance.issuance_id,
            expected_revision=1,
            new_status="issued",
            timestamp="2026-07-15T15:00:00+00:00",
        )
    existing_pages = tuple(paths.answer_sheet_pages_dir.glob("*.json"))

    with pytest.raises(AnswerSheetPredecessorError, match="Multiple current issued"):
        _plan(
            tmp_path,
            paths,
            assignment,
            (student,),
            paths.individual_templates_dir / "ambiguous.pdf",
            generation_digit="6",
        )

    assert tuple(paths.answer_sheet_pages_dir.glob("*.json")) == existing_pages
    assert not (paths.work_root / "routes").exists()
    assert not list(paths.individual_templates_dir.glob("*.pdf"))


def test_route_wrapper_message_preserves_underlying_error_text(tmp_path, monkeypatch):
    paths, assignment, roster = _managed(tmp_path)
    output = paths.individual_templates_dir / "student.pdf"
    plan = _plan(tmp_path, paths, assignment, (roster["students"][0],), output)
    original = routes_module.write_route_registration
    calls = 0

    def fail_first(root, registration):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("simulated route failure text")
        return original(root, registration)

    monkeypatch.setattr(routes_module, "write_route_registration", fail_first)
    result = execute_answer_sheet_artifact(tmp_path, paths.work_ref, plan)

    assert result.failure_stage == "route_persistence"
    assert "simulated route failure text" in result.error
    assert result.created_route_count == result.verified_route_count == 0
