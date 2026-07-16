"""Build synthetic assignment/roster inputs for installed release smoke tests."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--class-id", required=True)
    parser.add_argument("--assignment-id", required=True)
    parser.add_argument("--questions", type=int, required=True)
    parser.add_argument("--layout-id")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)

    assignment = {
        "assignment_id": args.assignment_id,
        "title": f"Synthetic {args.assignment_id}",
        "question_count": args.questions,
        "choices": ["A", "B", "C", "D"],
        "answer_key": {
            str(number): ("A", "B", "C", "D")[(number - 1) % 4]
            for number in range(1, args.questions + 1)
        },
    }
    if args.layout_id:
        assignment["layout_id"] = args.layout_id
    (args.output / "assignment.json").write_text(
        json.dumps(assignment, indent=2) + "\n", encoding="utf-8"
    )
    with (args.output / "roster.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("class_id", "student_id", "last_name", "first_name", "period"))
        writer.writerow((args.class_id, "student1", "Synthetic", "Student", "1"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
