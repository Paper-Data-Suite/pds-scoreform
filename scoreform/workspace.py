"""ScoreForm access to the shared Paper Data Suite workspace."""

from pathlib import Path

from pds_core.workspace import ensure_workspace_root, resolve_workspace_root


def get_scoreform_workspace_root() -> Path:
    """Return the resolved and ensured Paper Data Suite workspace root."""
    return ensure_workspace_root(resolve_workspace_root())
