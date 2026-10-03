"""Issue #219 Slice 2: current Standards-profile presentation ordering."""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime, timezone

from pds_core.standards import (
    StandardDefinition,
    StandardsLibrary,
    StandardsProfile,
    write_workspace_standards_library,
)

from scoreform.page_scoring import ScoredAnswer
from scoreform.results import (
    ScoreFormRoutedResult,
    ScoreFormRoutedResultHistoryRow,
)
from scoreform.results_analysis import analyze_class_results
from scoreform.results_analysis_menu import (
    launch_class_standards_analysis_menu,
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
    order_standard_items,
    resolve_results_standards_projection,
)
from scoreform.results_viewer import format_class_standards_analysis

GENERATED = datetime(2026, 10, 1, 21, 0, 0, tzinfo=timezone.utc)


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


def _library(
    *,
    profile_order: tuple[str, ...] = ("STD.C", "STD.A"),
    profile_id: str = "course_profile",
) -> StandardsLibrary:
    return StandardsLibrary(
        standards=(
            _definition("STD.A", "SYN.A", "Readable A"),
            _definition("STD.B", "SYN.B", "Readable B", active=False),
            _definition("STD.C", "SYN.C", "Readable C"),
        ),
        profiles=(
            StandardsProfile(
                profile_id=profile_id,
                standards=profile_order,
                subject="Synthetic",
                course="Synthetic Course",
                title="Synthetic Course Profile",
            ),
        ),
    )


def _assignment() -> dict[str, object]:
    return {
        "assignment_id": "quiz1",
        "title": "Synthetic Profile Ordering",
        "question_count": 4,
        "choices": ["A", "B", "C", "D"],
        "answer_key": {1: "A", 2: "B", 3: "C", 4: "D"},
        "standards": {
            "1": ["STD.A"],
            "2": ["STD.C", "STD.A"],
            "3": ["STD.B"],
            "4": ["STD.UNKNOWN"],
        },
        "standards_profile_id": "course_profile",
    }


def _history() -> tuple[ScoreFormRoutedResultHistoryRow, ...]:
    answers = (
        ScoredAnswer(1, "A", True),
        ScoredAnswer(2, "A", False),
        ScoredAnswer(3, "C", True),
        ScoredAnswer(4, "BLANK", False),
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
        2,
        4,
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


def _confirmed(snapshot, output_format):
    plan = prepare_results_report_plan(
        snapshot,
        output_format=output_format,
    )
    confirmed = confirm_results_report_plan(
        plan,
        REPORT_CONFIRMATION_TOKEN,
    )
    assert confirmed is not None
    return confirmed


def test_profile_order_is_projection_only_and_keeps_stale_tail_lexical(tmp_path):
    write_workspace_standards_library(tmp_path, _library())

    analysis = analyze_class_results(
        _history(),
        _assignment(),
        class_id="class1",
    )
    projection = resolve_results_standards_projection(
        (item.standard_id for item in analysis.standards),
        workspace_root=tmp_path,
        standards_profile_id="course_profile",
    )

    assert tuple(item.standard_id for item in analysis.standards) == (
        "STD.A",
        "STD.B",
        "STD.C",
        "STD.UNKNOWN",
    )
    assert projection.standard_ids == (
        "STD.C",
        "STD.A",
        "STD.B",
        "STD.UNKNOWN",
    )
    assert tuple(
        item.standard_id
        for item in order_standard_items(analysis.standards, projection)
    ) == projection.standard_ids

    by_id = {item.standard_id: item for item in analysis.standards}
    assert (by_id["STD.A"].correct, by_id["STD.A"].responses) == (1, 2)
    assert (by_id["STD.C"].correct, by_id["STD.C"].responses) == (0, 1)


def test_inactive_profile_member_remains_in_profile_order(tmp_path):
    write_workspace_standards_library(
        tmp_path,
        _library(profile_order=("STD.B", "STD.C", "STD.A")),
    )

    projection = resolve_results_standards_projection(
        ("STD.A", "STD.B", "STD.C"),
        workspace_root=tmp_path,
        standards_profile_id="course_profile",
    )

    assert projection.standard_ids == ("STD.B", "STD.C", "STD.A")
    assert projection.label_for("STD.B").endswith("[inactive]")


def test_missing_current_profile_falls_back_to_lexical_order_but_keeps_labels(
    tmp_path,
):
    write_workspace_standards_library(tmp_path, _library())

    projection = resolve_results_standards_projection(
        ("STD.C", "STD.A", "STD.B"),
        workspace_root=tmp_path,
        standards_profile_id="profile_removed_since_assignment",
    )

    assert projection.standard_ids == ("STD.A", "STD.B", "STD.C")
    assert projection.label_for("STD.A") == (
        "SYN.A | Readable A | Synthetic Core Library"
    )
    assert projection.resolved_for("STD.A") is True


def test_class_terminal_view_and_selection_follow_profile_order(tmp_path, capsys):
    write_workspace_standards_library(tmp_path, _library())

    responses = iter(("1", "", "B"))

    code = launch_class_standards_analysis_menu(
        _history(),
        _assignment(),
        class_id="class1",
        clear_screen_fn=lambda: None,
        workspace_root=tmp_path,
        input_fn=lambda _prompt: next(responses),
    )

    assert code == 0
    output = capsys.readouterr().out
    c_label = "SYN.C | Readable C | Synthetic Core Library"
    a_label = "SYN.A | Readable A | Synthetic Core Library"
    b_label = "SYN.B | Readable B | Synthetic Core Library [inactive]"

    assert output.index(c_label) < output.index(a_label) < output.index(b_label)
    assert f"Standard: {c_label}" in output


def test_formatter_profile_order_is_not_performance_order(tmp_path):
    write_workspace_standards_library(
        tmp_path,
        _library(profile_order=("STD.C", "STD.A", "STD.B")),
    )
    analysis = analyze_class_results(
        _history(),
        _assignment(),
        class_id="class1",
    )
    projection = resolve_results_standards_projection(
        (item.standard_id for item in analysis.standards),
        workspace_root=tmp_path,
        standards_profile_id="course_profile",
    )

    output = format_class_standards_analysis(
        analysis,
        standard_display=projection,
    )

    c_label = "SYN.C | Readable C | Synthetic Core Library"
    a_label = "SYN.A | Readable A | Synthetic Core Library"
    b_label = "SYN.B | Readable B | Synthetic Core Library [inactive]"
    assert output.index(c_label) < output.index(a_label) < output.index(b_label)


def test_report_snapshot_freezes_profile_order_across_all_renderers(tmp_path):
    write_workspace_standards_library(tmp_path, _library())

    snapshot = prepare_results_report_snapshot(
        _history(),
        _assignment(),
        class_id="class1",
        scope="class_analysis",
        generated_at=GENERATED,
        workspace_root=tmp_path,
    )
    assert snapshot.standards_projection.standard_ids == (
        "STD.C",
        "STD.A",
        "STD.B",
        "STD.UNKNOWN",
    )

    write_workspace_standards_library(
        tmp_path,
        _library(profile_order=("STD.A", "STD.C")),
        overwrite=True,
    )

    csv_report = render_results_report_csv(_confirmed(snapshot, "csv"))
    csv_rows = list(
        csv.DictReader(
            io.StringIO(
                csv_report.artifact("standards_analysis.csv").content.decode(
                    "utf-8"
                )
            )
        )
    )
    assert [row["standard_id"] for row in csv_rows] == [
        "STD.C",
        "STD.A",
        "STD.B",
        "STD.UNKNOWN",
    ]

    json_report = render_results_report_json(_confirmed(snapshot, "json"))
    payload = json.loads(json_report.artifacts[0].content)
    assert [
        item["standard_id"]
        for item in payload["class_analysis"]["standards_analysis"]
    ] == ["STD.C", "STD.A", "STD.B", "STD.UNKNOWN"]
    assert payload["schema_version"] == "scoreform_results_analysis_v1"

    pdf_report = render_results_report_pdf(_confirmed(snapshot, "pdf"))
    text = _pdf_text(pdf_report.artifacts[0].content)
    assert text.index("SYN.C") < text.index("SYN.A") < text.index("SYN.B")


def test_no_workspace_preserves_lexical_durable_id_fallback():
    projection = resolve_results_standards_projection(
        ("STD.C", "STD.A", "STD.B"),
        workspace_root=None,
        standards_profile_id="course_profile",
    )

    assert projection.standard_ids == ("STD.A", "STD.B", "STD.C")
    assert tuple(
        projection.label_for(standard_id)
        for standard_id in projection.standard_ids
    ) == ("STD.A", "STD.B", "STD.C")
