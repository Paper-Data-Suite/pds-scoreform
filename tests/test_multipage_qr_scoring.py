from scoreform import scoring


def _page(assessment_page, answers, *, scan_page=None):
    return {
        "page_num": scan_page or assessment_page,
        "assessment_page": assessment_page,
        "assignment_page_count": 2,
        "assignment_question_count": 16,
        "score": sum(answer["Correct"] for answer in answers),
        "total_points": len(answers),
        "answers": answers,
        "class_id": "class1",
        "assignment_id": "quiz",
        "student_id": "1001",
        "source_file": "scan.pdf",
    }


def test_obsolete_mutable_assembler_is_not_reachable():
    assert not hasattr(scoring, "_assemble_qr_attempts")


def test_legacy_source_filename_grouping_fixture_is_inactive():
    assert _page(1, [])["source_file"] == "scan.pdf"
