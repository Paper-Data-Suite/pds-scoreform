"""Issue #219 Slice 1: fail-soft teacher-readable Standard labels."""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime, timezone

from pds_core.standards import (
    StandardDefinition,
    StandardsLibrary,
    write_workspace_standards_library,
)

from scoreform.page_scoring import ScoredAnswer
from scoreform.results import (
    ScoreFormRoutedResult,
    ScoreFormRoutedResultHistoryRow,
)
from scoreform.results_analysis import (
    analyze_class_results,
    analyze_student_attempt,
)
from scoreform.results_report_csv import render_results_report_csv
from scoreform.results_report_json import render_results_report_json
from scoreform.results_report_pdf import render_results_report_pdf
from scoreform.results_reporting import (
    REPORT_CONFIRMATION_TOKEN,
    confirm_results_report_plan,
    prepare_results_report_plan,
    prepare_results_report_snapshot,
)
from scoreform.results_standard_display import (
    fallback_results_standards_projection,
    resolve_results_standards_projection,
)
from scoreform.results_viewer import (
    format_class_standard_detail,
    format_class_standards_analysis,
    format_student_attempt_detail,
    format_student_standard_detail,
)

GENERATED = datetime(2026, 10, 1, 20, 0, 0, tzinfo=timezone.utc)


def _definition(
    standard_id: str,
    code: str,
    short_name: str,
    *,
    active: bool = True,
) -> StandardDefinition:
    return StandardDefinition(
        standard_id=standard_id,
        code=code,
        source="Synthetic Core Library",
        short_name=short_name,
        description=f"{short_name} description.",
        subject="Synthetic",
        active=active,
        available_modules=("scoreform",),
    )


def _library(*, label_suffix: str = "") -> StandardsLibrary:
    return StandardsLibrary(
        standards=(
            _definition(
                "STD.A",
                "SYN.A",
                f"Readable A{label_suffix}",
            ),
            _definition(
                "STD.B",
                "SYN.B",
                f"Readable B{label_suffix}",
                active=False,
            ),
        )
    )


def _assignment() -> dict[str, object]:
    return {
        "assignment_id": "quiz1",
        "title": "Synthetic Label Projection",
        "question_count": 2,
        "choices": ["A", "B", "C", "D"],
        "answer_key": {1: "A", 2: "B"},
        "standards": {
            "1": ["STD.A"],
            "2": ["STD.B", "STD.UNKNOWN"],
        },
    }


def _history() -> tuple[ScoreFormRoutedResultHistoryRow, ...]:
    answers = (
        ScoredAnswer(1, "A", True),
        ScoredAnswer(2, "A", False),
    )
    result = ScoreFormRoutedResult(
        "plain_paper_manual",
        "class1",
        "quiz1",
        "1001",
        "Doe",
        "Jane",
        "1",
        "manual",
        1,
        2,
        answers,
        source_file="plain_paper_manual_entry",
    )
    return (
        ScoreFormRoutedResultHistoryRow(
            result,
            1,
            "2026-10-01T19:00:00+00:00",
        ),
    )


def _pdf_text(pdf_bytes: bytes) -> str:
    chunks: list[str] = []
    pattern = rb"\(((?:\\.|[^\\)])*)\)\s*Tj"
    for raw in re.findall(pattern, pdf_bytes):
        raw = re.sub(
            rb"\\([0-7]{1,3})",
            lambda match: bytes([int(match.group(1), 8)]),
            raw,
        )
        raw = raw.replace(rb"\(", b"(")
        raw = raw.replace(rb"\)", b")")
        chunks.append(raw.decode("latin-1"))
    return " ".join(" ".join(chunks).split())


def test_missing_library_is_zero_write_id_fallback(tmp_path):
    missing_workspace = tmp_path / "workspace-must-not-exist"

    projection = resolve_results_standards_projection(
        ("STD.B", "STD.A", "STD.A"),
        workspace_root=missing_workspace,
    )

    assert projection.standard_ids == ("STD.A", "STD.B")
    assert projection.label_for("STD.A") == "STD.A"
    assert projection.resolved_for("STD.A") is False
    assert not missing_workspace.exists()


def test_current_core_labels_resolve_independently_and_unknown_ids_fall_back(tmp_path):
    write_workspace_standards_library(tmp_path, _library())

    projection = resolve_results_standards_projection(
        ("STD.UNKNOWN", "STD.B", "STD.A"),
        workspace_root=tmp_path,
    )

    assert projection.standard_ids == ("STD.A", "STD.B", "STD.UNKNOWN")
    assert projection.label_for("STD.A") == (
        "SYN.A | Readable A | Synthetic Core Library"
    )
    assert projection.label_for("STD.B") == (
        "SYN.B | Readable B | Synthetic Core Library [inactive]"
    )
    assert projection.label_for("STD.UNKNOWN") == "STD.UNKNOWN"
    assert projection.resolved_for("STD.A") is True
    assert projection.resolved_for("STD.B") is True
    assert projection.resolved_for("STD.UNKNOWN") is False


def test_unreadable_library_fails_soft_to_all_durable_ids(tmp_path):
    library_path = tmp_path / "standards" / "library.json"
    library_path.parent.mkdir(parents=True)
    library_path.write_text("{not valid json", encoding="utf-8")

    projection = resolve_results_standards_projection(
        ("STD.A", "STD.UNKNOWN"),
        workspace_root=tmp_path,
    )

    assert projection == fallback_results_standards_projection(
        ("STD.A", "STD.UNKNOWN")
    )


def test_terminal_views_use_projection_without_changing_analysis(tmp_path):
    write_workspace_standards_library(tmp_path, _library())
    history = _history()
    assignment = _assignment()

    projection = resolve_results_standards_projection(
        ("STD.A", "STD.B", "STD.UNKNOWN"),
        workspace_root=tmp_path,
    )
    student = analyze_student_attempt(
        history[0],
        assignment,
        class_id="class1",
    )
    class_analysis = analyze_class_results(
        history,
        assignment,
        class_id="class1",
    )

    student_text = format_student_attempt_detail(
        student,
        standard_display=projection,
    )
    student_detail = format_student_standard_detail(
        student,
        "STD.A",
        standard_display=projection,
    )
    class_text = format_class_standards_analysis(
        class_analysis,
        standard_display=projection,
    )
    class_detail = format_class_standard_detail(
        class_analysis,
        "STD.B",
        standard_display=projection,
    )

    assert "SYN.A | Readable A | Synthetic Core Library" in student_text
    assert "Standard: SYN.A | Readable A | Synthetic Core Library" in student_detail
    assert "SYN.B | Readable B | Synthetic Core Library [inactive]" in class_text
    assert (
        "Standard: SYN.B | Readable B | Synthetic Core Library [inactive]"
        in class_detail
    )
    assert "STD.UNKNOWN" in student_text
    assert [item.standard_id for item in student.standards] == [
        "STD.A",
        "STD.B",
        "STD.UNKNOWN",
    ]
    assert [item.standard_id for item in class_analysis.standards] == [
        "STD.A",
        "STD.B",
        "STD.UNKNOWN",
    ]


def test_report_snapshot_freezes_current_labels_for_csv_json_and_pdf(tmp_path):
    write_workspace_standards_library(tmp_path, _library())

    snapshot = prepare_results_report_snapshot(
        _history(),
        _assignment(),
        class_id="class1",
        scope="class_analysis",
        generated_at=GENERATED,
        workspace_root=tmp_path,
    )
    frozen_label = "SYN.A | Readable A | Synthetic Core Library"
    assert snapshot.standards_projection.label_for("STD.A") == frozen_label

    write_workspace_standards_library(
        tmp_path,
        _library(label_suffix=" CHANGED AFTER SNAPSHOT"),
        overwrite=True,
    )

    csv_plan = prepare_results_report_plan(snapshot, output_format="csv")
    csv_confirmed = confirm_results_report_plan(
        csv_plan,
        REPORT_CONFIRMATION_TOKEN,
    )
    assert csv_confirmed is not None
    csv_report = render_results_report_csv(csv_confirmed)
    standards_csv = csv_report.artifact("standards_analysis.csv").content.decode(
        "utf-8"
    )
    rows = list(csv.DictReader(io.StringIO(standards_csv)))
    assert rows[0]["standard_id"] == "STD.A"
    assert rows[0]["display_label"] == frozen_label
    assert "CHANGED AFTER SNAPSHOT" not in standards_csv

    json_plan = prepare_results_report_plan(snapshot, output_format="json")
    json_confirmed = confirm_results_report_plan(
        json_plan,
        REPORT_CONFIRMATION_TOKEN,
    )
    assert json_confirmed is not None
    json_report = render_results_report_json(json_confirmed)
    payload = json.loads(json_report.artifacts[0].content)
    standard_json = payload["class_analysis"]["standards_analysis"][0]
    assert standard_json["standard_id"] == "STD.A"
    assert standard_json["display_label"] == frozen_label
    assert payload["schema_version"] == "scoreform_results_analysis_v1"

    pdf_plan = prepare_results_report_plan(snapshot, output_format="pdf")
    pdf_confirmed = confirm_results_report_plan(
        pdf_plan,
        REPORT_CONFIRMATION_TOKEN,
    )
    assert pdf_confirmed is not None
    pdf = render_results_report_pdf(pdf_confirmed).artifacts[0].content
    pdf_text = _pdf_text(pdf)
    assert "SYN.A" in pdf_text
    assert "Readable A" in pdf_text
    assert "Synthetic Core Library" in pdf_text
    assert "CHANGED AFTER SNAPSHOT" not in pdf_text


def test_report_with_unreadable_library_keeps_existing_schema_and_id_fallback(
    tmp_path,
):
    library_path = tmp_path / "standards" / "library.json"
    library_path.parent.mkdir(parents=True)
    library_path.write_text("{broken", encoding="utf-8")

    snapshot = prepare_results_report_snapshot(
        _history(),
        _assignment(),
        class_id="class1",
        scope="class_analysis",
        generated_at=GENERATED,
        workspace_root=tmp_path,
    )
    plan = prepare_results_report_plan(snapshot, output_format="json")
    confirmed = confirm_results_report_plan(plan, REPORT_CONFIRMATION_TOKEN)
    assert confirmed is not None
    payload = json.loads(
        render_results_report_json(confirmed).artifacts[0].content
    )

    assert payload["schema_version"] == "scoreform_results_analysis_v1"
    assert [
        item["display_label"]
        for item in payload["class_analysis"]["standards_analysis"]
    ] == ["STD.A", "STD.B", "STD.UNKNOWN"]
