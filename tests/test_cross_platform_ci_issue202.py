from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CI = ROOT / ".github" / "workflows" / "ci.yml"
RELEASE = ROOT / ".github" / "workflows" / "release-readiness.yml"
DOC = ROOT / "docs" / "continuous_integration.md"
README = ROOT / "README.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_ci_has_exact_supported_environment_matrix() -> None:
    text = _read(CI)

    assert text.startswith("name: CI\n")
    assert "pull_request:" in text
    assert "branches: [main]" in text
    assert "fail-fast: false" in text
    assert "os: [windows-latest, ubuntu-latest]" in text
    assert 'python: ["3.11", "3.12", "3.13", "3.14"]' in text
    assert "runs-on: ${{ matrix.os }}" in text
    assert "python-version: ${{ matrix.python }}" in text


def test_ci_authenticates_exact_released_core_reference() -> None:
    text = _read(CI)

    assert (
        "https://github.com/Paper-Data-Suite/pds-core/releases/download/"
        "v0.6.3/pds_core-0.6.3-py3-none-any.whl"
    ) in text
    assert (
        'Path(os.environ["RUNNER_TEMP"]) / "pds_core-0.6.3-py3-none-any.whl"'
        in text
    )
    assert (
        'python scripts/verify_core_wheel.py '
        '"${{ runner.temp }}/pds_core-0.6.3-py3-none-any.whl"'
        in text
    )
    assert 'version("pds-core") != "0.6.3"' in text
    assert "98d7596ce0eed26e4d56a17bbbbd644db3014259b56a45783a173fe8237af5e5" in text
    assert "../pds-core" not in text



def test_ci_uses_runner_context_only_at_step_scope() -> None:
    text = _read(CI)
    env_start = text.index("    env:\n")
    steps_start = text.index("\n    steps:\n", env_start)
    job_env = text[env_start:steps_start]

    assert "${{ runner." not in job_env
    assert 'RUFF_CACHE_DIR: ${{ runner.temp }}/ruff-cache' in text

def test_ci_installs_authenticated_poppler_on_both_platforms() -> None:
    text = _read(CI)

    assert "sudo apt-get update && sudo apt-get install -y poppler-utils" in text
    assert "v26.02.0-0/Release-26.02.0-0.zip" in text
    assert "993e4a94376ed712fafc7058d724ea0b943d118bbd2305cd9ed55174eb85cda5" in text
    assert "Get-FileHash -Algorithm SHA256" in text
    assert "Authenticated Poppler archive did not contain pdftoppm.exe" in text


def test_ci_runs_ordinary_repository_contract() -> None:
    text = _read(CI)

    required = (
        "python -m pip check",
        "python -m pytest tests",
        "python -m ruff check .",
        "python -m mypy scoreform",
        "python scripts/verify_release_compatibility.py",
        "git diff --check",
        "git diff --exit-code",
        "git diff --cached --exit-code",
        "git status --porcelain --untracked-files=all",
    )
    for marker in required:
        assert marker in text


def test_ci_mypy_targets_each_matrix_interpreter() -> None:
    text = _read(CI)

    assert '--python-version "${{ matrix.python }}"' in text
    assert 'python_version = "3.11"' not in text


def test_ci_keeps_generated_state_outside_checkout() -> None:
    text = _read(CI)

    assert 'PYTHONDONTWRITEBYTECODE: "1"' in text
    assert 'RUFF_CACHE_DIR: ${{ runner.temp }}/ruff-cache' in text
    assert '--basetemp "${{ runner.temp }}/pds-scoreform-pytest"' in text
    assert '-o cache_dir="${{ runner.temp }}/pytest-cache"' in text
    assert '--cache-dir "${{ runner.temp }}/mypy-cache"' in text
    assert 'Path("scoreform.egg-info")' in text


def test_ci_does_not_duplicate_heavyweight_release_acceptance() -> None:
    ci_text = _read(CI)
    release_text = _read(RELEASE)

    heavyweight = (
        "python -m build",
        "python -m twine check",
        "verify_release_artifacts.py",
        "verify_installed_assignment_copy_acceptance.py",
        "verify_installed_assignment_preset_acceptance.py",
        "verify_installed_assignment_bulk_entry_acceptance.py",
        "verify_installed_multi_class_generation_acceptance.py",
        "verify_installed_producer_acceptance.py",
    )
    for marker in heavyweight:
        assert marker not in ci_text
        assert marker in release_text

    assert "runs-on: ubuntu-latest" in release_text
    assert 'python-version: "3.11"' in release_text


def test_ci_documentation_defines_layering_and_support_boundary() -> None:
    text = _read(DOC)

    assert "Windows (`windows-latest`)" in text
    assert "Ubuntu (`ubuntu-latest`)" in text
    assert "3.11, 3.12, 3.13, 3.14" in text
    assert "Python 3.11 remains the language and package-metadata floor" in text
    assert "pds-core>=0.6.2,<0.7" in text
    assert "PDS Core 0.6.3" in text
    assert "not" in text and "printer/scanner acceptance" in text
    assert "run_tests.ps1" in text


def test_readme_links_ci_contract_and_keeps_python_floor() -> None:
    text = _read(README)
    normalized = " ".join(text.split())

    assert "Routine CI validates Windows and Ubuntu on Python 3.11 through 3.14." in normalized
    assert "Python 3.11 remains the minimum supported interpreter" in normalized
    assert "docs/continuous_integration.md" in text
    assert "pds-core>=0.6.2,<0.7" in text
