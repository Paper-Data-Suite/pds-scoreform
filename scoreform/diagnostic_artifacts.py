"""Bounded, failure-tolerant persistence for ScoreForm diagnostic artifacts."""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Literal

import cv2
import numpy as np

DiagnosticArtifactKind = Literal["registration_marks", "warped_page"]
DiagnosticArtifactStage = Literal[
    "encode",
    "prepare_root",
    "write",
    "verify",
    "collision",
]

DIAGNOSTIC_ARTIFACT_WRITE_FAILED_CODE: Final = "diagnostic_artifact_write_failed"
DIAGNOSTIC_TOKEN_HEX_LENGTH: Final = 20
MAX_DIAGNOSTIC_COLLISION_ATTEMPTS: Final = 32

_KIND_LABELS: Final[dict[DiagnosticArtifactKind, str]] = {
    "registration_marks": "corners",
    "warped_page": "warped",
}
_DIAGNOSTIC_NAME_DOMAIN: Final = "scoreform-diagnostic-artifact-v1"
_SHA256_HEX: Final = frozenset("0123456789abcdef")
_MAX_KIND_LABEL_LENGTH: Final = max(len(label) for label in _KIND_LABELS.values())
MAX_DIAGNOSTIC_FILENAME_LENGTH: Final = len(
    "sfdiag_"
    + ("x" * _MAX_KIND_LABEL_LENGTH)
    + "_"
    + ("0" * DIAGNOSTIC_TOKEN_HEX_LENGTH)
    + f"_{MAX_DIAGNOSTIC_COLLISION_ATTEMPTS:02d}.png"
)


@dataclass(frozen=True, slots=True)
class DiagnosticArtifactWarning:
    """Bounded technical detail for one optional diagnostic write failure."""

    kind: DiagnosticArtifactKind
    stage: DiagnosticArtifactStage
    exception_type: str | None = None
    code: str = field(
        default=DIAGNOSTIC_ARTIFACT_WRITE_FAILED_CODE,
        init=False,
    )


@dataclass(frozen=True, slots=True)
class DiagnosticArtifactWriteResult:
    """Exactly one diagnostic persistence success or bounded warning."""

    kind: DiagnosticArtifactKind
    intended_filename: str
    path: str | None = None
    warning: DiagnosticArtifactWarning | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.intended_filename, str) or not self.intended_filename:
            raise TypeError("intended_filename must be a nonempty string.")
        if len(self.intended_filename) > MAX_DIAGNOSTIC_FILENAME_LENGTH:
            raise ValueError("intended_filename exceeds the diagnostic filename budget.")
        if (self.path is None) == (self.warning is None):
            raise ValueError("result must contain exactly one of path or warning.")
        if self.path is not None and (not isinstance(self.path, str) or not self.path):
            raise TypeError("path must be a nonempty string when present.")
        if self.warning is not None and self.warning.kind != self.kind:
            raise ValueError("warning kind must match result kind.")


def build_diagnostic_artifact_name(
    *,
    kind: DiagnosticArtifactKind,
    source_sha256: str,
    source_page_number: int,
    page_id: str,
) -> str:
    """Build one deterministic opaque PNG filename with a fixed size budget."""
    label = _validate_kind(kind)
    _validate_source_identity(source_sha256, source_page_number, page_id)
    canonical = "\x00".join(
        (
            _DIAGNOSTIC_NAME_DOMAIN,
            kind,
            source_sha256,
            str(source_page_number),
            page_id,
        )
    ).encode("utf-8")
    token = hashlib.sha256(canonical).hexdigest()[:DIAGNOSTIC_TOKEN_HEX_LENGTH]
    filename = f"sfdiag_{label}_{token}.png"
    if len(filename) > MAX_DIAGNOSTIC_FILENAME_LENGTH:
        raise AssertionError("diagnostic filename exceeded its fixed budget")
    return filename


def write_png_diagnostic_artifact(
    image: np.ndarray,
    *,
    diagnostic_root: str | Path,
    kind: DiagnosticArtifactKind,
    source_sha256: str,
    source_page_number: int,
    page_id: str,
) -> DiagnosticArtifactWriteResult:
    """Encode and create one optional PNG diagnostic without overwriting files.

    Programmer-contract violations raise immediately. Encoding and filesystem
    failures are returned as bounded warnings so callers can keep diagnostic
    persistence subordinate to authoritative scoring.
    """
    base_filename = build_diagnostic_artifact_name(
        kind=kind,
        source_sha256=source_sha256,
        source_page_number=source_page_number,
        page_id=page_id,
    )

    encoded, encode_error = _encode_png(image)
    if encode_error is not None:
        return _warning_result(
            kind,
            base_filename,
            "encode",
            encode_error,
        )
    assert encoded is not None

    try:
        root = _prepare_diagnostic_root(diagnostic_root)
    except (OSError, RuntimeError, ValueError) as error:
        return _warning_result(
            kind,
            base_filename,
            "prepare_root",
            error,
        )

    for attempt in range(1, MAX_DIAGNOSTIC_COLLISION_ATTEMPTS + 1):
        filename = _collision_filename(base_filename, attempt)
        candidate = root / filename
        try:
            created = _write_create_only(candidate, encoded)
        except (OSError, RuntimeError, ValueError) as error:
            return _warning_result(kind, filename, "write", error)
        if not created:
            continue
        try:
            _verify_created_artifact(candidate, root)
        except (OSError, RuntimeError, ValueError) as error:
            _unlink_quietly(candidate)
            return _warning_result(kind, filename, "verify", error)
        return DiagnosticArtifactWriteResult(
            kind=kind,
            intended_filename=filename,
            path=str(candidate),
        )

    return DiagnosticArtifactWriteResult(
        kind=kind,
        intended_filename=_collision_filename(
            base_filename,
            MAX_DIAGNOSTIC_COLLISION_ATTEMPTS,
        ),
        warning=DiagnosticArtifactWarning(
            kind=kind,
            stage="collision",
            exception_type="FileExistsError",
        ),
    )


def _validate_kind(kind: DiagnosticArtifactKind) -> str:
    if kind not in _KIND_LABELS:
        raise ValueError("kind is not a supported diagnostic artifact kind.")
    return _KIND_LABELS[kind]


def _validate_source_identity(
    source_sha256: object,
    source_page_number: object,
    page_id: object,
) -> None:
    if (
        not isinstance(source_sha256, str)
        or len(source_sha256) != 64
        or any(char not in _SHA256_HEX for char in source_sha256)
    ):
        raise ValueError(
            "source_sha256 must be 64 lowercase hexadecimal characters."
        )
    if (
        isinstance(source_page_number, bool)
        or not isinstance(source_page_number, int)
        or source_page_number < 1
    ):
        raise ValueError("source_page_number must be a positive integer.")
    if not isinstance(page_id, str) or not page_id:
        raise ValueError("page_id must be a nonempty string.")


def _encode_png(image: object) -> tuple[bytes | None, Exception | None]:
    if not isinstance(image, np.ndarray) or image.size == 0:
        return None, TypeError("diagnostic image must be a nonempty ndarray")
    try:
        encoded_ok, encoded = cv2.imencode(".png", image)
    except Exception as error:  # OpenCV exposes backend-specific exception classes.
        return None, error
    if not encoded_ok or encoded is None or encoded.size == 0:
        return None, ValueError("OpenCV could not encode the diagnostic PNG")
    return encoded.tobytes(), None


def _prepare_diagnostic_root(diagnostic_root: str | Path) -> Path:
    if not isinstance(diagnostic_root, (str, Path)):
        raise TypeError("diagnostic_root must be a string or Path.")
    root = Path(diagnostic_root)
    if root.is_symlink():
        raise ValueError("diagnostic_root must not be a symlink.")
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("diagnostic_root must be a regular directory.")
    return root.resolve(strict=True)


def _collision_filename(base_filename: str, attempt: int) -> str:
    if attempt == 1:
        return base_filename
    stem = base_filename.removesuffix(".png")
    filename = f"{stem}_{attempt:02d}.png"
    if len(filename) > MAX_DIAGNOSTIC_FILENAME_LENGTH:
        raise AssertionError("collision filename exceeded its fixed budget")
    return filename


def _write_create_only(path: Path, content: bytes) -> bool:
    created = False
    try:
        with path.open("xb") as artifact_file:
            created = True
            artifact_file.write(content)
            artifact_file.flush()
            os.fsync(artifact_file.fileno())
            if not stat.S_ISREG(os.fstat(artifact_file.fileno()).st_mode):
                raise ValueError("diagnostic target is not a regular file")
    except FileExistsError:
        return False
    except (OSError, ValueError):
        if created:
            _unlink_quietly(path)
        raise
    return True


def _verify_created_artifact(path: Path, root: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError("created diagnostic is not a regular non-symlink file")
    resolved = path.resolve(strict=True)
    resolved.relative_to(root)


def _warning_result(
    kind: DiagnosticArtifactKind,
    intended_filename: str,
    stage: DiagnosticArtifactStage,
    error: Exception,
) -> DiagnosticArtifactWriteResult:
    exception_type: str | None = type(error).__name__
    if not exception_type or len(exception_type) > 128:
        exception_type = None
    return DiagnosticArtifactWriteResult(
        kind=kind,
        intended_filename=intended_filename,
        warning=DiagnosticArtifactWarning(
            kind=kind,
            stage=stage,
            exception_type=exception_type,
        ),
    )


def _unlink_quietly(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
