from __future__ import annotations

import ast
from pathlib import Path

import pytest

import scripts.verify_release_compatibility as compatibility


def test_release_version_is_unique_v010_identity() -> None:
    assert compatibility.RELEASE_VERSION == "0.10.0"
    assert compatibility.LEGACY_COLLIDING_VERSION == "0.9.1"
    assert compatibility.RELEASE_VERSION != compatibility.LEGACY_COLLIDING_VERSION


def test_release_identity_audit_passes_current_tree() -> None:
    compatibility.validate_release_identity()


def test_core_dependency_audit_passes_current_tree() -> None:
    compatibility.validate_core_dependency()


def test_sibling_import_audit_passes_current_tree() -> None:
    compatibility.validate_sibling_import_isolation()


def test_producer_profile_is_exact_downstream_contract() -> None:
    compatibility.validate_producer_profile()


def test_reader_policy_boundary_requires_explicit_attempt_identity() -> None:
    compatibility.validate_reader_policy_boundary()


def test_import_root_extracts_import_and_from_import_roots() -> None:
    tree = ast.parse(
        "import meridian.adapters\n"
        "import os, vitrine.models\n"
        "from pds_meridian.foo import bar\n"
        "from scoreform import cli\n"
    )
    roots = [
        root
        for node in ast.walk(tree)
        for root in compatibility._import_root(node)
    ]
    assert roots == ["meridian", "os", "vitrine", "pds_meridian", "scoreform"]


def test_release_identity_rejects_colliding_legacy_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "scoreform"\nversion = "0.10.0"\ndependencies = []\n',
        encoding="utf-8",
    )
    legacy = tmp_path / "live.txt"
    legacy.write_text("release 0.9.1\n", encoding="utf-8")
    monkeypatch.setattr(compatibility, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(compatibility, "STRICT_VERSION_FILES", (Path("live.txt"),))

    with pytest.raises(
        compatibility.ReleaseCompatibilityError, match="still names 0.9.1"
    ):
        compatibility.validate_release_identity()


def test_sibling_import_audit_rejects_runtime_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = tmp_path / "scoreform"
    package.mkdir()
    (package / "bad.py").write_text("import vitrine\n", encoding="utf-8")
    monkeypatch.setattr(compatibility, "PROJECT_ROOT", tmp_path)

    with pytest.raises(
        compatibility.ReleaseCompatibilityError, match="imports sibling modules"
    ):
        compatibility.validate_sibling_import_isolation()


def test_readme_allows_only_explicit_historical_v091_reference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "scoreform"\nversion = "0.10.0"\ndependencies = []\n',
        encoding="utf-8",
    )
    live = tmp_path / "live.txt"
    live.write_text("ScoreForm 0.10.0\n", encoding="utf-8")
    readme = tmp_path / "README.md"
    readme.write_text(
        "\n".join(
            [
                "Current version: `0.10.0`.",
                "scoreform-0.10.0-py3-none-any.whl",
                "Generate new v0.10.0 PDS2 answer sheets",
                "`RELEASE_NOTES_v0.10.0.md` — v0.10.0 GitHub Release body",
                "`RELEASE_NOTES_v0.9.1.md` — historical v0.9.1 GitHub Release body",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(compatibility, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(compatibility, "STRICT_VERSION_FILES", (Path("live.txt"),))

    compatibility.validate_release_identity()


def test_core_05_text_audit_is_limited_to_runtime_release_surfaces() -> None:
    assert Path("README.md") not in compatibility.CORE_RUNTIME_RELEASE_FILES
    assert Path("docs/release_checklist.md") not in compatibility.CORE_RUNTIME_RELEASE_FILES
    assert Path("docs/development_plan.md") not in compatibility.CORE_RUNTIME_RELEASE_FILES
    assert Path("pyproject.toml") in compatibility.CORE_RUNTIME_RELEASE_FILES
    assert Path("run_tests.ps1") in compatibility.CORE_RUNTIME_RELEASE_FILES
    assert Path(".github/workflows/release-readiness.yml") in (
        compatibility.CORE_RUNTIME_RELEASE_FILES
    )
