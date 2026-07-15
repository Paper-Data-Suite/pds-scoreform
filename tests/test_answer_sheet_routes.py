from pathlib import Path

import cv2
import numpy as np
import pytest
from pds_core.pds2 import parse_pds2_payload
from pds_core.route_registrations import load_route_registration
from pds_core.routes import route_registration_path
from pds_core.routing_models import PDS2_SCHEMA, RouteLocator

import scoreform.answer_sheet_generation as generation_module
import scoreform.answer_sheet_routes as routes_module
import scoreform.templates as templates_module
from scoreform.answer_sheet_generation import (
    execute_answer_sheet_artifact,
    generate_managed_answer_sheets,
    plan_answer_sheet_artifact,
)
from scoreform.answer_sheet_persistence import (
    load_answer_sheet_issuance,
    write_answer_sheet_record_set,
)
from scoreform.answer_sheet_records import build_answer_sheet_record_set
from scoreform.answer_sheet_routes import (
    RegisteredAnswerSheetPageRoute,
    build_answer_sheet_page_route,
    persist_answer_sheet_route_set,
    plan_answer_sheet_route_set,
)
from scoreform.folders import setup_assignment_folder
from scoreform.layouts import get_layout
from scoreform.templates import build_qr_payload, student_pdf_filename
from scoreform.work_paths import scoreform_work_paths


def _assignment(question_count=20, layout_id="standard_15q_abcd_v1"):
    return {
        "assignment_id": "quiz1",
        "title": "Quiz One",
        "question_count": question_count,
        "choices": ["A", "B", "C", "D"],
        "layout_id": layout_id,
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


def _managed_sources(
    tmp_path, *, question_count=20, layout_id="standard_15q_abcd_v1", students=None
):
    selected = students or [_student()]
    roster = {"class_id": "class1", "students": selected}
    assignment = _assignment(question_count, layout_id)
    setup = setup_assignment_folder(
        roster, assignment, workspace_root=tmp_path
    )
    assert setup is not None
    return setup["paths"], assignment, roster


def _records(assignment=None, student=None):
    return build_answer_sheet_record_set(
        "class1",
        assignment or _assignment(),
        student or _student(),
        generation_id="gen_00000000000000000000000000000001",
        artifact_id="art_00000000000000000000000000000002",
        output_kind="individual_pdf",
        reason="initial",
        issuance_id="iss_00000000000000000000000000000003",
        page_ids=(
            "pg_00000000000000000000000000000004",
            "pg_00000000000000000000000000000005",
        ),
        clock=lambda: "2026-07-15T12:00:00+00:00",
    )


def test_pure_route_model_has_exact_locator_registration_and_payload(tmp_path):
    paths = scoreform_work_paths(tmp_path, "class1", "quiz1")
    page = _records().pages[0]
    route = build_answer_sheet_page_route(
        paths.work_ref,
        page,
        route_id="rt_10000000000000000000000000000000",
    )

    assert route.locator.schema == "PDS2"
    assert route.locator.module_id == "scoreform"
    assert route.locator.class_id == "class1"
    assert route.locator.work_id == "quiz1"
    assert route.registration.target.record_kind == "answer_sheet_page"
    assert route.registration.target.record_id == page.page_id
    assert route.registration.status == "active"
    assert route.registration.created_at == page.created_at
    assert route.registration.module_details == {
        "issuance_id": page.issuance_id,
        "logical_page": 1,
        "total_pages": 2,
    }
    assert route.registration.human_fallback == (
        "ScoreForm | class=class1 | assignment=quiz1 | student=1001 | "
        f"page=1/2 | page_id={page.page_id}"
    )
    assert route.payload_text == (
        "PDS2|m=scoreform|c=class1|w=quiz1|"
        "r=rt_10000000000000000000000000000000"
    )
    assert parse_pds2_payload(route.payload_text) == route.locator
    assert build_qr_payload(route.locator) == route.payload_text
    assert "1001" not in route.payload_text
    assert page.page_id not in route.payload_text
    assert list(tmp_path.iterdir()) == []


def test_route_set_persists_one_core_registration_per_existing_page(tmp_path):
    paths, assignment, _roster = _managed_sources(tmp_path)
    records = _records(assignment)
    write_answer_sheet_record_set(tmp_path, paths.work_ref, records)
    ids = iter(
        (
            "rt_10000000000000000000000000000000",
            "rt_20000000000000000000000000000000",
        )
    )
    planned = plan_answer_sheet_route_set(
        paths.work_ref, records, route_id_generator=lambda: next(ids)
    )
    persisted = persist_answer_sheet_route_set(
        tmp_path, paths.work_ref, records, planned
    )

    assert len(persisted.routes) == len(records.pages) == 2
    for route in persisted.routes:
        assert route.registration_path == route_registration_path(
            tmp_path, route.locator
        )
        assert load_route_registration(tmp_path, route.locator) == route.registration
        assert route.registration.target.record_id == route.page.page_id

    with pytest.raises(Exception, match="already exists"):
        persist_answer_sheet_route_set(tmp_path, paths.work_ref, records, planned)


def test_artifact_pipeline_renders_then_regeneration_preserves_old_routes(tmp_path):
    paths, assignment, roster = _managed_sources(tmp_path)
    student = roster["students"][0]
    output = paths.individual_templates_dir / student_pdf_filename(student)

    first = plan_answer_sheet_artifact(
        tmp_path,
        paths.work_ref,
        assignment,
        (student,),
        output,
        output_kind="individual_pdf",
        generation_id="gen_10000000000000000000000000000000",
    )
    first_result = execute_answer_sheet_artifact(tmp_path, paths.work_ref, first)
    assert first_result.success
    assert output.is_file() and output.stat().st_size > 0
    old_routes = {
        path: path.read_bytes()
        for path in map(Path, first_result.created_registration_paths)
    }
    old_issuance = load_answer_sheet_issuance(
        tmp_path, paths.work_ref, first_result.issuance_ids[0]
    )
    assert old_issuance.lifecycle.status == "issued"

    second = plan_answer_sheet_artifact(
        tmp_path,
        paths.work_ref,
        assignment,
        (student,),
        output,
        output_kind="individual_pdf",
        generation_id="gen_20000000000000000000000000000000",
    )
    second_result = execute_answer_sheet_artifact(tmp_path, paths.work_ref, second)
    assert second_result.success
    assert set(first_result.page_ids).isdisjoint(second_result.page_ids)
    assert set(first_result.route_ids).isdisjoint(second_result.route_ids)
    assert all(path.read_bytes() == content for path, content in old_routes.items())
    old_issuance = load_answer_sheet_issuance(
        tmp_path, paths.work_ref, first_result.issuance_ids[0]
    )
    assert old_issuance.lifecycle.status == "superseded"
    assert old_issuance.lifecycle.replacement_issuance_id == second_result.issuance_ids[0]


def test_partial_route_failure_preserves_old_pdf_and_invalidates_issuance(
    tmp_path, monkeypatch
):
    paths, assignment, roster = _managed_sources(tmp_path)
    student = roster["students"][0]
    output = paths.individual_templates_dir / student_pdf_filename(student)
    output.write_bytes(b"old-pdf")
    plan = plan_answer_sheet_artifact(
        tmp_path,
        paths.work_ref,
        assignment,
        (student,),
        output,
        output_kind="individual_pdf",
        generation_id="gen_30000000000000000000000000000000",
    )
    original = routes_module.write_route_registration
    calls = 0

    def fail_second(root, registration):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated route failure")
        return original(root, registration)

    monkeypatch.setattr(routes_module, "write_route_registration", fail_second)
    result = execute_answer_sheet_artifact(tmp_path, paths.work_ref, plan)

    assert not result.success
    assert result.failure_stage == "route_persistence"
    assert "simulated route failure" in result.error
    assert result.planned_route_count == 2
    assert result.created_route_count == 1
    assert result.verified_route_count == 1
    assert output.read_bytes() == b"old-pdf"
    assert len(result.created_registration_paths) == 1
    issuance = load_answer_sheet_issuance(
        tmp_path, paths.work_ref, result.issuance_ids[0]
    )
    assert issuance.lifecycle.status == "invalidated"
    assert all(Path(path).is_file() for path in result.created_registration_paths)


def test_two_student_individuals_and_packet_have_separate_physical_identity(tmp_path):
    students = [_student("1001", "Doe"), _student("1002", "Smith")]
    paths, assignment, roster = _managed_sources(tmp_path, students=students)
    result = generate_managed_answer_sheets(
        tmp_path,
        paths.work_ref,
        assignment,
        roster,
        individual_dir=paths.individual_templates_dir,
        class_packet_path=paths.class_packet_path,
        student_filename=student_pdf_filename,
        generation_id="gen_40000000000000000000000000000000",
    )

    assert result.success
    assert len(result.artifacts) == 3
    individuals = result.artifacts[:2]
    packet = result.artifacts[2]
    assert all(item.output_kind == "individual_pdf" for item in individuals)
    assert packet.output_kind == "class_packet_pdf"
    assert packet.issuance_count == 2
    assert packet.physical_page_count == 4
    assert len({item.artifact_id for item in result.artifacts}) == 3
    assert len({page for item in result.artifacts for page in item.page_ids}) == 8
    assert len({route for item in result.artifacts for route in item.route_ids}) == 8
    page_files = tuple(paths.answer_sheet_pages_dir.glob("*.json"))
    route_files = tuple((paths.work_root / "routes").rglob("*.json"))
    assert len(page_files) == len(route_files) == 8
    assert paths.class_packet_path.is_file()


def test_render_failure_invalidates_issuance_and_preserves_routes_and_old_pdf(
    tmp_path, monkeypatch
):
    paths, assignment, roster = _managed_sources(tmp_path)
    student = roster["students"][0]
    output = paths.individual_templates_dir / student_pdf_filename(student)
    output.write_bytes(b"old-pdf")
    plan = plan_answer_sheet_artifact(
        tmp_path,
        paths.work_ref,
        assignment,
        (student,),
        output,
        output_kind="individual_pdf",
        generation_id="gen_50000000000000000000000000000000",
    )
    monkeypatch.setattr(
        generation_module,
        "render_registered_answer_sheet_pdf",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("render failed")),
    )

    result = execute_answer_sheet_artifact(tmp_path, paths.work_ref, plan)

    assert not result.success
    assert result.failure_stage == "pdf_rendering"
    assert result.created_route_count == result.verified_route_count == 2
    assert output.read_bytes() == b"old-pdf"
    assert len(result.created_registration_paths) == 2
    assert all(Path(path).is_file() for path in result.created_registration_paths)
    issuance = load_answer_sheet_issuance(
        tmp_path, paths.work_ref, result.issuance_ids[0]
    )
    assert issuance.lifecycle.status == "invalidated"


def test_route_collision_is_burned_and_retried_before_record_persistence(tmp_path):
    paths, assignment, roster = _managed_sources(tmp_path)
    student = roster["students"][0]
    collided = "rt_10000000000000000000000000000000"
    collision_locator = RouteLocator(PDS2_SCHEMA, paths.work_ref, collided)
    collision_path = route_registration_path(tmp_path, collision_locator)
    collision_path.parent.mkdir(parents=True)
    collision_path.write_text("historical route", encoding="utf-8")
    generated = iter(
        (
            collided,
            "rt_20000000000000000000000000000000",
            "rt_30000000000000000000000000000000",
        )
    )

    plan = plan_answer_sheet_artifact(
        tmp_path,
        paths.work_ref,
        assignment,
        (student,),
        paths.individual_templates_dir / student_pdf_filename(student),
        output_kind="individual_pdf",
        generation_id="gen_60000000000000000000000000000000",
        route_id_generator=lambda: next(generated),
    )

    assert tuple(route.locator.route_id for route in plan.route_sets[0]) == (
        "rt_20000000000000000000000000000000",
        "rt_30000000000000000000000000000000",
    )
    assert not paths.answer_sheets_dir.exists()
    assert collision_path.read_text(encoding="utf-8") == "historical route"
    plan.temporary_path.unlink()


def test_matching_prepared_issuance_blocks_concurrent_generation_before_new_records(
    tmp_path,
):
    paths, assignment, roster = _managed_sources(tmp_path)
    prepared = _records(assignment)
    write_answer_sheet_record_set(tmp_path, paths.work_ref, prepared)
    existing_page_ids = {page.page_id for page in prepared.pages}

    with pytest.raises(Exception, match="prepared issuance"):
        plan_answer_sheet_artifact(
            tmp_path,
            paths.work_ref,
            assignment,
            (roster["students"][0],),
            paths.individual_templates_dir / "concurrent.pdf",
            output_kind="individual_pdf",
            generation_id="gen_70000000000000000000000000000000",
        )

    assert {path.stem for path in paths.answer_sheet_pages_dir.glob("*.json")} == (
        existing_page_ids
    )
    assert not list(paths.individual_templates_dir.glob("*.pdf"))


@pytest.mark.parametrize(
    ("layout_id", "question_count", "ranges"),
    (
        ("standard_15q_abcd_v1", 20, ((1, 15), (16, 20))),
        ("compact_25q_abcd_v1", 50, ((1, 25), (26, 50))),
    ),
)
def test_rendered_pdf_qrs_decode_to_exact_planned_locators(
    tmp_path, layout_id, question_count, ranges
):
    pdf2image = pytest.importorskip("pdf2image")
    paths, assignment, roster = _managed_sources(
        tmp_path, question_count=question_count, layout_id=layout_id
    )
    student = roster["students"][0]
    output = paths.individual_templates_dir / student_pdf_filename(student)
    plan = plan_answer_sheet_artifact(
        tmp_path,
        paths.work_ref,
        assignment,
        (student,),
        output,
        output_kind="individual_pdf",
        generation_id="gen_80000000000000000000000000000000",
    )
    result = execute_answer_sheet_artifact(tmp_path, paths.work_ref, plan)
    assert result.success
    assert tuple(
        (page.question_start, page.question_end)
        for page in plan.record_sets[0].pages
    ) == ranges

    rendered_pages = pdf2image.convert_from_path(output, dpi=300)
    expected_payloads = [route.payload_text for route in plan.route_sets[0]]
    decoded_payloads = []
    detector = cv2.QRCodeDetector()
    for rendered_page in rendered_pages:
        image = cv2.cvtColor(np.array(rendered_page), cv2.COLOR_RGB2BGR)
        payload, _points, _straight = detector.detectAndDecode(image)
        decoded_payloads.append(payload)

    assert decoded_payloads == expected_payloads


class _RecordingCanvas:
    def __init__(self):
        self.text = []

    def setFont(self, *_args):
        pass

    def setLineWidth(self, *_args):
        pass

    def rect(self, *_args, **_kwargs):
        pass

    def drawImage(self, *_args):
        pass

    def drawString(self, _x, _y, value):
        self.text.append(value)


def _rectangles_intersect(first, second):
    left1, top1, right1, bottom1 = first
    left2, top2, right2, bottom2 = second
    return not (
        right1 <= left2 or right2 <= left1 or bottom1 <= top2 or bottom2 <= top1
    )


@pytest.mark.parametrize(
    ("layout_id", "question_count", "expected_range"),
    (
        ("standard_15q_abcd_v1", 15, "Questions 1\N{EN DASH}15"),
        ("compact_25q_abcd_v1", 25, "Questions 1\N{EN DASH}25"),
    ),
)
def test_identity_geometry_and_visible_text_are_safe_for_each_layout(
    tmp_path, monkeypatch, layout_id, question_count, expected_range
):
    layout = get_layout(layout_id)
    identity = layout.identity_bounds
    qr = (
        layout.qr_x,
        layout.qr_y,
        layout.qr_x + layout.qr_size,
        layout.qr_y + layout.qr_size,
    )
    assert not _rectangles_intersect(identity, qr)
    for x, y in layout.registration_marks:
        mark = (x, y, x + layout.registration_size, y + layout.registration_size)
        assert not _rectangles_intersect(identity, mark)
    for slot in layout.question_slots:
        for box in slot.boxes:
            answer_box = (box.x, box.y, box.x + box.size, box.y + box.size)
            assert not _rectangles_intersect(identity, answer_box)

    assignment = _assignment(question_count, layout_id)
    student = _student()
    records = build_answer_sheet_record_set(
        "class1",
        assignment,
        student,
        generation_id="gen_90000000000000000000000000000000",
        artifact_id="art_90000000000000000000000000000000",
        output_kind="individual_pdf",
        reason="initial",
    )
    route = build_answer_sheet_page_route(
        scoreform_work_paths(tmp_path, "class1", "quiz1").work_ref,
        records.pages[0],
    )
    registered = RegisteredAnswerSheetPageRoute(route, Path(__file__))
    canvas = _RecordingCanvas()
    monkeypatch.setattr(templates_module, "make_qr_image", lambda _payload: object())

    templates_module.draw_student_answer_sheet_page(
        canvas, assignment, student, registered, layout
    )

    assert f"Sheet ID: {records.pages[0].page_id}" in canvas.text
    assert f"Route ID: {route.locator.route_id}" in canvas.text
    assert "Page 1 of 1" in canvas.text
    assert expected_range in canvas.text
