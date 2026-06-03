import importlib.util
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "update_version.py"

spec = importlib.util.spec_from_file_location("update_version", SCRIPT_PATH)
update_version = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(update_version)


def test_validate_version_accepts_supported_formats():
    for version in ("0.8.0.dev0", "0.8.0", "1.0.0", "1.0.0.dev0"):
        assert update_version.validate_version(version) == version


def test_validate_version_rejects_malformed_or_unsafe_values():
    for version in ("../secret", "version=0.8.0", "0.8.0; rm -rf", "abc"):
        with pytest.raises(update_version.VersionUpdateError):
            update_version.validate_version(version)


def test_main_rejects_missing_or_extra_arguments(capsys):
    assert update_version.main([]) == 2
    assert "Usage: python scripts/update_version.py <version>" in capsys.readouterr().err

    assert update_version.main(["0.8.0.dev0", "1.0.0"]) == 2
    assert "Usage: python scripts/update_version.py <version>" in capsys.readouterr().err


def test_update_version_updates_known_version_references(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "pyproject.toml").write_text(
        """[build-system]
requires = ["setuptools>=61.0"]

[project]
name = "scoreform"
version = "0.7.0.dev0"
description = "Test fixture"
""",
        encoding="utf-8",
    )
    (tmp_path / "tests" / "test_cli_discoverability.py").write_text(
        """import re

import scoreform.cli


def assert_version_output(result):
    output = result.stdout + result.stderr
    assert re.search(r"0\\.7\\.0\\.dev0", output)


def test_get_version_prefers_local_pyproject_over_installed_metadata(monkeypatch):
    assert scoreform.cli.get_version() == "0.7.0.dev0"
""",
        encoding="utf-8",
    )

    update_version.update_version(tmp_path, "0.8.0.dev0")

    assert 'version = "0.8.0.dev0"' in (tmp_path / "pyproject.toml").read_text(encoding="utf-8")
    cli_test_text = (tmp_path / "tests" / "test_cli_discoverability.py").read_text(encoding="utf-8")
    assert 'assert re.search(r"0\\.8\\.0\\.dev0", output)' in cli_test_text
    assert 'assert scoreform.cli.get_version() == "0.8.0.dev0"' in cli_test_text


def test_update_version_fails_when_pyproject_pattern_is_missing(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "pyproject.toml").write_text("[project]\nname = \"scoreform\"\n", encoding="utf-8")
    (tmp_path / "tests" / "test_cli_discoverability.py").write_text(
        'assert re.search(r"0\\.7\\.0\\.dev0", output)\n'
        'assert scoreform.cli.get_version() == "0.7.0.dev0"\n',
        encoding="utf-8",
    )

    with pytest.raises(update_version.VersionUpdateError):
        update_version.update_version(tmp_path, "0.8.0.dev0")


def test_update_version_fails_when_cli_test_pattern_is_missing(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nversion = "0.7.0.dev0"\n',
        encoding="utf-8",
    )
    (tmp_path / "tests" / "test_cli_discoverability.py").write_text(
        "def test_placeholder():\n    assert True\n",
        encoding="utf-8",
    )

    with pytest.raises(update_version.VersionUpdateError):
        update_version.update_version(tmp_path, "0.8.0.dev0")
