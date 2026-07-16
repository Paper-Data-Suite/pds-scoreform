import importlib.util
import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "update_version.py"

spec = importlib.util.spec_from_file_location("update_version", SCRIPT_PATH)
assert spec is not None
assert spec.loader is not None
update_version = importlib.util.module_from_spec(spec)
spec.loader.exec_module(update_version)


def test_validate_version_accepts_supported_formats():
    for version in ("0.8.0.dev0", "0.8.0", "1.0.0", "1.0.0.dev0"):
        assert update_version.validate_version(version) == version


def test_validate_version_rejects_malformed_or_unsafe_values():
    for version in ("../secret", "version=0.8.0", "0.8.0; rm -rf", "abc"):
        with pytest.raises(update_version.VersionUpdateError):
            update_version.validate_version(version)


@pytest.mark.parametrize(
    ("version", "matching_output", "nonmatching_output"),
    [
        ("0.8.0", "ScoreForm 0.8.0", "ScoreForm 0.8.0.dev0"),
        ("0.9.0.dev0", "ScoreForm 0.9.0.dev0", "ScoreForm 0.9.0"),
    ],
)
def test_version_regex_literal_matches_only_the_exact_version_line(
    version,
    matching_output,
    nonmatching_output,
):
    pattern = update_version.version_regex_literal(version)

    assert re.search(pattern, f"prefix\n{matching_output}\nsuffix", re.MULTILINE)
    assert not re.search(pattern, nonmatching_output, re.MULTILINE)


def test_update_pyproject_version_updates_project_version():
    text = '[project]\nname = "scoreform"\nversion = "0.7.0.dev0"\n'

    updated = update_version.update_pyproject_version(text, "0.8.0")

    assert updated == '[project]\nname = "scoreform"\nversion = "0.8.0"\n'


@pytest.mark.parametrize(
    "existing_assertion",
    [
        'assert re.search(r"0\\.7\\.0", output)',
        'assert re.search(r"^ScoreForm 0\\.7\\.0$", output, re.MULTILINE)',
    ],
)
def test_update_cli_discoverability_test_version_replaces_loose_and_strict_assertions(
    existing_assertion,
):
    text = (
        f"{existing_assertion}\n"
        'assert scoreform.cli.get_version() == "0.7.0"\n'
    )

    updated = update_version.update_cli_discoverability_test_version(text, "0.8.0")

    assert 'assert re.search(r"^ScoreForm 0\\.8\\.0$", output, re.MULTILINE)' in updated
    assert 'assert scoreform.cli.get_version() == "0.8.0"' in updated


def test_update_cli_discoverability_test_version_supports_repeated_strict_updates():
    text = (
        'assert re.search(r"^ScoreForm 0\\.8\\.0$", output, re.MULTILINE)\n'
        'assert scoreform.cli.get_version() == "0.8.0"\n'
    )

    updated = update_version.update_cli_discoverability_test_version(text, "0.9.0.dev0")

    assert (
        'assert re.search(r"^ScoreForm 0\\.9\\.0\\.dev0$", output, re.MULTILINE)'
        in updated
    )
    assert 'assert scoreform.cli.get_version() == "0.9.0.dev0"' in updated


def test_update_readme_version_updates_only_current_version_line():
    text = "# ScoreForm\n\nCurrent version: `0.8.1`.\n\nHistory: v0.8.1\n"

    updated = update_version.update_readme_version(text, "0.9.1")

    assert "Current version: `0.9.1`." in updated
    assert "History: v0.8.1" in updated


def test_update_readme_version_requires_unique_authoritative_line():
    with pytest.raises(update_version.VersionUpdateError):
        update_version.update_readme_version("# ScoreForm\n", "0.9.1")


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
    (tmp_path / "README.md").write_text(
        "# ScoreForm\n\nCurrent version: `0.7.0.dev0`.\n",
        encoding="utf-8",
    )

    update_version.update_version(tmp_path, "0.8.0.dev0")

    assert 'version = "0.8.0.dev0"' in (tmp_path / "pyproject.toml").read_text(encoding="utf-8")
    cli_test_text = (tmp_path / "tests" / "test_cli_discoverability.py").read_text(encoding="utf-8")
    assert (
        'assert re.search(r"^ScoreForm 0\\.8\\.0\\.dev0$", output, re.MULTILINE)'
        in cli_test_text
    )
    assert 'assert scoreform.cli.get_version() == "0.8.0.dev0"' in cli_test_text
    assert "Current version: `0.8.0.dev0`." in (
        tmp_path / "README.md"
    ).read_text(encoding="utf-8")


def test_update_version_fails_when_pyproject_pattern_is_missing(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "pyproject.toml").write_text("[project]\nname = \"scoreform\"\n", encoding="utf-8")
    (tmp_path / "tests" / "test_cli_discoverability.py").write_text(
        'assert re.search(r"0\\.7\\.0\\.dev0", output)\n'
        'assert scoreform.cli.get_version() == "0.7.0.dev0"\n',
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text(
        "Current version: `0.7.0.dev0`.\n", encoding="utf-8"
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
    (tmp_path / "README.md").write_text(
        "Current version: `0.7.0.dev0`.\n", encoding="utf-8"
    )

    with pytest.raises(update_version.VersionUpdateError):
        update_version.update_version(tmp_path, "0.8.0.dev0")
