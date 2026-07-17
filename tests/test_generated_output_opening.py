from pathlib import Path

import pytest
from pds_core.local_open import LocalOpenError

from scoreform import generated_output_opening as opening


def test_workspace_file_and_folder_open_through_core_boundary(tmp_path, monkeypatch):
    folder = tmp_path / "outputs with spaces"
    folder.mkdir()
    output = folder / "class packet.pdf"
    output.write_bytes(b"pdf")
    opened = []
    monkeypatch.setattr(
        opening,
        "open_local_path",
        lambda path: opened.append(Path(path)) or Path(path),
    )

    assert opening.open_generated_output_file(tmp_path, output) == output.resolve()
    assert opening.open_generated_output_folder(
        tmp_path, "outputs with spaces"
    ) == folder.resolve()
    assert opened == [output.resolve(), folder.resolve()]


@pytest.mark.parametrize("value", ("", "   ", "http://example.test/x", "https://x", "file:///x"))
def test_empty_and_url_like_paths_are_rejected(tmp_path, monkeypatch, value):
    called = []
    monkeypatch.setattr(opening, "open_local_path", lambda path: called.append(path))

    with pytest.raises(opening.ScoreFormGeneratedOutputOpenError):
        opening.open_generated_output_file(tmp_path, value)

    assert called == []


def test_outside_missing_and_wrong_kind_paths_are_rejected(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"pdf")
    folder = workspace / "folder"
    folder.mkdir()
    output = workspace / "output.pdf"
    output.write_bytes(b"pdf")
    called = []
    monkeypatch.setattr(opening, "open_local_path", lambda path: called.append(path))

    rejected = (
        (opening.open_generated_output_file, outside),
        (opening.open_generated_output_file, workspace / "missing.pdf"),
        (opening.open_generated_output_folder, workspace / "missing"),
        (opening.open_generated_output_file, folder),
        (opening.open_generated_output_folder, output),
    )
    for operation, path in rejected:
        with pytest.raises(opening.ScoreFormGeneratedOutputOpenError):
            operation(workspace, path)

    assert called == []


def test_workspace_escaping_symlink_is_rejected_when_supported(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"pdf")
    link = workspace / "linked.pdf"
    try:
        link.symlink_to(outside)
    except (NotImplementedError, OSError):
        pytest.skip("File symlinks are unavailable on this platform.")
    called = []
    monkeypatch.setattr(opening, "open_local_path", lambda path: called.append(path))

    with pytest.raises(opening.ScoreFormGeneratedOutputOpenError, match="outside"):
        opening.open_generated_output_file(workspace, link)

    assert called == []


def test_core_open_error_is_wrapped(tmp_path, monkeypatch):
    output = tmp_path / "packet.pdf"
    output.write_bytes(b"pdf")

    def fail(_path):
        raise LocalOpenError("viewer failed")

    monkeypatch.setattr(opening, "open_local_path", fail)

    with pytest.raises(opening.ScoreFormGeneratedOutputOpenError) as caught:
        opening.open_generated_output_file(tmp_path, output)

    assert isinstance(caught.value.__cause__, LocalOpenError)
