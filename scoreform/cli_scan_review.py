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
    parser.add_argument("--status", choices=("unresolved", "deferred", "resolved"))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--class-id")
    parser.add_argument("--assignment-id")
    parser.add_argument("--student-id")
    parser.add_argument("--failure-category")
    parser.add_argument("--stage")
    parser.add_argument("--source-scan-id")
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
    parser.add_argument("--route-payload")
    parser.add_argument("--help", "-h", action="help")
    return parser


def _value(value) -> str:
    return str(value) if value not in (None, "") else "—"


def _identity_label(source: str) -> str:
    return {
        "validated_target": "Verified target identity",
        "validated_locator": "Validated locator identity",
        "scoreform_diagnostic": "Observed diagnostic identity",
        "none": "No available identity",
    }[source]


def print_review_items(discovery) -> None:
    print("ScoreForm scan review items")
    print()
    if not discovery.items:
        print("No matching active scan review items.")
    for index, item in enumerate(discovery.items, start=1):
        print(f"{index}. {item.failure_id}")
        print(f"   Status: {item.status}")
        print(f"   Created: {item.created_at}")
        print(f"   Category: {item.failure_category}")
        if item.scoreform_failure_category:
            print(f"   ScoreForm category: {item.scoreform_failure_category}")
        print(f"   Stage: {item.stage}")
        print(f"   Source: {_value(item.source_filename)}")
        print(f"   Page: {_value(item.source_page_number)}")
        print(f"   {_identity_label(item.identity.source)}")
        if item.identity.source != "none":
            print(f"     Class: {_value(item.identity.class_id)}")
            print(f"     Assignment: {_value(item.identity.assignment_id)}")
            print(f"     Student: {_value(item.identity.student_id)}")
            print(f"     Route ID: {_value(item.identity.route_id)}")
            print(f"     Page ID: {_value(item.identity.page_id)}")
            print(f"     Issuance ID: {_value(item.identity.issuance_id)}")
            print(f"     Logical page: {_value(item.identity.logical_page)}")
        if item.diagnostic_identity.source == "scoreform_diagnostic":
            print("   Observed diagnostic identity")
            print(f"     Class: {_value(item.diagnostic_identity.class_id)}")
            print(f"     Assignment: {_value(item.diagnostic_identity.assignment_id)}")
            print(f"     Student: {_value(item.diagnostic_identity.student_id)}")
        print(f"   Resolutions: {len(item.resolution_history)}")
        if item.latest_resolution_action:
            print(f"   Latest action: {item.latest_resolution_action}")
            print(f"   Latest resolution: {item.latest_resolution_time}")
        if (
            item.latest_resolution_details is not None
            and item.latest_resolution_details.identity_source == "teacher_verified"
        ):
            identity = item.latest_resolution_details.identity
            print("   Teacher-verified resolution identity")
            print(f"     Class: {_value(identity.get('class_id'))}")
            print(f"     Assignment: {_value(identity.get('assignment_id'))}")
            print(f"     Student: {_value(identity.get('student_id'))}")
        print(f"   Review record: {item.failure_metadata_relative_path}")
        print(f"   Retained source: {_value(item.retained_source_path)}")
    if discovery.warning_count:
        print()
        print(f"Warning: Ignored {discovery.warning_count} review record(s).")
        print(f"  Invalid failures: {discovery.invalid_failure_count}")
        print(f"  Invalid resolutions: {discovery.invalid_resolution_count}")
        print(f"  Unsupported v1 failures: {discovery.unsupported_v1_failure_count}")
        print(
            f"  Unsupported v1 resolutions: {discovery.unsupported_v1_resolution_count}"
        )
        print(f"  Orphan resolutions: {discovery.orphan_resolution_count}")
        print(f"  Provenance mismatches: {discovery.provenance_mismatch_count}")
        print(
            f"  Malformed ScoreForm details: {discovery.malformed_scoreform_details_count}"
        )
        print(f"  Foreign records: {discovery.foreign_record_count}")


def run_list_scan_review(args) -> int:
    try:
        options = _list_parser().parse_args(args)
        root = workspace.get_scoreform_workspace_root()
        discovery = discover_scan_review_items(
            root,
            include_resolved=options.include_resolved,
            status=options.status,
            limit=options.limit,
            class_id=options.class_id,
            assignment_id=options.assignment_id,
            student_id=options.student_id,
            failure_category=options.failure_category,
            stage=options.stage,
            source_scan_id=options.source_scan_id,
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
            route_payload=options.route_payload,
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
