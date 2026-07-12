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


def test_complete_pages_assemble_one_attempt():
    summary = scoring.QRBatchSummary()
    first = [{"Q": q, "Answer": "A", "Correct": True} for q in range(1, 16)]
    second = [{"Q": 16, "Answer": "B", "Correct": False}]
    results = scoring._assemble_qr_attempts([_page(1, first), _page(2, second)], summary)

    assert len(results) == 1
    assert results[0]["page_num"] == "1,2"
    assert results[0]["score"] == 15
    assert results[0]["total_points"] == 16
    assert [answer["Q"] for answer in results[0]["answers"]] == list(range(1, 17))


def test_missing_or_duplicate_page_prevents_partial_attempt():
    for pages in ([_page(1, [])], [_page(1, []), _page(1, [], scan_page=2), _page(2, [], scan_page=3)]):
        summary = scoring.QRBatchSummary()
        assert scoring._assemble_qr_attempts(pages, summary) == []
        assert summary.failures[-1].category == "multi_page_assembly_failed"
