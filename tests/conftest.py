from pathlib import Path

import pytest

from scoreform import workspace


@pytest.fixture(autouse=True)
def isolated_scoreform_workspace(tmp_path, monkeypatch):
    """Keep managed ScoreForm data inside each test's temporary directory."""
    monkeypatch.setenv("PDS_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setattr(
        workspace,
        "get_scoreform_workspace_root",
        lambda: Path(tmp_path),
    )
    return tmp_path
