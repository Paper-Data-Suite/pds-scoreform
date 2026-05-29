from scoreform import templates


def test_student_pdf_filename():
    student = {"student_id": "1001", "last_name": "Doe", "first_name": "Jane"}
    fname = templates.student_pdf_filename(student)
    assert fname == "1001_doe_jane.pdf"


def test_safe_filename_none():
    assert templates.safe_filename(None) == ""


def test_build_qr_payload_rejects_unsafe_identifiers():
    assignment = {"assignment_id": "rj_act1_quiz"}
    student = {
        "class_id": "english9_p2",
        "student_id": "../secret",
        "last_name": "Doe",
        "first_name": "Jane",
    }

    assert templates.build_qr_payload(assignment, student) is None
