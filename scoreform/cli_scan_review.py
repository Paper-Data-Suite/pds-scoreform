"""Direct ScoreForm scan-review commands."""

from __future__ import annotations

import argparse

from scoreform import workspace
from scoreform.scan_review_resolution import (
    RESOLUTION_ACTIONS,
    ScanReviewError,
    discover_scan_review_items,
    resolve_scan_review_item,
)


def _list_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="scoreform list-scan-review", add_help=False)
    parser.add_argument("--include-resolved", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--class-id")
    parser.add_argument("--assignment-id")
    parser.add_argument("--failure-category")
    parser.add_argument("--help", "-h", action="help")
    return parser


def _resolve_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scoreform resolve-scan-review", add_help=False
    )
    parser.add_argument("failure_id")
    parser.add_argument("--action", choices=RESOLUTION_ACTIONS, required=True)
    parser.add_argument("--message")
    parser.add_argument("--evidence-path")
    parser.add_argument("--class-id")
    parser.add_argument("--assignment-id")
    parser.add_argument("--student-id")
    parser.add_argument("--help", "-h", action="help")
    return parser


def _value(value) -> str:
    return str(value) if value not in (None, "") else "—"


def print_review_items(discovery) -> None:
    print("ScoreForm scan review items")
    print()
    if not discovery.items:
        print("No matching active scan review items.")
    for index, item in enumerate(discovery.items, start=1):
        print(f"{index}. {item.failure_id}")
        print(f"   Status: {item.status}")
        print(f"   Category: {item.failure_category}")
        print(f"   Source: {_value(item.source_filename)}")
        print(f"   Page: {_value(item.source_page_number)}")
        print(f"   Class: {_value(item.class_id)}")
        print(f"   Assignment: {_value(item.assignment_id)}")
        print(f"   Student: {_value(item.student_id)}")
        print(f"   Review record: {item.failure_metadata_relative_path}")
        print(f"   Retained source: {_value(item.retained_source_path)}")
    if discovery.warning_count:
        print()
        print(
            f"Warning: Ignored {discovery.warning_count} malformed review "
            "or resolution record(s)."
        )


def run_list_scan_review(args) -> int:
    try:
        options = _list_parser().parse_args(args)
        root = workspace.get_scoreform_workspace_root()
        discovery = discover_scan_review_items(
            root,
            include_resolved=options.include_resolved,
            limit=options.limit,
            class_id=options.class_id,
            assignment_id=options.assignment_id,
            failure_category=options.failure_category,
        )
        print_review_items(discovery)
        return 0
    except (ScanReviewError, SystemExit) as error:
        if isinstance(error, SystemExit):
            return int(error.code or 0)
        print(f"Error: {error}")
        return 1


def run_resolve_scan_review(args) -> int:
    try:
        options = _resolve_parser().parse_args(args)
        if options.action == "manual_entry":
            print(
                "Error: Manual entry requires answer-by-answer confirmation. "
                "Use Assignment Management > Resolve Scan Review Items."
            )
            return 1
        root = workspace.get_scoreform_workspace_root()
        result = resolve_scan_review_item(
            root,
            options.failure_id,
            options.action,
            message=options.message,
            evidence_path=options.evidence_path,
            class_id=options.class_id,
            assignment_id=options.assignment_id,
            student_id=options.student_id,
        )
        print(f"Scan review item {result.resolution_status}.")
        print(f"Action: {result.resolution_action}")
        print(f"Resolution record: {result.resolution_metadata_relative_path}")
        if result.evidence_path:
            print(f"Evidence: {result.evidence_path}")
        return 0
    except (ScanReviewError, SystemExit, OSError) as error:
        if isinstance(error, SystemExit):
            return int(error.code or 0)
        print(f"Error: {error}")
        return 1
