"""Privacy-minimized direct CLI for ScoreForm publication management."""

from __future__ import annotations

from collections.abc import Sequence

from pds_core.academic_catalog import AcademicCatalogError, CatalogPublication
from pds_core.publication_records import PublicationRecord, PublicationWithdrawal

from scoreform import workspace
from scoreform.academic_result_publication import (
    AcademicResultPublicationResult,
    AcademicResultWithdrawalResult,
    ScoreFormAcademicResultPublicationError,
    ScoreFormAcademicResultPublicationPartialSuccessError,
    load_scoreform_publication,
    load_scoreform_publication_series_status,
    publish_scoreform_academic_results,
    rebuild_full_academic_catalog,
    republish_scoreform_academic_results_after_withdrawal,
    supersede_scoreform_academic_results,
    withdraw_scoreform_academic_result_publication,
)

PUBLICATION_USAGE = """Usage:
  scoreform publication status --class-id <class_id> --assignment-id <assignment_id>
  scoreform publication list --class-id <class_id> --assignment-id <assignment_id>
  scoreform publication show --class-id <class_id> --assignment-id <assignment_id> --publication-id <publication_id>
  scoreform publication publish --class-id <class_id> --assignment-id <assignment_id> --revision <revision>
  scoreform publication supersede --class-id <class_id> --assignment-id <assignment_id> --revision <revision> --expected-current-publication-id <publication_id>
  scoreform publication republish-after-withdrawal --class-id <class_id> --assignment-id <assignment_id> --expected-current-publication-id <publication_id>
  scoreform publication withdraw --class-id <class_id> --assignment-id <assignment_id> --publication-id <publication_id> --reason <reason>
  scoreform publication rebuild-catalog"""


def print_publication_help() -> None:
    print(PUBLICATION_USAGE)
    print()
    print("Writes are explicit. Core owns publication IDs and canonical records.")
    print("Output never displays students, manifest content, or withdrawal reasons.")


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
    missing = tuple(option for option in required if option not in values)
    if missing:
        raise ValueError("Missing required option(s): " + ", ".join(missing) + ".")
    return values


def _revision(value: str) -> int:
    if not value.isdecimal() or value == "0" or str(int(value)) != value:
        raise ValueError("revision must be a canonical positive integer.")
    return int(value)


def _print_record(
    publication: PublicationRecord,
    withdrawal: PublicationWithdrawal | None,
    *,
    flags: CatalogPublication | None = None,
) -> None:
    print(f"publication ID: {publication.publication_id}")
    print(f"record-set revision: {publication.record_set_revision}")
    print(f"published at: {publication.published_at.isoformat()}")
    print(f"manifest path: {publication.manifest_path}")
    print(f"manifest SHA-256: {publication.manifest_digest}")
    print(
        "supersedes: "
        + (publication.supersedes_publication_id or "none")
    )
    print(f"withdrawn: {'yes' if withdrawal is not None else 'no'}")
    if withdrawal is not None:
        print(f"withdrawn at: {withdrawal.withdrawn_at.isoformat()}")
    if flags is not None:
        print(f"series head: {'yes' if flags.is_series_head else 'no'}")
        print(f"current selectable: {'yes' if flags.is_current_selectable else 'no'}")


def _print_publication_result(result: AcademicResultPublicationResult) -> None:
    print(f"operation: {result.operation}")
    print(f"disposition: {result.disposition}")
    _print_record(
        result.publication,
        result.withdrawal,
        flags=result.catalog.publication,
    )
    print(f"registration revision: {result.registration.registration_revision}")
    print("producer compatibility: compatible")
    print("catalog reconciliation: verified")


def _print_withdrawal_result(result: AcademicResultWithdrawalResult) -> None:
    print("operation: withdraw")
    print(f"disposition: {result.disposition}")
    _print_record(
        result.publication,
        result.withdrawal,
        flags=result.catalog.publication,
    )
    if result.manifest_verification != "verified":
        print(
            "Warning: the publication was withdrawn, but its bound manifest "
            "could not be verified. No producer bytes were changed."
        )
    print("catalog reconciliation: verified")


def run_publication(args: Sequence[str]) -> int:
    """Dispatch ``scoreform publication`` without expected-failure tracebacks."""
    if not args or args[0] in {"help", "--help", "-h"}:
        print_publication_help()
        return 0 if args else 1
    action = args[0]
    actions = {
        "status",
        "list",
        "show",
        "publish",
        "supersede",
        "republish-after-withdrawal",
        "withdraw",
        "rebuild-catalog",
    }
    if action not in actions:
        print(f"Error: Unknown publication command: {action}.")
        print_publication_help()
        return 1
    if len(args) == 2 and args[1] in {"help", "--help", "-h"}:
        print_publication_help()
        return 0
    try:
        root = workspace.get_scoreform_workspace_root()
        if action == "rebuild-catalog":
            if len(args) != 1:
                raise ValueError("rebuild-catalog accepts no options.")
            build = rebuild_full_academic_catalog(root)
            print("Academic catalog rebuilt and verified.")
            print(f"source snapshot SHA-256: {build.metadata.source_snapshot_sha256}")
            print(f"source file count: {build.metadata.source_file_count}")
            print(f"publication count: {build.metadata.publication_count}")
            print(f"withdrawal count: {build.metadata.withdrawal_count}")
            print(f"replaced existing catalog: {'yes' if build.replaced_existing_catalog else 'no'}")
            return 0
        required: tuple[str, ...] = ("--class-id", "--assignment-id")
        if action in {"show", "withdraw"}:
            required += ("--publication-id",)
        if action in {"publish", "supersede"}:
            required += ("--revision",)
        if action in {"supersede", "republish-after-withdrawal"}:
            required += ("--expected-current-publication-id",)
        if action == "withdraw":
            required += ("--reason",)
        values = _parse_options(args[1:], required)
        class_id = values["--class-id"]
        assignment_id = values["--assignment-id"]
        if action == "withdraw" and not values["--reason"].strip():
            raise ValueError("withdrawal reason must be nonempty.")
        if action in {"status", "list"}:
            state = load_scoreform_publication_series_status(
                root, class_id, assignment_id
            )
            if action == "status":
                print(f"class ID: {class_id}")
                print(f"assignment ID: {assignment_id}")
                print(f"producer head revision: {state.producer_head_revision or 'none'}")
                print(f"publication count: {len(state.publications)}")
                print(f"withdrawal count: {len(state.withdrawals)}")
                print(
                    "canonical series head: "
                    + (state.head.publication_id if state.head else "none")
                )
                print(f"catalog available: {'yes' if state.catalog_available else 'no'}")
                return 0
            if not state.publications:
                print("No ScoreForm academic-result publications exist.")
                return 0
            withdrawals = {item.publication_id: item for item in state.withdrawals}
            flags = {item.publication_id: item for item in state.catalog_rows}
            for index, publication in enumerate(state.publications):
                if index:
                    print()
                _print_record(
                    publication,
                    withdrawals.get(publication.publication_id),
                    flags=flags.get(publication.publication_id),
                )
            return 0
        if action == "show":
            publication, withdrawal = load_scoreform_publication(
                root,
                class_id,
                assignment_id,
                values["--publication-id"],
            )
            _print_record(publication, withdrawal)
            return 0
        if action == "publish":
            result = publish_scoreform_academic_results(
                root,
                class_id,
                assignment_id,
                manifest_revision=_revision(values["--revision"]),
            )
            _print_publication_result(result)
            return 0
        if action == "supersede":
            result = supersede_scoreform_academic_results(
                root,
                class_id,
                assignment_id,
                manifest_revision=_revision(values["--revision"]),
                expected_current_publication_id=values[
                    "--expected-current-publication-id"
                ],
            )
            _print_publication_result(result)
            return 0
        if action == "republish-after-withdrawal":
            result = republish_scoreform_academic_results_after_withdrawal(
                root,
                class_id,
                assignment_id,
                expected_withdrawn_head_publication_id=values[
                    "--expected-current-publication-id"
                ],
            )
            _print_publication_result(result)
            return 0
        withdrawal_result = withdraw_scoreform_academic_result_publication(
            root,
            class_id,
            assignment_id,
            publication_id=values["--publication-id"],
            reason=values["--reason"],
        )
        _print_withdrawal_result(withdrawal_result)
        return 0
    except ScoreFormAcademicResultPublicationPartialSuccessError as error:
        print(f"Error: {error}")
        partial = error.state
        if partial.canonical_state_confirmed:
            print(
                "Warning: canonical Core state is confirmed, but later "
                "verification or catalog reconciliation failed."
            )
        else:
            print(
                "Warning: canonical Core state may already be durable; "
                "reload exact state before retrying."
            )
        if (
            partial.withdrawal_manifest_verification is not None
            and partial.withdrawal_manifest_verification != "verified"
        ):
            print(
                "Warning: the bound manifest could not be verified. "
                "No producer bytes were changed."
            )
        if partial.publication is not None:
            print(f"publication ID: {partial.publication.publication_id}")
        print(f"recommended next action: {partial.recommended_next_action}")
        return 1
    except (ScoreFormAcademicResultPublicationError, AcademicCatalogError, ValueError, TypeError) as error:
        print(f"Error: {error}")
        print()
        print(PUBLICATION_USAGE)
        return 1
    except Exception as error:
        print(f"Error: Publication operation failed: {error}")
        print()
        print(PUBLICATION_USAGE)
        return 1


__all__ = ["PUBLICATION_USAGE", "print_publication_help", "run_publication"]
