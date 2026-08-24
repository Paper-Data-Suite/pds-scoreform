"""Typed failures for ScoreForm's Core module boundary."""


class ScoreFormModuleError(Exception):
    """Base class for failures raised through the installed module profile."""


class ScoreFormRegistrationValidationError(ScoreFormModuleError, ValueError):
    """A Core registration violates ScoreForm's structural route contract."""


class ScoreFormRouteContextError(ScoreFormModuleError):
    """A direct route-handler call or its canonical roots are invalid."""


class ScoreFormTargetIntegrityError(ScoreFormModuleError):
    """The registered target and authoritative answer-sheet data disagree."""


class ScoreFormIssuanceAuthorizationError(ScoreFormModuleError):
    """An issuance is not currently authorized for scoring."""


class ScoreFormAssignmentCompatibilityError(ScoreFormModuleError):
    """The managed assignment cannot score the issued physical form safely."""


class ScoreFormRetainedPageError(ScoreFormModuleError):
    """Retained-source provenance or page extraction is invalid."""


PAGE_SCORING_DIAGNOSTIC_CODES = frozenset(
    {
        "page_scoring_error",
        "registration_marks_missing",
        "omr_processing_failed",
        "malformed_page_result",
        "diagnostic_write_failed",
    }
)


class ScoreFormPageScoringError(ScoreFormModuleError):
    """Strict one-page OMR scoring failed with a stable ScoreForm diagnosis."""

    def __init__(
        self,
        message: str,
        *,
        diagnostic_paths: tuple[str, ...] = (),
        diagnostic_code: str = "page_scoring_error",
    ) -> None:
        super().__init__(message)
        if diagnostic_code not in PAGE_SCORING_DIAGNOSTIC_CODES:
            raise ValueError("diagnostic_code is unsupported.")
        self.diagnostic_paths = tuple(diagnostic_paths)
        self.diagnostic_code = diagnostic_code


class ScoreFormScanDispatchError(ScoreFormModuleError):
    """Base class for retained PDS2 scan-intake orchestration failures."""


class ScoreFormScanPreflightError(ScoreFormScanDispatchError, ValueError):
    """The workspace, source file, or injected registry failed preflight."""


class ScoreFormSourceMissingError(ScoreFormScanPreflightError):
    """The selected scan source does not exist."""


class ScoreFormSourceTypeUnsupportedError(ScoreFormScanPreflightError):
    """The selected scan source uses an unsupported file type."""


class ScoreFormRegistryError(ScoreFormScanDispatchError):
    """The application-owned installed module registry could not be built."""


class ScoreFormQrDetectionError(ScoreFormScanDispatchError):
    """A retained page did not yield raw QR payload text."""


class ScoreFormQrMissingError(ScoreFormQrDetectionError):
    """No QR symbol was detected on a usable retained page."""


class ScoreFormQrUnreadableError(ScoreFormQrDetectionError):
    """QR detection could not produce usable decoded text."""


class ScoreFormQrDiagnosticWriteError(ScoreFormScanDispatchError):
    """A privacy-conscious QR diagnostic could not be written."""


class ScoreFormDispatchIntegrationError(ScoreFormScanDispatchError):
    """A module success violated ScoreForm's application integration contract."""


class ScoreFormAttemptAssemblyError(ScoreFormModuleError):
    """Base error for post-dispatch issuance assembly."""


class ScoreFormDuplicatePageError(ScoreFormAttemptAssemblyError):
    """An issuance has repeated physical identity."""


class ScoreFormIncompleteAttemptError(ScoreFormAttemptAssemblyError):
    """An observed issuance is missing authoritative pages."""


class ScoreFormAttemptConflictError(ScoreFormAttemptAssemblyError):
    """Observations for one issuance contradict each other."""


class ScoreFormRoutedResultValidationError(ScoreFormModuleError, ValueError):
    """An in-memory routed result violates schema v2."""


class ScoreFormRoutedResultReadError(ScoreFormModuleError):
    """An existing routed history cannot be read safely."""


class ScoreFormRoutedResultWriteError(ScoreFormModuleError):
    """A routed history cannot be replaced safely."""


class ScoreFormRoutedResultIntegrityError(ScoreFormModuleError):
    """Durable exported identity was reused contradictorily."""
