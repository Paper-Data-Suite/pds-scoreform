"""Update ScoreForm's known version references."""

from __future__ import annotations

import re
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = Path("pyproject.toml")
CLI_DISCOVERABILITY_TEST_PATH = Path("tests/test_cli_discoverability.py")
VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:\.dev\d+)?$")


class VersionUpdateError(Exception):
    """Raised when a known version reference cannot be updated safely."""


def validate_version(version: str) -> str:
    if not VERSION_PATTERN.fullmatch(version):
        raise VersionUpdateError(
            "Invalid version. Expected formats like 0.8.0, 1.0.0, or 0.8.0.dev0."
        )
    return version


def version_regex_literal(version: str) -> str:
    return rf"^ScoreForm {re.escape(version)}$"


def update_pyproject_version(text: str, version: str) -> str:
    lines = text.splitlines(keepends=True)
    in_project_section = False

    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "[project]":
            in_project_section = True
            continue
        if in_project_section and stripped.startswith("["):
            break
        if in_project_section and re.match(r"^version\s*=", stripped):
            updated, count = re.subn(
                r'^(?P<prefix>\s*version\s*=\s*)(?P<quote>["\'])(?P<version>[^"\']+)(?P=quote)(?P<suffix>\s*(?:#.*)?(?:\r?\n)?)$',
                rf'\g<prefix>"{version}"\g<suffix>',
                line,
            )
            if count != 1:
                raise VersionUpdateError(
                    "Could not update pyproject.toml: malformed [project].version line."
                )
            lines[index] = updated
            return "".join(lines)

    raise VersionUpdateError("Could not update pyproject.toml: missing [project].version line.")


def update_cli_discoverability_test_version(text: str, version: str) -> str:
    escaped_version = version_regex_literal(version)
    updated = text

    updated, regex_count = re.subn(
        r'assert re\.search\(r"(?:\^ScoreForm )?[0-9]+\\\.[0-9]+\\\.[0-9]+(?:\\\.dev[0-9]+)?(?:\$)?", output(?:, re\.MULTILINE)?\)',
        f'assert re.search(r"{escaped_version}", output, re.MULTILINE)',
        updated,
    )
    updated, string_count = re.subn(
        r'assert scoreform\.cli\.get_version\(\) == "[0-9]+\.[0-9]+\.[0-9]+(?:\.dev[0-9]+)?"',
        f'assert scoreform.cli.get_version() == "{version}"',
        updated,
    )

    if regex_count != 1:
        raise VersionUpdateError(
            "Could not update tests/test_cli_discoverability.py: missing expected version regex assertion."
        )
    if string_count != 1:
        raise VersionUpdateError(
            "Could not update tests/test_cli_discoverability.py: missing get_version assertion."
        )

    return updated


def write_updated_file(path: Path, updated_text: str) -> None:
    path.write_text(updated_text, encoding="utf-8")


def update_version(root: Path, version: str) -> None:
    validate_version(version)

    pyproject_path = root / PYPROJECT_PATH
    cli_test_path = root / CLI_DISCOVERABILITY_TEST_PATH

    pyproject_updated = update_pyproject_version(
        pyproject_path.read_text(encoding="utf-8"),
        version,
    )
    cli_test_updated = update_cli_discoverability_test_version(
        cli_test_path.read_text(encoding="utf-8"),
        version,
    )

    write_updated_file(pyproject_path, pyproject_updated)
    write_updated_file(cli_test_path, cli_test_updated)


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    if len(argv) != 1:
        print("Usage: python scripts/update_version.py <version>", file=sys.stderr)
        return 2

    version = argv[0]
    try:
        update_version(PROJECT_ROOT, version)
    except (OSError, VersionUpdateError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Updated ScoreForm version references to {version}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
