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


class ScoreFormPageScoringError(ScoreFormModuleError):
    """Strict one-page OMR scoring failed."""

    def __init__(
        self,
        message: str,
        *,
        diagnostic_paths: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.diagnostic_paths = tuple(diagnostic_paths)
