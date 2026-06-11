from pathlib import Path

import pds_core.workspace as core_workspace

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


def test_set_scoreform_workspace_root_ensures_then_saves(monkeypatch, tmp_path):
    requested_root = tmp_path / "requested"
    ensured_root = tmp_path / "ensured"
    calls = []

    monkeypatch.setattr(
        workspace,
        "ensure_workspace_root",
        lambda path: calls.append(("ensure", path)) or ensured_root,
    )
    monkeypatch.setattr(
        workspace,
        "save_workspace_root",
        lambda path: calls.append(("save", path)) or Path(path),
    )

    assert workspace.set_scoreform_workspace_root(requested_root) == ensured_root
    assert calls == [
        ("ensure", requested_root),
        ("save", ensured_root),
    ]


def test_validate_scoreform_workspace_root_resolves_then_ensures(
    monkeypatch,
    tmp_path,
):
    resolved_root = tmp_path / "resolved"
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

    assert workspace.validate_scoreform_workspace_root() == resolved_root
    assert calls == [
        ("resolve", None),
        ("ensure", resolved_root),
    ]


def test_reset_scoreform_workspace_root_clears_then_resolves(
    monkeypatch,
    tmp_path,
):
    resolved_root = tmp_path / "resolved"
    calls = []

    monkeypatch.setattr(
        workspace,
        "clear_saved_workspace_root",
        lambda: calls.append(("clear", None)) or True,
    )
    monkeypatch.setattr(
        workspace,
        "resolve_workspace_root",
        lambda: calls.append(("resolve", None)) or resolved_root,
    )

    assert workspace.reset_scoreform_workspace_root() == (True, resolved_root)
    assert calls == [
        ("clear", None),
        ("resolve", None),
    ]


def test_set_and_reset_use_isolated_pds_core_config(
    monkeypatch,
    tmp_path,
):
    config_path = tmp_path / "config" / "config.json"
    requested_root = tmp_path / "shared-workspace"
    data_file = requested_root / "classes" / "existing.txt"

    monkeypatch.delenv("PDS_WORKSPACE_ROOT", raising=False)
    monkeypatch.setattr(
        core_workspace,
        "get_workspace_config_path",
        lambda: config_path,
    )
    monkeypatch.setattr(
        core_workspace,
        "get_default_workspace_root",
        lambda: tmp_path / "default-workspace",
    )

    assert workspace.set_scoreform_workspace_root(requested_root) == requested_root
    assert requested_root.is_dir()
    assert (requested_root / ".pds" / "workspace.json").is_file()
    assert config_path.is_file()
    assert core_workspace.resolve_workspace_root() == requested_root

    data_file.parent.mkdir()
    data_file.write_text("keep me", encoding="utf-8")

    cleared, resolved_root = workspace.reset_scoreform_workspace_root()

    assert cleared is True
    assert resolved_root == tmp_path / "default-workspace"
    assert not config_path.exists()
    assert data_file.read_text(encoding="utf-8") == "keep me"
