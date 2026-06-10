from pathlib import Path

from scoreform import workspace

GET_SCOREFORM_WORKSPACE_ROOT = workspace.get_scoreform_workspace_root


def test_get_scoreform_workspace_root_resolves_and_ensures(monkeypatch, tmp_path):
    resolved_root = tmp_path / "resolved-workspace"
    calls = []

    monkeypatch.setattr(
        workspace,
        "resolve_workspace_root",
        lambda: calls.append(("resolve", None)) or resolved_root,
    )
    monkeypatch.setattr(
        workspace,
        "ensure_workspace_root",
        lambda path: calls.append(("ensure", path)) or Path(path),
    )

    assert GET_SCOREFORM_WORKSPACE_ROOT() == resolved_root
    assert calls == [
        ("resolve", None),
        ("ensure", resolved_root),
    ]
