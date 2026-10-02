"""Pure rendered-report artifact contracts for ScoreForm results reporting."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Literal

RenderedFormat = Literal["csv", "json", "pdf"]
RenderedScope = Literal["class_analysis", "student_detail"]


@dataclass(frozen=True, slots=True)
class RenderedReportArtifact:
    """One immutable renderer output before output-custody writes it."""

    filename: str
    media_type: str
    content: bytes

    def __post_init__(self) -> None:
        if (
            not isinstance(self.filename, str)
            or not self.filename
            or self.filename in {".", ".."}
            or "/" in self.filename
            or "\\" in self.filename
        ):
            raise ValueError("filename must be one safe relative basename.")
        if not isinstance(self.media_type, str) or not self.media_type:
            raise ValueError("media_type must be a nonempty string.")
        if not isinstance(self.content, bytes) or not self.content:
            raise ValueError("content must be nonempty bytes.")

    @property
    def sha256_hex(self) -> str:
        return sha256(self.content).hexdigest()


@dataclass(frozen=True, slots=True)
class RenderedResultsReport:
    """A deterministic bounded set of artifacts produced by one renderer."""

    output_format: RenderedFormat
    scope: RenderedScope
    artifacts: tuple[RenderedReportArtifact, ...]

    def __post_init__(self) -> None:
        if self.output_format not in {"csv", "json", "pdf"}:
            raise ValueError("output_format is unsupported.")
        if self.scope not in {"class_analysis", "student_detail"}:
            raise ValueError("scope is unsupported.")
        if not isinstance(self.artifacts, tuple) or not self.artifacts:
            raise ValueError("artifacts must be a nonempty tuple.")
        filenames = tuple(artifact.filename for artifact in self.artifacts)
        if len(set(filenames)) != len(filenames):
            raise ValueError("artifact filenames must be unique.")

    def artifact(self, filename: str) -> RenderedReportArtifact:
        """Return one exact artifact by logical filename."""
        matches = tuple(
            artifact for artifact in self.artifacts if artifact.filename == filename
        )
        if len(matches) != 1:
            raise KeyError(filename)
        return matches[0]
