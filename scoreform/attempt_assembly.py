"""Authoritative post-dispatch assembly of complete ScoreForm issuances."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pds_core.identifiers import validate_identifier
from pds_core.module_dispatch import RouteDispatchSuccess
from pds_core.routing_models import PDS2_SCHEMA

from scoreform.answer_sheet_persistence import load_answer_sheet_record_set
from scoreform.answer_sheet_records import (
    validate_artifact_id,
    validate_generation_id,
    validate_issuance_id,
    validate_page_id,
)
from scoreform.answer_sheet_routes import validate_route_id
from scoreform.layouts import require_layout
from scoreform.module_errors import (
    ScoreFormAttemptAssemblyError,
    ScoreFormAttemptConflictError,
    ScoreFormDuplicatePageError,
    ScoreFormIncompleteAttemptError,
)
from scoreform.page_scoring import (
    ScoreFormPageDispatchResult,
    validate_page_dispatch_result,
)
from scoreform.pds2_scan_dispatch import Pds2ScanDispatchResult
from scoreform.pds_contract import (
    ANSWER_SHEET_PAGE_CONTRACT_VERSION,
    ANSWER_SHEET_PAGE_RECORD_KIND,
    SCOREFORM_MODULE_ID,
)
from scoreform.results import (
    ScoreFormAttemptExportBatch,
    ScoreFormRoutedResult,
    pds2_result_content_key,
    pds2_results_semantically_equivalent,
)
from scoreform.retained_page import validate_canonical_retained_source_relative_path
from scoreform.work_paths import scoreform_work_ref

AssemblyFailureCategory = Literal[
    "missing_pages", "duplicate_page", "duplicate_route", "conflicting_duplicate",
    "inconsistent_issuance", "unexpected_page", "invalid_page_order",
    "invalid_question_coverage", "invalid_result_identity",
]
ASSEMBLY_FAILURE_CATEGORIES = frozenset({
    "missing_pages", "duplicate_page", "duplicate_route", "conflicting_duplicate",
    "inconsistent_issuance", "unexpected_page", "invalid_page_order",
    "invalid_question_coverage", "invalid_result_identity",
})
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _positive_numbers(values: object, name: str) -> tuple[int, ...]:
    if not isinstance(values, tuple):
        raise TypeError(f"{name} must be a tuple.")
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in values):
        raise ValueError(f"{name} must contain positive non-Boolean integers.")
    return values


def _string_tuple(values: object, name: str) -> tuple[str, ...]:
    if not isinstance(values, tuple) or any(not isinstance(value, str) or not value for value in values):
        raise TypeError(f"{name} must contain nonempty strings in a tuple.")
    return values


@dataclass(frozen=True, slots=True)
class ScoreFormPageObservation:
    page_result: ScoreFormPageDispatchResult

    def __post_init__(self) -> None:
        if not isinstance(self.page_result, ScoreFormPageDispatchResult):
            raise TypeError("page_result must be a ScoreFormPageDispatchResult.")


@dataclass(frozen=True, slots=True)
class ScoreFormInvalidPageObservation:
    """One malformed ScoreForm success retained outside issuance-level assembly."""

    page_result: ScoreFormPageDispatchResult
    source_page_number: int
    route_id: str | None
    raw_route_id: object
    raw_page_id: object
    raw_issuance_id: object
    raw_generation_id: object
    raw_artifact_id: object
    raw_class_id: object
    raw_assignment_id: object
    raw_student_id: object
    raw_source_scan_id: object
    raw_retained_source_relative_path: object
    raw_source_sha256: object
    source_scan_id: str
    retained_source_relative_path: str
    source_sha256: str
    diagnostic_paths: tuple[str, ...]
    error: ScoreFormAttemptAssemblyError

    def __post_init__(self) -> None:
        if not isinstance(self.page_result, ScoreFormPageDispatchResult):
            raise TypeError("page_result must retain the malformed module result.")
        if (
            isinstance(self.source_page_number, bool)
            or not isinstance(self.source_page_number, int)
            or self.source_page_number < 1
        ):
            raise ValueError("source_page_number must be a positive integer.")
        if self.route_id is not None:
            validate_route_id(self.route_id)
        validate_identifier(self.source_scan_id, "source_scan_id")
        validate_canonical_retained_source_relative_path(
            self.retained_source_relative_path
        )
        if not isinstance(self.source_sha256, str) or not _SHA256.fullmatch(
            self.source_sha256
        ):
            raise ValueError("source_sha256 must be lowercase hexadecimal SHA-256.")
        if (
            not isinstance(self.diagnostic_paths, tuple)
            or any(not isinstance(path, str) or not path for path in self.diagnostic_paths)
            or len(self.diagnostic_paths) != len(set(self.diagnostic_paths))
        ):
            raise ValueError("diagnostic_paths must be unique nonempty strings.")
        if type(self.error) is not ScoreFormAttemptAssemblyError:
            raise TypeError("Invalid observations require a typed assembly error.")
        raw_values = (
            self.raw_route_id, self.raw_page_id, self.raw_issuance_id,
            self.raw_generation_id, self.raw_artifact_id, self.raw_class_id,
            self.raw_assignment_id, self.raw_student_id,
            self.raw_source_scan_id, self.raw_retained_source_relative_path,
            self.raw_source_sha256,
        )
        actual_values = (
            self.page_result.route_id, self.page_result.page_id,
            self.page_result.issuance_id, self.page_result.generation_id,
            self.page_result.artifact_id, self.page_result.class_id,
            self.page_result.assignment_id, self.page_result.student_id,
            self.page_result.source_scan_id,
            self.page_result.retained_source_relative_path,
            self.page_result.source_sha256,
        )
        if any(raw is not actual for raw, actual in zip(raw_values, actual_values)):
            raise ValueError("Raw invalid-observation values must remain exact.")


@dataclass(frozen=True, slots=True)
class ScoreFormAttemptAssemblyFailure:
    category: AssemblyFailureCategory
    class_id: str
    assignment_id: str
    student_id: str
    issuance_id: str
    generation_id: str
    artifact_id: str
    source_scan_id: str
    retained_source_relative_path: str
    source_sha256: str
    reason: str
    error: ScoreFormAttemptAssemblyError
    expected_page_ids: tuple[str, ...] = ()
    observed_page_ids: tuple[str, ...] = ()
    observed_route_ids: tuple[str, ...] = ()
    expected_logical_pages: tuple[int, ...] = ()
    observed_logical_pages: tuple[int, ...] = ()
    missing_page_ids: tuple[str, ...] = ()
    missing_logical_pages: tuple[int, ...] = ()
    duplicate_page_ids: tuple[str, ...] = ()
    duplicate_route_ids: tuple[str, ...] = ()
    conflicting_page_ids: tuple[str, ...] = ()
    source_page_numbers: tuple[int, ...] = ()
    diagnostic_paths: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.category not in ASSEMBLY_FAILURE_CATEGORIES:
            raise ValueError("Unsupported assembly failure category.")
        validate_identifier(self.class_id, "class_id")
        validate_identifier(self.assignment_id, "assignment_id")
        validate_identifier(self.student_id, "student_id")
        validate_identifier(self.source_scan_id, "source_scan_id")
        validate_issuance_id(self.issuance_id)
        validate_generation_id(self.generation_id)
        validate_artifact_id(self.artifact_id)
        try:
            validate_canonical_retained_source_relative_path(
                self.retained_source_relative_path
            )
        except (TypeError, ValueError) as error:
            raise ValueError(
                f"retained_source_relative_path is not canonical: {error}"
            ) from error
        if not isinstance(self.source_sha256, str) or not _SHA256.fullmatch(self.source_sha256):
            raise ValueError("source_sha256 must be lowercase hexadecimal SHA-256.")
        for value in (*self.expected_page_ids, *self.observed_page_ids,
                      *self.missing_page_ids, *self.duplicate_page_ids,
                      *self.conflicting_page_ids):
            validate_page_id(value)
        for value in (*self.observed_route_ids, *self.duplicate_route_ids):
            validate_route_id(value)
        for name in (
            "expected_page_ids", "observed_page_ids", "observed_route_ids",
            "missing_page_ids", "duplicate_page_ids", "duplicate_route_ids",
            "conflicting_page_ids", "diagnostic_paths",
        ):
            _string_tuple(getattr(self, name), name)
        for name in (
            "expected_logical_pages", "observed_logical_pages",
            "missing_logical_pages", "source_page_numbers",
        ):
            _positive_numbers(getattr(self, name), name)
        observed_length = len(self.observed_page_ids)
        if observed_length < 1 or not (
            observed_length == len(self.observed_route_ids)
            == len(self.observed_logical_pages) == len(self.source_page_numbers)
        ):
            raise ValueError("Observed provenance collections must be nonempty and aligned.")
        if len(set(self.source_page_numbers)) != observed_length:
            raise ValueError("Observed source page numbers must be unique.")
        if self.source_page_numbers != tuple(sorted(self.source_page_numbers)):
            raise ValueError("Observed provenance must use deterministic source-page order.")
        if len(self.expected_page_ids) != len(self.expected_logical_pages):
            raise ValueError("Expected page and logical-page collections must align.")
        if self.expected_page_ids:
            if (
                len(set(self.expected_page_ids)) != len(self.expected_page_ids)
                or len(set(self.expected_logical_pages)) != len(self.expected_logical_pages)
                or self.expected_logical_pages != tuple(sorted(self.expected_logical_pages))
            ):
                raise ValueError("Expected pages must be unique and authoritatively ordered.")
        if len(self.missing_page_ids) != len(self.missing_logical_pages):
            raise ValueError("Missing page and logical-page collections must align.")
        if (
            len(set(self.missing_page_ids)) != len(self.missing_page_ids)
            or len(set(self.missing_logical_pages)) != len(self.missing_logical_pages)
        ):
            raise ValueError("Missing identities must be unique.")
        expected_pairs = dict(zip(self.expected_page_ids, self.expected_logical_pages))
        if any(
            expected_pairs.get(page_id) != logical_page
            for page_id, logical_page in zip(
                self.missing_page_ids, self.missing_logical_pages
            )
        ):
            raise ValueError("Missing identities must match authoritative expected pages.")
        missing_pairs = tuple(zip(self.missing_page_ids, self.missing_logical_pages))
        authoritative_missing = tuple(
            pair for pair in zip(self.expected_page_ids, self.expected_logical_pages)
            if pair[0] in set(self.missing_page_ids)
        )
        if missing_pairs != authoritative_missing:
            raise ValueError("Missing identities must use authoritative expected ordering.")
        duplicate_pages = _duplicates(self.observed_page_ids)
        duplicate_routes = _duplicates(self.observed_route_ids)
        duplicate_logicals = _duplicates(self.observed_logical_pages)
        duplicate_page_set = set(duplicate_pages)
        duplicate_route_set = set(duplicate_routes)
        duplicate_logical_set = set(duplicate_logicals)
        conflict_candidates = set(
            page_id for page_id, route_id, logical_page in zip(
                self.observed_page_ids, self.observed_route_ids,
                self.observed_logical_pages,
            )
            if (
                page_id in duplicate_page_set
                or route_id in duplicate_route_set
                or logical_page in duplicate_logical_set
            )
        )
        for name, values, observed_values in (
            ("duplicate_page_ids", self.duplicate_page_ids, self.observed_page_ids),
            ("duplicate_route_ids", self.duplicate_route_ids, self.observed_route_ids),
            ("conflicting_page_ids", self.conflicting_page_ids, self.observed_page_ids),
        ):
            if len(values) != len(set(values)) or not set(values).issubset(observed_values):
                raise ValueError(f"{name} must be unique and derived from observations.")
        if self.duplicate_page_ids != duplicate_pages:
            raise ValueError("duplicate_page_ids must exactly describe observed duplicates.")
        if self.duplicate_route_ids != duplicate_routes:
            raise ValueError("duplicate_route_ids must exactly describe observed duplicates.")
        if not set(self.conflicting_page_ids).issubset(conflict_candidates):
            raise ValueError("conflicting_page_ids must derive from duplicate observations.")
        duplicate_category = self.category in {
            "duplicate_page", "duplicate_route", "conflicting_duplicate"
        }
        if not duplicate_category and (
            duplicate_pages or duplicate_routes or duplicate_logicals
            or self.conflicting_page_ids
        ):
            raise ValueError("Only duplicate categories may contain duplicate observations.")
        if self.category == "missing_pages":
            if not self.missing_page_ids or self.duplicate_page_ids or self.duplicate_route_ids:
                raise ValueError("Missing-page failures require only missing identities.")
        elif self.missing_page_ids or self.missing_logical_pages:
            raise ValueError("Only missing-page failures may contain missing identities.")
        if self.category == "duplicate_page" and not self.duplicate_page_ids:
            raise ValueError("Duplicate-page failures require duplicate page IDs.")
        if self.category == "duplicate_route" and not self.duplicate_route_ids:
            raise ValueError("Duplicate-route failures require duplicate route IDs.")
        if self.category == "conflicting_duplicate" and (
            not self.conflicting_page_ids
            or not (duplicate_pages or duplicate_routes or duplicate_logicals)
        ):
            raise ValueError("Conflicting duplicates require observed conflicting identities.")
        if self.category != "conflicting_duplicate" and self.conflicting_page_ids:
            raise ValueError("Only conflicting duplicates may name conflicting page IDs.")
        if len(self.diagnostic_paths) != len(set(self.diagnostic_paths)):
            raise ValueError("diagnostic_paths must not contain duplicates.")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("reason must be a nonempty string.")
        if not isinstance(self.error, ScoreFormAttemptAssemblyError):
            raise TypeError("error must be a ScoreFormAttemptAssemblyError.")
        expected_error = {
            "missing_pages": ScoreFormIncompleteAttemptError,
            "duplicate_page": ScoreFormDuplicatePageError,
            "duplicate_route": ScoreFormDuplicatePageError,
            "conflicting_duplicate": ScoreFormAttemptConflictError,
        }.get(self.category, ScoreFormAttemptAssemblyError)
        if type(self.error) is not expected_error:
            raise TypeError("Assembly failure category and error type disagree.")


@dataclass(frozen=True, slots=True)
class ScoreFormAssembledAttempt:
    routed_result: ScoreFormRoutedResult
    observations: tuple[ScoreFormPageObservation, ...]

    def __post_init__(self) -> None:
        result = self.routed_result
        if not isinstance(result, ScoreFormRoutedResult) or result.result_origin != "pds2_scan":
            raise TypeError("An assembled attempt requires a pds2_scan routed result.")
        if not isinstance(self.observations, tuple) or not self.observations:
            raise ValueError("An assembled attempt requires observations.")
        if any(not isinstance(item, ScoreFormPageObservation) for item in self.observations):
            raise TypeError("observations must contain ScoreFormPageObservation values.")
        pages = tuple(item.page_result for item in self.observations)
        if any(page.issuance_id != result.issuance_id for page in pages):
            raise ValueError("Every observation must use the assembled issuance.")
        if any(
            (
                page.class_id, page.assignment_id, page.student_id,
                page.generation_id, page.artifact_id, page.source_scan_id,
                page.retained_source_relative_path, page.source_sha256,
            ) != (
                result.class_id, result.assignment_id, result.student_id,
                result.generation_id, result.artifact_id, result.source_scan_id,
                result.retained_source_relative_path, result.source_sha256,
            )
            for page in pages
        ):
            raise ValueError("Observation identity and provenance must match routed result.")
        if tuple(page.logical_page for page in pages) != tuple(range(1, len(pages) + 1)):
            raise ValueError("Observations must be ordered by authoritative logical page.")
        expected = (
            tuple(page.page_id for page in pages), tuple(page.route_id for page in pages),
            tuple(page.logical_page for page in pages),
            tuple(page.source_page_number for page in pages),
            sum(page.score for page in pages), sum(page.total_points for page in pages),
            tuple(answer for page in pages for answer in page.answers),
            pages[0].generation_id, pages[0].artifact_id, pages[0].source_scan_id,
            pages[0].retained_source_relative_path, pages[0].source_sha256,
        )
        actual = (
            result.page_ids, result.route_ids, result.logical_pages,
            result.source_page_numbers, result.score, result.total_points,
            result.answers, result.generation_id, result.artifact_id,
            result.source_scan_id, result.retained_source_relative_path,
            result.source_sha256,
        )
        if actual != expected:
            raise ValueError("Assembled observations do not exactly match routed result.")

    @property
    def issuance_id(self) -> str:
        assert self.routed_result.issuance_id is not None
        return self.routed_result.issuance_id


@dataclass(frozen=True, slots=True)
class ScoreFormAttemptAssemblyBatch:
    dispatch_result: Pds2ScanDispatchResult
    completed_attempts: tuple[ScoreFormAssembledAttempt, ...] = ()
    failures: tuple[ScoreFormAttemptAssemblyFailure, ...] = ()
    invalid_observations: tuple[ScoreFormInvalidPageObservation, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.dispatch_result, Pds2ScanDispatchResult):
            raise TypeError("dispatch_result must be a Pds2ScanDispatchResult.")
        if not isinstance(self.completed_attempts, tuple) or any(
            not isinstance(item, ScoreFormAssembledAttempt) for item in self.completed_attempts
        ):
            raise TypeError("completed_attempts must be an immutable typed tuple.")
        if not isinstance(self.failures, tuple) or any(
            not isinstance(item, ScoreFormAttemptAssemblyFailure) for item in self.failures
        ):
            raise TypeError("failures must be an immutable typed tuple.")
        if not isinstance(self.invalid_observations, tuple) or any(
            not isinstance(item, ScoreFormInvalidPageObservation)
            for item in self.invalid_observations
        ):
            raise TypeError("invalid_observations must be an immutable typed tuple.")
        invalid_order = tuple(
            item.source_page_number for item in self.invalid_observations
        )
        if (
            len(invalid_order) != len(set(invalid_order))
            or invalid_order != tuple(sorted(invalid_order))
        ):
            raise ValueError("Invalid observations must use unique source-page order.")
        completed_ids = tuple(item.issuance_id for item in self.completed_attempts)
        failed_ids = tuple(item.issuance_id for item in self.failures)
        if len(completed_ids) != len(set(completed_ids)):
            raise ValueError("Completed issuances must not repeat.")
        if len(failed_ids) != len(set(failed_ids)):
            raise ValueError("Failure candidates must not repeat.")
        if set(completed_ids) & set(failed_ids):
            raise ValueError("An issuance cannot be both completed and failed.")
        order = tuple(
            (min(item.routed_result.source_page_numbers), item.issuance_id)
            for item in self.completed_attempts
        )
        if order != tuple(sorted(order)):
            raise ValueError("Completed attempts must use deterministic source order.")
        invalid_result_ids = {
            id(item.page_result) for item in self.invalid_observations
        }
        clean_results = tuple(
            page.scoreform_page_score for page in self.dispatch_result.pages
            if (
                page.scoreform_page_score is not None
                and id(page.scoreform_page_score) not in invalid_result_ids
            )
        )
        clean_by_issuance = defaultdict(list)
        clean_tuples_by_issuance: dict[
            str, dict[tuple[str, str, int, int], ScoreFormPageDispatchResult]
        ] = defaultdict(dict)
        for item in clean_results:
            clean_by_issuance[item.issuance_id].append(item)
            clean_tuples_by_issuance[item.issuance_id][(
                item.page_id, item.route_id, item.logical_page,
                item.source_page_number,
            )] = item
        for attempt in self.completed_attempts:
            observed = tuple(item.page_result for item in attempt.observations)
            clean = tuple(clean_by_issuance.get(attempt.issuance_id, ()))
            if (
                len(observed) != len(clean)
                or any(
                    not any(candidate is page for candidate in clean)
                    for page in observed
                )
                or {id(page) for page in observed} != {id(page) for page in clean}
            ):
                raise ValueError(
                    "Completed attempts must trace to the exact clean dispatch observations."
                )
        for failure in self.failures:
            failure_provenance: tuple[tuple[str, str, int, int], ...] = tuple(
                zip(
                    failure.observed_page_ids, failure.observed_route_ids,
                    failure.observed_logical_pages, failure.source_page_numbers,
                )
            )
            clean_for_failure = clean_tuples_by_issuance.get(failure.issuance_id, {})
            matched = tuple(clean_for_failure.get(item) for item in failure_provenance)
            if any(item is None for item in matched):
                raise ValueError(
                    "Failure provenance must trace to exact clean dispatch observations."
                )
            if any(
                (
                    item.class_id, item.assignment_id, item.student_id,
                    item.generation_id, item.artifact_id, item.source_scan_id,
                    item.retained_source_relative_path, item.source_sha256,
                ) != (
                    failure.class_id, failure.assignment_id, failure.student_id,
                    failure.generation_id, failure.artifact_id,
                    failure.source_scan_id,
                    failure.retained_source_relative_path, failure.source_sha256,
                )
                for item in matched if item is not None
            ):
                raise ValueError(
                    "Failure identity must match its exact clean dispatch observations."
                )
        wrappers = {
            page.source_page_number: page for page in self.dispatch_result.pages
        }
        for invalid in self.invalid_observations:
            wrapper = wrappers.get(invalid.source_page_number)
            outcome = None if wrapper is None else wrapper.dispatch_outcome
            retained = self.dispatch_result.retained_source
            if (
                not isinstance(outcome, RouteDispatchSuccess)
                or outcome.profile.module_id != SCOREFORM_MODULE_ID
                or outcome.module_result is not invalid.page_result
                or outcome.request.source_page_number != invalid.source_page_number
                or outcome.request.locator.route_id != invalid.route_id
                or retained is None
                or (
                    invalid.source_scan_id,
                    invalid.retained_source_relative_path,
                    invalid.source_sha256,
                ) != (
                    retained.source_scan_id,
                    retained.retained_source_relative_path,
                    retained.source_sha256,
                )
            ):
                raise ValueError(
                    "Invalid observations must trace to exact ScoreForm dispatch results."
                )


@dataclass(frozen=True, slots=True)
class ScoreFormRoutedScoringBatch:
    dispatch_result: Pds2ScanDispatchResult
    assembly_result: ScoreFormAttemptAssemblyBatch
    export_result: ScoreFormAttemptExportBatch | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.dispatch_result, Pds2ScanDispatchResult):
            raise TypeError("dispatch_result must be a Pds2ScanDispatchResult.")
        if not isinstance(self.assembly_result, ScoreFormAttemptAssemblyBatch):
            raise TypeError("assembly_result must be a ScoreFormAttemptAssemblyBatch.")
        if self.assembly_result.dispatch_result is not self.dispatch_result:
            raise ValueError("Assembly must retain the exact dispatch result.")
        if self.export_result is None:
            return
        if not isinstance(self.export_result, ScoreFormAttemptExportBatch):
            raise TypeError("export_result must be a ScoreFormAttemptExportBatch.")
        completed = tuple(
            item.routed_result for item in self.assembly_result.completed_attempts
        )
        if any(
            item.result not in completed
            for item in self.export_result.appended_attempts
        ):
            raise ValueError(
                "Every appended attempt must exactly match completed assembly."
            )
        for item in self.export_result.already_present_attempts:
            result = item.result
            if result.result_origin == "pds2_scan":
                if not any(
                    pds2_result_content_key(candidate)
                    == pds2_result_content_key(result)
                    and pds2_results_semantically_equivalent(candidate, result)
                    for candidate in completed
                ):
                    raise ValueError(
                        "Every already-present PDS2 attempt must semantically "
                        "match completed assembly."
                    )
            elif result not in completed:
                raise ValueError(
                    "Every already-present manual attempt must exactly match "
                    "completed assembly."
                )

    @property
    def status(self) -> str:
        dispatch = self.dispatch_result
        if dispatch.file_error is not None:
            return "file_failure"
        exported = self.export_result
        if exported is not None and exported.failures:
            return "export_failure"
        observed = 0 if exported is None else (
            len(exported.appended_attempts) + len(exported.already_present_attempts)
        )
        if (
            not self.assembly_result.completed_attempts
            and not self.assembly_result.failures
            and not self.assembly_result.invalid_observations
            and dispatch.scoreform_page_score_count == 0
            and dispatch.complete_success
        ):
            return "dispatch_only_success"
        has_page_failures = not dispatch.complete_success
        if (
            observed and not has_page_failures
            and not self.assembly_result.failures
            and not self.assembly_result.invalid_observations
        ):
            return "full_success"
        if observed:
            return "partial_success"
        if (
            dispatch.batch_status == "integration_failure"
            or self.assembly_result.invalid_observations
        ):
            return "integration_failure"
        return "zero_success"

    def exit_code(self) -> int:
        return 0 if self.status in {"full_success", "dispatch_only_success"} else 1


def format_routed_scoring_summary(batch: ScoreFormRoutedScoringBatch) -> str:
    assembly = batch.assembly_result
    exported = batch.export_result
    lines = [
        "ScoreForm routed scoring summary",
        f"Status: {batch.status}",
        f"Issuance candidates: {len(assembly.completed_attempts) + len(assembly.failures)}",
        f"Completed attempts: {len(assembly.completed_attempts)}",
        f"Assembly failures: {len(assembly.failures)}",
        f"Invalid page observations: {len(assembly.invalid_observations)}",
    ]
    if exported is not None:
        lines.extend((
            f"Attempts appended: {len(exported.appended_attempts)}",
            f"Attempts already present: {len(exported.already_present_attempts)}",
            f"Export failures: {len(exported.failures)}",
        ))
        if (
            not exported.appended_attempts
            and exported.already_present_attempts
            and not exported.failures
        ):
            lines.append(
                "No new ScoreForm attempt was added because identical scan "
                "content was already recorded."
            )
        lines.extend(f"Output: {path}" for path in exported.output_paths)
    for failure in assembly.failures:
        lines.append(f"Assembly failure [{failure.category}] {failure.issuance_id}: {failure.reason}")
    for invalid in assembly.invalid_observations:
        lines.append(
            f"Invalid page observation [source page {invalid.source_page_number}]: "
            f"{invalid.error}"
        )
    if exported is not None:
        for export_failure in exported.failures:
            lines.append(f"Export failure: {export_failure.reason}")
            for cleanup in export_failure.cleanup_failures:
                lines.append(
                    f"Temporary cleanup failure: {cleanup.temporary_path} "
                    f"for {cleanup.target_path}: {cleanup.error}"
                )
    return "\n".join(lines)


def _typed_assembly_error(category, reason, cause=None):
    error_type = {
        "missing_pages": ScoreFormIncompleteAttemptError,
        "duplicate_page": ScoreFormDuplicatePageError,
        "duplicate_route": ScoreFormDuplicatePageError,
        "conflicting_duplicate": ScoreFormAttemptConflictError,
    }.get(category, ScoreFormAttemptAssemblyError)
    error = error_type(reason)
    if cause is not None:
        error.__cause__ = cause
    return error


def _failure(category, observed, reason, *, expected_pages=(), cause=None, **details):
    observed = tuple(sorted(observed, key=lambda item: item.source_page_number))
    first = observed[0]
    diagnostics = tuple(dict.fromkeys(path for item in observed for path in item.diagnostic_paths))
    return ScoreFormAttemptAssemblyFailure(
        category=category, class_id=first.class_id,
        assignment_id=first.assignment_id, student_id=first.student_id,
        issuance_id=first.issuance_id, generation_id=first.generation_id,
        artifact_id=first.artifact_id, source_scan_id=first.source_scan_id,
        retained_source_relative_path=first.retained_source_relative_path,
        source_sha256=first.source_sha256,
        reason=reason, error=_typed_assembly_error(category, reason, cause),
        expected_page_ids=tuple(page.page_id for page in expected_pages),
        observed_page_ids=tuple(item.page_id for item in observed),
        observed_route_ids=tuple(item.route_id for item in observed),
        expected_logical_pages=tuple(page.logical_page for page in expected_pages),
        observed_logical_pages=tuple(item.logical_page for item in observed),
        source_page_numbers=tuple(item.source_page_number for item in observed),
        diagnostic_paths=diagnostics, **details,
    )


def _invalid_observation(page, item, retained, reason, cause=None):
    if retained is None:
        raise ScoreFormAttemptAssemblyError(
            "A ScoreForm dispatch success requires retained-source provenance."
        )
    route_id = None
    try:
        candidate_route_id = page.dispatch_outcome.request.locator.route_id
        validate_route_id(candidate_route_id)
        route_id = candidate_route_id
    except (AttributeError, TypeError, ValueError):
        pass
    diagnostics = tuple(dict.fromkeys(
        path for path in (
            item.diagnostic_paths if isinstance(item.diagnostic_paths, tuple) else ()
        )
        if isinstance(path, str) and path
    ))
    return ScoreFormInvalidPageObservation(
        page_result=item, source_page_number=page.source_page_number,
        route_id=route_id, raw_route_id=item.route_id,
        raw_page_id=item.page_id, raw_issuance_id=item.issuance_id,
        raw_generation_id=item.generation_id, raw_artifact_id=item.artifact_id,
        raw_class_id=item.class_id, raw_assignment_id=item.assignment_id,
        raw_student_id=item.student_id, raw_source_scan_id=item.source_scan_id,
        raw_retained_source_relative_path=item.retained_source_relative_path,
        raw_source_sha256=item.source_sha256,
        source_scan_id=retained.source_scan_id,
        retained_source_relative_path=retained.retained_source_relative_path,
        source_sha256=retained.source_sha256,
        diagnostic_paths=diagnostics,
        error=_typed_assembly_error("invalid_result_identity", reason, cause),
    )


def _duplicates(values):
    counts = Counter(values)
    return tuple(value for value in dict.fromkeys(values) if counts[value] > 1)


def _duplicate_is_conflicting(items):
    indexes = (defaultdict(list), defaultdict(list), defaultdict(list))
    for item in items:
        indexes[0][item.page_id].append(item)
        indexes[1][item.route_id].append(item)
        indexes[2][item.logical_page].append(item)
    def content(item):
        return (
            item.route_id, item.page_id, item.issuance_id, item.generation_id,
            item.artifact_id, item.class_id, item.assignment_id, item.student_id,
            item.logical_page, item.total_pages, item.question_start,
            item.question_end, item.layout_id, item.score, item.total_points,
            item.answers, item.source_scan_id, item.retained_source_relative_path,
            item.source_sha256,
        )
    return any(
        len(group) > 1 and any(content(candidate) != content(group[0]) for candidate in group[1:])
        for index in indexes for group in index.values()
    )


def _conflicting_page_ids(items):
    conflicts = set()
    for attribute in ("page_id", "route_id", "logical_page"):
        groups = defaultdict(list)
        for item in items:
            groups[getattr(item, attribute)].append(item)
        for group in groups.values():
            if len(group) > 1:
                first = group[0]
                if any(candidate != first for candidate in group[1:]):
                    conflicts.update(candidate.page_id for candidate in group)
    return tuple(dict.fromkeys(
        item.page_id for item in items if item.page_id in conflicts
    ))


def _observation_matches_dispatch(item, wrapper, retained) -> bool:
    try:
        outcome = wrapper.dispatch_outcome
        request = outcome.request
        resolution = outcome.resolution
        registration = resolution.registration
        target = registration.target
        expected_work_ref = scoreform_work_ref(item.class_id, item.assignment_id)
        return (
            isinstance(outcome, RouteDispatchSuccess)
            and outcome.profile.module_id == SCOREFORM_MODULE_ID
            and outcome.module_result is item
            and request.locator.schema == PDS2_SCHEMA
            and request.locator.work == expected_work_ref
            and request.locator.work.module_id == SCOREFORM_MODULE_ID
            and request.locator.work.class_id == item.class_id
            and request.locator.work.work_id == item.assignment_id
            and request.locator.route_id == item.route_id
            and request.source_page_number == item.source_page_number
            and request.retained_source is retained
            and retained is not None
            and item.source_scan_id == retained.source_scan_id
            and item.retained_source_relative_path
            == retained.retained_source_relative_path
            and item.source_sha256 == retained.source_sha256
            and resolution.locator == request.locator
            and registration.locator == request.locator
            and target.record_id == item.page_id
            and target.module_id == SCOREFORM_MODULE_ID
            and target.record_kind == ANSWER_SHEET_PAGE_RECORD_KIND
            and target.contract_version == ANSWER_SHEET_PAGE_CONTRACT_VERSION
        )
    except (AttributeError, TypeError, ValueError):
        return False


def assemble_scoreform_attempts(
    dispatch_result: Pds2ScanDispatchResult,
    *,
    workspace_root: Path,
) -> ScoreFormAttemptAssemblyBatch:
    """Assemble successful ScoreForm pages only by authoritative issuance ID."""
    if not isinstance(dispatch_result, Pds2ScanDispatchResult):
        raise TypeError("dispatch_result must be a Pds2ScanDispatchResult.")
    retained = dispatch_result.retained_source
    groups = defaultdict(list)
    invalid_observations = []
    wrappers = {page.source_page_number: page for page in dispatch_result.pages}
    for page in dispatch_result.pages:
        outcome = page.dispatch_outcome
        if (
            isinstance(outcome, RouteDispatchSuccess)
            and outcome.profile.module_id == "scoreform"
            and page.failure_stage is None
            and isinstance(outcome.module_result, ScoreFormPageDispatchResult)
        ):
            item = outcome.module_result
            try:
                if not _observation_matches_dispatch(item, page, retained):
                    raise ScoreFormAttemptAssemblyError(
                        "Observed result contradicts its exact dispatch relationship."
                    )
                choices = require_layout(item.layout_id).choices
                validate_page_dispatch_result(item, valid_choices=choices)
            except Exception as error:
                invalid_observations.append(_invalid_observation(
                    page, item, retained, str(error), cause=error
                ))
                continue
            groups[item.issuance_id].append(item)

    completed = []
    failures = []
    for issuance_id, items in groups.items():
        observed = tuple(items)
        first = observed[0]
        try:
            record_set = load_answer_sheet_record_set(
                workspace_root, scoreform_work_ref(first.class_id, first.assignment_id),
                issuance_id,
            )
        except Exception as error:
            failures.append(_failure("inconsistent_issuance", observed, str(error), cause=error))
            continue
        issuance = record_set.issuance
        expected_pages = record_set.pages
        shared_expected = (
            issuance.issuance_id, issuance.generation_id, issuance.artifact_id,
            issuance.class_id, issuance.assignment_id, issuance.student_id,
            issuance.page_count, issuance.assignment_snapshot.layout_id,
        )
        retained_expected = None if retained is None else (
            retained.source_scan_id, retained.retained_source_relative_path,
            retained.source_sha256,
        )
        invalid = False
        for item in observed:
            shared_actual = (
                item.issuance_id, item.generation_id, item.artifact_id, item.class_id,
                item.assignment_id, item.student_id, item.total_pages, item.layout_id,
            )
            source_actual = (item.source_scan_id, item.retained_source_relative_path, item.source_sha256)
            wrapper = wrappers.get(item.source_page_number)
            if (
                shared_actual != shared_expected
                or source_actual != retained_expected
                or wrapper is None
                or not _observation_matches_dispatch(item, wrapper, retained)
            ):
                invalid = True
                break
        if invalid:
            failures.append(_failure("invalid_result_identity", observed, "Observed identity or retained provenance disagrees with authoritative dispatch data.", expected_pages=expected_pages))
            continue
        expected_by_id = {page.page_id: page for page in expected_pages}
        if any(item.page_id not in expected_by_id for item in observed):
            failures.append(_failure("unexpected_page", observed, "Observed page does not belong to the issuance.", expected_pages=expected_pages))
            continue
        duplicate_pages = _duplicates(tuple(item.page_id for item in observed))
        duplicate_routes = _duplicates(tuple(item.route_id for item in observed))
        duplicate_logicals = _duplicates(tuple(item.logical_page for item in observed))
        if duplicate_pages or duplicate_routes or duplicate_logicals:
            conflicting = _duplicate_is_conflicting(observed)
            category = "conflicting_duplicate" if conflicting else ("duplicate_route" if duplicate_routes and not duplicate_pages else "duplicate_page")
            failures.append(_failure(category, observed, "Conflicting duplicate observations require review." if conflicting else "Duplicate observations require a clean rescan.", expected_pages=expected_pages, duplicate_page_ids=duplicate_pages, duplicate_route_ids=duplicate_routes, conflicting_page_ids=_conflicting_page_ids(observed) if conflicting else ()))
            continue
        for item in observed:
            authoritative_page = expected_by_id[item.page_id]
            actual = (item.logical_page, item.total_pages, item.question_start, item.question_end, item.layout_id, item.generation_id, item.artifact_id, item.class_id, item.assignment_id, item.student_id)
            expected = (authoritative_page.logical_page, authoritative_page.total_pages, authoritative_page.question_start, authoritative_page.question_end, authoritative_page.layout_id, authoritative_page.generation_id, authoritative_page.artifact_id, authoritative_page.class_id, authoritative_page.assignment_id, authoritative_page.student_id)
            if actual != expected:
                invalid = True
                break
        if invalid:
            failures.append(_failure("invalid_result_identity", observed, "Observed page fields disagree with the authoritative page record.", expected_pages=expected_pages))
            continue
        observed_ids = {item.page_id for item in observed}
        missing = tuple(page.page_id for page in expected_pages if page.page_id not in observed_ids)
        if missing:
            missing_logicals = tuple(page.logical_page for page in expected_pages if page.page_id in missing)
            failures.append(_failure("missing_pages", observed, "The retained intake does not contain every page in the issuance.", expected_pages=expected_pages, missing_page_ids=missing, missing_logical_pages=missing_logicals))
            continue
        ordered = tuple({item.page_id: item for item in observed}[page_id] for page_id in issuance.page_ids)
        question_count = issuance.assignment_snapshot.question_count
        answers = tuple(answer for item in ordered for answer in item.answers)
        if (
            tuple(item.logical_page for item in ordered) != tuple(range(1, issuance.page_count + 1))
            or tuple(answer.question_number for answer in answers) != tuple(range(1, question_count + 1))
            or sum(item.total_points for item in ordered) != question_count
        ):
            failures.append(_failure("invalid_question_coverage", observed, "The complete page set does not cover the assignment exactly once.", expected_pages=expected_pages))
            continue
        snapshot = issuance.student_snapshot
        try:
            routed = ScoreFormRoutedResult(
                result_origin="pds2_scan", class_id=issuance.class_id,
                assignment_id=issuance.assignment_id, student_id=issuance.student_id,
                last_name=snapshot.last_name, first_name=snapshot.first_name,
                period=snapshot.period,
                page_display=",".join(str(item.source_page_number) for item in ordered),
                score=sum(item.score for item in ordered), total_points=question_count,
                answers=answers, issuance_id=issuance.issuance_id,
                generation_id=issuance.generation_id, artifact_id=issuance.artifact_id,
                page_ids=tuple(item.page_id for item in ordered),
                route_ids=tuple(item.route_id for item in ordered),
                logical_pages=tuple(item.logical_page for item in ordered),
                source_file=retained.source_filename if retained else "",
                source_scan_id=first.source_scan_id,
                source_page_numbers=tuple(item.source_page_number for item in ordered),
                retained_source_relative_path=first.retained_source_relative_path,
                source_sha256=first.source_sha256,
            )
            assembled = ScoreFormAssembledAttempt(
                routed,
                tuple(ScoreFormPageObservation(item) for item in ordered),
            )
        except Exception as error:
            failures.append(_failure(
                "invalid_result_identity", observed,
                f"Completed result construction failed: {error}",
                expected_pages=expected_pages, cause=error,
            ))
            continue
        completed.append(assembled)
    completed.sort(key=lambda item: (min(item.routed_result.source_page_numbers), item.issuance_id))
    invalid_observations.sort(key=lambda item: item.source_page_number)
    return ScoreFormAttemptAssemblyBatch(
        dispatch_result, tuple(completed), tuple(failures),
        tuple(invalid_observations),
    )
