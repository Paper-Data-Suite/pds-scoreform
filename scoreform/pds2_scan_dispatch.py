"""Retained-source PDS2 intake and ordered Core page dispatch."""

from __future__ import annotations

import os
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

import cv2
import numpy as np
from pds_core.module_dispatch import (
    RouteDispatchFailure,
    RouteDispatchOutcome,
    RouteDispatchRequest,
    RouteDispatchSuccess,
    dispatch_routes,
)
from pds_core.module_profiles import (
    ModuleDiscoveryError,
    ModuleRegistry,
    ModuleRegistryError,
    UnsupportedModuleError,
    build_module_registry,
)
from pds_core.pds2 import Pds2PayloadError, parse_pds2_payload
from pds_core.routing_models import RouteLocator
from pds_core.scan_retention import (
    RetainedSourceScan,
    SourceRetentionError,
    retain_source_scan,
)

from scoreform.module_errors import (
    ScoreFormDispatchIntegrationError,
    ScoreFormQrMissingError,
    ScoreFormQrUnreadableError,
    ScoreFormRegistryError,
    ScoreFormScanPreflightError,
    ScoreFormSourceMissingError,
    ScoreFormSourceTypeUnsupportedError,
)
from scoreform.page_scoring import ScoreFormPageDispatchResult
from scoreform.retained_page import (
    SUPPORTED_RETAINED_SOURCE_EXTENSIONS,
    load_retained_page_for_qr,
    retained_source_page_count,
    validate_retained_source,
)
from scoreform.scoring import (
    _qr_candidate_images,
    save_qr_failure_diagnostics_with_status,
)

FailureStage = Literal[
    "source_page_loading",
    "qr_detection",
    "payload_parsing",
    "request_construction",
    "scoreform_result_validation",
    "core_outcome_validation",
]
_FAILURE_STAGES = frozenset(
    {
        "source_page_loading",
        "qr_detection",
        "payload_parsing",
        "request_construction",
        "scoreform_result_validation",
        "core_outcome_validation",
    }
)


@dataclass(frozen=True, slots=True)
class QrPayloadDetectionResult:
    """Raw QR detector output, deliberately independent of payload grammar."""

    raw_payload_text: str | None
    decode_method: str | None
    diagnostic_paths: tuple[str, ...] = ()
    diagnostic_errors: tuple[Exception, ...] = ()
    error: Exception | None = None

    def __post_init__(self) -> None:
        _validate_diagnostics(self.diagnostic_paths, self.diagnostic_errors)


def _validate_diagnostics(
    paths: tuple[str, ...], errors: tuple[Exception, ...]
) -> None:
    if not isinstance(paths, tuple) or any(
        not isinstance(path, str) or not path for path in paths
    ):
        raise TypeError("diagnostic_paths must contain only nonempty strings.")
    if len(paths) != len(set(paths)):
        raise ValueError("diagnostic_paths must not contain duplicates.")
    if not isinstance(errors, tuple) or any(
        not isinstance(error, Exception) for error in errors
    ):
        raise TypeError("diagnostic_errors must contain only Exception values.")


@dataclass(frozen=True, slots=True)
class Pds2ScanPageOutcome:
    """One source page's immutable decode, parse, request, and dispatch state."""

    source_page_number: int
    raw_payload_text: str | None = None
    locator: RouteLocator | None = None
    decode_method: str | None = None
    dispatch_request: RouteDispatchRequest | None = None
    dispatch_outcome: RouteDispatchOutcome | None = None
    failure_stage: FailureStage | None = None
    error: Exception | None = None
    diagnostic_paths: tuple[str, ...] = ()
    diagnostic_errors: tuple[Exception, ...] = ()

    def __post_init__(self) -> None:
        number = self.source_page_number
        if isinstance(number, bool) or not isinstance(number, int) or number < 1:
            raise ValueError("source_page_number must be a positive integer.")
        _validate_diagnostics(self.diagnostic_paths, self.diagnostic_errors)
        if self.failure_stage is not None and self.failure_stage not in _FAILURE_STAGES:
            raise ValueError(
                "failure_stage is not a supported closed-vocabulary value."
            )
        if self.failure_stage is not None and self.error is None:
            raise ValueError("A failure_stage requires an error.")
        if self.failure_stage is None and self.error is not None:
            raise ValueError("A page error requires a failure_stage.")
        if self.locator is not None and self.raw_payload_text is None:
            raise ValueError("A parsed locator requires raw payload text.")
        if self.locator is None and self.dispatch_request is not None:
            raise ValueError("A dispatch request requires a validated locator.")
        request = self.dispatch_request
        if request is not None:
            if request.locator != self.locator:
                raise ValueError("The dispatch request locator must equal locator.")
            if request.source_page_number != number:
                raise ValueError(
                    "The dispatch request source page must equal source_page_number."
                )
        if self.dispatch_outcome is not None and self.dispatch_request is None:
            raise ValueError("A dispatch outcome requires a dispatch request.")
        if self.dispatch_outcome is not None:
            if self.dispatch_outcome.request != self.dispatch_request:
                mismatch_allowed = self.failure_stage == "core_outcome_validation"
                if not mismatch_allowed:
                    raise ValueError(
                        "A dispatch outcome must carry the recorded request."
                    )
        if isinstance(self.dispatch_outcome, RouteDispatchFailure):
            if self.failure_stage not in {None, "core_outcome_validation"}:
                raise ValueError(
                    "Core dispatch failures must remain unwrapped outcomes."
                )
        if isinstance(self.dispatch_outcome, RouteDispatchSuccess):
            success_stages = {
                "scoreform_result_validation",
                "core_outcome_validation",
            }
            if (
                self.failure_stage is not None
                and self.failure_stage not in success_stages
            ):
                raise ValueError(
                    "A Core success has an invalid application failure stage."
                )

    @property
    def successful_module_id(self) -> str | None:
        outcome = self.dispatch_outcome
        if isinstance(outcome, RouteDispatchSuccess) and self.failure_stage is None:
            return outcome.profile.module_id
        return None

    @property
    def scoreform_page_score(self) -> ScoreFormPageDispatchResult | None:
        outcome = self.dispatch_outcome
        if (
            isinstance(outcome, RouteDispatchSuccess)
            and outcome.profile.module_id == "scoreform"
            and isinstance(outcome.module_result, ScoreFormPageDispatchResult)
            and self.failure_stage is None
        ):
            return outcome.module_result
        return None


@dataclass(frozen=True, slots=True)
class Pds2ScanDispatchResult:
    """Immutable retained-source batch result for page-level dispatch only."""

    retained_source: RetainedSourceScan | None
    pages: tuple[Pds2ScanPageOutcome, ...] = ()
    registry_module_ids: tuple[str, ...] = ()
    file_error: Exception | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.pages, tuple):
            raise TypeError("pages must be a tuple.")
        numbers = tuple(page.source_page_number for page in self.pages)
        if numbers != tuple(sorted(numbers)) or len(numbers) != len(set(numbers)):
            raise ValueError("Page numbers must be unique and ascending.")
        ids = self.registry_module_ids
        if (
            not isinstance(ids, tuple)
            or any(not isinstance(module_id, str) or not module_id for module_id in ids)
            or ids != tuple(sorted(set(ids)))
        ):
            raise ValueError("registry_module_ids must be unique and deterministic.")
        if self.pages and self.retained_source is None:
            raise ValueError("Page outcomes require retained-source provenance.")
        if self.retained_source is None and self.file_error is not None and self.pages:
            raise ValueError("A pre-retention file error cannot contain page outcomes.")
        for page in self.pages:
            request = page.dispatch_request
            if (
                request is not None
                and request.retained_source is not self.retained_source
            ):
                raise ValueError(
                    "Every dispatch request must share exact retained provenance."
                )
        if self.file_error is None and self.terminal_page_count != len(self.pages):
            raise ValueError(
                "Every source page must have exactly one terminal category."
            )

    @property
    def total_source_pages(self) -> int:
        return len(self.pages)

    @property
    def decoded_payload_count(self) -> int:
        return sum(page.raw_payload_text is not None for page in self.pages)

    @property
    def valid_locator_count(self) -> int:
        return sum(page.locator is not None for page in self.pages)

    @property
    def dispatch_success_count(self) -> int:
        return sum(page.successful_module_id is not None for page in self.pages)

    @property
    def dispatch_failure_count(self) -> int:
        return sum(
            isinstance(page.dispatch_outcome, RouteDispatchFailure)
            for page in self.pages
        )

    @property
    def pre_dispatch_failure_count(self) -> int:
        return sum(
            page.dispatch_outcome is None and page.failure_stage is not None
            for page in self.pages
        )

    @property
    def application_failure_count(self) -> int:
        return sum(
            isinstance(page.dispatch_outcome, RouteDispatchSuccess)
            and page.failure_stage is not None
            for page in self.pages
        )

    @property
    def terminal_page_count(self) -> int:
        return (
            self.dispatch_success_count
            + self.dispatch_failure_count
            + self.pre_dispatch_failure_count
            + self.application_failure_count
        )

    @property
    def scoreform_page_score_count(self) -> int:
        return sum(page.scoreform_page_score is not None for page in self.pages)

    @property
    def scoreform_page_scores(self) -> tuple[ScoreFormPageDispatchResult, ...]:
        return tuple(
            result
            for page in self.pages
            if (result := page.scoreform_page_score) is not None
        )

    @property
    def other_module_success_count(self) -> int:
        return sum(
            module_id is not None and module_id != "scoreform"
            for page in self.pages
            if (module_id := page.successful_module_id) is not None
        )

    @property
    def successful_pages_by_module(self) -> tuple[tuple[str, int], ...]:
        counts = Counter(
            module_id
            for page in self.pages
            if (module_id := page.successful_module_id) is not None
        )
        return tuple(sorted(counts.items()))

    @property
    def complete_success(self) -> bool:
        return (
            self.file_error is None
            and bool(self.pages)
            and self.dispatch_success_count == len(self.pages)
        )

    @property
    def partial_success(self) -> bool:
        return 0 < self.dispatch_success_count < len(self.pages)

    @property
    def zero_success(self) -> bool:
        return self.dispatch_success_count == 0

    @property
    def batch_status(self) -> str:
        if self.file_error is not None:
            return "file_failure"
        if self.complete_success:
            return "complete_success"
        if self.application_failure_count and self.zero_success:
            return "integration_failure"
        if self.partial_success:
            return "partial_success"
        return "zero_success"

    def exit_code(self) -> int:
        return 0 if self.complete_success else 1


def build_scoreform_scan_registry() -> ModuleRegistry:
    """Build a fresh installed application registry and require ScoreForm."""
    try:
        registry = build_module_registry(discover_installed=True)
        registry.require("scoreform")
        return registry
    except (
        ModuleDiscoveryError,
        ModuleRegistryError,
        UnsupportedModuleError,
        TypeError,
        ValueError,
    ) as error:
        raise ScoreFormRegistryError(
            f"Could not build the installed scan module registry: {error}"
        ) from error


def validate_scan_registry(registry: ModuleRegistry) -> ModuleRegistry:
    """Validate an independently supplied application registry."""
    if not isinstance(registry, ModuleRegistry):
        raise ScoreFormScanPreflightError("registry must be a ModuleRegistry.")
    try:
        registry.require("scoreform")
        registry.module_ids()
    except (
        ModuleRegistryError,
        UnsupportedModuleError,
        TypeError,
        ValueError,
    ) as error:
        raise ScoreFormScanPreflightError(
            f"The scan module registry is invalid: {error}"
        ) from error
    return registry


def _validate_workspace_root(workspace_root: Path) -> Path:
    if not isinstance(workspace_root, Path):
        raise ScoreFormScanPreflightError("workspace_root must be a Path.")
    try:
        resolved = workspace_root.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise ScoreFormScanPreflightError(
            "The workspace root must be an existing directory."
        ) from error
    if workspace_root.is_symlink() or not resolved.is_dir():
        raise ScoreFormScanPreflightError(
            "The workspace root must be a non-symlinked directory."
        )
    return resolved


def validate_pds2_scan_source(source_file: str | Path) -> Path:
    """Preflight one external active-scan source without creating anything."""
    if isinstance(source_file, Path):
        path = source_file
    elif isinstance(source_file, str) and source_file:
        path = Path(source_file)
    else:
        raise ScoreFormScanPreflightError("One source file path is required.")
    if path.is_symlink():
        raise ScoreFormScanPreflightError("Symlinked source files are not allowed.")
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise ScoreFormSourceMissingError(
            f"Source file does not exist: {path}"
        ) from error
    if not resolved.is_file():
        raise ScoreFormScanPreflightError("The source must be a regular file.")
    if not os.access(resolved, os.R_OK):
        raise ScoreFormScanPreflightError("The source file is not readable.")
    suffix = resolved.suffix.lower()
    if suffix not in SUPPORTED_RETAINED_SOURCE_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_RETAINED_SOURCE_EXTENSIONS))
        raise ScoreFormSourceTypeUnsupportedError(
            f"Unsupported active-scan extension {suffix or '(none)'}; expected {supported}."
        )
    return resolved


def detect_qr_payload_text(
    image: np.ndarray,
    *,
    retained_source: RetainedSourceScan,
    source_page_number: int,
    workspace_root: Path,
) -> QrPayloadDetectionResult:
    """Detect exact raw QR text without parsing or module-specific interpretation."""
    if not isinstance(image, np.ndarray) or image.size == 0 or image.dtype != np.uint8:
        error = ScoreFormQrUnreadableError(
            "QR detection requires nonempty uint8 image data."
        )
        return QrPayloadDetectionResult(None, None, error=error)
    attempted = 0
    completed = 0
    last_detector_error: Exception | None = None
    for method, candidate in _qr_candidate_images(image):
        attempted += 1
        try:
            detector = cv2.QRCodeDetector()
            payload, _, _ = detector.detectAndDecode(candidate)
        except Exception as error:
            last_detector_error = error
            continue
        completed += 1
        if payload:
            return QrPayloadDetectionResult(payload, method)
    if attempted and completed == 0:
        failure = ScoreFormQrUnreadableError("QR image detection failed.")
        failure.__cause__ = last_detector_error
        return QrPayloadDetectionResult(None, None, error=failure)
    diagnostics = save_qr_failure_diagnostics_with_status(
        image,
        f"{retained_source.source_scan_id}_source",
        source_page_number,
        workspace_root=workspace_root,
    )
    return QrPayloadDetectionResult(
        None,
        None,
        diagnostic_paths=diagnostics.paths,
        diagnostic_errors=diagnostics.errors,
        error=ScoreFormQrMissingError(
            "No QR code was detected on the retained source page."
        ),
    )


def _decode_pages(
    workspace_root: Path,
    retained_source: RetainedSourceScan,
) -> tuple[Pds2ScanPageOutcome, ...]:
    count = retained_source_page_count(retained_source, workspace_root=workspace_root)
    pages: list[Pds2ScanPageOutcome] = []
    for number in range(1, count + 1):
        try:
            image = load_retained_page_for_qr(
                retained_source, number, workspace_root=workspace_root
            )
        except Exception as error:
            pages.append(
                Pds2ScanPageOutcome(
                    number, failure_stage="source_page_loading", error=error
                )
            )
            continue
        try:
            detection = detect_qr_payload_text(
                image,
                retained_source=retained_source,
                source_page_number=number,
                workspace_root=workspace_root,
            )
        except Exception as error:
            failure = ScoreFormQrUnreadableError(
                "QR detection failed unexpectedly for the retained source page."
            )
            failure.__cause__ = error
            pages.append(
                Pds2ScanPageOutcome(
                    number,
                    failure_stage="qr_detection",
                    error=failure,
                )
            )
            continue
        if detection.raw_payload_text is None:
            pages.append(
                Pds2ScanPageOutcome(
                    number,
                    decode_method=detection.decode_method,
                    failure_stage="qr_detection",
                    error=detection.error,
                    diagnostic_paths=detection.diagnostic_paths,
                    diagnostic_errors=detection.diagnostic_errors,
                )
            )
            continue
        raw = detection.raw_payload_text
        try:
            locator = parse_pds2_payload(raw)
        except Pds2PayloadError as error:
            pages.append(
                Pds2ScanPageOutcome(
                    number,
                    raw_payload_text=raw,
                    decode_method=detection.decode_method,
                    failure_stage="payload_parsing",
                    error=error,
                    diagnostic_paths=detection.diagnostic_paths,
                    diagnostic_errors=detection.diagnostic_errors,
                )
            )
            continue
        try:
            request = RouteDispatchRequest(
                locator=locator,
                retained_source=retained_source,
                source_page_number=number,
            )
        except Exception as error:
            pages.append(
                Pds2ScanPageOutcome(
                    number,
                    raw_payload_text=raw,
                    locator=locator,
                    decode_method=detection.decode_method,
                    failure_stage="request_construction",
                    error=error,
                    diagnostic_paths=detection.diagnostic_paths,
                    diagnostic_errors=detection.diagnostic_errors,
                )
            )
            continue
        pages.append(
            Pds2ScanPageOutcome(
                number,
                raw_payload_text=raw,
                locator=locator,
                decode_method=detection.decode_method,
                dispatch_request=request,
                diagnostic_paths=detection.diagnostic_paths,
                diagnostic_errors=detection.diagnostic_errors,
            )
        )
    return tuple(pages)


def _core_outcome_alignment_error(
    outcome: RouteDispatchOutcome,
    expected: RouteDispatchRequest,
    page: Pds2ScanPageOutcome,
    retained_source: RetainedSourceScan,
) -> ScoreFormDispatchIntegrationError | None:
    """Reject any Core outcome that contradicts its positional request."""
    if outcome.request != expected:
        return ScoreFormDispatchIntegrationError(
            "Core dispatch outcome carried a substituted or reordered request."
        )
    if outcome.request.locator != page.locator:
        return ScoreFormDispatchIntegrationError(
            "Core dispatch outcome locator did not match the source page locator."
        )
    if outcome.request.retained_source != retained_source:
        return ScoreFormDispatchIntegrationError(
            "Core dispatch outcome did not preserve retained-source provenance."
        )
    if outcome.request.source_page_number != page.source_page_number:
        return ScoreFormDispatchIntegrationError(
            "Core dispatch outcome source-page number did not match its page."
        )
    if isinstance(outcome, RouteDispatchSuccess):
        locator = page.locator
        assert locator is not None
        try:
            profile_module_id = outcome.profile.module_id
        except AttributeError as error:
            failure = ScoreFormDispatchIntegrationError(
                "Core success did not contain a structurally usable profile."
            )
            failure.__cause__ = error
            return failure
        if profile_module_id != locator.module_id:
            return ScoreFormDispatchIntegrationError(
                "Core success profile module did not match the locator module."
            )
        try:
            resolution_locator = outcome.resolution.locator
            registration_locator = outcome.resolution.registration.locator
        except (AttributeError, TypeError) as error:
            failure = ScoreFormDispatchIntegrationError(
                "Core success did not contain a structurally usable resolution."
            )
            failure.__cause__ = error
            return failure
        if resolution_locator != locator:
            return ScoreFormDispatchIntegrationError(
                "Core success resolution locator did not match the page locator."
            )
        if registration_locator != locator:
            return ScoreFormDispatchIntegrationError(
                "Core success registration locator did not match the page locator."
            )
    return None


def _registry_module_ids(registry: object) -> tuple[str, ...]:
    if not isinstance(registry, ModuleRegistry):
        return ()
    try:
        return registry.module_ids()
    except Exception:
        return ()


def dispatch_retained_scan(
    workspace_root: Path,
    retained_source: RetainedSourceScan,
    *,
    registry: ModuleRegistry,
) -> Pds2ScanDispatchResult:
    """Decode, strictly parse, and Core-dispatch every retained source page."""
    registry_ids = _registry_module_ids(registry)
    try:
        root = _validate_workspace_root(workspace_root)
        validated_registry = validate_scan_registry(registry)
        registry_ids = validated_registry.module_ids()
        validate_retained_source(retained_source, workspace_root=root)
        pages = _decode_pages(root, retained_source)
    except Exception as error:
        return Pds2ScanDispatchResult(
            retained_source,
            registry_module_ids=registry_ids,
            file_error=error,
        )
    requests = tuple(
        page.dispatch_request for page in pages if page.dispatch_request is not None
    )
    try:
        outcomes = (
            dispatch_routes(root, validated_registry, requests) if requests else ()
        )
    except Exception as error:
        return Pds2ScanDispatchResult(
            retained_source,
            pages,
            registry_ids,
            ScoreFormDispatchIntegrationError(
                f"Core ordered batch dispatch failed unexpectedly: {error}"
            ),
        )
    if not isinstance(outcomes, tuple):
        return Pds2ScanDispatchResult(
            retained_source,
            pages,
            registry_ids,
            ScoreFormDispatchIntegrationError(
                "Core ordered batch dispatch must return a tuple of outcomes."
            ),
        )
    if len(outcomes) != len(requests):
        integration_error = ScoreFormDispatchIntegrationError(
            "Core dispatch did not return exactly one outcome per request."
        )
        return Pds2ScanDispatchResult(
            retained_source,
            pages,
            registry_ids,
            integration_error,
        )
    if any(
        not isinstance(outcome, (RouteDispatchSuccess, RouteDispatchFailure))
        for outcome in outcomes
    ):
        return Pds2ScanDispatchResult(
            retained_source,
            pages,
            registry_ids,
            ScoreFormDispatchIntegrationError(
                "Core dispatch returned an unsupported outcome type."
            ),
        )
    outcome_iterator = iter(outcomes)
    merged: list[Pds2ScanPageOutcome] = []
    for page in pages:
        request = page.dispatch_request
        if request is None:
            merged.append(page)
            continue
        outcome = next(outcome_iterator)
        alignment_error = _core_outcome_alignment_error(
            outcome, request, page, retained_source
        )
        diagnostic_paths = page.diagnostic_paths
        if alignment_error is None and isinstance(outcome, RouteDispatchSuccess):
            if outcome.profile.module_id == "scoreform" and isinstance(
                outcome.module_result, ScoreFormPageDispatchResult
            ):
                diagnostic_paths += tuple(outcome.module_result.diagnostic_paths)
        elif (
            isinstance(outcome, RouteDispatchFailure)
            and page.locator is not None
            and page.locator.module_id == "scoreform"
        ):
            current: Exception | None = outcome.error
            while current is not None:
                paths = getattr(current, "diagnostic_paths", ())
                if isinstance(paths, tuple) and all(
                    isinstance(path, str) for path in paths
                ):
                    diagnostic_paths += paths
                cause = current.__cause__
                current = cause if isinstance(cause, Exception) else None
        diagnostic_paths = tuple(dict.fromkeys(diagnostic_paths))
        if alignment_error is not None:
            updated = replace(
                page,
                dispatch_outcome=outcome,
                diagnostic_paths=diagnostic_paths,
                failure_stage="core_outcome_validation",
                error=alignment_error,
            )
        else:
            updated = replace(
                page,
                dispatch_outcome=outcome,
                diagnostic_paths=diagnostic_paths,
            )
        if (
            alignment_error is None
            and isinstance(outcome, RouteDispatchSuccess)
            and outcome.profile.module_id == "scoreform"
            and not isinstance(outcome.module_result, ScoreFormPageDispatchResult)
        ):
            integration_error = ScoreFormDispatchIntegrationError(
                "The installed ScoreForm handler returned an unexpected result type."
            )
            updated = replace(
                updated,
                failure_stage="scoreform_result_validation",
                error=integration_error,
            )
        merged.append(updated)
    return Pds2ScanDispatchResult(
        retained_source,
        tuple(merged),
        registry_ids,
    )


def process_pds2_scan(
    source_file: str | Path,
    *,
    workspace_root: Path,
    registry: ModuleRegistry | None = None,
) -> Pds2ScanDispatchResult:
    """Preflight, retain exactly once, then process only the retained source."""
    try:
        root = _validate_workspace_root(workspace_root)
        source = validate_pds2_scan_source(source_file)
        selected_registry = (
            build_scoreform_scan_registry()
            if registry is None
            else validate_scan_registry(registry)
        )
    except Exception as error:
        return Pds2ScanDispatchResult(None, file_error=error)
    try:
        retained = retain_source_scan(root, source)
    except SourceRetentionError as error:
        return Pds2ScanDispatchResult(
            None,
            registry_module_ids=selected_registry.module_ids(),
            file_error=error,
        )
    return dispatch_retained_scan(root, retained, registry=selected_registry)


def format_pds2_dispatch_summary(result: Pds2ScanDispatchResult) -> str:
    """Render a dispatch-only summary without claiming downstream persistence."""
    retained = result.retained_source
    lines = [
        "PDS2 retained-source page dispatch summary",
        f"Batch status: {result.batch_status}",
    ]
    if retained is not None:
        lines.extend(
            [
                f"Source scan ID: {retained.source_scan_id}",
                f"Retained source path: {retained.retained_source_relative_path}",
            ]
        )
    lines.extend(
        [
            f"Source pages discovered: {result.total_source_pages}",
            f"Pages with decoded QR text: {result.decoded_payload_count}",
            f"Valid PDS2 locators: {result.valid_locator_count}",
            f"Dispatch successes: {result.dispatch_success_count}",
            f"Dispatch failures: {result.dispatch_failure_count}",
            f"Pre-dispatch failures: {result.pre_dispatch_failure_count}",
            f"Application integration failures: {result.application_failure_count}",
            f"ScoreForm pages scored: {result.scoreform_page_score_count}",
            f"Pages handled by other modules: {result.other_module_success_count}",
            "Successful pages by module: "
            + (
                ", ".join(
                    f"{module_id}={count}"
                    for module_id, count in result.successful_pages_by_module
                )
                or "(none)"
            ),
        ]
    )
    if result.file_error is not None:
        lines.append(f"File/registry failure: {result.file_error}")
    diagnostic_errors = tuple(
        error for page in result.pages for error in page.diagnostic_errors
    )
    if diagnostic_errors:
        lines.append("Diagnostic write warnings:")
        lines.extend(f"- {error}" for error in diagnostic_errors)
    failed = [
        page
        for page in result.pages
        if page.failure_stage is not None
        or isinstance(page.dispatch_outcome, RouteDispatchFailure)
    ]
    if failed:
        lines.append("Failed pages:")
        for page in failed:
            locator = page.locator
            stage: str
            if page.failure_stage is not None:
                stage = page.failure_stage
                error = page.error
            elif isinstance(page.dispatch_outcome, RouteDispatchFailure):
                stage = "core_dispatch"
                error = page.dispatch_outcome.error
            else:
                stage = page.failure_stage or "unknown"
                error = page.error
            identity = ""
            if locator is not None:
                identity = f"; module={locator.module_id}; route={locator.route_id}"
            lines.append(
                f"- Source page {page.source_page_number}: {stage}: {error}{identity}"
            )
    return "\n".join(lines)
