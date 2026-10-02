"""Clean-wheel installed Results Analysis acceptance for ScoreForm Issue #219."""

from __future__ import annotations

import argparse
import csv
import importlib
import io
import json
import sys
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pds_core
from pds_core.standards import (
    StandardDefinition,
    StandardsLibrary,
    StandardsProfile,
    write_workspace_standards_library,
)

from scoreform.generated_output_opening import (
    open_generated_output_file,
    open_generated_output_folder,
)
from scoreform.page_scoring import ScoredAnswer
from scoreform.results import (
    ScoreFormRoutedResult,
    ScoreFormRoutedResultHistoryRow,
)
from scoreform.results_analysis import (
    ATTEMPT_DISPLAY_BASIS,
    STANDARDS_ALIGNMENT_BASIS,
    analyze_class_results,
    analyze_student_attempt,
    select_recent_display_attempts,
    select_student_attempts,
)
from scoreform.results_report_artifacts import (
    RenderedReportArtifact,
    RenderedResultsReport,
)
from scoreform.results_report_csv import render_results_report_csv
from scoreform.results_report_json import render_results_report_json
from scoreform.results_report_output import (
    ResultsReportOutputError,
    install_rendered_results_report,
    plan_results_report_destination,
)
from scoreform.results_report_pdf import render_results_report_pdf
from scoreform.results_reporting import (
    REPORT_CONFIRMATION_TOKEN,
    RESULTS_ANALYSIS_REPORT_SCHEMA,
    ConfirmedResultsReportPlan,
    ReportFormat,
    ResultsReportSnapshot,
    confirm_results_report_plan,
    prepare_results_report_plan,
    prepare_results_report_snapshot,
)
from scoreform.work_paths import scoreform_work_paths

CLASS_ID = "issue219_class"
ASSIGNMENT_ID = "issue219_results"
STUDENT_ALPHA = "student_alpha"
STUDENT_BETA = "student_beta"
PROFILE_ID = "issue219_profile"
GENERATED = datetime(2026, 10, 2, 8, 0, 0, tzinfo=timezone.utc)


class AcceptanceFailure(RuntimeError):
    """Bounded installed Results Analysis acceptance failure."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AcceptanceFailure(message)


def _module_origin(module_name: str) -> Path:
    module = importlib.import_module(module_name)
    module_file = getattr(module, "__file__", None)
    if not isinstance(module_file, str) or not module_file:
        raise AcceptanceFailure(f"{module_name} has no import origin.")
    return Path(module_file).resolve()


def _is_isolated_installed_origin(path: Path, repository: Path) -> bool:
    try:
        resolved = path.resolve()
        return (
            resolved.is_relative_to(Path(sys.prefix).resolve())
            and "site-packages" in {part.lower() for part in resolved.parts}
            and not resolved.is_relative_to(repository.resolve())
        )
    except (OSError, RuntimeError, ValueError):
        return False


def _verify_installed_provenance(
    workspace: Path,
    repository: Path,
    *,
    version: str,
    expected_core_version: str,
) -> None:
    _require(not workspace.exists(), f"workspace must begin absent: {workspace}")
    _require(metadata.version("scoreform") == version, "ScoreForm version mismatch.")
    _require(
        metadata.version("pds-core") == expected_core_version,
        "PDS Core distribution version mismatch.",
    )
    _require(
        getattr(pds_core, "__version__", None) == expected_core_version,
        "PDS Core module/distribution versions disagree.",
    )

    for module_name in (
        "scoreform",
        "scoreform.results_analysis",
        "scoreform.results_reporting",
        "scoreform.results_standard_display",
        "scoreform.results_report_csv",
        "scoreform.results_report_json",
        "scoreform.results_report_pdf",
        "scoreform.results_report_output",
        "scoreform.generated_output_opening",
        "pds_core",
    ):
        origin = _module_origin(module_name)
        _require(
            _is_isolated_installed_origin(origin, repository),
            f"{module_name} did not import from isolated site-packages: {origin}",
        )


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
        source="Installed Synthetic",
        short_name=short_name,
        description=f"{short_name} installed acceptance definition.",
        subject="Synthetic",
        course="Installed Results Analysis",
        active=active,
        available_modules=("scoreform",),
    )


def _library(*, changed: bool = False) -> StandardsLibrary:
    suffix = " CHANGED" if changed else ""
    order = (
        ("STD.A", "STD.C", "STD.B")
        if changed
        else ("STD.C", "STD.A", "STD.B")
    )
    return StandardsLibrary(
        standards=(
            _definition("STD.A", "SYN.A", f"Alpha{suffix}"),
            _definition("STD.B", "SYN.B", f"Beta{suffix}", active=False),
            _definition("STD.C", "SYN.C", f"Gamma{suffix}"),
        ),
        profiles=(
            StandardsProfile(
                profile_id=PROFILE_ID,
                standards=order,
                subject="Synthetic",
                course="Installed Results Analysis",
                title="Installed Results Profile",
            ),
        ),
    )


def _assignment() -> dict[str, object]:
    return {
        "assignment_id": ASSIGNMENT_ID,
        "title": "Installed Results Analysis Qualification",
        "question_count": 5,
        "choices": ["A", "B", "C", "D"],
        "answer_key": {1: "A", 2: "B", 3: "C", 4: "D", 5: "A"},
        "standards": {
            "1": ["STD.A"],
            "2": ["STD.B", "STD.A"],
            "3": [],
            "4": ["STD.C"],
            "5": ["STD.UNKNOWN"],
        },
        "standards_profile_id": PROFILE_ID,
    }


def _row(
    *,
    student_id: str,
    last_name: str,
    first_name: str,
    attempt_number: int,
    timestamp: str,
    answers: tuple[ScoredAnswer, ...],
) -> ScoreFormRoutedResultHistoryRow:
    result = ScoreFormRoutedResult(
        "plain_paper_manual",
        CLASS_ID,
        ASSIGNMENT_ID,
        student_id,
        last_name,
        first_name,
        "1",
        "manual",
        sum(answer.correct for answer in answers),
        len(answers),
        answers,
        source_file="plain_paper_manual_entry",
    )
    return ScoreFormRoutedResultHistoryRow(result, attempt_number, timestamp)


def _history() -> tuple[ScoreFormRoutedResultHistoryRow, ...]:
    return (
        _row(
            student_id=STUDENT_ALPHA,
            last_name="Alpha",
            first_name="Learner",
            attempt_number=1,
            timestamp="2026-10-01T12:00:00+00:00",
            answers=(
                ScoredAnswer(1, "A", True),
                ScoredAnswer(2, "B", True),
                ScoredAnswer(3, "BLANK", False),
                ScoredAnswer(4, "D", True),
                ScoredAnswer(5, "A", True),
            ),
        ),
        _row(
            student_id=STUDENT_ALPHA,
            last_name="Alpha",
            first_name="Learner",
            attempt_number=2,
            timestamp="2026-10-01T13:00:00+00:00",
            answers=(
                ScoredAnswer(1, "B", False),
                ScoredAnswer(2, "B", True),
                ScoredAnswer(3, "AMBIGUOUS", False),
                ScoredAnswer(4, "A", False),
                ScoredAnswer(5, "BLANK", False),
            ),
        ),
        _row(
            student_id=STUDENT_BETA,
            last_name="Beta",
            first_name="Learner",
            attempt_number=1,
            timestamp="2026-10-01T12:30:00+00:00",
            answers=(
                ScoredAnswer(1, "A", True),
                ScoredAnswer(2, "C", False),
                ScoredAnswer(3, "C", True),
                ScoredAnswer(4, "D", True),
                ScoredAnswer(5, "B", False),
            ),
        ),
    )


def _confirmed(
    snapshot: ResultsReportSnapshot,
    output_format: ReportFormat,
) -> ConfirmedResultsReportPlan:
    plan = prepare_results_report_plan(
        snapshot,
        output_format=output_format,
    )
    _require(
        confirm_results_report_plan(plan, "BACK") is None,
        "non-GENERATE confirmation unexpectedly authorized report creation.",
    )
    confirmed = confirm_results_report_plan(plan, REPORT_CONFIRMATION_TOKEN)
    _require(confirmed is not None, "exact GENERATE did not confirm report.")
    return confirmed


def _render(
    confirmed: ConfirmedResultsReportPlan,
) -> RenderedResultsReport:
    output_format = confirmed.plan.output_format
    if output_format == "csv":
        return render_results_report_csv(confirmed)
    if output_format == "json":
        return render_results_report_json(confirmed)
    if output_format == "pdf":
        return render_results_report_pdf(confirmed)
    raise AcceptanceFailure(f"unsupported report format: {output_format}")


def _verify_analysis(
    history: tuple[ScoreFormRoutedResultHistoryRow, ...],
    assignment: dict[str, object],
) -> None:
    selections = select_recent_display_attempts(history)
    by_student = {item.student_id: item for item in selections}
    _require(
        by_student[STUDENT_ALPHA].row.attempt_number == 2,
        "class display basis did not choose the most recent alpha attempt.",
    )
    _require(
        by_student[STUDENT_ALPHA].row.result.score == 1,
        "synthetic recent alpha attempt did not remain lower-scoring.",
    )
    _require(
        history[0].result.score == 4,
        "synthetic older alpha attempt did not remain higher-scoring.",
    )

    analysis = analyze_class_results(history, assignment, class_id=CLASS_ID)
    _require(
        analysis.attempt_basis == ATTEMPT_DISPLAY_BASIS,
        "class analysis changed the documented display-attempt basis.",
    )
    _require(
        analysis.standards_basis == STANDARDS_ALIGNMENT_BASIS,
        "class analysis changed the current-alignment basis.",
    )
    _require(
        analysis.students_represented == 2,
        "class analysis represented an unexpected student count.",
    )

    q3 = analysis.questions[2]
    _require(
        (q3.correct, q3.incorrect, q3.blank, q3.ambiguous, q3.total)
        == (1, 0, 0, 1, 2),
        "Q3 blank/ambiguous descriptive counts changed.",
    )
    q5 = analysis.questions[4]
    _require(
        (q5.correct, q5.incorrect, q5.blank, q5.ambiguous, q5.total)
        == (0, 1, 1, 0, 2),
        "Q5 blank/incorrect descriptive counts changed.",
    )
    q3_distribution = {
        item.response: item.count for item in q3.response_distribution
    }
    _require(
        q3_distribution["C"] == 1
        and q3_distribution["AMBIGUOUS"] == 1,
        "Q3 response distribution changed.",
    )

    standards = {item.standard_id: item for item in analysis.standards}
    _require(
        (standards["STD.A"].correct, standards["STD.A"].responses) == (2, 4),
        "multi-Standard STD.A aggregation changed.",
    )
    _require(
        (standards["STD.B"].correct, standards["STD.B"].responses) == (1, 2),
        "STD.B aggregation changed.",
    )
    _require(
        (standards["STD.C"].correct, standards["STD.C"].responses) == (1, 2),
        "STD.C aggregation changed.",
    )
    _require(
        (
            standards["STD.UNKNOWN"].correct,
            standards["STD.UNKNOWN"].responses,
        )
        == (0, 2),
        "unknown aligned Standard aggregation changed.",
    )
    _require(
        (analysis.unaligned.correct, analysis.unaligned.responses) == (1, 2),
        "unaligned reconciliation changed.",
    )

    alpha_attempts = select_student_attempts(history, STUDENT_ALPHA)
    _require(
        tuple(row.attempt_number for row in alpha_attempts) == (1, 2),
        "preserved alpha attempts were not returned chronologically.",
    )
    detail = analyze_student_attempt(
        alpha_attempts[0],
        assignment,
        class_id=CLASS_ID,
        attempt_count=len(alpha_attempts),
    )
    _require(
        detail.attempt_number == 1 and detail.score == 4,
        "explicit historical Student Detail did not preserve attempt 1.",
    )
    _require(
        tuple(item.outcome for item in detail.questions)
        == ("correct", "correct", "blank", "correct", "correct"),
        "Student Detail response-state interpretation changed.",
    )


def _verify_reports_and_custody(
    workspace: Path,
    history: tuple[ScoreFormRoutedResultHistoryRow, ...],
    assignment: dict[str, object],
) -> None:
    paths = scoreform_work_paths(workspace, CLASS_ID, ASSIGNMENT_ID)
    paths.work_root.mkdir(parents=True, exist_ok=True)
    standards_path = workspace / "standards" / "library.json"

    snapshot = prepare_results_report_snapshot(
        history,
        assignment,
        class_id=CLASS_ID,
        scope="class_analysis",
        generated_at=GENERATED,
        workspace_root=workspace,
    )
    _require(
        snapshot.schema_version == RESULTS_ANALYSIS_REPORT_SCHEMA
        == "scoreform_results_analysis_v1",
        "class report schema identity changed.",
    )
    _require(
        snapshot.standards_projection.standard_ids
        == ("STD.C", "STD.A", "STD.B", "STD.UNKNOWN"),
        "current profile presentation order/fallback changed.",
    )
    _require(
        snapshot.standards_projection.label_for("STD.A")
        == "SYN.A | Alpha | Installed Synthetic",
        "teacher-readable STD.A label changed.",
    )
    _require(
        snapshot.standards_projection.label_for("STD.B")
        == "SYN.B | Beta | Installed Synthetic [inactive]",
        "inactive Standard label changed.",
    )
    _require(
        snapshot.standards_projection.label_for("STD.UNKNOWN")
        == "STD.UNKNOWN",
        "unknown Standard did not fall back to durable identity.",
    )

    write_workspace_standards_library(
        workspace,
        _library(changed=True),
        overwrite=True,
    )

    before_planning = {
        path.relative_to(workspace) for path in workspace.rglob("*")
    }
    rendered_by_format: dict[ReportFormat, RenderedResultsReport] = {}
    destinations = {}
    for output_format in ("csv", "json", "pdf"):
        typed_format: ReportFormat = output_format
        confirmed = _confirmed(snapshot, typed_format)
        rendered_by_format[typed_format] = _render(confirmed)
        destinations[typed_format] = plan_results_report_destination(
            workspace,
            class_id=CLASS_ID,
            assignment_id=ASSIGNMENT_ID,
            snapshot=snapshot,
            output_format=typed_format,
        )

    after_planning = {
        path.relative_to(workspace) for path in workspace.rglob("*")
    }
    _require(
        before_planning == after_planning,
        "report destination planning performed filesystem writes.",
    )
    _require(
        len({item.report_dir for item in destinations.values()}) == 3,
        "cross-format same-second destinations still collide.",
    )

    for output_format, destination in destinations.items():
        _require(
            destination.report_dir.name
            == f"class_analysis_{output_format}_20261002T080000Z",
            f"{output_format} destination identity changed.",
        )
        path_text = destination.workspace_relative_dir.as_posix()
        for private in (STUDENT_ALPHA, STUDENT_BETA, "Alpha", "Beta"):
            _require(
                private not in path_text,
                "class report destination leaked student identity.",
            )

    csv_report = rendered_by_format["csv"]
    csv_text = csv_report.artifact("standards_analysis.csv").content.decode(
        "utf-8"
    )
    rows = list(csv.DictReader(io.StringIO(csv_text)))
    _require(
        [row["standard_id"] for row in rows]
        == ["STD.C", "STD.A", "STD.B", "STD.UNKNOWN"],
        "CSV Standards order changed.",
    )
    _require(
        rows[1]["display_label"] == "SYN.A | Alpha | Installed Synthetic",
        "CSV did not preserve frozen pre-edit display label.",
    )
    csv_filenames = tuple(
        artifact.filename for artifact in csv_report.artifacts
    )
    _require(
        "student_responses.csv" not in csv_filenames,
        "class CSV report unexpectedly included full student response rows.",
    )
    overview_text = csv_report.artifact(
        "assignment_overview.csv"
    ).content.decode("utf-8")
    overview_rows = list(csv.DictReader(io.StringIO(overview_text)))
    _require(
        [row["student_id"] for row in overview_rows]
        == [STUDENT_ALPHA, STUDENT_BETA],
        "class CSV assignment overview changed student identity/order.",
    )
    _require(
        [row["attempt_number"] for row in overview_rows] == ["2", "1"],
        "class CSV assignment overview changed recent-attempt selection.",
    )

    json_report = rendered_by_format["json"]
    payload = json.loads(
        json_report.artifact("results_analysis.json").content
    )
    _require(
        payload["schema_version"] == "scoreform_results_analysis_v1",
        "JSON schema version changed.",
    )
    json_standards = payload["class_analysis"]["standards_analysis"]
    _require(
        [item["standard_id"] for item in json_standards]
        == ["STD.C", "STD.A", "STD.B", "STD.UNKNOWN"],
        "JSON Standards order changed.",
    )
    _require(
        json_standards[1]["display_label"]
        == "SYN.A | Alpha | Installed Synthetic",
        "JSON did not preserve frozen pre-edit display label.",
    )
    json_overview = payload["class_analysis"]["assignment_overview"]
    _require(
        [row["student_id"] for row in json_overview]
        == [STUDENT_ALPHA, STUDENT_BETA],
        "class JSON assignment overview changed student identity/order.",
    )
    _require(
        [row["attempt_number"] for row in json_overview] == [2, 1],
        "class JSON assignment overview changed recent-attempt selection.",
    )
    _require(
        all("questions" not in row for row in json_overview),
        "class JSON assignment overview exposed per-question student detail.",
    )
    _require(
        "student_detail" not in payload,
        "class JSON report unexpectedly included student_detail.",
    )
    _require(
        payload["report_basis"]["include_individual_response_rows"] is False,
        "class JSON report changed its individual-response privacy basis.",
    )

    pdf = rendered_by_format["pdf"].artifact("results_analysis.pdf").content
    _require(
        pdf.startswith(b"%PDF-") and len(pdf) > 1000,
        "PDF renderer did not produce a substantive PDF artifact.",
    )

    installed_json = install_rendered_results_report(
        destinations["json"],
        json_report,
    )
    installed_csv = install_rendered_results_report(
        destinations["csv"],
        csv_report,
    )
    installed_pdf = install_rendered_results_report(
        destinations["pdf"],
        rendered_by_format["pdf"],
    )
    _require(
        len(installed_json.workspace_relative_files) == 1
        and len(installed_csv.workspace_relative_files) == 6
        and len(installed_pdf.workspace_relative_files) == 1,
        "installed report artifact counts changed.",
    )

    try:
        plan_results_report_destination(
            workspace,
            class_id=CLASS_ID,
            assignment_id=ASSIGNMENT_ID,
            snapshot=snapshot,
            output_format="json",
        )
    except ResultsReportOutputError:
        pass
    else:
        raise AcceptanceFailure(
            "same-format/same-second replay did not fail create-only."
        )

    student_snapshot = prepare_results_report_snapshot(
        history,
        assignment,
        class_id=CLASS_ID,
        scope="student_detail",
        generated_at=datetime(2026, 10, 2, 8, 1, 0, tzinfo=timezone.utc),
        student_id=STUDENT_ALPHA,
        attempt_number=1,
        workspace_root=workspace,
    )
    detail = student_snapshot.student_detail
    _require(
        detail is not None
        and detail.attempt_number == 1
        and detail.score == 4,
        "student report snapshot did not preserve requested historical attempt.",
    )
    student_json = _render(_confirmed(student_snapshot, "json"))
    student_payload = json.loads(
        student_json.artifact("results_analysis.json").content
    )
    _require(
        student_payload["student_detail"]["attempt_number"] == 1,
        "student JSON report changed exact attempt selection.",
    )

    mismatch_destination = plan_results_report_destination(
        workspace,
        class_id=CLASS_ID,
        assignment_id=ASSIGNMENT_ID,
        snapshot=student_snapshot,
        output_format="csv",
    )
    try:
        install_rendered_results_report(mismatch_destination, student_json)
    except ResultsReportOutputError:
        pass
    else:
        raise AcceptanceFailure(
            "rendered-format/destination-format mismatch was accepted."
        )
    _require(
        not mismatch_destination.report_dir.exists(),
        "format mismatch created a report directory.",
    )

    cleanup_snapshot = prepare_results_report_snapshot(
        history,
        assignment,
        class_id=CLASS_ID,
        scope="class_analysis",
        generated_at=datetime(2026, 10, 2, 8, 2, 0, tzinfo=timezone.utc),
        workspace_root=workspace,
    )
    cleanup_destination = plan_results_report_destination(
        workspace,
        class_id=CLASS_ID,
        assignment_id=ASSIGNMENT_ID,
        snapshot=cleanup_snapshot,
        output_format="csv",
    )
    synthetic = RenderedResultsReport(
        output_format="csv",
        scope="class_analysis",
        artifacts=(
            RenderedReportArtifact(
                filename="first.csv",
                media_type="text/csv",
                content=b"first\n",
            ),
            RenderedReportArtifact(
                filename="second.csv",
                media_type="text/csv",
                content=b"second\n",
            ),
        ),
    )
    real_path_open = Path.open

    def fail_second_open(
        path: Path,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        if path.name == "second.csv":
            raise OSError("synthetic second-artifact failure")
        return real_path_open(path, *args, **kwargs)

    try:
        with patch.object(Path, "open", new=fail_second_open):
            install_rendered_results_report(cleanup_destination, synthetic)
    except ResultsReportOutputError:
        pass
    else:
        raise AcceptanceFailure(
            "synthetic partial-write failure unexpectedly succeeded."
        )
    _require(
        not cleanup_destination.report_dir.exists(),
        "partial report directory survived cleanup.",
    )

    opened: list[Path] = []

    def fake_open(path: str | Path) -> Path:
        resolved = Path(path).resolve(strict=True)
        opened.append(resolved)
        return resolved

    with patch(
        "scoreform.generated_output_opening.open_local_path",
        new=fake_open,
    ):
        opened_file = open_generated_output_file(
            workspace,
            installed_json.workspace_relative_files[0],
        )
        opened_folder = open_generated_output_folder(
            workspace,
            installed_json.destination.workspace_relative_dir,
        )
    _require(
        opened == [opened_file, opened_folder],
        "local-open boundary did not receive the exact created file/folder.",
    )

    _require(
        not paths.results_path.exists(),
        "Results Analysis acceptance unexpectedly created results.csv.",
    )
    _require(
        standards_path.is_file(),
        "synthetic Standards Library disappeared during reporting.",
    )


def run_acceptance(
    *,
    workspace: Path,
    repository: Path,
    version: str,
    expected_core_version: str,
) -> dict[str, object]:
    workspace = workspace.resolve()
    repository = repository.resolve(strict=True)
    _verify_installed_provenance(
        workspace,
        repository,
        version=version,
        expected_core_version=expected_core_version,
    )
    write_workspace_standards_library(workspace, _library())

    history = _history()
    assignment = _assignment()
    _verify_analysis(history, assignment)
    _verify_reports_and_custody(workspace, history, assignment)

    return {
        "scoreform_version": version,
        "core_version": expected_core_version,
        "schema_version": RESULTS_ANALYSIS_REPORT_SCHEMA,
        "attempt_basis": ATTEMPT_DISPLAY_BASIS,
        "standards_basis": STANDARDS_ALIGNMENT_BASIS,
        "formats": ["csv", "json", "pdf"],
        "results_analysis_installed_acceptance": "passed",
        "local_open": "mocked_boundary_passed",
        "physical_acceptance": "not_claimed",
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--repository", required=True, type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--expected-core-version", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    options = _parse_args(argv)
    try:
        result = run_acceptance(
            workspace=options.workspace,
            repository=options.repository,
            version=options.version,
            expected_core_version=options.expected_core_version,
        )
    except (
        AcceptanceFailure,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
    ) as error:
        print(
            f"Installed Results Analysis acceptance failed: {error}",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
