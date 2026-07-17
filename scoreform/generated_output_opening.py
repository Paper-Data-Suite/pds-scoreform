"""Safe ScoreForm boundary for opening generated local output."""

from __future__ import annotations

import os
from pathlib import Path

from pds_core.local_open import LocalOpenError, open_local_path


class ScoreFormGeneratedOutputOpenError(RuntimeError):
    """Raised when a generated output cannot be opened safely."""


def _resolved_generated_output(
    workspace_root: str | os.PathLike[str],
    output_path: str | os.PathLike[str],
) -> Path:
    text = os.fspath(output_path)
    if not text.strip():
        raise ScoreFormGeneratedOutputOpenError("Generated output path is empty.")
    if text.strip().lower().startswith(("http://", "https://", "file://")):
        raise ScoreFormGeneratedOutputOpenError(
            "Generated output must be a local workspace path."
        )

    try:
        root = Path(workspace_root).resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise ScoreFormGeneratedOutputOpenError(
            "The active PDS workspace is unavailable."
        ) from error
    if not root.is_dir():
        raise ScoreFormGeneratedOutputOpenError(
            "The active PDS workspace is not a directory."
        )

    candidate = Path(text)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise ScoreFormGeneratedOutputOpenError(
            f"Generated output does not exist: {candidate}"
        ) from error
    if not resolved.is_relative_to(root):
        raise ScoreFormGeneratedOutputOpenError(
            "Generated output is outside the active PDS workspace."
        )
    return resolved


def _open_generated_output(
    workspace_root: str | os.PathLike[str],
    output_path: str | os.PathLike[str],
    *,
    require_file: bool,
) -> Path:
    resolved = _resolved_generated_output(workspace_root, output_path)
    if require_file and not resolved.is_file():
        raise ScoreFormGeneratedOutputOpenError(
            f"Generated output is not a regular file: {resolved}"
        )
    if not require_file and not resolved.is_dir():
        raise ScoreFormGeneratedOutputOpenError(
            f"Generated output is not a directory: {resolved}"
        )
    try:
        opened = open_local_path(resolved)
    except LocalOpenError as error:
        raise ScoreFormGeneratedOutputOpenError(
            f"Could not open generated output: {resolved}"
        ) from error
    return Path(opened).resolve(strict=True)


def open_generated_output_file(
    workspace_root: str | os.PathLike[str],
    output_path: str | os.PathLike[str],
) -> Path:
    """Open one existing regular file contained by the active workspace."""
    return _open_generated_output(workspace_root, output_path, require_file=True)


def open_generated_output_folder(
    workspace_root: str | os.PathLike[str],
    output_path: str | os.PathLike[str],
) -> Path:
    """Open one existing directory contained by the active workspace."""
    return _open_generated_output(workspace_root, output_path, require_file=False)
