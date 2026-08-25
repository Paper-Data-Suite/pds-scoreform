"""Read-only direct CLI for ScoreForm-local diagnostic events."""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from dataclasses import asdict

from scoreform import workspace
from scoreform.diagnostic_events import (
    DEFAULT_EVENT_LIST_LIMIT,
    MAX_EVENT_LIST_LIMIT,
    DiagnosticEvent,
    DiagnosticEventError,
    DiagnosticEventListing,
    DiagnosticEventStorageError,
    list_diagnostic_events,
    load_diagnostic_event,
)

DIAGNOSTICS_USAGE = """Usage:
  scoreform diagnostics list [--limit <n>] [--format <text|json>]
  scoreform diagnostics show --event-id <event_id> [--format <text|json>]"""


class DiagnosticCliError(ValueError):
    """One direct diagnostics command is invalid."""


def print_diagnostics_help() -> None:
    print(DIAGNOSTICS_USAGE)
    print()
    print(
        "Diagnostics are read-only, ScoreForm-local, privacy-minimal "
        "troubleshooting history."
    )
    print(
        f"List defaults to {DEFAULT_EVENT_LIST_LIMIT} events and accepts at most "
        f"{MAX_EVENT_LIST_LIMIT}."
    )
    print("No command here clears, repairs, uploads, streams, or changes domain state.")


def _parse_options(
    args: Sequence[str],
    *,
    allowed: frozenset[str],
) -> dict[str, str]:
    values: dict[str, str] = {}
    index = 0
    while index < len(args):
        token = args[index]
        if token not in allowed:
            if token.startswith("--"):
                raise DiagnosticCliError(f"Unknown option: {token}.")
            raise DiagnosticCliError(f"Unexpected positional argument: {token}.")
        if token in values:
            raise DiagnosticCliError(f"Duplicate option: {token}.")
        if index + 1 >= len(args) or args[index + 1].startswith("--"):
            raise DiagnosticCliError(f"Missing value for {token}.")
        values[token] = args[index + 1]
        index += 2
    return values


def _parse_format(value: str | None) -> str:
    rendered = "text" if value is None else value
    if rendered not in {"text", "json"}:
        raise DiagnosticCliError("--format must be text or json.")
    return rendered


def _parse_limit(value: str | None) -> int:
    if value is None:
        return DEFAULT_EVENT_LIST_LIMIT
    if not value.isdecimal():
        raise DiagnosticCliError("--limit must be a positive integer.")
    limit = int(value)
    if not 1 <= limit <= MAX_EVENT_LIST_LIMIT:
        raise DiagnosticCliError(
            f"--limit must be between 1 and {MAX_EVENT_LIST_LIMIT}."
        )
    return limit


def _event_payload(event: DiagnosticEvent) -> dict[str, object]:
    """Return only the fixed schema-v1 dataclass fields."""
    return asdict(event)


def _print_warnings(warning_codes: Sequence[str]) -> None:
    if not warning_codes:
        return
    print(f"Warnings: {len(warning_codes)} retained diagnostic entries were skipped.")
    for code in sorted(set(warning_codes)):
        print(f"  - {code}")


def _print_list_text(listing: DiagnosticEventListing) -> None:
    if not listing.events:
        print("No retained ScoreForm diagnostic events.")
        _print_warnings(listing.warning_codes)
        return

    print(f"ScoreForm diagnostic events: {len(listing.events)}")
    for event in listing.events:
        context = []
        if event.class_id is not None:
            context.append(f"class={event.class_id}")
        if event.assignment_id is not None:
            context.append(f"assignment={event.assignment_id}")
        rendered_context = "" if not context else " " + " ".join(context)
        print(
            f"{event.occurred_at} {event.event_id} "
            f"{event.outcome} {event.code}{rendered_context}"
        )
        print(f"  {event.safe_summary}")
    _print_warnings(listing.warning_codes)


def _print_event_text(event: DiagnosticEvent) -> None:
    for field, value in _event_payload(event).items():
        rendered = "null" if value is None else str(value)
        print(f"{field}: {rendered}")


def _run_list(args: Sequence[str]) -> int:
    values = _parse_options(
        args,
        allowed=frozenset({"--limit", "--format"}),
    )
    limit = _parse_limit(values.get("--limit"))
    output_format = _parse_format(values.get("--format"))
    root = workspace.resolve_workspace_root()
    listing = (
        list_diagnostic_events(root, limit=limit)
        if os.path.lexists(root)
        else DiagnosticEventListing(events=(), warning_codes=())
    )

    if output_format == "json":
        print(
            json.dumps(
                {
                    "events": [_event_payload(event) for event in listing.events],
                    "warning_codes": list(listing.warning_codes),
                },
                ensure_ascii=True,
                indent=2,
                sort_keys=True,
            )
        )
    else:
        _print_list_text(listing)
    return 0


def _run_show(args: Sequence[str]) -> int:
    values = _parse_options(
        args,
        allowed=frozenset({"--event-id", "--format"}),
    )
    event_id = values.get("--event-id")
    if event_id is None:
        raise DiagnosticCliError("Missing required option: --event-id.")
    output_format = _parse_format(values.get("--format"))
    root = workspace.resolve_workspace_root()
    if not os.path.lexists(root):
        raise DiagnosticEventStorageError("Diagnostic event was not found.")
    event = load_diagnostic_event(root, event_id)

    if output_format == "json":
        print(
            json.dumps(
                _event_payload(event),
                ensure_ascii=True,
                indent=2,
                sort_keys=True,
            )
        )
    else:
        _print_event_text(event)
    return 0


def run_diagnostics(args: Sequence[str]) -> int:
    """Dispatch ``scoreform diagnostics`` without mutating diagnostic state."""
    if not args or args[0] in {"help", "--help", "-h"}:
        print_diagnostics_help()
        return 0 if args else 1

    action = args[0]
    try:
        if action == "list":
            return _run_list(args[1:])
        if action == "show":
            return _run_show(args[1:])
        raise DiagnosticCliError(f"Unknown diagnostics command: {action}.")
    except (DiagnosticCliError, DiagnosticEventError, workspace.WorkspaceRootError) as error:
        print(f"Error: {error}")
        print()
        print(DIAGNOSTICS_USAGE)
        return 1


__all__ = [
    "DIAGNOSTICS_USAGE",
    "DiagnosticCliError",
    "print_diagnostics_help",
    "run_diagnostics",
]
