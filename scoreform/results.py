import csv
import datetime
import json
import ntpath
import os
import re
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Literal, cast

from pds_core.identifiers import validate_identifier as validate_core_identifier
from pds_core.routes import (
    class_roster_path as core_class_roster_path,
)

from scoreform import workspace
from scoreform.answer_sheet_records import (
    validate_artifact_id,
    validate_generation_id,
    validate_issuance_id,
    validate_page_id,
)
from scoreform.answer_sheet_routes import validate_route_id
from scoreform.assignment import load_assignment
from scoreform.folders import ensure_parent_dir
from scoreform.module_errors import (
    ScoreFormRoutedResultIntegrityError,
    ScoreFormRoutedResultReadError,
    ScoreFormRoutedResultValidationError,
    ScoreFormRoutedResultWriteError,
)
from scoreform.page_scoring import ScoredAnswer
from scoreform.retained_page import (
    SUPPORTED_RETAINED_SOURCE_EXTENSIONS,
    validate_canonical_retained_source_relative_path,
)
from scoreform.validation import validate_identifier
from scoreform.work_paths import scoreform_work_paths

ROUTED_RESULTS_SCHEMA_VERSION = "2"
RESULT_ORIGINS = frozenset({"pds2_scan", "plain_paper_manual", "legacy_scan"})
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class ScoreFormRoutedResult:
    result_origin: Literal["pds2_scan", "plain_paper_manual", "legacy_scan"]
    class_id: str
    assignment_id: str
    student_id: str
    last_name: str
    first_name: str
    period: str
    page_display: str
    score: int
    total_points: int
    answers: tuple[ScoredAnswer, ...]
    issuance_id: str | None = None
    generation_id: str | None = None
    artifact_id: str | None = None
    page_ids: tuple[str, ...] = ()
    route_ids: tuple[str, ...] = ()
    logical_pages: tuple[int, ...] = ()
    source_file: str = ""
    source_scan_id: str | None = None
    source_page_numbers: tuple[int, ...] = ()
    retained_source_relative_path: str | None = None
    source_sha256: str | None = None

    def __post_init__(self) -> None:
        validate_routed_result(self)


def _single_line(value: object, *, nonempty: bool = False) -> bool:
    return (
        isinstance(value, str)
        and (bool(value) or not nonempty)
        and all(ord(character) >= 32 and ord(character) != 127 for character in value)
    )


def validate_routed_result(result: ScoreFormRoutedResult) -> ScoreFormRoutedResult:
    if not isinstance(result, ScoreFormRoutedResult):
        raise ScoreFormRoutedResultValidationError("Wrong routed-result model type.")
    if result.result_origin not in RESULT_ORIGINS:
        raise ScoreFormRoutedResultValidationError("Unsupported result_origin.")
    try:
        validate_core_identifier(result.class_id, "class_id")
        validate_core_identifier(result.assignment_id, "assignment_id")
        validate_core_identifier(result.student_id, "student_id")
    except Exception as error:
        raise ScoreFormRoutedResultValidationError("Invalid routed identity.") from error
    if any(not _single_line(value) for value in (result.last_name, result.first_name, result.period)):
        raise ScoreFormRoutedResultValidationError("Student display fields must be control-free single-line strings.")
    if not _single_line(result.page_display, nonempty=True) or not _single_line(result.source_file):
        raise ScoreFormRoutedResultValidationError("Page and source display fields are invalid.")
    for name, value in (("score", result.score), ("total_points", result.total_points)):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ScoreFormRoutedResultValidationError(f"{name} must be an integer.")
    if result.total_points < 1 or not 0 <= result.score <= result.total_points:
        raise ScoreFormRoutedResultValidationError("Score or total is out of range.")
    if not isinstance(result.answers, tuple) or any(not isinstance(answer, ScoredAnswer) for answer in result.answers):
        raise ScoreFormRoutedResultValidationError("answers must be immutable ScoredAnswer values.")
    if any(
        isinstance(answer.question_number, bool)
        or not isinstance(answer.question_number, int)
        or not isinstance(answer.selected_answer, str)
        or answer.selected_answer not in {"A", "B", "C", "D", "BLANK", "AMBIGUOUS"}
        or not isinstance(answer.correct, bool)
        for answer in result.answers
    ):
        raise ScoreFormRoutedResultValidationError("answers contain invalid typed values.")
    numbers = tuple(answer.question_number for answer in result.answers)
    if numbers != tuple(range(1, result.total_points + 1)):
        raise ScoreFormRoutedResultValidationError("answers must cover the result total exactly in order.")
    if any(not isinstance(answer.correct, bool) for answer in result.answers) or result.score != sum(answer.correct for answer in result.answers):
        raise ScoreFormRoutedResultValidationError("Score and answer correctness disagree.")
    tuple_fields = (result.page_ids, result.route_ids, result.logical_pages, result.source_page_numbers)
    if any(not isinstance(value, tuple) for value in tuple_fields):
        raise ScoreFormRoutedResultValidationError("Provenance collections must be tuples.")
    if result.result_origin == "pds2_scan":
        try:
            validate_issuance_id(result.issuance_id)
            validate_generation_id(result.generation_id)
            validate_artifact_id(result.artifact_id)
            validate_core_identifier(result.source_scan_id, "source_scan_id")
            for page_id in result.page_ids:
                validate_page_id(page_id)
            for route_id in result.route_ids:
                validate_route_id(route_id)
        except Exception as error:
            raise ScoreFormRoutedResultValidationError("Invalid PDS2 provenance identity.") from error
        length = len(result.page_ids)
        if length < 1 or not (length == len(result.route_ids) == len(result.logical_pages) == len(result.source_page_numbers)):
            raise ScoreFormRoutedResultValidationError("PDS2 provenance collections must be nonempty and aligned.")
        if len(set(result.page_ids)) != length or len(set(result.route_ids)) != length or len(set(result.source_page_numbers)) != length:
            raise ScoreFormRoutedResultValidationError("PDS2 provenance collections must not contain duplicates.")
        if result.logical_pages != tuple(range(1, length + 1)):
            raise ScoreFormRoutedResultValidationError("PDS2 logical pages must be complete and ordered.")
        if any(isinstance(number, bool) or not isinstance(number, int) or number < 1 for number in result.source_page_numbers):
            raise ScoreFormRoutedResultValidationError("Source page numbers must be positive integers.")
        retained_path = result.retained_source_relative_path or ""
        if not isinstance(result.source_sha256, str) or not _SHA256.fullmatch(result.source_sha256):
            raise ScoreFormRoutedResultValidationError("source_sha256 is invalid.")
        if (
            not result.source_file
            or result.source_file != result.source_file.strip()
            or ntpath.basename(result.source_file) != result.source_file
            or "/" in result.source_file
            or "\\" in result.source_file
            or Path(result.source_file).suffix.lower() not in SUPPORTED_RETAINED_SOURCE_EXTENSIONS
        ):
            raise ScoreFormRoutedResultValidationError("PDS2 source_file must be a filename only.")
        try:
            validate_canonical_retained_source_relative_path(
                retained_path,
                expected_extension=Path(result.source_file).suffix,
            )
        except (TypeError, ValueError) as error:
            raise ScoreFormRoutedResultValidationError(
                "Retained source path must use canonical scans/source/YYYY-MM-DD/<filename>."
            ) from error
        if result.page_display != ",".join(str(number) for number in result.source_page_numbers):
            raise ScoreFormRoutedResultValidationError(
                "PDS2 page_display must exactly summarize source pages."
            )
    elif any((result.issuance_id, result.generation_id, result.artifact_id, result.page_ids, result.route_ids, result.logical_pages, result.source_scan_id, result.source_page_numbers, result.retained_source_relative_path, result.source_sha256)):
        raise ScoreFormRoutedResultValidationError("Manual and legacy results cannot fabricate PDS2 provenance.")
    if result.result_origin == "plain_paper_manual" and (result.page_display != "manual" or result.source_file != "plain_paper_manual_entry"):
        raise ScoreFormRoutedResultValidationError("Manual result markers are invalid.")
    if result.result_origin == "legacy_scan" and result.source_file:
        windows_source = PureWindowsPath(result.source_file)
        if (
            windows_source.is_absolute()
            or windows_source.drive
            or result.source_file.startswith("/")
            or ".." in PurePosixPath(result.source_file).parts
            or "\\" in result.source_file
        ):
            raise ScoreFormRoutedResultValidationError(
                "Legacy source_file must be empty or a privacy-safe relative value."
            )
    return result


def privacy_safe_source_file(source_file, workspace_root=None):
    """Return a workspace-relative source path or a basename-only fallback."""
    if source_file is None:
        return ""

    try:
        raw_path = os.fspath(source_file)
    except TypeError:
        return ""
    if isinstance(raw_path, bytes):
        raw_path = os.fsdecode(raw_path)
    raw_path = raw_path.strip()
    if not raw_path:
        return ""

    basename = ntpath.basename(raw_path.rstrip("/\\"))
    if not basename:
        return ""
    if workspace_root is None:
        return basename

    source_path = None
    try:
        source_path = Path(raw_path).expanduser()
        if source_path.is_absolute():
            root_path = Path(workspace_root).expanduser()
            if not root_path.is_absolute():
                root_path = Path.cwd() / root_path
            relative_path = source_path.resolve(strict=False).relative_to(
                root_path.resolve(strict=False)
            )
            return relative_path.as_posix()
    except (OSError, RuntimeError, TypeError, ValueError):
        pass

    if ntpath.isabs(raw_path):
        return basename
    if source_path is None:
        return basename
    if ".." in source_path.parts:
        return basename
    return source_path.as_posix()


def _get_max_question_count(results):
    """Return the maximum question number seen across a list of results."""
    max_question = 0
    for res in results:
        for ans in res.get("answers", []):
            q_num = ans.get("Q")
            if isinstance(q_num, int) and q_num > max_question:
                max_question = q_num
    return max_question


def _routed_headers(question_count):
    headers = [
        "Page",
        "class_id",
        "assignment_id",
        "student_id",
        "last_name",
        "first_name",
        "period",
        "source_file",
        "attempt_number",
        "scan_timestamp",
        "Score",
        "Total",
    ]

    for i in range(1, question_count + 1):
        headers.append(f"Q{i}")
        headers.append(f"Q{i}_Correct")

    return headers


def _routed_header_question_count(fieldnames):
    base_headers = _routed_headers(0)

    if not fieldnames:
        return None
    if fieldnames[: len(base_headers)] != base_headers:
        return None

    question_fields = fieldnames[len(base_headers) :]
    if len(question_fields) % 2 != 0:
        return None

    question_count = len(question_fields) // 2
    if fieldnames != _routed_headers(question_count):
        return None

    return question_count


def _print_routed_results_permission_error(output_file, operation, error):
    print(f"Error: Could not {operation} routed results at:")
    print(output_file)
    print()
    print(
        "The file may be open or locked by Excel, OneDrive, a preview pane, "
        "or another process."
    )
    print("Close the file, wait for sync to finish, and try again.")
    print()
    print(f"Technical detail: {error}")


def _read_existing_routed_results(output_file):
    """Read and validate an existing routed results CSV."""
    try:
        with open(output_file, mode="r", newline="", encoding="utf-8") as csv_file:
            reader = csv.DictReader(csv_file, strict=True)
            question_count = _routed_header_question_count(reader.fieldnames)
            if question_count is None:
                print(
                    f"Error: Existing routed results file has incompatible headers: "
                    f"{output_file}"
                )
                return None, None

            rows = []
            for row in reader:
                if None in row or any(value is None for value in row.values()):
                    print(
                        f"Error: Existing routed results file has malformed rows: "
                        f"{output_file}"
                    )
                    return None, None
                rows.append(row)
            return rows, question_count
    except PermissionError as e:
        _print_routed_results_permission_error(output_file, "read", e)
        return None, None
    except csv.Error as e:
        print(f"Error: Existing routed results file is not valid CSV {output_file}: {e}")
        return None, None
    except Exception as e:
        print(f"Error: Could not read existing routed results file {output_file}: {e}")
        return None, None


def _write_routed_results_safely(output_file, headers, rows):
    """Write routed results via same-directory temp file and atomic replace."""
    output_dir = os.path.dirname(output_file) or "."
    temp_path = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            newline="",
            encoding="utf-8",
            dir=output_dir,
            prefix=".results.",
            suffix=".tmp",
            delete=False,
        ) as csv_file:
            temp_path = csv_file.name
            writer = csv.DictWriter(csv_file, fieldnames=headers)
            writer.writeheader()
            writer.writerows(rows)
            csv_file.flush()
            os.fsync(csv_file.fileno())

        os.replace(temp_path, output_file)
        temp_path = None
        return True
    except PermissionError as e:
        _print_routed_results_permission_error(output_file, "write", e)
    except Exception as e:
        print(f"Error writing routed results to {output_file}: {e}")

    if temp_path and os.path.exists(temp_path):
        try:
            os.remove(temp_path)
        except Exception as cleanup_error:
            print(
                f"Warning: Could not remove temporary routed results file "
                f"{temp_path}: {cleanup_error}"
            )
            print(f"Temporary routed results file remains at: {temp_path}")
    return False


def export_to_csv(all_results, output_file, workspace_root=None):
    """Exports structured scoring data to a CSV file.
    
    Includes metadata columns (class_id, assignment_id, student_id) when present
    in the result data.
    
    Returns True on success, False on failure.
    """
    if not all_results:
        print("No results to export.")
        return False
    if workspace_root is None:
        workspace_root = workspace.get_scoreform_workspace_root()

    # Define the CSV headers - start with Page
    headers = ["Page"]
    
    # Check if any results have metadata; if so, include metadata columns
    has_metadata = any(
        "class_id" in res or "assignment_id" in res or "student_id" in res
        for res in all_results
    )
    # Check if any results include source_file
    has_source = any("source_file" in res for res in all_results)
    
    if has_metadata:
        headers.extend(["class_id", "assignment_id", "student_id"])
    if has_source:
        headers.append("source_file")
    
    # Add score fields
    headers.extend(["Score", "Total"])
    
    # Add question fields
    question_count = _get_max_question_count(all_results)
    for i in range(1, question_count + 1):
        headers.append(f"Q{i}")
        headers.append(f"Q{i}_Correct")

    try:
        ensure_parent_dir(output_file)

        with open(output_file, mode="w", newline="", encoding="utf-8") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=headers)
            writer.writeheader()

            for res in all_results:
                row = {
                    "Page": res["page_num"],
                    "Score": res["score"],
                    "Total": res["total_points"],
                }
                
                # Add metadata if present
                if has_metadata:
                    row["class_id"] = res.get("class_id", "")
                    row["assignment_id"] = res.get("assignment_id", "")
                    row["student_id"] = res.get("student_id", "")
                # Add source file if present
                if has_source:
                    row["source_file"] = privacy_safe_source_file(
                        res.get("source_file", ""),
                        workspace_root=workspace_root,
                    )
                
                # Add answer details
                for ans in res["answers"]:
                    q_num = ans["Q"]
                    row[f"Q{q_num}"] = ans["Answer"]
                    row[f"Q{q_num}_Correct"] = ans["Correct"]

                writer.writerow(row)

        print(f"Results successfully exported to {output_file}")
        return True
    except Exception as e:
        print(f"Error exporting to CSV: {e}")
        return False


def _enrich_results_with_roster(all_results, workspace_root=None):
    """Attach roster-derived fields to results in place.

    Adds `last_name`, `first_name`, and `period` to each result dict when possible.
    Returns True if at least one roster was successfully loaded, False otherwise.
    """
    if not all_results:
        return False

    # Group results by class_id for efficient roster loading
    by_class = {}
    for res in all_results:
        class_id = res.get("class_id")
        if not class_id:
            print(f"Warning: result missing class_id for page {res.get('page_num')}")
            # Ensure fields exist
            res.setdefault("last_name", "")
            res.setdefault("first_name", "")
            res.setdefault("period", "")
            continue
        by_class.setdefault(class_id, []).append(res)

    any_loaded = False
    if workspace_root is None:
        workspace_root = workspace.get_scoreform_workspace_root()

    for class_id, results in by_class.items():
        roster_path = os.fspath(core_class_roster_path(workspace_root, class_id))

        # Import locally to avoid circular imports
        try:
            from scoreform.roster import load_roster
        except Exception:
            print("Warning: Could not import load_roster from scoreform.roster")
            # Leave fields blank
            for r in results:
                r.setdefault("last_name", "")
                r.setdefault("first_name", "")
                r.setdefault("period", "")
            continue

        if not os.path.exists(roster_path):
            print(f"Warning: Roster file not found for class '{class_id}': {roster_path}")
            for r in results:
                r.setdefault("last_name", "")
                r.setdefault("first_name", "")
                r.setdefault("period", "")
            continue

        roster = load_roster(roster_path)
        if roster is None:
            print(f"Warning: Failed to load roster for class '{class_id}': {roster_path}")
            for r in results:
                r.setdefault("last_name", "")
                r.setdefault("first_name", "")
                r.setdefault("period", "")
            continue

        any_loaded = True

        # Build lookup by student_id
        lookup = {s["student_id"]: s for s in roster.get("students", [])}

        for r in results:
            sid = r.get("student_id", "")
            student = lookup.get(sid)
            if student:
                r["last_name"] = student.get("last_name", "")
                r["first_name"] = student.get("first_name", "")
                r["period"] = student.get("period", "")
            else:
                print(f"Warning: student_id '{sid}' not found in roster {roster_path}")
                r.setdefault("last_name", "")
                r.setdefault("first_name", "")
                r.setdefault("period", "")

    return any_loaded


def _build_routed_result_target_plan(
    class_id,
    assignment_id,
    results,
    workspace_root,
):
    paths = scoreform_work_paths(workspace_root, class_id, assignment_id)
    output_dir = os.fspath(paths.work_root)
    output_file = os.fspath(paths.results_path)

    if paths.work_root.is_symlink() or not os.path.isdir(output_dir):
        print(
            f"Error: Could not prepare routed results target for class "
            f"'{class_id}', assignment '{assignment_id}':"
        )
        print(output_file)
        print(f"Assignment directory does not exist: {output_dir}")
        return None

    if paths.assignment_path.is_symlink() or not paths.assignment_path.is_file():
        print(
            f"Error: Managed assignment file does not exist for class "
            f"'{class_id}', assignment '{assignment_id}': {paths.assignment_path}"
        )
        return None
    assignment = load_assignment(paths.assignment_path)
    if assignment is None:
        print(f"Error: Managed assignment is invalid: {paths.assignment_path}")
        return None
    if assignment.get("assignment_id") != assignment_id:
        print(
            "Error: Managed assignment identifier does not match its work ID: "
            f"{paths.assignment_path}"
        )
        return None

    work_root_abs = os.path.abspath(output_dir)
    output_abs = os.path.abspath(output_file)
    if os.path.normcase(os.path.commonpath([work_root_abs, output_abs])) != os.path.normcase(
        work_root_abs
    ):
        print(f"Error: Results destination escapes managed work: {output_file}")
        return None

    question_count = max(1, _get_max_question_count(results))
    existing_rows_raw = []

    if os.path.exists(output_file):
        if paths.results_path.is_symlink() or not os.path.isfile(output_file):
            print(
                f"Error: Routed results destination is not a file for class "
                f"'{class_id}', assignment '{assignment_id}': {output_file}"
            )
            return None

        existing_rows_raw, existing_question_count = _read_existing_routed_results(
            output_file
        )
        if existing_rows_raw is None:
            print(
                f"Preflight failed for assignment {assignment_id} in class "
                f"{class_id}: {output_file}"
            )
            return None
        question_count = max(question_count, existing_question_count)

    headers = _routed_headers(question_count)
    existing_rows = []
    attempt_counts = {}

    for row in existing_rows_raw:
        preserved = {header: row.get(header, "") for header in headers}
        preserved["source_file"] = privacy_safe_source_file(
            row.get("source_file", ""),
            workspace_root=workspace_root,
        )

        raw_attempt = row.get("attempt_number", "")
        if raw_attempt and raw_attempt.isdigit():
            preserved_attempt = int(raw_attempt)
        else:
            preserved_attempt = 1
            preserved["attempt_number"] = "1"

        preserved["scan_timestamp"] = row.get("scan_timestamp", "")
        existing_rows.append(preserved)

        attempt_key = (
            preserved.get("class_id", ""),
            preserved.get("assignment_id", ""),
            preserved.get("student_id", ""),
        )
        if all(attempt_key):
            attempt_counts[attempt_key] = max(
                attempt_counts.get(attempt_key, 0),
                preserved_attempt,
            )

    batch_timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows_to_write = list(existing_rows)

    for res in results:
        attempt_key = (
            res.get("class_id", ""),
            res.get("assignment_id", ""),
            res.get("student_id", ""),
        )
        next_attempt = attempt_counts.get(attempt_key, 0) + 1
        attempt_counts[attempt_key] = next_attempt

        row = {
            "Page": res["page_num"],
            "class_id": res.get("class_id", ""),
            "assignment_id": res.get("assignment_id", ""),
            "student_id": res.get("student_id", ""),
            "last_name": res.get("last_name", ""),
            "first_name": res.get("first_name", ""),
            "period": res.get("period", ""),
            "source_file": privacy_safe_source_file(
                res.get("source_file", ""),
                workspace_root=workspace_root,
            ),
            "attempt_number": str(next_attempt),
            "scan_timestamp": batch_timestamp,
            "Score": res["score"],
            "Total": res["total_points"],
        }

        for ans in res["answers"]:
            q_num = ans["Q"]
            row[f"Q{q_num}"] = ans["Answer"]
            row[f"Q{q_num}_Correct"] = ans["Correct"]

        rows_to_write.append(row)

    return {
        "class_id": class_id,
        "assignment_id": assignment_id,
        "output_file": output_file,
        "headers": headers,
        "rows": rows_to_write,
    }


def _build_routed_result_write_plan(groups, workspace_root):
    write_plan = []
    for (class_id, assignment_id), target_results in sorted(groups.items()):
        try:
            target_plan = _build_routed_result_target_plan(
                class_id,
                assignment_id,
                target_results,
                workspace_root,
            )
        except (OSError, KeyError, TypeError, ValueError) as error:
            print(
                f"Error: Could not preflight routed results for class "
                f"'{class_id}', assignment '{assignment_id}'."
            )
            print(f"Technical detail: {error}")
            return None

        if target_plan is None:
            return None
        write_plan.append(target_plan)

    return write_plan


def _legacy_export_routed_results(all_results, workspace_root=None):
    """Route and export scoring results to ScoreForm managed-work folders.
    
    Groups results by (class_id, assignment_id) and writes each group to:
        classes/<class_id>/modules/scoreform/work/<assignment_id>/results.csv
    
    Returns True on success, False on failure.
    """
    if not all_results:
        print("No results to export.")
        return False
    if workspace_root is None:
        workspace_root = workspace.get_scoreform_workspace_root()

    # Validate all general result identifiers before loading or writing anything.
    groups = {}
    for res in all_results:
        class_id = res.get("class_id")
        assignment_id = res.get("assignment_id")
        student_id = res.get("student_id")

        if class_id is None or assignment_id is None or student_id is None:
            print(
                f"Error: Result missing required metadata. "
                f"class_id={class_id}, assignment_id={assignment_id}, student_id={student_id}"
            )
            return False

        try:
            scoreform_work_paths(workspace_root, class_id, assignment_id)
        except (TypeError, ValueError) as error:
            print(
                f"Error: Invalid managed result target for class '{class_id}', "
                f"assignment '{assignment_id}': {error}"
            )
            return False
        if not validate_identifier("student_id", student_id, context="result"):
            print(
                f"Error: Unsafe student_id in routed result: '{student_id}'. "
                "Rejecting export."
            )
            return False

        key = (class_id, assignment_id)
        if key not in groups:
            groups[key] = []
        groups[key].append(res)

    # Enrich results with roster metadata (last_name, first_name, period)
    enriched_ok = _enrich_results_with_roster(
        all_results,
        workspace_root=workspace_root,
    )
    if not enriched_ok:
        # Continue exporting even if some roster lookups failed; warnings printed by helper
        pass

    # Preflight every target before modifying any routed results file.
    write_plan = _build_routed_result_write_plan(groups, workspace_root)
    if write_plan is None:
        print("Routed results export aborted before writing any target.")
        return False

    for target in write_plan:
        output_file = target["output_file"]
        if not _write_routed_results_safely(
            output_file,
            target["headers"],
            target["rows"],
        ):
            return False
        print(f"Results routed to {output_file}")

    return True


# The mutable v1 implementation above is retained only as source-level migration
# context. Remove its callable name so no supported caller can select that policy.
del _legacy_export_routed_results


# Durable routed-results schema v2. The generic ``export_to_csv`` above remains
# intentionally separate for manual image scoring with an explicit answer key.
_V2_BASE_HEADERS = [
    "Page", "class_id", "assignment_id", "student_id", "last_name",
    "first_name", "period", "source_file", "result_schema_version",
    "result_origin", "issuance_id", "generation_id", "artifact_id",
    "page_ids", "route_ids", "logical_pages", "source_scan_id",
    "source_pages", "retained_source_path", "source_sha256",
    "attempt_number", "scan_timestamp", "Score", "Total",
]


def routed_results_v2_headers(question_count: int) -> list[str]:
    headers = list(_V2_BASE_HEADERS)
    for number in range(1, question_count + 1):
        headers.extend((f"Q{number}", f"Q{number}_Correct"))
    return headers


@dataclass(frozen=True, slots=True)
class ScoreFormExportedAttempt:
    result: ScoreFormRoutedResult
    output_path: Path
    attempt_number: int

    def __post_init__(self) -> None:
        if not isinstance(self.result, ScoreFormRoutedResult):
            raise TypeError("result must be a ScoreFormRoutedResult.")
        if not isinstance(self.output_path, Path):
            raise TypeError("output_path must be a Path.")
        if (
            isinstance(self.attempt_number, bool)
            or not isinstance(self.attempt_number, int)
            or self.attempt_number < 1
        ):
            raise ValueError("attempt_number must be a positive integer.")


@dataclass(frozen=True, slots=True)
class ScoreFormTemporaryCleanupFailure:
    temporary_path: Path
    target_path: Path
    error: OSError

    def __post_init__(self) -> None:
        if not isinstance(self.temporary_path, Path) or not isinstance(self.target_path, Path):
            raise TypeError("Cleanup paths must be Path values.")
        if not isinstance(self.error, OSError):
            raise TypeError("Cleanup error must be an OSError.")


@dataclass(frozen=True, slots=True)
class ScoreFormAttemptExportFailure:
    class_id: str
    assignment_id: str
    output_path: Path
    reason: str
    error: Exception
    stage: Literal["preflight", "integrity", "staging", "replacement", "not_attempted"] = "preflight"
    affected_targets: tuple[tuple[str, str], ...] = ()
    cleanup_failures: tuple[ScoreFormTemporaryCleanupFailure, ...] = ()

    def __post_init__(self) -> None:
        if self.stage not in {"preflight", "integrity", "staging", "replacement", "not_attempted"}:
            raise ValueError("Unsupported export failure stage.")
        if not isinstance(self.output_path, Path) or not isinstance(self.error, Exception):
            raise TypeError("Export failure path or error has the wrong type.")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("Export failure reason must be nonempty.")
        if not isinstance(self.affected_targets, tuple) or not isinstance(self.cleanup_failures, tuple):
            raise TypeError("Export failure collections must be tuples.")


@dataclass(frozen=True, slots=True)
class ScoreFormAttemptExportBatch:
    appended_attempts: tuple[ScoreFormExportedAttempt, ...] = ()
    already_present_attempts: tuple[ScoreFormExportedAttempt, ...] = ()
    failures: tuple[ScoreFormAttemptExportFailure, ...] = ()
    output_paths: tuple[Path, ...] = ()

    def __post_init__(self) -> None:
        for name in ("appended_attempts", "already_present_attempts", "failures", "output_paths"):
            if not isinstance(getattr(self, name), tuple):
                raise TypeError(f"{name} must be a tuple.")
        if any(not isinstance(item, ScoreFormExportedAttempt) for item in (*self.appended_attempts, *self.already_present_attempts)):
            raise TypeError("Attempt collections contain the wrong model type.")
        if any(not isinstance(item, ScoreFormAttemptExportFailure) for item in self.failures):
            raise TypeError("failures contains the wrong model type.")
        if any(not isinstance(path, Path) for path in self.output_paths):
            raise TypeError("output_paths must contain Path values.")
        if len(self.output_paths) != len(set(self.output_paths)):
            raise ValueError("output_paths must not repeat.")
        confirmed_paths = {item.output_path for item in (*self.appended_attempts, *self.already_present_attempts)}
        if not confirmed_paths.issubset(self.output_paths):
            raise ValueError("Every confirmed attempt path must appear in output_paths.")
        append_ids = tuple(
            (item.result.source_scan_id, item.result.issuance_id)
            for item in self.appended_attempts if item.result.result_origin == "pds2_scan"
        )
        present_ids = tuple(
            (item.result.source_scan_id, item.result.issuance_id)
            for item in self.already_present_attempts if item.result.result_origin == "pds2_scan"
        )
        if len((*append_ids, *present_ids)) != len(set((*append_ids, *present_ids))):
            raise ValueError("Exported identities must not repeat.")

    @property
    def succeeded(self) -> bool:
        return not self.failures


def _json_array(values) -> str:
    return json.dumps(list(values), ensure_ascii=False, separators=(",", ":"))


def _answer_columns(result: ScoreFormRoutedResult, width: int) -> dict[str, object]:
    values: dict[str, object] = {}
    by_number = {answer.question_number: answer for answer in result.answers}
    for number in range(1, width + 1):
        answer = by_number.get(number)
        values[f"Q{number}"] = "" if answer is None else answer.selected_answer
        values[f"Q{number}_Correct"] = "" if answer is None else str(answer.correct)
    return values


def _result_row(result: ScoreFormRoutedResult, width: int, attempt: int, timestamp: str) -> dict[str, object]:
    row: dict[str, object] = {
        "Page": result.page_display, "class_id": result.class_id,
        "assignment_id": result.assignment_id, "student_id": result.student_id,
        "last_name": result.last_name, "first_name": result.first_name,
        "period": result.period, "source_file": result.source_file,
        "result_schema_version": ROUTED_RESULTS_SCHEMA_VERSION,
        "result_origin": result.result_origin,
        "issuance_id": result.issuance_id or "",
        "generation_id": result.generation_id or "",
        "artifact_id": result.artifact_id or "",
        "page_ids": _json_array(result.page_ids),
        "route_ids": _json_array(result.route_ids),
        "logical_pages": _json_array(result.logical_pages),
        "source_scan_id": result.source_scan_id or "",
        "source_pages": _json_array(result.source_page_numbers),
        "retained_source_path": result.retained_source_relative_path or "",
        "source_sha256": result.source_sha256 or "",
        "attempt_number": str(attempt), "scan_timestamp": timestamp,
        "Score": str(result.score), "Total": str(result.total_points),
    }
    row.update(_answer_columns(result, width))
    return row


def _parse_positive(value: str, label: str) -> int:
    if not value.isdigit() or int(value) < 1 or str(int(value)) != value:
        raise ScoreFormRoutedResultReadError(f"Existing {label} must be a positive integer.")
    return int(value)


def _parse_score(value: str, label: str, *, minimum=0) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise ScoreFormRoutedResultReadError(f"Existing {label} must be an integer.") from error
    if parsed < minimum or str(parsed) != value:
        raise ScoreFormRoutedResultReadError(f"Existing {label} is out of range.")
    return parsed


def _question_width(fieldnames: Sequence[str], base: list[str]) -> int | None:
    if fieldnames[:len(base)] != base:
        return None
    tail = fieldnames[len(base):]
    if len(tail) % 2:
        return None
    width = len(tail) // 2
    expected: list[str] = []
    for number in range(1, width + 1):
        expected.extend((f"Q{number}", f"Q{number}_Correct"))
    return width if tail == expected else None


def _answers_from_row(row: dict[str, str], total: int) -> tuple[ScoredAnswer, ...]:
    answers = []
    for number in range(1, total + 1):
        selected = row.get(f"Q{number}", "")
        correct_text = row.get(f"Q{number}_Correct", "")
        if not selected or correct_text not in {"True", "False"}:
            raise ScoreFormRoutedResultReadError("Existing question cells are incomplete or invalid.")
        answers.append(ScoredAnswer(number, selected, correct_text == "True"))
    return tuple(answers)


def _validated_existing_timestamp(
    value: str,
    *,
    result_origin: Literal["pds2_scan", "plain_paper_manual", "legacy_scan"],
) -> str:
    if not isinstance(value, str) or not value:
        raise ScoreFormRoutedResultReadError("Existing scan_timestamp must be nonempty.")
    try:
        parsed = datetime.datetime.fromisoformat(value)
    except ValueError as iso_error:
        raise ScoreFormRoutedResultReadError(
            "Existing scan_timestamp is not a supported timestamp."
        ) from iso_error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        historical = False
        if result_origin != "pds2_scan":
            try:
                historical = (
                    datetime.datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
                    .strftime("%Y-%m-%d %H:%M:%S") == value
                )
            except ValueError:
                historical = False
        if not historical:
            requirement = (
                "PDS2 scan timestamps must be timezone-aware ISO 8601."
                if result_origin == "pds2_scan"
                else "Historical timestamps must use YYYY-MM-DD HH:MM:SS."
            )
            raise ScoreFormRoutedResultReadError(requirement)
    return value


def _arrays(row: dict[str, str], field: str, item_type):
    try:
        value = json.loads(row[field])
    except (KeyError, json.JSONDecodeError, TypeError) as error:
        raise ScoreFormRoutedResultReadError(f"Existing {field} is not canonical JSON.") from error
    if not isinstance(value, list) or any(isinstance(item, bool) or not isinstance(item, item_type) for item in value):
        raise ScoreFormRoutedResultReadError(f"Existing {field} has invalid values.")
    if row[field] != _json_array(value):
        raise ScoreFormRoutedResultReadError(f"Existing {field} is not canonical JSON.")
    return tuple(value)


def _model_from_v2(row: dict[str, str]) -> ScoreFormRoutedResult:
    total = _parse_positive(row["Total"], "Total")
    score = _parse_score(row["Score"], "Score")
    def optional(name):
        return row[name] or None
    try:
        return ScoreFormRoutedResult(
            result_origin=cast(Literal["pds2_scan", "plain_paper_manual", "legacy_scan"], row["result_origin"]), class_id=row["class_id"],
            assignment_id=row["assignment_id"], student_id=row["student_id"],
            last_name=row["last_name"], first_name=row["first_name"],
            period=row["period"], page_display=row["Page"], score=score,
            total_points=total, answers=_answers_from_row(row, total),
            issuance_id=optional("issuance_id"), generation_id=optional("generation_id"),
            artifact_id=optional("artifact_id"), page_ids=_arrays(row, "page_ids", str),
            route_ids=_arrays(row, "route_ids", str),
            logical_pages=_arrays(row, "logical_pages", int),
            source_file=row["source_file"], source_scan_id=optional("source_scan_id"),
            source_page_numbers=_arrays(row, "source_pages", int),
            retained_source_relative_path=optional("retained_source_path"),
            source_sha256=optional("source_sha256"),
        )
    except ScoreFormRoutedResultValidationError:
        raise
    except Exception as error:
        raise ScoreFormRoutedResultReadError("Existing v2 result is invalid.") from error


def _read_history(path: Path):
    if not path.exists():
        return [], 0
    if path.is_symlink() or not path.is_file():
        raise ScoreFormRoutedResultReadError("Routed results destination is not a regular file.")
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle, strict=True)
            fieldnames = reader.fieldnames or []
            v2_width = _question_width(fieldnames, _V2_BASE_HEADERS)
            v1_width = _question_width(fieldnames, _routed_headers(0))
            if v2_width is None and v1_width is None:
                raise ScoreFormRoutedResultReadError("Existing routed results header is incompatible.")
            raw_rows = list(reader)
    except (OSError, UnicodeError, csv.Error) as error:
        raise ScoreFormRoutedResultReadError(f"Could not read routed results: {error}") from error
    if any(None in row or any(value is None for value in row.values()) for row in raw_rows):
        raise ScoreFormRoutedResultReadError("Existing routed results contain malformed rows.")
    width = v2_width if v2_width is not None else v1_width
    assert width is not None
    rows = []
    for raw in raw_rows:
        attempt = _parse_positive(raw.get("attempt_number", ""), "attempt_number")
        if v2_width is not None:
            if raw.get("result_schema_version") != ROUTED_RESULTS_SCHEMA_VERSION:
                raise ScoreFormRoutedResultReadError("Existing result_schema_version is unsupported.")
            model = _model_from_v2(raw)
        else:
            total = _parse_positive(raw.get("Total", ""), "Total")
            score = _parse_score(raw.get("Score", ""), "Score")
            manual = raw.get("Page") == "manual" or raw.get("source_file") == "plain_paper_manual_entry"
            model = ScoreFormRoutedResult(
                result_origin="plain_paper_manual" if manual else "legacy_scan",
                class_id=raw.get("class_id", ""), assignment_id=raw.get("assignment_id", ""),
                student_id=raw.get("student_id", ""), last_name=raw.get("last_name", ""),
                first_name=raw.get("first_name", ""), period=raw.get("period", ""),
                page_display="manual" if manual else raw.get("Page", ""),
                score=score, total_points=total, answers=_answers_from_row(raw, total),
                source_file="plain_paper_manual_entry" if manual else raw.get("source_file", ""),
            )
        timestamp = _validated_existing_timestamp(
            raw.get("scan_timestamp", ""), result_origin=model.result_origin
        )
        for number in range(model.total_points + 1, width + 1):
            if raw.get(f"Q{number}", "") or raw.get(f"Q{number}_Correct", ""):
                raise ScoreFormRoutedResultReadError(
                    "Existing question cells beyond Total must be empty."
                )
        rows.append((model, attempt, timestamp))
    return rows, width


def _same_exported_content(left: ScoreFormRoutedResult, right: ScoreFormRoutedResult) -> bool:
    return left == right


class _HistoryStageError(ScoreFormRoutedResultWriteError):
    def __init__(self, message, *, temporary_path, cleanup_failures):
        super().__init__(message)
        self.temporary_path = temporary_path
        self.cleanup_failures = cleanup_failures


def _stage_history(path: Path, headers: list[str], rows: list[dict[str, object]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", newline="", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
            temp_path = Path(handle.name)
            writer = csv.DictWriter(handle, fieldnames=headers)
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        return temp_path
    except Exception as error:
        cleanup_failures = []
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError as cleanup_error:
                cleanup_failures.append(ScoreFormTemporaryCleanupFailure(
                    temp_path, path, cleanup_error
                ))
        staged_error = _HistoryStageError(
            f"Could not stage {path}: {error}", temporary_path=temp_path,
            cleanup_failures=tuple(cleanup_failures),
        )
        staged_error.__cause__ = error
        raise staged_error


def _cleanup_staged(staged) -> tuple[ScoreFormTemporaryCleanupFailure, ...]:
    failures = []
    for temporary_path, target_path in staged:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError as error:
            failures.append(ScoreFormTemporaryCleanupFailure(
                temporary_path, target_path, error
            ))
    return tuple(failures)


def _adapt_legacy_mapping(value, workspace_root) -> ScoreFormRoutedResult:
    if isinstance(value, ScoreFormRoutedResult):
        return value
    answers = tuple(ScoredAnswer(answer["Q"], answer["Answer"], answer["Correct"]) for answer in value["answers"])
    manual = value.get("page_num") == "manual" or value.get("source_file") == "plain_paper_manual_entry"
    if not manual:
        raise ScoreFormRoutedResultValidationError("Mutable mappings are supported only for plain-paper manual compatibility.")
    class_id, student_id = value["class_id"], value["student_id"]
    last_name, first_name, period = value.get("last_name", ""), value.get("first_name", ""), value.get("period", "")
    if not (last_name or first_name or period):
        try:
            from scoreform.roster import load_roster
            roster = load_roster(core_class_roster_path(workspace_root, class_id))
            if roster is None:
                raise ValueError("Roster is unavailable.")
            student = next(item for item in roster["students"] if item["student_id"] == student_id)
            last_name, first_name, period = student["last_name"], student["first_name"], student["period"]
        except Exception:
            pass
    return ScoreFormRoutedResult(
        result_origin="plain_paper_manual", class_id=class_id,
        assignment_id=value["assignment_id"], student_id=student_id,
        last_name=last_name, first_name=first_name, period=period,
        page_display="manual", score=value["score"], total_points=value["total_points"],
        answers=answers, source_file="plain_paper_manual_entry",
    )


def _export_result_models(results, *, workspace_root: Path, explicit_output_file: Path | None = None) -> ScoreFormAttemptExportBatch:
    validated = tuple(_adapt_legacy_mapping(value, workspace_root) for value in results)
    groups = {("explicit", "explicit"): list(validated)} if explicit_output_file is not None else {}
    if explicit_output_file is None:
        for result in validated:
            groups.setdefault((result.class_id, result.assignment_id), []).append(result)
    plans = []
    failures = []
    for key, target_results in sorted(groups.items()):
        class_id, assignment_id = key
        path = explicit_output_file
        managed_width = None
        try:
            if path is None:
                paths = scoreform_work_paths(workspace_root, class_id, assignment_id)
                if paths.work_root.is_symlink() or not paths.work_root.is_dir() or paths.assignment_path.is_symlink() or not paths.assignment_path.is_file():
                    raise ScoreFormRoutedResultReadError("Managed assignment target does not exist.")
                assignment = load_assignment(paths.assignment_path)
                if assignment is None or assignment.get("assignment_id") != assignment_id:
                    raise ScoreFormRoutedResultReadError("Managed assignment is invalid.")
                managed_width = assignment["question_count"]
                path = paths.results_path
            assert path is not None
            if path.exists() and path.is_symlink():
                raise ScoreFormRoutedResultReadError("Routed results destination cannot be a symlink.")
            existing, old_width = _read_history(path)
            if managed_width is not None:
                if (
                    old_width not in {0, managed_width}
                    or any(item.total_points != managed_width for item in target_results)
                    or any(
                        model.class_id != class_id
                        or model.assignment_id != assignment_id
                        or model.total_points != managed_width
                        for model, _attempt, _stamp in existing
                    )
                ):
                    raise ScoreFormRoutedResultIntegrityError("Managed result question width disagrees with the assignment.")
                width = managed_width
            else:
                width = max([old_width, *(item.total_points for item in target_results)], default=0)
            plans.append((key, path, target_results, existing, width))
        except Exception as error:
            target = path or Path(".")
            affected = tuple(sorted({(item.class_id, item.assignment_id) for item in target_results}))
            failures.append(ScoreFormAttemptExportFailure(
                class_id, assignment_id, target, str(error), error,
                stage="preflight", affected_targets=affected,
            ))
    if failures:
        return ScoreFormAttemptExportBatch(failures=tuple(failures))

    timestamp = datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat()
    prepared = []
    present = []
    for key, path, target_results, existing, width in plans:
        affected = tuple(sorted({(item.class_id, item.assignment_id) for item in target_results}))
        failure_class = affected[0][0] if len({item[0] for item in affected}) == 1 else "multiple"
        failure_assignment = affected[0][1] if len({item[1] for item in affected}) == 1 else "multiple"
        existing_export_ids = {}
        for model, attempt, _stamp in existing:
            if model.result_origin != "pds2_scan":
                continue
            export_id = (model.source_scan_id, model.issuance_id)
            if export_id in existing_export_ids:
                integrity_error = ScoreFormRoutedResultIntegrityError(
                    "Existing history contains a duplicate source_scan_id + issuance_id."
                )
                failures.append(ScoreFormAttemptExportFailure(
                    failure_class, failure_assignment, path, str(integrity_error),
                    integrity_error, stage="integrity", affected_targets=affected,
                ))
                break
            existing_export_ids[export_id] = (model, attempt)
        if failures:
            break
        unique_incoming = []
        incoming_ids: dict[tuple[str | None, str | None], ScoreFormRoutedResult] = {}
        for result in target_results:
            if result.result_origin != "pds2_scan":
                unique_incoming.append(result)
                continue
            export_id = (result.source_scan_id, result.issuance_id)
            prior = incoming_ids.get(export_id)
            if prior is None:
                incoming_ids[export_id] = result
                unique_incoming.append(result)
            elif prior != result:
                integrity_error = ScoreFormRoutedResultIntegrityError(
                    "Incoming transaction contradicts source_scan_id + issuance_id."
                )
                failures.append(ScoreFormAttemptExportFailure(
                    failure_class, failure_assignment, path, str(integrity_error),
                    integrity_error, stage="integrity", affected_targets=affected,
                ))
                break
        if failures:
            break
        counts: dict[tuple[str, str, str], int] = {}
        for model, attempt, _stamp in existing:
            attempt_key = (model.class_id, model.assignment_id, model.student_id)
            counts[attempt_key] = max(counts.get(attempt_key, 0), attempt)
        rows = [_result_row(model, width, attempt, stamp) for model, attempt, stamp in existing]
        pending = []
        for result in unique_incoming:
            match = existing_export_ids.get((result.source_scan_id, result.issuance_id)) if result.result_origin == "pds2_scan" else None
            if match is not None:
                if not _same_exported_content(match[0], result):
                    integrity_error = ScoreFormRoutedResultIntegrityError("Contradictory reuse of source_scan_id + issuance_id.")
                    failures.append(ScoreFormAttemptExportFailure(
                        failure_class, failure_assignment, path,
                        str(integrity_error), integrity_error, stage="integrity",
                        affected_targets=affected,
                    ))
                    break
                present.append(ScoreFormExportedAttempt(result, path, match[1]))
                continue
            attempt_key = (result.class_id, result.assignment_id, result.student_id)
            attempt = counts.get(attempt_key, 0) + 1
            counts[attempt_key] = attempt
            rows.append(_result_row(result, width, attempt, timestamp))
            pending.append(ScoreFormExportedAttempt(result, path, attempt))
        prepared.append((key, path, routed_results_v2_headers(width), rows, tuple(pending), affected, failure_class, failure_assignment))
    if failures:
        return ScoreFormAttemptExportBatch(
            already_present_attempts=tuple(present), failures=tuple(failures),
            output_paths=tuple(dict.fromkeys(item.output_path for item in present)),
        )

    staged = []
    for prepared_target in prepared:
        _key, path, headers, rows, pending_attempts, affected, failure_class, failure_assignment = prepared_target
        if not pending_attempts:
            continue
        try:
            temporary_path = _stage_history(path, headers, rows)
            staged.append((temporary_path, prepared_target))
        except Exception as error:
            stage_cleanup = getattr(error, "cleanup_failures", ())
            cleanup = (*stage_cleanup, *_cleanup_staged(
                (item[0], item[1][1]) for item in staged
            ))
            failures.append(ScoreFormAttemptExportFailure(
                failure_class, failure_assignment, path, str(error), error,
                stage="staging", affected_targets=affected,
                cleanup_failures=tuple(cleanup),
            ))
            for other in prepared:
                if other is prepared_target or not other[4]:
                    continue
                not_attempted = ScoreFormRoutedResultWriteError(
                    "Target was not attempted because transaction staging failed."
                )
                failures.append(ScoreFormAttemptExportFailure(
                    other[6], other[7], other[1], str(not_attempted), not_attempted,
                    stage="not_attempted", affected_targets=other[5],
                ))
            break
    if failures:
        return ScoreFormAttemptExportBatch(
            already_present_attempts=tuple(present), failures=tuple(failures),
            output_paths=tuple(dict.fromkeys(item.output_path for item in present)),
        )

    appended: list[ScoreFormExportedAttempt] = []
    written = []
    for index, (temporary_path, prepared_target) in enumerate(staged):
        _key, path, _headers, _rows, pending_attempts, affected, failure_class, failure_assignment = prepared_target
        try:
            os.replace(temporary_path, path)
        except OSError as error:
            write_error = ScoreFormRoutedResultWriteError(
                f"Could not replace {path}: {error}"
            )
            write_error.__cause__ = error
            cleanup = _cleanup_staged(
                (item[0], item[1][1]) for item in staged[index:]
            )
            failures.append(ScoreFormAttemptExportFailure(
                failure_class, failure_assignment, path, str(write_error),
                write_error, stage="replacement", affected_targets=affected,
                cleanup_failures=cleanup,
            ))
            for _later_temp, later in staged[index + 1:]:
                not_attempted = ScoreFormRoutedResultWriteError(
                    "Target was not attempted because an earlier replacement failed."
                )
                failures.append(ScoreFormAttemptExportFailure(
                    later[6], later[7], later[1], str(not_attempted), not_attempted,
                    stage="not_attempted", affected_targets=later[5],
                ))
            break
        appended.extend(pending_attempts)
        written.append(path)
    output_paths = tuple(dict.fromkeys(
        [*written, *(item.output_path for item in present)]
    ))
    return ScoreFormAttemptExportBatch(
        tuple(appended), tuple(present), tuple(failures), output_paths
    )


def export_scoreform_attempts(assembly, *, workspace_root: Path, explicit_output_file: Path | None = None) -> ScoreFormAttemptExportBatch:
    """Export a typed assembly batch without interpreting dispatch outcomes."""
    results = tuple(attempt.routed_result for attempt in assembly.completed_attempts)
    if not results:
        return ScoreFormAttemptExportBatch()
    return _export_result_models(results, workspace_root=Path(workspace_root), explicit_output_file=Path(explicit_output_file) if explicit_output_file is not None else None)


def export_routed_results(all_results, workspace_root=None):
    """Compatibility Boolean wrapper over the strict shared v2 writer."""
    if not all_results:
        print("No results to export.")
        return False
    root = Path(workspace_root) if workspace_root is not None else workspace.get_scoreform_workspace_root()
    try:
        batch = _export_result_models(all_results, workspace_root=root)
    except Exception as error:
        print(f"Error: Routed results export failed: {error}")
        return False
    for path in batch.output_paths:
        print(f"Results routed to {path}")
    for failure in batch.failures:
        print(f"Error: {failure.reason}")
    return batch.succeeded
