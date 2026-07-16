"""Verify release-relevant tracked text is strict UTF-8 without mojibake."""

from __future__ import annotations

import subprocess
from pathlib import Path

TEXT_SUFFIXES = frozenset({".md", ".toml", ".yml", ".yaml", ".py", ".ps1"})
MOJIBAKE_SEQUENCES = (
    "\u0393\u00c7",
    "\u00e2\u20ac",
    "\u00ef\u00bf\u00bd",
    "\ufffd",
)


def find_mojibake(text: str) -> tuple[str, ...]:
    return tuple(sequence for sequence in MOJIBAKE_SEQUENCES if sequence in text)


def tracked_text_paths(root: Path) -> tuple[Path, ...]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return tuple(
        root / line
        for line in result.stdout.splitlines()
        if Path(line).suffix.lower() in TEXT_SUFFIXES
    )


def validate_text_encoding(root: Path) -> list[str]:
    failures: list[str] = []
    for path in tracked_text_paths(root):
        relative = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding="utf-8", errors="strict")
        except UnicodeDecodeError as error:
            failures.append(f"{relative}: invalid UTF-8: {error}")
            continue
        for sequence in find_mojibake(text):
            failures.append(f"{relative}: mojibake sequence {sequence!r}")
    return failures


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    failures = validate_text_encoding(root)
    if failures:
        print("Release text encoding validation failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("Tracked release text is strict UTF-8 with no known mojibake markers.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
