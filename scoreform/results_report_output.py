"""Create-only local output custody for ScoreForm results reports."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from scoreform.results_report_artifacts import RenderedResultsReport
from scoreform.results_reporting import ReportFormat, ResultsReportSnapshot
from scoreform.work_paths import scoreform_work_paths

RESULTS_ANALYSIS_EXPORT_DIR = "results_analysis"


class ResultsReportOutputError(RuntimeError):
    """Raised when a rendered report cannot be installed safely."""


@dataclass(frozen=True, slots=True)
class ResultsReportDestination:
    """One planned assignment-local report directory."""

    workspace_root: Path
    report_dir: Path
    workspace_relative_dir: Path
    scope: str
    output_format: ReportFormat
    generated_at: str

    def __post_init__(self) -> None:
        if not self.workspace_root.is_absolute():
            raise ValueError("workspace_root must be absolute.")
        if not self.report_dir.is_absolute():
            raise ValueError("report_dir must be absolute.")
        if self.workspace_relative_dir.is_absolute():
            raise ValueError("workspace_relative_dir must be relative.")
        if self.scope not in {"class_analysis", "student_detail"}:
            raise ValueError("Unsupported report destination scope.")
        if self.output_format not in {"csv", "json", "pdf"}:
            raise ValueError("Unsupported report destination format.")
        if not isinstance(self.generated_at, str) or not self.generated_at:
            raise ValueError("generated_at must be a nonempty string.")


@dataclass(frozen=True, slots=True)
class InstalledResultsReport:
    """Paths installed by one successful create-only report operation."""

    destination: ResultsReportDestination
    workspace_relative_files: tuple[Path, ...]

    def __post_init__(self) -> None:
        if not self.workspace_relative_files:
            raise ValueError("Installed report must contain at least one file.")
        if any(path.is_absolute() for path in self.workspace_relative_files):
            raise ValueError("Installed report file paths must be workspace-relative.")


def _timestamp_token(generated_at: str) -> str:
    value = generated_at
    for character in "-:":
        value = value.replace(character, "")
    if not value.endswith("Z") or "T" not in value:
        raise ResultsReportOutputError(
            "Report generated timestamp is not a canonical UTC timestamp."
        )
    token = value.replace(".", "")
    if not token.replace("T", "").replace("Z", "").isdigit():
        raise ResultsReportOutputError(
            "Report generated timestamp is not safe for a report directory."
        )
    return token


def _validate_managed_work_root(work_root: Path) -> None:
    if work_root.is_symlink() or not work_root.is_dir():
        raise ResultsReportOutputError(
            f"Managed assignment work directory is unavailable: {work_root}"
        )


def plan_results_report_destination(
    workspace_root: str | Path,
    *,
    class_id: str,
    assignment_id: str,
    snapshot: ResultsReportSnapshot,
    output_format: ReportFormat,
) -> ResultsReportDestination:
    """Plan one privacy-minimized create-only destination without writing."""
    if not isinstance(snapshot, ResultsReportSnapshot):
        raise ResultsReportOutputError(
            "Report destination planning requires a ResultsReportSnapshot."
        )
    if snapshot.class_id != class_id:
        raise ResultsReportOutputError(
            "Report snapshot class does not match selected assignment."
        )
    if snapshot.assignment.assignment_id != assignment_id:
        raise ResultsReportOutputError(
            "Report snapshot assignment does not match selected assignment."
        )
    if output_format not in {"csv", "json", "pdf"}:
        raise ResultsReportOutputError(
            "Report destination format is unsupported."
        )

    root = Path(workspace_root).expanduser().resolve(strict=False)
    paths = scoreform_work_paths(root, class_id, assignment_id)
    _validate_managed_work_root(paths.work_root)

    token = _timestamp_token(snapshot.generated_at)
    report_dir = (
        paths.exports_dir
        / RESULTS_ANALYSIS_EXPORT_DIR
        / f"{snapshot.scope}_{output_format}_{token}"
    )
    try:
        relative = report_dir.relative_to(root)
    except ValueError as error:
        raise ResultsReportOutputError(
            "Planned report destination escaped the workspace root."
        ) from error

    if report_dir.exists() or report_dir.is_symlink():
        raise ResultsReportOutputError(
            "A report already exists at the planned destination. "
            "Run export again to prepare a new timestamped report."
        )

    return ResultsReportDestination(
        workspace_root=root,
        report_dir=report_dir,
        workspace_relative_dir=relative,
        scope=snapshot.scope,
        output_format=output_format,
        generated_at=snapshot.generated_at,
    )


def _prepare_parent_directory(
    path: Path,
    *,
    created_parents: list[Path],
) -> None:
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_dir():
            raise ResultsReportOutputError(
                f"Report parent is not a regular directory: {path}"
            )
        return

    parent = path.parent
    if not parent.exists():
        _prepare_parent_directory(parent, created_parents=created_parents)
    elif parent.is_symlink() or not parent.is_dir():
        raise ResultsReportOutputError(
            f"Report parent is not a regular directory: {parent}"
        )

    try:
        path.mkdir()
    except FileExistsError:
        if path.is_symlink() or not path.is_dir():
            raise ResultsReportOutputError(
                f"Report parent became an incompatible filesystem entry: {path}"
            )
    except OSError as error:
        raise ResultsReportOutputError(
            f"Could not create report parent directory {path}: {error}"
        ) from error
    else:
        created_parents.append(path)


def _cleanup_empty_parents(created_parents: list[Path]) -> None:
    for path in reversed(created_parents):
        try:
            path.rmdir()
        except OSError:
            pass


def install_rendered_results_report(
    destination: ResultsReportDestination,
    rendered: RenderedResultsReport,
) -> InstalledResultsReport:
    """Install exactly one rendered report set with create-only semantics."""
    if not isinstance(destination, ResultsReportDestination):
        raise ResultsReportOutputError(
            "Report installation requires a ResultsReportDestination."
        )
    if not isinstance(rendered, RenderedResultsReport):
        raise ResultsReportOutputError(
            "Report installation requires a RenderedResultsReport."
        )
    if rendered.scope != destination.scope:
        raise ResultsReportOutputError(
            "Rendered report scope does not match planned destination."
        )
    if rendered.output_format != destination.output_format:
        raise ResultsReportOutputError(
            "Rendered report format does not match planned destination."
        )

    created_parents: list[Path] = []
    created_files: list[Path] = []
    created_report_dir = False
    results_root = destination.report_dir.parent

    try:
        _prepare_parent_directory(
            results_root,
            created_parents=created_parents,
        )

        try:
            destination.report_dir.mkdir()
        except FileExistsError as error:
            raise ResultsReportOutputError(
                "Report destination already exists; existing reports are never "
                "overwritten."
            ) from error
        except OSError as error:
            raise ResultsReportOutputError(
                f"Could not create report destination: {error}"
            ) from error
        created_report_dir = True

        for artifact in rendered.artifacts:
            target = destination.report_dir / artifact.filename
            if target.parent != destination.report_dir:
                raise ResultsReportOutputError(
                    "Rendered report artifact escaped the report directory."
                )
            try:
                with target.open("xb") as output:
                    created_files.append(target)
                    output.write(artifact.content)
                    output.flush()
                    os.fsync(output.fileno())
            except FileExistsError as error:
                raise ResultsReportOutputError(
                    f"Report artifact already exists and was not overwritten: "
                    f"{artifact.filename}"
                ) from error
            except OSError as error:
                raise ResultsReportOutputError(
                    f"Could not write report artifact {artifact.filename}: {error}"
                ) from error

        relative_files = tuple(
            target.relative_to(destination.workspace_root)
            for target in created_files
        )
        return InstalledResultsReport(
            destination=destination,
            workspace_relative_files=relative_files,
        )
    except Exception:
        for path in reversed(created_files):
            try:
                path.unlink()
            except OSError:
                pass
        if created_report_dir:
            try:
                destination.report_dir.rmdir()
            except OSError:
                pass
        _cleanup_empty_parents(created_parents)
        raise
