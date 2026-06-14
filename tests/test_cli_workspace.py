from types import SimpleNamespace

import scoreform.cli


def test_workspace_show_uses_workspace_status(
    tmp_path,
    monkeypatch,
    capsys,
):
    resolved_root = tmp_path / "resolved"
    config_path = tmp_path / "config" / "config.json"
    default_root = tmp_path / "default"
    calls = []

    def fake_inspect_workspace_root():
        calls.append(True)
        return SimpleNamespace(
            root=resolved_root,
            source="saved_config",
            exists=True,
            is_dir=True,
            is_writable=False,
            config_path=config_path,
            default_root=default_root,
        )

    monkeypatch.setattr(
        scoreform.cli.workspace,
        "inspect_workspace_root",
        fake_inspect_workspace_root,
    )

    assert scoreform.cli.main(["workspace", "show"]) == 0

    output = capsys.readouterr().out
    assert calls == [True]
    assert f"Current PDS workspace root:\n{resolved_root}" in output
    assert "Source:\nsaved_config" in output
    assert "Exists:\nyes" in output
    assert "Directory:\nyes" in output
    assert "Writable:\nno" in output
    assert f"Config file:\n{config_path}" in output
    assert f"Default workspace root:\n{default_root}" in output


def test_workspace_show_rejects_extra_arguments(monkeypatch, capsys):
    monkeypatch.setattr(
        scoreform.cli.workspace,
        "inspect_workspace_root",
        lambda: (_ for _ in ()).throw(AssertionError("must not inspect")),
    )

    assert scoreform.cli.run_workspace(["show", "extra"]) == 1
    assert "Usage: scoreform workspace show" in capsys.readouterr().out


def test_workspace_show_reports_workspace_error(monkeypatch, capsys):
    def raise_workspace_error():
        raise scoreform.cli.workspace.WorkspaceRootError("bad workspace")

    monkeypatch.setattr(
        scoreform.cli.workspace,
        "inspect_workspace_root",
        raise_workspace_error,
    )

    assert scoreform.cli.run_workspace(["show"]) == 1
    assert "Error: bad workspace" in capsys.readouterr().out


def test_workspace_set_reports_saved_root_without_migrating_files(
    tmp_path,
    monkeypatch,
    capsys,
):
    old_root = tmp_path / "old"
    old_file = old_root / "classes" / "existing.txt"
    old_file.parent.mkdir(parents=True)
    old_file.write_text("keep me", encoding="utf-8")
    requested_root = tmp_path / "new"
    calls = []

    def fake_set(path):
        calls.append(path)
        requested_root.mkdir()
        return requested_root

    monkeypatch.setattr(
        scoreform.cli.workspace,
        "set_scoreform_workspace_root",
        fake_set,
    )

    assert scoreform.cli.main(["workspace", "set", str(requested_root)]) == 0

    output = capsys.readouterr().out
    assert calls == [str(requested_root)]
    assert f"Saved PDS workspace root:\n{requested_root}" in output
    assert "This does not move existing ScoreForm files." in output
    assert old_file.read_text(encoding="utf-8") == "keep me"
    assert not (requested_root / "classes" / "existing.txt").exists()


def test_workspace_validate_prints_success(tmp_path, monkeypatch, capsys):
    resolved_root = tmp_path / "resolved"
    monkeypatch.setattr(
        scoreform.cli.workspace,
        "validate_scoreform_workspace_root",
        lambda: resolved_root,
    )

    assert scoreform.cli.main(["workspace", "validate"]) == 0

    output = capsys.readouterr().out
    assert f"Workspace is valid:\n{resolved_root}" in output


def test_workspace_reset_reports_cleared_without_deleting_files(
    tmp_path,
    monkeypatch,
    capsys,
):
    workspace_root = tmp_path / "workspace"
    data_file = workspace_root / "classes" / "existing.txt"
    data_file.parent.mkdir(parents=True)
    data_file.write_text("keep me", encoding="utf-8")

    monkeypatch.setattr(
        scoreform.cli.workspace,
        "reset_scoreform_workspace_root",
        lambda: (True, workspace_root),
    )

    assert scoreform.cli.main(["workspace", "reset"]) == 0

    output = capsys.readouterr().out
    assert "Cleared saved PDS workspace root preference." in output
    assert "No workspace files were deleted." in output
    assert f"Current resolved workspace root:\n{workspace_root}" in output
    assert data_file.read_text(encoding="utf-8") == "keep me"


def test_workspace_reset_reports_when_no_preference_existed(
    tmp_path,
    monkeypatch,
    capsys,
):
    workspace_root = tmp_path / "workspace"
    monkeypatch.setattr(
        scoreform.cli.workspace,
        "reset_scoreform_workspace_root",
        lambda: (False, workspace_root),
    )

    assert scoreform.cli.main(["workspace", "reset"]) == 0
    assert (
        "No saved PDS workspace root preference was set."
        in capsys.readouterr().out
    )


def test_workspace_help_forms_and_invalid_subcommand(capsys):
    for args in (
        ["workspace"],
        ["workspace", "help"],
        ["workspace", "--help"],
        ["workspace", "-h"],
    ):
        assert scoreform.cli.main(args) == 0
        assert "Usage:\n  scoreform workspace show" in capsys.readouterr().out

    assert scoreform.cli.main(["workspace", "nonsense"]) == 1
    output = capsys.readouterr().out
    assert "Unknown workspace command: nonsense" in output
    assert "scoreform workspace reset" in output


def test_workspace_error_is_user_facing(monkeypatch, capsys):
    monkeypatch.setattr(
        scoreform.cli.workspace,
        "validate_scoreform_workspace_root",
        lambda: (_ for _ in ()).throw(
            scoreform.cli.workspace.WorkspaceRootError("cannot use workspace")
        ),
    )

    assert scoreform.cli.main(["workspace", "validate"]) == 1
    assert "Error: cannot use workspace" in capsys.readouterr().out


def test_workspace_menu_opens_and_returns(monkeypatch, capsys):
    responses = iter(["3", "5", "5"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    assert scoreform.cli.launch_menu() == 0

    output = capsys.readouterr().out
    assert "ScoreForm\nWorkspace Settings" in output
    assert "1. Show current workspace" in output
    assert "2. Set workspace folder" in output
    assert "3. Validate/create current workspace" in output
    assert "4. Reset saved workspace preference" in output
    assert "5. Back" in output
    assert "Goodbye." in output


def test_workspace_menu_blank_set_path_cancels(monkeypatch, capsys):
    responses = iter(["2", "", "", "5"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    assert scoreform.cli.launch_workspace_menu() == 0

    output = capsys.readouterr().out
    assert "Cancelled: Workspace folder was not changed." in output
