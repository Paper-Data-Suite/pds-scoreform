"""Persistent ScoreForm settings for assignment-local scan filing."""

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scoreform import workspace

SCAN_FILING_MODES = ("copy", "move", "off")
DEFAULT_SCAN_FILING_MODE = "copy"
SCAN_FILING_MODE_KEY = "scan_filing_mode"

MODE_EXPLANATIONS = {
    "copy": (
        "copy: file an assignment-local scored-copy after full-success QR-aware "
        "routed scoring and preserve the original source."
    ),
    "move": (
        "move: after a safe full-success filing, remove the original only when "
        "it is a direct child of scans_inbox."
    ),
    "off": (
        "off: do not file automatic assignment-local scored-copies; preserve the "
        "original source."
    ),
}


class ScoreFormSettingsError(ValueError):
    """Raised when ScoreForm settings cannot be updated safely."""


@dataclass(frozen=True)
class ScanFilingSettings:
    path: Path
    configured_mode: str | None
    effective_mode: str = DEFAULT_SCAN_FILING_MODE
    exists: bool = False
    warning: str | None = None


def scoreform_settings_path(workspace_root=None) -> Path:
    root = (
        Path(workspace_root)
        if workspace_root is not None
        else workspace.get_scoreform_workspace_root()
    )
    return root / ".pds" / "scoreform.json"


def _read_settings_object(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ScoreFormSettingsError(str(error)) from error
    if not isinstance(data, dict):
        raise ScoreFormSettingsError("settings root must be a JSON object")
    return data


def inspect_scan_filing_settings(workspace_root=None) -> ScanFilingSettings:
    path = scoreform_settings_path(workspace_root)
    if not path.exists():
        return ScanFilingSettings(path=path, configured_mode=None)

    try:
        data = _read_settings_object(path)
    except ScoreFormSettingsError:
        return ScanFilingSettings(
            path=path,
            configured_mode=None,
            exists=True,
            warning="ScoreForm settings could not be read safely.",
        )

    configured = data.get(SCAN_FILING_MODE_KEY)
    if configured is None:
        return ScanFilingSettings(path=path, configured_mode=None, exists=True)
    if configured not in SCAN_FILING_MODES:
        return ScanFilingSettings(
            path=path,
            configured_mode=str(configured),
            exists=True,
            warning=(
                "ScoreForm scan filing mode is invalid; expected copy, move, or off."
            ),
        )
    return ScanFilingSettings(
        path=path,
        configured_mode=configured,
        effective_mode=configured,
        exists=True,
    )


def get_scan_filing_mode(workspace_root=None) -> str:
    return inspect_scan_filing_settings(workspace_root).effective_mode


def _write_settings_object(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(data, temporary, indent=2, sort_keys=True)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
    except OSError as error:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise ScoreFormSettingsError(str(error)) from error


def _settings_for_update(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return _read_settings_object(path)


def set_scan_filing_mode(mode: str, workspace_root=None) -> ScanFilingSettings:
    if mode not in SCAN_FILING_MODES:
        raise ScoreFormSettingsError("mode must be copy, move, or off")
    path = scoreform_settings_path(workspace_root)
    data = _settings_for_update(path)
    data[SCAN_FILING_MODE_KEY] = mode
    _write_settings_object(path, data)
    return inspect_scan_filing_settings(workspace_root)


def reset_scan_filing_mode(workspace_root=None) -> ScanFilingSettings:
    path = scoreform_settings_path(workspace_root)
    if not path.exists():
        return inspect_scan_filing_settings(workspace_root)
    data = _settings_for_update(path)
    data.pop(SCAN_FILING_MODE_KEY, None)
    _write_settings_object(path, data)
    return inspect_scan_filing_settings(workspace_root)
