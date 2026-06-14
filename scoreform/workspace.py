"""ScoreForm access to the shared Paper Data Suite workspace."""

from pathlib import Path

from pds_core.workspace import (
    WorkspaceRootError,
    clear_saved_workspace_root,
    ensure_workspace_root,
    get_default_workspace_root,
    get_workspace_config_path,
    inspect_workspace_root,
    resolve_workspace_root,
    save_workspace_root,
)

__all__ = [
    "WorkspaceRootError",
    "get_default_workspace_root",
    "get_scoreform_workspace_root",
    "get_workspace_config_path",
    "inspect_workspace_root",
    "reset_scoreform_workspace_root",
    "resolve_workspace_root",
    "set_scoreform_workspace_root",
    "validate_scoreform_workspace_root",
]


def get_scoreform_workspace_root() -> Path:
    """Return the resolved and ensured Paper Data Suite workspace root."""
    return ensure_workspace_root(resolve_workspace_root())


def set_scoreform_workspace_root(path: str | Path) -> Path:
    """Validate, create, and save the shared workspace root."""
    workspace_root = ensure_workspace_root(path)
    return save_workspace_root(workspace_root)


def validate_scoreform_workspace_root() -> Path:
    """Resolve and validate/create the shared workspace root."""
    return ensure_workspace_root(resolve_workspace_root())


def reset_scoreform_workspace_root() -> tuple[bool, Path]:
    """Clear the saved preference and return the newly resolved root."""
    cleared = clear_saved_workspace_root()
    return cleared, resolve_workspace_root()
