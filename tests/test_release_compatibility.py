from __future__ import annotations

import ast
from pathlib import Path

import pytest

import scripts.verify_release_compatibility as compatibility


def test_release_version_is_exact_v0130_identity() -> None:
    assert compatibility.RELEASE_VERSION == "0.13.0"
    assert compatibility.HISTORICAL_RELEASE_VERSION == "0.10.0"
    assert compatibility.HISTORICAL_V011_RELEASE_VERSION == "0.11.0"
    assert compatibility.HISTORICAL_V012_RELEASE_VERSION == "0.12.0"
    assert compatibility.RELEASE_VERSION != compatibility.HISTORICAL_V012_RELEASE_VERSION


def test_release_identity_audit_passes_current_tree() -> None:
    compatibility.validate_release_identity()


def test_core_dependency_audit_passes_current_tree() -> None:
    compatibility.validate_core_dependency()


def test_sibling_import_audit_passes_current_tree() -> None:
    compatibility.validate_sibling_import_isolation()


def test_producer_profile_is_exact_downstream_contract() -> None:
    compatibility.validate_producer_profile()


def test_operations_profile_is_exact_attention_and_readiness_contract() -> None:
    compatibility.validate_operations_profile()


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


def _write_v0130_readme(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "Current version: `0.13.0`.",
                "scoreform-0.13.0-py3-none-any.whl",
                "RELEASE_NOTES_v0.13.0.md",
                "v0.13.0_release_audit.md",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _write_required_v0130_files(root: Path) -> tuple[Path, ...]:
    required = (Path("notes.md"), Path("audit.md"), Path("bridge.py"))
    for relative in required:
        (root / relative).write_text("ok\n", encoding="utf-8")
    return required


def _patch_release_identity_paths(
    monkeypatch: pytest.MonkeyPatch,
    root: Path,
    *,
    live: tuple[Path, ...],
    historical_v010: tuple[Path, ...],
    historical_v012: tuple[Path, ...],
    required: tuple[Path, ...],
) -> None:
    monkeypatch.setattr(compatibility, "PROJECT_ROOT", root)
    monkeypatch.setattr(compatibility, "LIVE_VERSION_FILES", live)
    monkeypatch.setattr(compatibility, "HISTORICAL_RELEASE_FILES", historical_v010)
    monkeypatch.setattr(compatibility, "HISTORICAL_V011_RELEASE_FILES", ())
    monkeypatch.setattr(compatibility, "HISTORICAL_V0121_RELEASE_FILES", ())
    monkeypatch.setattr(compatibility, "HISTORICAL_V012_RELEASE_FILES", historical_v012)
    monkeypatch.setattr(compatibility, "REQUIRED_V0130_FILES", required)


def test_release_identity_requires_v0130_on_live_surface(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "scoreform"\nversion = "0.13.0"\ndependencies = []\n',
        encoding="utf-8",
    )
    live = tmp_path / "live.txt"
    live.write_text("release 0.10.0\n", encoding="utf-8")
    historical = tmp_path / "historical.txt"
    historical.write_text("released 0.10.0\n", encoding="utf-8")
    _write_v0130_readme(tmp_path / "README.md")
    required = _write_required_v0130_files(tmp_path)

    _patch_release_identity_paths(
        monkeypatch,
        tmp_path,
        live=(Path("live.txt"),),
        historical_v010=(Path("historical.txt"),),
        historical_v012=(),
        required=required,
    )

    with pytest.raises(
        compatibility.ReleaseCompatibilityError,
        match="does not name 0.13.0",
    ):
        compatibility.validate_release_identity()


def test_release_identity_allows_truthful_historical_v010_and_v012(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "scoreform"\nversion = "0.13.0"\ndependencies = []\n',
        encoding="utf-8",
    )
    live = tmp_path / "live.txt"
    live.write_text("ScoreForm 0.13.0\n", encoding="utf-8")
    historical_v010 = tmp_path / "historical-v010.txt"
    historical_v010.write_text(
        "ScoreForm 0.10.0 release evidence\n", encoding="utf-8"
    )
    historical_v012 = tmp_path / "historical-v012.txt"
    historical_v012.write_text(
        "ScoreForm 0.12.0 release evidence\n", encoding="utf-8"
    )
    _write_v0130_readme(tmp_path / "README.md")
    required = _write_required_v0130_files(tmp_path)

    _patch_release_identity_paths(
        monkeypatch,
        tmp_path,
        live=(Path("live.txt"),),
        historical_v010=(Path("historical-v010.txt"),),
        historical_v012=(Path("historical-v012.txt"),),
        required=required,
    )

    compatibility.validate_release_identity()


def test_release_identity_rejects_rewritten_historical_v012(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "scoreform"\nversion = "0.13.0"\ndependencies = []\n',
        encoding="utf-8",
    )
    live = tmp_path / "live.txt"
    live.write_text("ScoreForm 0.13.0\n", encoding="utf-8")
    historical_v010 = tmp_path / "historical-v010.txt"
    historical_v010.write_text(
        "ScoreForm 0.10.0 release evidence\n", encoding="utf-8"
    )
    historical_v012 = tmp_path / "historical-v012.txt"
    historical_v012.write_text(
        "ScoreForm 0.12.0 release evidence rewritten for 0.13.0\n",
        encoding="utf-8",
    )
    _write_v0130_readme(tmp_path / "README.md")
    required = _write_required_v0130_files(tmp_path)

    _patch_release_identity_paths(
        monkeypatch,
        tmp_path,
        live=(Path("live.txt"),),
        historical_v010=(Path("historical-v010.txt"),),
        historical_v012=(Path("historical-v012.txt"),),
        required=required,
    )

    with pytest.raises(
        compatibility.ReleaseCompatibilityError,
        match="historical v0.12 release surface was rewritten as 0.13.0",
    ):
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
