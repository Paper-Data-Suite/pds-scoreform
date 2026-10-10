"""Inspect or explicitly recover one interrupted ScoreForm roster/metadata pair.

Only run --apply after stopping all ScoreForm and Core writers for this class.
No student or metadata content is printed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from scoreform.class_pair_recovery import (
    ClassPairRecoveryError,
    inspect_class_pair_recovery,
    recover_class_pair,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--class-id", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-writers-stopped", action="store_true")
    args = parser.parse_args()
    if args.apply and not args.confirm_writers_stopped:
        parser.error("--apply requires --confirm-writers-stopped")
    try:
        status = inspect_class_pair_recovery(args.workspace, args.class_id)
        print(f"Class-pair journal inspection: {status}")
        if args.apply:
            print("Class-pair recovery: " + recover_class_pair(args.workspace, args.class_id))
        elif status != "none":
            print("Read-only inspection. No files changed. Stop writers before --apply.")
        return 2 if status == "conflict" else 0
    except (ClassPairRecoveryError, OSError, ValueError) as error:
        print(f"Class-pair recovery refused: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
