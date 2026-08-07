from __future__ import annotations

import pytest

import scoreform.cli_publication as cli_publication_module
from scoreform.academic_result_publication import (
    ScoreFormAcademicResultPublicationConflictError,
    ScoreFormAcademicResultPublicationIntegrityError,
    ScoreFormAcademicResultPublicationValidationError,
    ScoreFormAcademicResultPublicationWriteError,
)
from scoreform.cli import main
from scoreform.cli_publication import run_publication


def test_publication_command_family_is_discoverable(capsys):
    assert main(["publication", "help"], default_to_menu=False) == 0
    output = capsys.readouterr().out
    for action in (
        "status",
        "list",
        "show",
        "publish",
        "supersede",
        "republish-after-withdrawal",
        "withdraw",
        "rebuild-catalog",
    ):
        assert f"publication {action}" in output
    assert "--force" not in output


def test_expected_failures_are_nonzero_without_traceback(capsys):
    assert main(["publication", "publish"], default_to_menu=False) == 1
    output = capsys.readouterr().out
    assert "Error:" in output
    assert "Traceback" not in output


def test_unrelated_help_does_not_create_registry(tmp_path):
    assert main(["help"], default_to_menu=False) == 0
    assert not (tmp_path / "registry").exists()


@pytest.mark.parametrize(
    "args",
    [
        ["status", "--unknown", "x"],
        ["status", "--class-id", "class1", "--class-id", "class1", "--assignment-id", "quiz1"],
        ["status", "--class-id"],
        ["status", "extra", "--class-id", "class1", "--assignment-id", "quiz1"],
        ["status", "--class-id", "../unsafe", "--assignment-id", "quiz1"],
        ["status", "--class-id", "class1", "--assignment-id", "../unsafe"],
        ["show", "--class-id", "class1", "--assignment-id", "quiz1", "--publication-id", "bad"],
        ["publish", "--class-id", "class1", "--assignment-id", "quiz1", "--revision", "01"],
        ["withdraw", "--class-id", "class1", "--assignment-id", "quiz1", "--publication-id", "pub_" + "0" * 32, "--reason", ""],
        ["unknown-action"],
        ["publish", "--class-id", "class1", "--assignment-id", "quiz1", "--revision", "1", "--force", "yes"],
    ],
    ids=[
        "unknown-option", "duplicate-option", "missing-value", "unexpected-positional",
        "unsafe-class", "unsafe-assignment", "malformed-publication-id",
        "noncanonical-revision", "empty-reason", "unknown-action", "force-rejected",
    ],
)
def test_publication_parser_rejects_invalid_input(args, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SCOREFORM_WORKSPACE_ROOT", str(tmp_path))
    assert run_publication(args) == 1
    assert "Error:" in capsys.readouterr().out
    assert not (tmp_path / "registry").exists()


@pytest.mark.parametrize(
    "error",
    [
        ScoreFormAcademicResultPublicationValidationError("validation"),
        ScoreFormAcademicResultPublicationConflictError("conflict"),
        ScoreFormAcademicResultPublicationIntegrityError("integrity"),
        ScoreFormAcademicResultPublicationWriteError("write"),
    ],
)
def test_explicit_catalog_cli_failures_are_traceback_free(
    tmp_path, monkeypatch, capsys, error
):
    monkeypatch.setenv("SCOREFORM_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setattr(
        cli_publication_module,
        "rebuild_full_academic_catalog",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(error),
    )
    assert run_publication(["rebuild-catalog"]) == 1
    output = capsys.readouterr().out
    assert "Error:" in output
    assert "Traceback" not in output
