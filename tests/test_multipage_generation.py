import pytest

from scoreform.migration import ScoreFormMigrationPendingError
from scoreform.templates import build_qr_payload


def test_multipage_qr_generation_waits_for_authoritative_page_records() -> None:
    with pytest.raises(ScoreFormMigrationPendingError, match=r"#141"):
        build_qr_payload(
            {"assignment_id": "quiz", "question_count": 16},
            {"class_id": "class1", "student_id": "1001"},
            page_number=2,
        )
