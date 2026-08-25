from __future__ import annotations

import subprocess
import sys
from pathlib import Path

TEST_PATH = Path("tests/test_share_results_release_integration_issue191.py")
ACCEPTANCE_PATH = Path(
    "scripts/verify_installed_share_results_with_meridian_acceptance.py"
)

OLD_TEST = '''def test_package_contract_stays_core_06_range_without_meridian_dependency() -> None:
    pyproject = _read("pyproject.toml")
    dependencies_block = pyproject.split("dependencies = [", 1)[1].split("]", 1)[0]
    requirements = [
        Requirement(line.strip().strip('",'))
        for line in dependencies_block.splitlines()
        if line.strip().startswith('"')
    ]
    names = {canonicalize_name(item.name) for item in requirements}

    assert "pds-core" in names
    core = next(item for item in requirements if canonicalize_name(item.name) == "pds-core")
    assert str(core.specifier) in {">=0.6,<0.7", "<0.7,>=0.6"}
    assert "pds-meridian" not in names
    assert "meridian" not in names
    assert 'version = "0.10.0"' in pyproject
'''

NEW_TEST = '''def test_package_contract_stays_core_06_range_without_meridian_dependency() -> None:
    pyproject_path = PROJECT_ROOT / "pyproject.toml"
    pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    project = pyproject["project"]
    requirements = [Requirement(item) for item in project["dependencies"]]
    names = {canonicalize_name(item.name) for item in requirements}

    assert "pds-core" in names
    core = next(
        item
        for item in requirements
        if canonicalize_name(item.name) == "pds-core"
    )
    assert str(core.specifier) in {">=0.6,<0.7", "<0.7,>=0.6"}
    assert "pds-meridian" not in names
    assert "meridian" not in names
    assert project["version"] == "0.10.0"
'''


def patch_test() -> None:
    text = TEST_PATH.read_text(encoding="utf-8")
    if "import tomllib\n" not in text:
        marker = "from pathlib import Path\n"
        if marker not in text:
            raise SystemExit("Expected pathlib import marker not found.")
        text = text.replace(marker, marker + "import tomllib\n", 1)

    if NEW_TEST not in text:
        if OLD_TEST not in text:
            raise SystemExit("Expected brittle package-contract test block not found.")
        text = text.replace(OLD_TEST, NEW_TEST, 1)

    TEST_PATH.write_text(text, encoding="utf-8", newline="\n")
    print("Replaced brittle dependency parsing with tomllib.")


def fix_imports() -> None:
    if not ACCEPTANCE_PATH.is_file():
        raise SystemExit(f"Missing expected acceptance script: {ACCEPTANCE_PATH}")
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--fix",
            "--select",
            "I",
            str(ACCEPTANCE_PATH),
        ],
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)
    print("Normalized #191 installed-acceptance imports with Ruff.")


def main() -> None:
    patch_test()
    fix_imports()
    try:
        Path(__file__).unlink()
    except OSError:
        pass
    print("Applied #191 Slice 7a acceptance-scaffolding fixes.")


if __name__ == "__main__":
    main()
