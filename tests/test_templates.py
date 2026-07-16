import pytest
from pds_core.routing_models import PDS2_SCHEMA, ModuleWorkRef, RouteLocator

from scoreform import templates


def test_student_pdf_filename():
    student = {"student_id": "1001", "last_name": "Doe", "first_name": "Jane"}
    fname = templates.student_pdf_filename(student)
    assert fname == "1001_doe_jane.pdf"


def test_generate_template_uses_workspace_defaults(tmp_path, monkeypatch):
    generated = []
    monkeypatch.setattr(
        templates,
        "_generate_template_pdf",
        lambda path: generated.append(("pdf", path)),
    )
    monkeypatch.setattr(
        templates,
        "_generate_template_png",
        lambda path: generated.append(("png", path)),
    )

    templates.generate_template()

    assert generated == [
        ("pdf", str(tmp_path / "local_outputs" / "templates" / "template.pdf")),
        ("png", str(tmp_path / "local_outputs" / "templates" / "template.png")),
    ]


def test_safe_filename_none():
    assert templates.safe_filename(None) == ""


def test_build_qr_payload_serializes_only_a_pds2_locator():
    locator = RouteLocator(
        PDS2_SCHEMA,
        ModuleWorkRef("scoreform", "english9_p2", "rj_act1_quiz"),
        "rt_10000000000000000000000000000000",
    )
    assert templates.build_qr_payload(locator) == (
        "PDS2|m=scoreform|c=english9_p2|w=rj_act1_quiz|"
        "r=rt_10000000000000000000000000000000"
    )
    with pytest.raises(TypeError):
        templates.build_qr_payload({"assignment_id": "rj_act1_quiz"})
