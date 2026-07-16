"""Immutable public models for ScoreForm scan-review persistence."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

from pds_core.scan_failure_metadata import RoutingFailureMetadata

from scoreform.scan_review_details import FAILURE_ORIGINS

PERSISTENCE_STAGES = frozenset(
    {"conversion", "validation", "write", "collision_exhausted"}
)


def _safe_relative(value: str) -> None:
    windows = PureWindowsPath(value)
    posix = PurePosixPath(value)
    parts = value.replace("\\", "/").split("/")
    if (
        not value
        or windows.is_absolute()
        or windows.drive
        or posix.is_absolute()
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise ValueError("metadata_relative_path must be workspace-relative and safe.")


@dataclass(frozen=True, slots=True)
class ScoreFormPersistedFailure:
    occurrence_key: str
    failure_id: str
    metadata: RoutingFailureMetadata
    metadata_path: Path
    metadata_relative_path: str
    origin: str
    source_page_number: int | None

    def __post_init__(self) -> None:
        if not isinstance(self.occurrence_key, str) or not self.occurrence_key:
            raise ValueError("occurrence_key must be nonempty.")
        if not isinstance(self.metadata, RoutingFailureMetadata):
            raise TypeError("metadata must be RoutingFailureMetadata.")
        if not isinstance(self.metadata_path, Path):
            raise TypeError("metadata_path must be a Path.")
        if not isinstance(self.failure_id, str) or not self.failure_id:
            raise ValueError("failure_id must be nonempty.")
        if self.metadata.failure_id != self.failure_id:
            raise ValueError("metadata failure identity must agree with failure_id.")
        if self.metadata_path.name != f"{self.failure_id}.json":
            raise ValueError("metadata path must agree with failure_id.")
        _safe_relative(self.metadata_relative_path)
        expected_relative = f"scans/review/{self.failure_id}.json"
        if self.metadata_relative_path != expected_relative:
            raise ValueError("metadata_relative_path must be canonical.")
        if self.origin not in FAILURE_ORIGINS:
            raise ValueError("origin must use the closed failure vocabulary.")
        if self.source_page_number != self.metadata.source_page_number:
            raise ValueError("source page must agree with metadata.")
        if self.source_page_number is not None and (
            isinstance(self.source_page_number, bool)
            or not isinstance(self.source_page_number, int)
            or self.source_page_number < 1
        ):
            raise ValueError("source_page_number must be positive or null.")


@dataclass(frozen=True, slots=True)
class ScoreFormFailurePersistenceError:
    occurrence_key: str
    origin: str
    source_page_number: int | None
    persistence_stage: str
    reason: str
    error: Exception

    def __post_init__(self) -> None:
        if not isinstance(self.occurrence_key, str) or not self.occurrence_key:
            raise ValueError("occurrence_key must be nonempty.")
        if self.origin not in FAILURE_ORIGINS:
            raise ValueError("origin must use the closed failure vocabulary.")
        if self.persistence_stage not in PERSISTENCE_STAGES:
            raise ValueError("persistence_stage is unsupported.")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("reason must be nonempty.")
        if not isinstance(self.error, Exception):
            raise TypeError("error must be an Exception.")
        if self.source_page_number is not None and (
            isinstance(self.source_page_number, bool)
            or not isinstance(self.source_page_number, int)
            or self.source_page_number < 1
        ):
            raise ValueError("source_page_number must be positive or null.")


@dataclass(frozen=True, slots=True)
class ScoreFormFailurePersistenceBatch:
    persisted: tuple[ScoreFormPersistedFailure, ...] = ()
    failures: tuple[ScoreFormFailurePersistenceError, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.persisted, tuple) or not isinstance(
            self.failures, tuple
        ):
            raise TypeError("persistence collections must be immutable tuples.")
        if any(
            not isinstance(item, ScoreFormPersistedFailure) for item in self.persisted
        ):
            raise TypeError("persisted must contain ScoreFormPersistedFailure values.")
        if any(
            not isinstance(item, ScoreFormFailurePersistenceError)
            for item in self.failures
        ):
            raise TypeError("failures must contain persistence error values.")
        ids = tuple(item.failure_id for item in self.persisted)
        paths = tuple(item.metadata_path for item in self.persisted)
        persisted_keys = tuple(item.occurrence_key for item in self.persisted)
        failed_keys = tuple(item.occurrence_key for item in self.failures)
        if len(ids) != len(set(ids)) or len(paths) != len(set(paths)):
            raise ValueError("persisted failure IDs and paths must be unique.")
        if len(persisted_keys) != len(set(persisted_keys)):
            raise ValueError("persisted occurrence keys must be unique.")
        if len(failed_keys) != len(set(failed_keys)):
            raise ValueError("failed occurrence keys must be unique.")
        if set(persisted_keys) & set(failed_keys):
            raise ValueError("an occurrence cannot be persisted and failed.")

    @property
    def complete(self) -> bool:
        return not self.failures
