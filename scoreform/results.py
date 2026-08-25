import csv
import datetime
import io
import json
import ntpath
import os
import re
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

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
from scoreform.diagnostic_events import try_emit_diagnostic_event
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
from scoreform.work_paths import scoreform_work_paths

ROUTED_RESULTS_SCHEMA_VERSION = "2"
RESULT_ORIGINS = frozenset(
    {"pds2_scan", "plain_paper_manual", "scan_review_manual"}
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class ScoreFormRoutedResult:
    result_origin: Literal[
        "pds2_scan", "plain_paper_manual", "scan_review_manual"
    ]
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
        raise ScoreFormRoutedResultValidationError(
            "Invalid routed identity."
        ) from error
    if any(
        not _single_line(value)
        for value in (result.last_name, result.first_name, result.period)
    ):
        raise ScoreFormRoutedResultValidationError(
            "Student display fields must be control-free single-line strings."
        )
    if not _single_line(result.page_display, nonempty=True) or not _single_line(
        result.source_file
    ):
        raise ScoreFormRoutedResultValidationError(
            "Page and source display fields are invalid."
        )
    for name, value in (("score", result.score), ("total_points", result.total_points)):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ScoreFormRoutedResultValidationError(f"{name} must be an integer.")
    if result.total_points < 1 or not 0 <= result.score <= result.total_points:
        raise ScoreFormRoutedResultValidationError("Score or total is out of range.")
    if not isinstance(result.answers, tuple) or any(
        not isinstance(answer, ScoredAnswer) for answer in result.answers
    ):
        raise ScoreFormRoutedResultValidationError(
            "answers must be immutable ScoredAnswer values."
        )
    if any(
        isinstance(answer.question_number, bool)
        or not isinstance(answer.question_number, int)
        or not isinstance(answer.selected_answer, str)
        or answer.selected_answer not in {"A", "B", "C", "D", "BLANK", "AMBIGUOUS"}
        or not isinstance(answer.correct, bool)
        for answer in result.answers
    ):
        raise ScoreFormRoutedResultValidationError(
            "answers contain invalid typed values."
        )
    numbers = tuple(answer.question_number for answer in result.answers)
    if numbers != tuple(range(1, result.total_points + 1)):
        raise ScoreFormRoutedResultValidationError(
            "answers must cover the result total exactly in order."
        )
    if any(
        not isinstance(answer.correct, bool) for answer in result.answers
    ) or result.score != sum(answer.correct for answer in result.answers):
        raise ScoreFormRoutedResultValidationError(
            "Score and answer correctness disagree."
        )
    tuple_fields = (
        result.page_ids,
        result.route_ids,
        result.logical_pages,
        result.source_page_numbers,
    )
    if any(not isinstance(value, tuple) for value in tuple_fields):
        raise ScoreFormRoutedResultValidationError(
            "Provenance collections must be tuples."
        )
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
            raise ScoreFormRoutedResultValidationError(
                "Invalid PDS2 provenance identity."
            ) from error
        length = len(result.page_ids)
        if length < 1 or not (
            length
            == len(result.route_ids)
            == len(result.logical_pages)
            == len(result.source_page_numbers)
        ):
            raise ScoreFormRoutedResultValidationError(
                "PDS2 provenance collections must be nonempty and aligned."
            )
        if (
            len(set(result.page_ids)) != length
            or len(set(result.route_ids)) != length
            or len(set(result.source_page_numbers)) != length
        ):
            raise ScoreFormRoutedResultValidationError(
                "PDS2 provenance collections must not contain duplicates."
            )
        if result.logical_pages != tuple(range(1, length + 1)):
            raise ScoreFormRoutedResultValidationError(
                "PDS2 logical pages must be complete and ordered."
            )
        if any(
            isinstance(number, bool) or not isinstance(number, int) or number < 1
            for number in result.source_page_numbers
        ):
            raise ScoreFormRoutedResultValidationError(
                "Source page numbers must be positive integers."
            )
        retained_path = result.retained_source_relative_path or ""
        if not isinstance(result.source_sha256, str) or not _SHA256.fullmatch(
            result.source_sha256
        ):
            raise ScoreFormRoutedResultValidationError("source_sha256 is invalid.")
        if (
            not result.source_file
            or result.source_file != result.source_file.strip()
            or ntpath.basename(result.source_file) != result.source_file
            or "/" in result.source_file
            or "\\" in result.source_file
            or Path(result.source_file).suffix.lower()
            not in SUPPORTED_RETAINED_SOURCE_EXTENSIONS
        ):
            raise ScoreFormRoutedResultValidationError(
                "PDS2 source_file must be a filename only."
            )
        try:
            validate_canonical_retained_source_relative_path(
                retained_path,
                expected_extension=Path(result.source_file).suffix,
            )
        except (TypeError, ValueError) as error:
            raise ScoreFormRoutedResultValidationError(
                "Retained source path must use canonical scans/source/YYYY-MM-DD/<filename>."
            ) from error
        if result.page_display != ",".join(
            str(number) for number in result.source_page_numbers
        ):
            raise ScoreFormRoutedResultValidationError(
                "PDS2 page_display must exactly summarize source pages."
            )
    elif any(
        (
            result.issuance_id,
            result.generation_id,
            result.artifact_id,
            result.page_ids,
            result.route_ids,
            result.logical_pages,
            result.source_scan_id,
            result.source_page_numbers,
            result.retained_source_relative_path,
            result.source_sha256,
        )
    ):
        raise ScoreFormRoutedResultValidationError(
            "Manual results cannot fabricate PDS2 provenance."
        )
    if result.result_origin == "plain_paper_manual" and (
        result.page_display != "manual"
        or result.source_file != "plain_paper_manual_entry"
    ):
        raise ScoreFormRoutedResultValidationError("Manual result markers are invalid.")
    if result.result_origin == "scan_review_manual":
        prefix = "scan_review_manual:"
        if result.page_display != "review" or not result.source_file.startswith(prefix):
            raise ScoreFormRoutedResultValidationError(
                "Scan-review result markers are invalid."
            )
        try:
            validate_core_identifier(result.source_file[len(prefix) :], "failure_id")
        except Exception as error:
            raise ScoreFormRoutedResultValidationError(
                "Scan-review failure link is invalid."
            ) from error
    return result


def privacy_safe_source_file(
    source_file: str | bytes | os.PathLike[str] | os.PathLike[bytes] | None,
    workspace_root: str | os.PathLike[str] | None = None,
) -> str:
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


def _get_max_question_count(results: Sequence[Mapping[str, Any]]) -> int:
    """Return the maximum question number seen across a list of results."""
    max_question = 0
    for res in results:
        for ans in res.get("answers", []):
            q_num = ans.get("Q")
            if isinstance(q_num, int) and q_num > max_question:
                max_question = q_num
    return max_question


def export_to_csv(
    all_results: Sequence[Mapping[str, Any]],
    output_file: str | os.PathLike[str],
    workspace_root: str | os.PathLike[str] | None = None,
) -> bool:
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


# Durable routed-results schema v2. The generic ``export_to_csv`` above remains
# intentionally separate for manual image scoring with an explicit answer key.
_V2_LEGACY_BASE_HEADERS = [
    "Page",
    "class_id",
    "assignment_id",
    "student_id",
    "last_name",
    "first_name",
    "period",
    "source_file",
    "result_schema_version",
    "result_origin",
    "issuance_id",
    "generation_id",
    "artifact_id",
    "page_ids",
    "route_ids",
    "logical_pages",
    "source_scan_id",
    "source_pages",
    "retained_source_path",
    "source_sha256",
    "attempt_number",
    "scan_timestamp",
    "Score",
    "Total",
]

_V2_TEACHER_PREFIX_HEADERS = [
    "class_id",
    "assignment_id",
    "student_id",
    "last_name",
    "first_name",
    "period",
    "Score",
    "Total",
]

_V2_TEACHER_SUFFIX_HEADERS = [
    "Page",
    "attempt_number",
    "scan_timestamp",
    "source_file",
    "result_schema_version",
    "result_origin",
    "issuance_id",
    "generation_id",
    "artifact_id",
    "page_ids",
    "route_ids",
    "logical_pages",
    "source_scan_id",
    "source_pages",
    "retained_source_path",
    "source_sha256",
]


def routed_results_v2_headers(question_count: int) -> list[str]:
    headers = list(_V2_TEACHER_PREFIX_HEADERS)
    for number in range(1, question_count + 1):
        headers.extend((f"Q{number}", f"Q{number}_Correct"))
    headers.extend(_V2_TEACHER_SUFFIX_HEADERS)
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
class ScoreFormRoutedResultHistoryRow:
    """One strictly validated schema-v2 managed-history row."""

    result: ScoreFormRoutedResult
    attempt_number: int
    scan_timestamp: str

    def __post_init__(self) -> None:
        if not isinstance(self.result, ScoreFormRoutedResult):
            raise TypeError("result must be a ScoreFormRoutedResult.")
        if (
            isinstance(self.attempt_number, bool)
            or not isinstance(self.attempt_number, int)
            or self.attempt_number < 1
        ):
            raise ValueError("attempt_number must be a positive integer.")
        if not isinstance(self.scan_timestamp, str):
            raise TypeError("scan_timestamp must be a string.")
        try:
            _validated_existing_timestamp(
                self.scan_timestamp,
                result_origin=self.result.result_origin,
            )
        except ScoreFormRoutedResultReadError as error:
            raise ValueError(
                "scan_timestamp must be timezone-aware ISO 8601."
            ) from error


@dataclass(frozen=True, slots=True)
class ScoreFormRoutedResultHistory:
    """Strict schema-v2 rows plus the exact accepted CSV header structure."""

    rows: tuple[ScoreFormRoutedResultHistoryRow, ...]
    question_count: int
    legacy_header_order: bool

    def __post_init__(self) -> None:
        if not isinstance(self.rows, tuple) or any(
            not isinstance(row, ScoreFormRoutedResultHistoryRow) for row in self.rows
        ):
            raise TypeError("rows must contain routed-result history rows.")
        if (
            isinstance(self.question_count, bool)
            or not isinstance(self.question_count, int)
            or self.question_count < 0
        ):
            raise ValueError("question_count must be a nonnegative integer.")
        if not isinstance(self.legacy_header_order, bool):
            raise TypeError("legacy_header_order must be a Boolean.")


@dataclass(frozen=True, slots=True)
class ScoreFormTemporaryCleanupFailure:
    temporary_path: Path
    target_path: Path
    error: OSError

    def __post_init__(self) -> None:
        if not isinstance(self.temporary_path, Path) or not isinstance(
            self.target_path, Path
        ):
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
    stage: Literal[
        "preflight", "integrity", "staging", "replacement", "not_attempted"
    ] = "preflight"
    affected_targets: tuple[tuple[str, str], ...] = ()
    cleanup_failures: tuple[ScoreFormTemporaryCleanupFailure, ...] = ()

    def __post_init__(self) -> None:
        if self.stage not in {
            "preflight",
            "integrity",
            "staging",
            "replacement",
            "not_attempted",
        }:
            raise ValueError("Unsupported export failure stage.")
        if not isinstance(self.output_path, Path) or not isinstance(
            self.error, Exception
        ):
            raise TypeError("Export failure path or error has the wrong type.")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("Export failure reason must be nonempty.")
        if not isinstance(self.affected_targets, tuple) or not isinstance(
            self.cleanup_failures, tuple
        ):
            raise TypeError("Export failure collections must be tuples.")


@dataclass(frozen=True, slots=True)
class ScoreFormAttemptExportBatch:
    appended_attempts: tuple[ScoreFormExportedAttempt, ...] = ()
    already_present_attempts: tuple[ScoreFormExportedAttempt, ...] = ()
    failures: tuple[ScoreFormAttemptExportFailure, ...] = ()
    output_paths: tuple[Path, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "appended_attempts",
            "already_present_attempts",
            "failures",
            "output_paths",
        ):
            if not isinstance(getattr(self, name), tuple):
                raise TypeError(f"{name} must be a tuple.")
        if any(
            not isinstance(item, ScoreFormExportedAttempt)
            for item in (*self.appended_attempts, *self.already_present_attempts)
        ):
            raise TypeError("Attempt collections contain the wrong model type.")
        if any(
            not isinstance(item, ScoreFormAttemptExportFailure)
            for item in self.failures
        ):
            raise TypeError("failures contains the wrong model type.")
        if any(not isinstance(path, Path) for path in self.output_paths):
            raise TypeError("output_paths must contain Path values.")
        if len(self.output_paths) != len(set(self.output_paths)):
            raise ValueError("output_paths must not repeat.")
        confirmed_paths = {
            item.output_path
            for item in (*self.appended_attempts, *self.already_present_attempts)
        }
        if not confirmed_paths.issubset(self.output_paths):
            raise ValueError(
                "Every confirmed attempt path must appear in output_paths."
            )
        content_ids = tuple(
            pds2_result_content_key(item.result)
            for item in (*self.appended_attempts, *self.already_present_attempts)
            if item.result.result_origin == "pds2_scan"
        )
        if len(content_ids) != len(set(content_ids)):
            raise ValueError("PDS2 content identities must not repeat.")

    @property
    def succeeded(self) -> bool:
        return not self.failures


def _json_array(values: Sequence[object]) -> str:
    return json.dumps(list(values), ensure_ascii=False, separators=(",", ":"))


def _answer_columns(result: ScoreFormRoutedResult, width: int) -> dict[str, object]:
    values: dict[str, object] = {}
    by_number = {answer.question_number: answer for answer in result.answers}
    for number in range(1, width + 1):
        answer = by_number.get(number)
        values[f"Q{number}"] = "" if answer is None else answer.selected_answer
        values[f"Q{number}_Correct"] = "" if answer is None else str(answer.correct)
    return values


def _result_row(
    result: ScoreFormRoutedResult, width: int, attempt: int, timestamp: str
) -> dict[str, object]:
    row: dict[str, object] = {
        "Page": result.page_display,
        "class_id": result.class_id,
        "assignment_id": result.assignment_id,
        "student_id": result.student_id,
        "last_name": result.last_name,
        "first_name": result.first_name,
        "period": result.period,
        "source_file": result.source_file,
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
        "attempt_number": str(attempt),
        "scan_timestamp": timestamp,
        "Score": str(result.score),
        "Total": str(result.total_points),
    }
    row.update(_answer_columns(result, width))
    return row


def _parse_positive(value: str, label: str) -> int:
    if not value.isdigit() or int(value) < 1 or str(int(value)) != value:
        raise ScoreFormRoutedResultReadError(
            f"Existing {label} must be a positive integer."
        )
    return int(value)


def _parse_score(value: str, label: str, *, minimum: int = 0) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise ScoreFormRoutedResultReadError(
            f"Existing {label} must be an integer."
        ) from error
    if parsed < minimum or str(parsed) != value:
        raise ScoreFormRoutedResultReadError(f"Existing {label} is out of range.")
    return parsed


def _question_headers(width: int) -> list[str]:
    headers: list[str] = []
    for number in range(1, width + 1):
        headers.extend((f"Q{number}", f"Q{number}_Correct"))
    return headers


def _question_width(fieldnames: Sequence[str]) -> tuple[int, bool] | None:
    legacy = fieldnames[: len(_V2_LEGACY_BASE_HEADERS)] == _V2_LEGACY_BASE_HEADERS
    if legacy:
        question_fields = fieldnames[len(_V2_LEGACY_BASE_HEADERS) :]
    elif (
        fieldnames[: len(_V2_TEACHER_PREFIX_HEADERS)]
        == _V2_TEACHER_PREFIX_HEADERS
        and fieldnames[-len(_V2_TEACHER_SUFFIX_HEADERS) :]
        == _V2_TEACHER_SUFFIX_HEADERS
    ):
        question_fields = fieldnames[
            len(_V2_TEACHER_PREFIX_HEADERS) : -len(_V2_TEACHER_SUFFIX_HEADERS)
        ]
    else:
        return None
    if len(question_fields) % 2:
        return None
    width = len(question_fields) // 2
    if question_fields != _question_headers(width):
        return None
    return width, legacy


def _answers_from_row(row: dict[str, str], total: int) -> tuple[ScoredAnswer, ...]:
    answers = []
    for number in range(1, total + 1):
        selected = row.get(f"Q{number}", "")
        correct_text = row.get(f"Q{number}_Correct", "")
        if not selected or correct_text not in {"True", "False"}:
            raise ScoreFormRoutedResultReadError(
                "Existing question cells are incomplete or invalid."
            )
        answers.append(ScoredAnswer(number, selected, correct_text == "True"))
    return tuple(answers)


def _validated_existing_timestamp(
    value: str,
    *,
    result_origin: Literal[
        "pds2_scan", "plain_paper_manual", "scan_review_manual"
    ],
) -> str:
    if not isinstance(value, str) or not value:
        raise ScoreFormRoutedResultReadError(
            "Existing scan_timestamp must be nonempty."
        )
    try:
        parsed = datetime.datetime.fromisoformat(value)
    except ValueError as iso_error:
        raise ScoreFormRoutedResultReadError(
            "Existing scan_timestamp is not a supported timestamp."
        ) from iso_error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ScoreFormRoutedResultReadError(
            "Existing scan_timestamp must be timezone-aware ISO 8601."
        )
    return value


def _arrays(
    row: dict[str, str], field: str, item_type: type[Any]
) -> tuple[Any, ...]:
    try:
        value = json.loads(row[field])
    except (KeyError, json.JSONDecodeError, TypeError) as error:
        raise ScoreFormRoutedResultReadError(
            f"Existing {field} is not canonical JSON."
        ) from error
    if not isinstance(value, list) or any(
        isinstance(item, bool) or not isinstance(item, item_type) for item in value
    ):
        raise ScoreFormRoutedResultReadError(f"Existing {field} has invalid values.")
    if row[field] != _json_array(value):
        raise ScoreFormRoutedResultReadError(f"Existing {field} is not canonical JSON.")
    return tuple(value)


def _model_from_v2(row: dict[str, str]) -> ScoreFormRoutedResult:
    total = _parse_positive(row["Total"], "Total")
    score = _parse_score(row["Score"], "Score")

    def optional(name: str) -> str | None:
        return row[name] or None

    try:
        return ScoreFormRoutedResult(
            result_origin=cast(
                Literal[
                    "pds2_scan",
                    "plain_paper_manual",
                    "scan_review_manual",
                ],
                row["result_origin"],
            ),
            class_id=row["class_id"],
            assignment_id=row["assignment_id"],
            student_id=row["student_id"],
            last_name=row["last_name"],
            first_name=row["first_name"],
            period=row["period"],
            page_display=row["Page"],
            score=score,
            total_points=total,
            answers=_answers_from_row(row, total),
            issuance_id=optional("issuance_id"),
            generation_id=optional("generation_id"),
            artifact_id=optional("artifact_id"),
            page_ids=_arrays(row, "page_ids", str),
            route_ids=_arrays(row, "route_ids", str),
            logical_pages=_arrays(row, "logical_pages", int),
            source_file=row["source_file"],
            source_scan_id=optional("source_scan_id"),
            source_page_numbers=_arrays(row, "source_pages", int),
            retained_source_relative_path=optional("retained_source_path"),
            source_sha256=optional("source_sha256"),
        )
    except ScoreFormRoutedResultValidationError as error:
        raise ScoreFormRoutedResultReadError(
            "Existing v2 result is invalid."
        ) from error
    except Exception as error:
        raise ScoreFormRoutedResultReadError(
            "Existing v2 result is invalid."
        ) from error


def _read_history_text(text: str) -> ScoreFormRoutedResultHistory:
    try:
        reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
        fieldnames = reader.fieldnames or []
        header_layout = _question_width(fieldnames)
        if header_layout is None:
            raise ScoreFormRoutedResultReadError(
                "The managed results history is not schema version 2."
            )
        v2_width, legacy_header_order = header_layout
        raw_rows = list(reader)
    except csv.Error as error:
        raise ScoreFormRoutedResultReadError(
            f"Could not read routed results: {error}"
        ) from error
    if any(
        None in row or any(value is None for value in row.values()) for row in raw_rows
    ):
        raise ScoreFormRoutedResultReadError(
            "Existing routed results contain malformed rows."
        )
    width = v2_width
    assert width is not None
    rows: list[ScoreFormRoutedResultHistoryRow] = []
    pds2_content: dict[tuple[str, str], ScoreFormRoutedResult] = {}
    for raw in raw_rows:
        attempt = _parse_positive(raw.get("attempt_number", ""), "attempt_number")
        if raw.get("result_schema_version") != ROUTED_RESULTS_SCHEMA_VERSION:
            raise ScoreFormRoutedResultReadError(
                "Existing result_schema_version is unsupported."
            )
        model = _model_from_v2(raw)
        timestamp = _validated_existing_timestamp(
            raw.get("scan_timestamp", ""), result_origin=model.result_origin
        )
        for number in range(model.total_points + 1, width + 1):
            if raw.get(f"Q{number}", "") or raw.get(f"Q{number}_Correct", ""):
                raise ScoreFormRoutedResultReadError(
                    "Existing question cells beyond Total must be empty."
                )
        if model.result_origin == "pds2_scan":
            content_key = pds2_result_content_key(model)
            prior = pds2_content.get(content_key)
            if prior is not None and not pds2_results_semantically_equivalent(
                prior, model
            ):
                raise ScoreFormRoutedResultReadError(
                    "Existing history contradicts a source_sha256 + issuance_id key."
                )
            pds2_content.setdefault(content_key, model)
        rows.append(ScoreFormRoutedResultHistoryRow(model, attempt, timestamp))
    return ScoreFormRoutedResultHistory(tuple(rows), width, legacy_header_order)


def parse_routed_results_history_csv_bytes(
    data: bytes,
) -> ScoreFormRoutedResultHistory:
    """Parse exact schema-v2 bytes while retaining their validated header width."""
    if not isinstance(data, bytes):
        raise ScoreFormRoutedResultReadError("Routed results input must be bytes.")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ScoreFormRoutedResultReadError(
            "Routed results must be valid UTF-8."
        ) from error
    return _read_history_text(text)


def routed_results_history_from_csv_bytes(
    data: bytes,
) -> tuple[ScoreFormRoutedResultHistoryRow, ...]:
    """Strictly parse schema-v2 history from the exact immutable CSV bytes."""
    return parse_routed_results_history_csv_bytes(data).rows


def _read_history(
    path: Path,
) -> tuple[list[tuple[ScoreFormRoutedResult, int, str]], int, bool]:
    if not path.exists():
        return [], 0, False
    if path.is_symlink() or not path.is_file():
        raise ScoreFormRoutedResultReadError(
            "Routed results destination is not a regular file."
        )
    try:
        content = path.read_bytes()
    except OSError as error:
        raise ScoreFormRoutedResultReadError(
            f"Could not read routed results: {error}"
        ) from error
    parsed = parse_routed_results_history_csv_bytes(content)
    return (
        [
            (row.result, row.attempt_number, row.scan_timestamp)
            for row in parsed.rows
        ],
        parsed.question_count,
        parsed.legacy_header_order,
    )


def load_routed_results_history(
    results_csv_path: str | os.PathLike[str],
) -> tuple[ScoreFormRoutedResultHistoryRow, ...]:
    """Load an exact schema-v2 routed history without mutating it."""
    path = Path(results_csv_path)
    if not path.exists():
        return ()
    if path.is_symlink() or not path.is_file():
        raise ScoreFormRoutedResultReadError(
            "Routed results destination is not a regular file."
        )
    try:
        return parse_routed_results_history_csv_bytes(path.read_bytes()).rows
    except OSError as error:
        raise ScoreFormRoutedResultReadError(
            f"Could not read routed results: {error}"
        ) from error


def _same_exported_content(
    left: ScoreFormRoutedResult, right: ScoreFormRoutedResult
) -> bool:
    return left == right


def pds2_result_content_key(result: ScoreFormRoutedResult) -> tuple[str, str]:
    if result.result_origin != "pds2_scan":
        raise ValueError("PDS2 content keys require a pds2_scan result.")
    assert result.source_sha256 is not None
    assert result.issuance_id is not None
    return result.source_sha256, result.issuance_id


def pds2_results_semantically_equivalent(
    left: ScoreFormRoutedResult, right: ScoreFormRoutedResult
) -> bool:
    return (
        left.result_origin,
        left.class_id,
        left.assignment_id,
        left.student_id,
        left.last_name,
        left.first_name,
        left.period,
        left.page_display,
        left.issuance_id,
        left.generation_id,
        left.artifact_id,
        left.page_ids,
        left.route_ids,
        left.logical_pages,
        left.source_page_numbers,
        left.score,
        left.total_points,
        left.answers,
        left.source_sha256,
    ) == (
        right.result_origin,
        right.class_id,
        right.assignment_id,
        right.student_id,
        right.last_name,
        right.first_name,
        right.period,
        right.page_display,
        right.issuance_id,
        right.generation_id,
        right.artifact_id,
        right.page_ids,
        right.route_ids,
        right.logical_pages,
        right.source_page_numbers,
        right.score,
        right.total_points,
        right.answers,
        right.source_sha256,
    )


def _managed_review_result_links(
    workspace_root: Path,
) -> dict[str, list[tuple[ScoreFormRoutedResult, int, Path]]]:
    """Read review-linked rows only from canonical managed ScoreForm histories."""
    workspace_root = workspace_root.resolve(strict=True)
    links: dict[str, list[tuple[ScoreFormRoutedResult, int, Path]]] = {}
    classes_root = workspace_root / "classes"
    if not classes_root.exists():
        return links
    if classes_root.is_symlink() or not classes_root.is_dir():
        raise ScoreFormRoutedResultIntegrityError(
            "Managed classes root is not a real directory."
        )
    resolved_classes = classes_root.resolve(strict=True)
    for class_path in sorted(classes_root.iterdir(), key=lambda item: item.name):
        if class_path.is_symlink() or not class_path.is_dir():
            continue
        try:
            validate_core_identifier(class_path.name, "class_id")
        except Exception:
            continue
        resolved_class = class_path.resolve(strict=True)
        if resolved_class.parent != resolved_classes:
            raise ScoreFormRoutedResultIntegrityError(
                "Managed class directory escapes the classes root."
            )
        modules_root = class_path / "modules"
        if not modules_root.exists():
            continue
        if modules_root.is_symlink() or not modules_root.is_dir():
            raise ScoreFormRoutedResultIntegrityError(
                "Managed modules root is not a real directory."
            )
        scoreform_root = modules_root / "scoreform"
        if not scoreform_root.exists():
            continue
        if scoreform_root.is_symlink() or not scoreform_root.is_dir():
            raise ScoreFormRoutedResultIntegrityError(
                "Managed ScoreForm module root is not a real directory."
            )
        work_root = scoreform_root / "work"
        if not work_root.exists():
            continue
        if work_root.is_symlink() or not work_root.is_dir():
            raise ScoreFormRoutedResultIntegrityError(
                "Managed ScoreForm work root is not a real directory."
            )
        resolved_work = work_root.resolve(strict=True)
        if (
            modules_root.resolve(strict=True).parent != resolved_class
            or scoreform_root.resolve(strict=True).parent
            != modules_root.resolve(strict=True)
            or resolved_work.parent != scoreform_root.resolve(strict=True)
        ):
            raise ScoreFormRoutedResultIntegrityError(
                "Managed ScoreForm work ancestry is not canonical."
            )
        for assignment_path in sorted(
            work_root.iterdir(), key=lambda item: item.name
        ):
            if assignment_path.is_symlink() or not assignment_path.is_dir():
                continue
            try:
                validate_core_identifier(assignment_path.name, "assignment_id")
            except Exception:
                continue
            resolved_assignment = assignment_path.resolve(strict=True)
            if resolved_assignment.parent != resolved_work:
                raise ScoreFormRoutedResultIntegrityError(
                    "Managed assignment directory escapes the work root."
                )
            definition = assignment_path / "assignment.json"
            if definition.is_symlink() or not definition.is_file():
                raise ScoreFormRoutedResultIntegrityError(
                    "Managed assignment definition is not a non-symlink file."
                )
            assignment = load_assignment(definition)
            if (
                assignment is None
                or assignment.get("assignment_id") != assignment_path.name
            ):
                raise ScoreFormRoutedResultIntegrityError(
                    "Managed assignment definition disagrees with its directory."
                )
            results_path = assignment_path / "results.csv"
            if not results_path.exists():
                continue
            if results_path.is_symlink() or not results_path.is_file():
                raise ScoreFormRoutedResultIntegrityError(
                    "Managed results history must be a non-symlink regular file."
                )
            if results_path.resolve(strict=True).parent != resolved_assignment:
                raise ScoreFormRoutedResultIntegrityError(
                    "Managed results history escapes its assignment directory."
                )
            existing, _width, _legacy_header_order = _read_history(results_path)
            for model, attempt, _stamp in existing:
                if (
                    model.class_id != class_path.name
                    or model.assignment_id != assignment_path.name
                ):
                    raise ScoreFormRoutedResultIntegrityError(
                        "Managed result row identity disagrees with its history path."
                    )
                if model.result_origin == "scan_review_manual":
                    expected_path = (
                        workspace_root
                        / "classes"
                        / model.class_id
                        / "modules"
                        / "scoreform"
                        / "work"
                        / model.assignment_id
                        / "results.csv"
                    )
                    if results_path != expected_path:
                        raise ScoreFormRoutedResultIntegrityError(
                            "Review-linked result row is not in its canonical history."
                        )
                    links.setdefault(model.source_file, []).append(
                        (model, attempt, results_path)
                    )
    return links


class _HistoryStageError(ScoreFormRoutedResultWriteError):  # type: ignore[misc]
    def __init__(
        self,
        message: str,
        *,
        temporary_path: Path | None,
        cleanup_failures: tuple[ScoreFormTemporaryCleanupFailure, ...],
    ) -> None:
        super().__init__(message)
        self.temporary_path = temporary_path
        self.cleanup_failures = cleanup_failures


def _stage_history(
    path: Path, headers: list[str], rows: list[dict[str, object]]
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            newline="",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
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
                cleanup_failures.append(
                    ScoreFormTemporaryCleanupFailure(temp_path, path, cleanup_error)
                )
        staged_error = _HistoryStageError(
            f"Could not stage {path}: {error}",
            temporary_path=temp_path,
            cleanup_failures=tuple(cleanup_failures),
        )
        staged_error.__cause__ = error
        raise staged_error


def _cleanup_staged(
    staged: Iterable[tuple[Path, Path]],
) -> tuple[ScoreFormTemporaryCleanupFailure, ...]:
    failures = []
    for temporary_path, target_path in staged:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError as error:
            failures.append(
                ScoreFormTemporaryCleanupFailure(temporary_path, target_path, error)
            )
    return tuple(failures)


def _adapt_manual_mapping(
    value: ScoreFormRoutedResult | Mapping[str, Any], workspace_root: Path
) -> ScoreFormRoutedResult:
    if isinstance(value, ScoreFormRoutedResult):
        return value
    answers = tuple(
        ScoredAnswer(answer["Q"], answer["Answer"], answer["Correct"])
        for answer in value["answers"]
    )
    manual = (
        value.get("page_num") == "manual"
        or value.get("source_file") == "plain_paper_manual_entry"
    )
    if not manual:
        raise ScoreFormRoutedResultValidationError(
            "Mutable mappings are supported only for plain-paper manual compatibility."
        )
    class_id, student_id = value["class_id"], value["student_id"]
    last_name, first_name, period = (
        value.get("last_name", ""),
        value.get("first_name", ""),
        value.get("period", ""),
    )
    if not (last_name or first_name or period):
        try:
            from scoreform.roster import load_roster

            roster = load_roster(core_class_roster_path(workspace_root, class_id))
            if roster is None:
                raise ValueError("Roster is unavailable.")
            student = next(
                item for item in roster["students"] if item["student_id"] == student_id
            )
            last_name, first_name, period = (
                student["last_name"],
                student["first_name"],
                student["period"],
            )
        except Exception:
            pass
    return ScoreFormRoutedResult(
        result_origin="plain_paper_manual",
        class_id=class_id,
        assignment_id=value["assignment_id"],
        student_id=student_id,
        last_name=last_name,
        first_name=first_name,
        period=period,
        page_display="manual",
        score=value["score"],
        total_points=value["total_points"],
        answers=answers,
        source_file="plain_paper_manual_entry",
    )


def _export_result_models(
    results: Sequence[ScoreFormRoutedResult | Mapping[str, Any]],
    *,
    workspace_root: Path,
    explicit_output_file: Path | None = None,
) -> ScoreFormAttemptExportBatch:
    validated = tuple(_adapt_manual_mapping(value, workspace_root) for value in results)
    review_results = tuple(
        result for result in validated if result.result_origin == "scan_review_manual"
    )
    if review_results and explicit_output_file is None:
        try:
            global_links = _managed_review_result_links(workspace_root)
            for result in review_results:
                matches = global_links.get(result.source_file, [])
                if len(matches) > 1:
                    raise ScoreFormRoutedResultIntegrityError(
                        "Managed histories contain duplicate scan-review failure links."
                    )
                if matches and not _same_exported_content(matches[0][0], result):
                    raise ScoreFormRoutedResultIntegrityError(
                        "Contradictory global reuse of a scan-review failure link."
                    )
        except Exception as error:
            affected = tuple(
                sorted({(item.class_id, item.assignment_id) for item in review_results})
            )
            first = review_results[0]
            return ScoreFormAttemptExportBatch(
                failures=(
                    ScoreFormAttemptExportFailure(
                        first.class_id,
                        first.assignment_id,
                        scoreform_work_paths(
                            workspace_root, first.class_id, first.assignment_id
                        ).results_path,
                        str(error),
                        error,
                        stage="integrity",
                        affected_targets=affected,
                    ),
                )
            )
    groups = (
        {("explicit", "explicit"): list(validated)}
        if explicit_output_file is not None
        else {}
    )
    if explicit_output_file is None:
        for result in validated:
            groups.setdefault((result.class_id, result.assignment_id), []).append(
                result
            )
    plans = []
    failures = []
    for key, target_results in sorted(groups.items()):
        class_id, assignment_id = key
        path = explicit_output_file
        managed_width = None
        try:
            if path is None:
                paths = scoreform_work_paths(workspace_root, class_id, assignment_id)
                if (
                    paths.work_root.is_symlink()
                    or not paths.work_root.is_dir()
                    or paths.assignment_path.is_symlink()
                    or not paths.assignment_path.is_file()
                ):
                    raise ScoreFormRoutedResultReadError(
                        "Managed assignment target does not exist."
                    )
                assignment = load_assignment(paths.assignment_path)
                if (
                    assignment is None
                    or assignment.get("assignment_id") != assignment_id
                ):
                    raise ScoreFormRoutedResultReadError(
                        "Managed assignment is invalid."
                    )
                managed_width = assignment["question_count"]
                path = paths.results_path
            assert path is not None
            if path.exists() and path.is_symlink():
                raise ScoreFormRoutedResultReadError(
                    "Routed results destination cannot be a symlink."
                )
            existing, old_width, legacy_header_order = _read_history(path)
            if managed_width is not None:
                if (
                    old_width not in {0, managed_width}
                    or any(
                        item.total_points != managed_width for item in target_results
                    )
                    or any(
                        model.class_id != class_id
                        or model.assignment_id != assignment_id
                        or model.total_points != managed_width
                        for model, _attempt, _stamp in existing
                    )
                ):
                    raise ScoreFormRoutedResultIntegrityError(
                        "Managed result question width disagrees with the assignment."
                    )
                width = managed_width
            else:
                width = max(
                    [old_width, *(item.total_points for item in target_results)],
                    default=0,
                )
            plans.append(
                (
                    key,
                    path,
                    target_results,
                    existing,
                    width,
                    legacy_header_order,
                )
            )
        except Exception as error:
            target = path or Path(".")
            affected = tuple(
                sorted({(item.class_id, item.assignment_id) for item in target_results})
            )
            failures.append(
                ScoreFormAttemptExportFailure(
                    class_id,
                    assignment_id,
                    target,
                    str(error),
                    error,
                    stage="preflight",
                    affected_targets=affected,
                )
            )
    if failures:
        return ScoreFormAttemptExportBatch(failures=tuple(failures))

    timestamp = datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat()
    prepared = []
    present = []
    for key, path, target_results, existing, width, legacy_header_order in plans:
        affected = tuple(
            sorted({(item.class_id, item.assignment_id) for item in target_results})
        )
        failure_class = (
            affected[0][0] if len({item[0] for item in affected}) == 1 else "multiple"
        )
        failure_assignment = (
            affected[0][1] if len({item[1] for item in affected}) == 1 else "multiple"
        )
        existing_export_ids: dict[
            tuple[str, str], tuple[ScoreFormRoutedResult, int]
        ] = {}
        existing_review_ids = {}
        for model, attempt, _stamp in existing:
            if model.result_origin == "scan_review_manual":
                if model.source_file in existing_review_ids:
                    integrity_error = ScoreFormRoutedResultIntegrityError(
                        "Existing history contains a duplicate scan-review failure link."
                    )
                    failures.append(
                        ScoreFormAttemptExportFailure(
                            failure_class,
                            failure_assignment,
                            path,
                            str(integrity_error),
                            integrity_error,
                            stage="integrity",
                            affected_targets=affected,
                        )
                    )
                    break
                existing_review_ids[model.source_file] = (model, attempt)
                continue
            if model.result_origin != "pds2_scan":
                continue
            export_id = pds2_result_content_key(model)
            existing_prior = existing_export_ids.get(export_id)
            if existing_prior is not None:
                if not pds2_results_semantically_equivalent(
                    existing_prior[0], model
                ):
                    integrity_error = ScoreFormRoutedResultIntegrityError(
                        "Existing history contradicts a source_sha256 + issuance_id key."
                    )
                    failures.append(
                        ScoreFormAttemptExportFailure(
                            failure_class,
                            failure_assignment,
                            path,
                            str(integrity_error),
                            integrity_error,
                            stage="integrity",
                            affected_targets=affected,
                        )
                    )
                    break
                if attempt < existing_prior[1]:
                    existing_export_ids[export_id] = (model, attempt)
                continue
            existing_export_ids[export_id] = (model, attempt)
        if failures:
            break
        unique_incoming = []
        incoming_ids: dict[tuple[str, str], ScoreFormRoutedResult] = {}
        incoming_review_ids: dict[str, ScoreFormRoutedResult] = {}
        for result in target_results:
            if result.result_origin == "scan_review_manual":
                prior_review = incoming_review_ids.get(result.source_file)
                if prior_review is None:
                    incoming_review_ids[result.source_file] = result
                    unique_incoming.append(result)
                elif prior_review != result:
                    integrity_error = ScoreFormRoutedResultIntegrityError(
                        "Incoming transaction contradicts a scan-review failure link."
                    )
                    failures.append(
                        ScoreFormAttemptExportFailure(
                            failure_class,
                            failure_assignment,
                            path,
                            str(integrity_error),
                            integrity_error,
                            stage="integrity",
                            affected_targets=affected,
                        )
                    )
                continue
            if result.result_origin != "pds2_scan":
                unique_incoming.append(result)
                continue
            export_id = pds2_result_content_key(result)
            incoming_prior = incoming_ids.get(export_id)
            if incoming_prior is None:
                incoming_ids[export_id] = result
                unique_incoming.append(result)
            elif not pds2_results_semantically_equivalent(incoming_prior, result):
                integrity_error = ScoreFormRoutedResultIntegrityError(
                    "Incoming transaction contradicts source_sha256 + issuance_id."
                )
                failures.append(
                    ScoreFormAttemptExportFailure(
                        failure_class,
                        failure_assignment,
                        path,
                        str(integrity_error),
                        integrity_error,
                        stage="integrity",
                        affected_targets=affected,
                    )
                )
                break
        if failures:
            break
        counts: dict[tuple[str, str, str], int] = {}
        for model, attempt, _stamp in existing:
            attempt_key = (model.class_id, model.assignment_id, model.student_id)
            counts[attempt_key] = max(counts.get(attempt_key, 0), attempt)
        rows = [
            _result_row(model, width, attempt, stamp)
            for model, attempt, stamp in existing
        ]
        pending = []
        for result in unique_incoming:
            if result.result_origin == "pds2_scan":
                match = existing_export_ids.get(pds2_result_content_key(result))
            elif result.result_origin == "scan_review_manual":
                match = existing_review_ids.get(result.source_file)
            else:
                match = None
            if match is not None:
                equivalent = (
                    pds2_results_semantically_equivalent(match[0], result)
                    if result.result_origin == "pds2_scan"
                    else _same_exported_content(match[0], result)
                )
                if not equivalent:
                    integrity_error = ScoreFormRoutedResultIntegrityError(
                        "Contradictory reuse of an existing result identity."
                    )
                    failures.append(
                        ScoreFormAttemptExportFailure(
                            failure_class,
                            failure_assignment,
                            path,
                            str(integrity_error),
                            integrity_error,
                            stage="integrity",
                            affected_targets=affected,
                        )
                    )
                    break
                recorded_result = (
                    match[0] if result.result_origin == "pds2_scan" else result
                )
                present.append(
                    ScoreFormExportedAttempt(recorded_result, path, match[1])
                )
                continue
            attempt_key = (result.class_id, result.assignment_id, result.student_id)
            attempt = counts.get(attempt_key, 0) + 1
            counts[attempt_key] = attempt
            rows.append(_result_row(result, width, attempt, timestamp))
            pending.append(ScoreFormExportedAttempt(result, path, attempt))
        prepared.append(
            (
                key,
                path,
                routed_results_v2_headers(width),
                rows,
                tuple(pending),
                affected,
                failure_class,
                failure_assignment,
                legacy_header_order,
            )
        )
    if failures:
        return ScoreFormAttemptExportBatch(
            already_present_attempts=tuple(present),
            failures=tuple(failures),
            output_paths=tuple(dict.fromkeys(item.output_path for item in present)),
        )

    staged = []
    for prepared_target in prepared:
        (
            _key,
            path,
            headers,
            rows,
            pending_attempts,
            affected,
            failure_class,
            failure_assignment,
            legacy_header_order,
        ) = prepared_target
        if not pending_attempts and not legacy_header_order:
            continue
        try:
            temporary_path = _stage_history(path, headers, rows)
            staged.append((temporary_path, prepared_target))
        except Exception as error:
            stage_cleanup = getattr(error, "cleanup_failures", ())
            cleanup = (
                *stage_cleanup,
                *_cleanup_staged((item[0], item[1][1]) for item in staged),
            )
            failures.append(
                ScoreFormAttemptExportFailure(
                    failure_class,
                    failure_assignment,
                    path,
                    str(error),
                    error,
                    stage="staging",
                    affected_targets=affected,
                    cleanup_failures=tuple(cleanup),
                )
            )
            for other in prepared:
                if other is prepared_target or (not other[4] and not other[8]):
                    continue
                not_attempted = ScoreFormRoutedResultWriteError(
                    "Target was not attempted because transaction staging failed."
                )
                failures.append(
                    ScoreFormAttemptExportFailure(
                        other[6],
                        other[7],
                        other[1],
                        str(not_attempted),
                        not_attempted,
                        stage="not_attempted",
                        affected_targets=other[5],
                    )
                )
            break
    if failures:
        return ScoreFormAttemptExportBatch(
            already_present_attempts=tuple(present),
            failures=tuple(failures),
            output_paths=tuple(dict.fromkeys(item.output_path for item in present)),
        )

    appended: list[ScoreFormExportedAttempt] = []
    written = []
    for index, (temporary_path, prepared_target) in enumerate(staged):
        (
            _key,
            path,
            _headers,
            _rows,
            pending_attempts,
            affected,
            failure_class,
            failure_assignment,
            _legacy_header_order,
        ) = prepared_target
        try:
            os.replace(temporary_path, path)
        except OSError as error:
            write_error = ScoreFormRoutedResultWriteError(
                f"Could not replace {path}: {error}"
            )
            write_error.__cause__ = error
            cleanup = _cleanup_staged((item[0], item[1][1]) for item in staged[index:])
            failures.append(
                ScoreFormAttemptExportFailure(
                    failure_class,
                    failure_assignment,
                    path,
                    str(write_error),
                    write_error,
                    stage="replacement",
                    affected_targets=affected,
                    cleanup_failures=cleanup,
                )
            )
            for _later_temp, later in staged[index + 1 :]:
                not_attempted = ScoreFormRoutedResultWriteError(
                    "Target was not attempted because an earlier replacement failed."
                )
                failures.append(
                    ScoreFormAttemptExportFailure(
                        later[6],
                        later[7],
                        later[1],
                        str(not_attempted),
                        not_attempted,
                        stage="not_attempted",
                        affected_targets=later[5],
                    )
                )
            break
        appended.extend(pending_attempts)
        written.append(path)
    output_paths = tuple(
        dict.fromkeys([*written, *(item.output_path for item in present)])
    )
    return ScoreFormAttemptExportBatch(
        tuple(appended), tuple(present), tuple(failures), output_paths
    )


def _record_result_export_diagnostics(
    workspace_root: Path,
    batch: ScoreFormAttemptExportBatch,
) -> None:
    """Record batch-level persistence outcomes without student/result content."""
    if batch.failures:
        first = batch.failures[0]
        if batch.appended_attempts:
            try_emit_diagnostic_event(
                workspace_root,
                component="results",
                workflow="persist_results",
                stage="post_write_verify",
                outcome="partial_success",
                code="result_persistence_partial_success",
                exception=first.error,
            )
            return

        class_id = (
            first.class_id
            if first.class_id not in {"multiple", "explicit"}
            else None
        )
        assignment_id = (
            first.assignment_id
            if first.assignment_id not in {"multiple", "explicit"}
            else None
        )
        stage = (
            "preflight"
            if first.stage in {"preflight", "not_attempted"}
            else "write_record"
        )
        try_emit_diagnostic_event(
            workspace_root,
            component="results",
            workflow="persist_results",
            stage=stage,
            outcome="failure",
            code="result_persistence_failed",
            class_id=class_id,
            assignment_id=assignment_id,
            exception=first.error,
        )
        return

    identities = sorted(
        {
            (item.result.class_id, item.result.assignment_id)
            for item in batch.appended_attempts
        }
    )
    for class_id, assignment_id in identities:
        try_emit_diagnostic_event(
            workspace_root,
            component="results",
            workflow="persist_results",
            stage="verify_record",
            outcome="success",
            code="result_persistence_verified",
            class_id=class_id,
            assignment_id=assignment_id,
        )


def export_scoreform_attempts(
    assembly: Any,
    *,
    workspace_root: Path,
    explicit_output_file: Path | None = None,
) -> ScoreFormAttemptExportBatch:
    """Export a typed assembly batch without interpreting dispatch outcomes."""
    results = tuple(attempt.routed_result for attempt in assembly.completed_attempts)
    if not results:
        return ScoreFormAttemptExportBatch()
    root = Path(workspace_root)
    batch = _export_result_models(
        results,
        workspace_root=root,
        explicit_output_file=Path(explicit_output_file)
        if explicit_output_file is not None
        else None,
    )
    _record_result_export_diagnostics(root, batch)
    return batch


def export_scoreform_result_models(
    results: Sequence[ScoreFormRoutedResult], *, workspace_root: Path
) -> ScoreFormAttemptExportBatch:
    """Export validated typed results through the shared schema-v2 writer."""
    root = Path(workspace_root)
    batch = _export_result_models(tuple(results), workspace_root=root)
    _record_result_export_diagnostics(root, batch)
    return batch


def export_routed_results(
    all_results: Sequence[ScoreFormRoutedResult | Mapping[str, Any]],
    workspace_root: str | os.PathLike[str] | None = None,
) -> bool:
    """Compatibility Boolean wrapper over the strict shared v2 writer."""
    if not all_results:
        print("No results to export.")
        return False
    root = (
        Path(workspace_root)
        if workspace_root is not None
        else workspace.get_scoreform_workspace_root()
    )
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
