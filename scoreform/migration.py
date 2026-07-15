"""Deliberate boundaries for work pending the Core 0.5/PDS2 migration."""

from __future__ import annotations

from typing import NoReturn


class ScoreFormMigrationPendingError(RuntimeError):
    """Raised when an operation depends on a later PDS2 migration issue."""


def migration_pending(operation: str, follow_up_issue: str) -> NoReturn:
    """Stop an unavailable operation before it can write partial artifacts."""
    raise ScoreFormMigrationPendingError(
        f"{operation} is temporarily unavailable during the Core 0.5/PDS2 "
        f"migration. Follow-up issue {follow_up_issue} will provide the PDS2 "
        "implementation; no legacy PDS1 data or partial routing artifacts "
        "were written."
    )


def print_migration_error(error: ScoreFormMigrationPendingError) -> int:
    """Render an expected migration boundary as a normal CLI failure."""
    print(f"Error: {error}")
    return 1
