"""Privacy-minimized direct CLI for immutable academic-result manifests."""

from __future__ import annotations

from collections.abc import Sequence

from scoreform import workspace
from scoreform.academic_result_manifest_generation import (
    ScoreFormManifestGenerationError,
    ScoreFormManifestGenerationPartialSuccessError,
    generate_academic_result_manifest,
    list_academic_result_manifest_revisions,
    load_academic_result_manifest_revision,
    validate_academic_result_manifest_revision,
)
from scoreform.work_paths import scoreform_work_ref

MANIFEST_USAGE = """Usage:
  scoreform manifest list --class-id <class_id> --assignment-id <assignment_id>
  scoreform manifest show --class-id <class_id> --assignment-id <assignment_id> --revision <revision>
  scoreform manifest validate --class-id <class_id> --assignment-id <assignment_id> --revision <revision>
  scoreform manifest generate --class-id <class_id> --assignment-id <assignment_id>"""


def print_manifest_help() -> None:
    print(MANIFEST_USAGE)
    print()
    print("Manifest revisions are immutable producer bytes.")
    print("Generation does not publish through Core and does not create a Grade.")


def _parse_options(args: Sequence[str], required: tuple[str, ...]) -> dict[str, str]:
    values: dict[str, str] = {}
    index = 0
    while index < len(args):
        option = args[index]
        if option not in required:
            kind = "Unknown option" if option.startswith("--") else "Unexpected positional argument"
            raise ValueError(f"{kind}: {option}.")
        if option in values:
            raise ValueError(f"Duplicate option: {option}.")
        if index + 1 >= len(args) or args[index + 1].startswith("--"):
            raise ValueError(f"Missing value for {option}.")
        values[option] = args[index + 1]
        index += 2
    missing = [option for option in required if option not in values]
    if missing:
        raise ValueError("Missing required option(s): " + ", ".join(missing) + ".")
    return values


def _revision(value: str) -> int:
    if not value.isdecimal() or value == "0" or str(int(value)) != value:
        raise ValueError("revision must be a canonical positive integer.")
    return int(value)


def _counts(manifest) -> tuple[int, int]:
    return len(manifest.students), sum(len(student.attempts) for student in manifest.students)


def _print_stored(stored, *, include_identity: bool) -> None:
    manifest = stored.manifest
    students, attempts = _counts(manifest)
    if include_identity:
        print(f"module_id: {manifest.work.module_id}")
        print(f"class_id: {manifest.work.class_id}")
        print(f"assignment_id: {manifest.work.work_id}")
        print(f"record-set ID: {manifest.record_set.record_set_id}")
        print(f"contract version: {manifest.contract_version}")
        print(
            "assignment source: "
            f"{manifest.source_snapshot.assignment.relative_path} "
            f"sha256={manifest.source_snapshot.assignment.sha256}"
        )
        print(
            "results source: "
            f"{manifest.source_snapshot.results_history.relative_path} "
            f"sha256={manifest.source_snapshot.results_history.sha256}"
        )
    print(f"revision: {stored.revision}")
    print(f"generated_at: {manifest.generated_at.isoformat()}")
    print(f"manifest path: {stored.relative_path}")
    print(f"manifest SHA-256: {stored.sha256}")
    print(f"student count: {students}")
    print(f"attempt count: {attempts}")


def run_manifest(args: Sequence[str]) -> int:
    """Dispatch ``scoreform manifest`` without traceback for expected failures."""
    if not args or args[0] in {"help", "--help", "-h"}:
        print_manifest_help()
        return 0 if args else 1
    action = args[0]
    if action not in {"list", "show", "validate", "generate"}:
        print(f"Error: Unknown manifest command: {action}.")
        print_manifest_help()
        return 1
    required: tuple[str, ...] = ("--class-id", "--assignment-id")
    if action in {"show", "validate"}:
        required += ("--revision",)
    try:
        values = _parse_options(args[1:], required)
        work = scoreform_work_ref(values["--class-id"], values["--assignment-id"])
        root = workspace.get_scoreform_workspace_root()
        if action == "list":
            history = list_academic_result_manifest_revisions(root, work)
            if not history:
                print("No academic-result manifest revisions are allocated.")
                return 0
            for index, stored in enumerate(history):
                if index:
                    print()
                _print_stored(stored, include_identity=False)
            return 0
        if action == "generate":
            result = generate_academic_result_manifest(
                root, work.class_id, work.work_id
            )
            students, attempts = _counts(result.manifest)
            print(f"disposition: {result.disposition.value}")
            print(f"reason: {result.reason.value}")
            print(f"revision: {result.revision}")
            print(f"manifest path: {result.relative_path}")
            print(f"manifest SHA-256: {result.sha256}")
            print(f"student count: {students}")
            print(f"attempt count: {attempts}")
            return 0
        revision = _revision(values["--revision"])
        if action == "show":
            stored = load_academic_result_manifest_revision(root, work, revision)
            _print_stored(stored, include_identity=True)
        else:
            stored = validate_academic_result_manifest_revision(root, work, revision)
            print(f"Valid academic-result manifest revision: {stored.revision}")
            print(f"manifest path: {stored.relative_path}")
            print(f"manifest SHA-256: {stored.sha256}")
        return 0
    except ScoreFormManifestGenerationPartialSuccessError as error:
        print(f"Error: {error}")
        print("Warning: an immutable manifest revision is durably allocated.")
        print(f"revision: {error.state.revision}")
        print(f"manifest path: {error.state.relative_path}")
        return 1
    except (ScoreFormManifestGenerationError, ValueError, TypeError) as error:
        print(f"Error: {error}")
        print()
        print(MANIFEST_USAGE)
        return 1
    except Exception as error:
        print(f"Error: Manifest operation failed: {error}")
        print()
        print(MANIFEST_USAGE)
        return 1


__all__ = ["MANIFEST_USAGE", "print_manifest_help", "run_manifest"]
