"""Read-only physical OMR trial on existing Core-retained ScoreForm failures.

Example:
  python scripts/qualify_issue225_physical_recovery.py --workspace PRIVATE_ROOT \\
      --page 'failure_id=@recorded' --output PRIVATE_REPORT.json

This command never writes a result or a route decision. Its small report is not
proof that the physical paper's bubble marks were interpreted correctly.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scoreform.cli_scan_recovery import parse_recovery_page_spec
from scoreform.qr_physical_recovery_qualification import (
    PhysicalRecoverySelection,
    build_physical_recovery_report,
    qualify_physical_recovery_page,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True, help="Existing authorized PDS workspace root")
    parser.add_argument(
        "--page", action="append", required=True, metavar="FAILURE_ID=ROUTE",
        help="Exact canonical PDS2 route or @recorded, repeated per failed page",
    )
    parser.add_argument(
        "--correct-failure", action="append", default=[], metavar="FAILURE_ID",
        help="Deliberate permission to preview correction of a prior route (no write)",
    )
    parser.add_argument("--output", type=Path, required=True, help="New privacy-bounded JSON output file")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        options = _parser().parse_args(argv)
        root = options.workspace.resolve(strict=True)
        if not root.is_dir():
            raise ValueError("workspace is not a directory")
        output = options.output.resolve(strict=False)
        if output.is_relative_to(root) or output.is_relative_to(Path(__file__).resolve().parents[1]):
            raise ValueError("Report must be outside the workspace and repository.")
        if output.exists() or not output.parent.is_dir():
            raise ValueError("Report must be a new file in an existing directory.")
        corrected = set(options.correct_failure)
        if len(corrected) != len(options.correct_failure):
            raise ValueError("Duplicate correction choices are not allowed.")
        choices = tuple(
            parse_recovery_page_spec(
                page, allow_route_correction=page.partition("=")[0] in corrected
            ) for page in options.page
        )
        ids = tuple(choice.failure_id for choice in choices)
        if len(ids) != len(set(ids)) or not corrected.issubset(set(ids)):
            raise ValueError("Failure IDs must be distinct; correction flags must match.")
        selections = tuple(
            PhysicalRecoverySelection(
                failure_id=choice.failure_id,
                route_locator=choice.route_locator,
                use_recorded_route=choice.use_recorded_route,
                allow_route_correction=choice.allow_route_correction,
            ) for choice in choices
        )
        outcomes = tuple(
            qualify_physical_recovery_page(root, selection, index=i)
            for i, selection in enumerate(selections, start=1)
        )
        report = build_physical_recovery_report(outcomes)
        with output.open("x", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, sort_keys=True)
            handle.write("\n")
        for page in outcomes:
            print(f"Selection {page.index}: {page.outcome} ({page.stage})")
        print("Privacy-bounded qualification written; no result or route decision saved.")
        print("Teacher paper-mark comparison and actual recovery remain separate.")
        return 0 if report["all_pages_scored"] else 2
    except (OSError, TypeError, ValueError) as error:
        # Do not print error values: they can contain local paths or identifiers.
        print(f"Physical recovery qualification could not start ({type(error).__name__}).")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
