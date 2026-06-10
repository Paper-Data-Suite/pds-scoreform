from scoreform import templates

VALID_ASSIGNMENT = {"assignment_id": "rj_act1_quiz"}
VALID_STUDENT = {
    "class_id": "english9_p2",
    "student_id": "1001",
    "last_name": "Doe",
    "first_name": "Jane",
}
VALID_PDS1_PAYLOAD = (
    "PDS1|module=scoreform|class=english9_p2|"
    "aid=rj_act1_quiz|sid=1001|page=1"
)


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


def test_build_qr_payload_uses_pds1_scoreform_contract():
    assert templates.build_qr_payload(VALID_ASSIGNMENT, VALID_STUDENT) == (
        VALID_PDS1_PAYLOAD
    )


def test_student_and_class_packet_pages_use_pds1_payloads(monkeypatch):
    payloads = []

    def fake_make_qr_image(payload):
        payloads.append(payload)
        return object()

    class FakeCanvas:
        def setFont(self, *_args):
            pass

        def drawString(self, *_args):
            pass

        def setLineWidth(self, *_args):
            pass

        def rect(self, *_args, **_kwargs):
            pass

        def drawImage(self, *_args):
            pass

    monkeypatch.setattr(templates, "make_qr_image", fake_make_qr_image)

    canvas = FakeCanvas()
    assert templates.draw_student_answer_sheet_page(
        canvas, VALID_ASSIGNMENT, VALID_STUDENT
    )
    assert templates.draw_student_answer_sheet_page(
        canvas,
        VALID_ASSIGNMENT,
        {**VALID_STUDENT, "student_id": "1002"},
    )

    assert payloads == [
        VALID_PDS1_PAYLOAD,
        (
            "PDS1|module=scoreform|class=english9_p2|"
            "aid=rj_act1_quiz|sid=1002|page=1"
        ),
    ]


def test_build_qr_payload_rejects_unsafe_identifiers():
    assignment = {"assignment_id": "rj_act1_quiz"}
    student = {
        "class_id": "english9_p2",
        "student_id": "../secret",
        "last_name": "Doe",
        "first_name": "Jane",
    }

    assert templates.build_qr_payload(assignment, student) is None


def test_build_qr_payload_contains_core_validation_errors(monkeypatch):
    def fake_build(_payload):
        raise templates.Pds1PayloadError("invalid payload")

    monkeypatch.setattr(templates, "build_pds1_payload", fake_build)

    assert templates.build_qr_payload(VALID_ASSIGNMENT, VALID_STUDENT) is None
