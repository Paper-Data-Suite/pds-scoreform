"""Teacher-facing menu for explicit Academic Result Publication management."""

from __future__ import annotations

from typing import Any

from pds_core.academic_catalog import (
    AcademicCatalogError,
    CatalogPublication,
)
from pds_core.publication_records import PublicationRecord, PublicationWithdrawal

from scoreform import workspace
from scoreform.academic_result_publication import (
    ScoreFormAcademicResultPublicationConflictError,
    ScoreFormAcademicResultPublicationError,
    ScoreFormAcademicResultPublicationIntegrityError,
    ScoreFormAcademicResultPublicationNotFoundError,
    ScoreFormAcademicResultPublicationPartialSuccessError,
    ScoreFormAcademicResultPublicationValidationError,
    ScoreFormAcademicResultPublicationWriteError,
    load_scoreform_publication,
    load_scoreform_publication_series_status,
    publish_scoreform_academic_results,
    rebuild_full_academic_catalog,
    republish_scoreform_academic_results_after_withdrawal,
    supersede_scoreform_academic_results,
    withdraw_scoreform_academic_result_publication,
)
from scoreform.menu_navigation import (
    parse_scoreform_navigation,
    print_scoreform_navigation_options,
)
from scoreform.workflows import (
    discover_class_assignments,
    discover_class_rosters,
    parse_single_selection,
    print_menu_header,
)


def _select_assignment() -> tuple[str, dict[str, Any]] | None:
    classes = discover_class_rosters()
    if not classes:
        print("No valid classes found.")
        return None
    print("Available classes:")
    for index, record in enumerate(classes, start=1):
        print(f"{index}. {record['class_id']}")
    print_scoreform_navigation_options()
    choice = input("Select class: ")
    if parse_scoreform_navigation(choice) is not None:
        return None
    class_record = parse_single_selection(choice, classes, "class")
    class_id = class_record["class_id"]
    assignments = discover_class_assignments(class_id)
    if not assignments:
        print(f"No managed ScoreForm assignments found for class '{class_id}'.")
        return None
    print("Available managed assignments:")
    for index, record in enumerate(assignments, start=1):
        print(f"{index}. {record['assignment_id']} - {record['assignment']['title']}")
    print_scoreform_navigation_options()
    choice = input("Select assignment: ")
    if parse_scoreform_navigation(choice) is not None:
        return None
    return class_id, parse_single_selection(choice, assignments, "assignment")


def _positive_revision(prompt: str) -> int:
    value = input(prompt).strip()
    if not value.isdecimal() or value == "0" or str(int(value)) != value:
        raise ValueError("revision must be a canonical positive integer.")
    return int(value)


def _publication_error_summary(
    error: ScoreFormAcademicResultPublicationError,
) -> str:
    if isinstance(error, ScoreFormAcademicResultPublicationValidationError):
        return "Publication request is invalid."
    if isinstance(error, ScoreFormAcademicResultPublicationNotFoundError):
        return "Required publication state was not found."
    if isinstance(error, ScoreFormAcademicResultPublicationConflictError):
        return "Publication operation conflicts with current canonical state."
    if isinstance(error, ScoreFormAcademicResultPublicationIntegrityError):
        return "Publication state failed integrity validation."
    if isinstance(error, ScoreFormAcademicResultPublicationWriteError):
        return "Publication operation could not be completed safely."
    return "Publication operation failed."


def _summary(
    publication: PublicationRecord,
    withdrawal: PublicationWithdrawal | None = None,
    flags: CatalogPublication | None = None,
) -> None:
    print(f"publication ID: {publication.publication_id}")
    print(f"producer revision: {publication.record_set_revision}")
    print(f"published at: {publication.published_at.isoformat()}")
    print(f"withdrawn: {'yes' if withdrawal is not None else 'no'}")
    if flags is not None:
        print(f"series head: {'yes' if flags.is_series_head else 'no'}")
        print(f"current selectable: {'yes' if flags.is_current_selectable else 'no'}")


def launch_academic_result_publications_menu() -> int:
    """Manage one selected assignment's publication series."""
    print_menu_header("Academic Result Publications")
    try:
        selected = _select_assignment()
        if selected is None:
            print("Cancelled: no publication state was changed.")
            return 0
        class_id, assignment = selected
        assignment_id = assignment["assignment_id"]
        root = workspace.get_scoreform_workspace_root()
        state = load_scoreform_publication_series_status(root, class_id, assignment_id)
        print()
        print(f"Class: {class_id}")
        print(f"Assignment: {assignment_id} - {assignment['assignment']['title']}")
        print(f"Producer head revision: {state.producer_head_revision or 'none'}")
        print(f"Publication count: {len(state.publications)}")
        print("Canonical head: " + (state.head.publication_id if state.head else "none"))
        print(f"Catalog available: {'yes' if state.catalog_available else 'no'}")
        print()
        print("1. Refresh status")
        print("2. List publications")
        print("3. Show publication")
        print("4. Publish producer head")
        print("5. Supersede exact Core head")
        print("6. Republish after head withdrawal")
        print("7. Withdraw exact publication")
        print("8. Rebuild full Core catalog")
        print("9. Return")
        action = input("Select an option: ").strip()
        if action == "1":
            print("Status refreshed.")
            return 0
        if action == "2":
            withdrawals = {item.publication_id: item for item in state.withdrawals}
            flags = {item.publication_id: item for item in state.catalog_rows}
            if not state.publications:
                print("No ScoreForm academic-result publications exist.")
            for publication in state.publications:
                _summary(
                    publication,
                    withdrawals.get(publication.publication_id),
                    flags.get(publication.publication_id),
                )
            return 0
        if action == "3":
            publication_id = input("Publication ID: ").strip()
            publication, withdrawal = load_scoreform_publication(
                root, class_id, assignment_id, publication_id
            )
            _summary(publication, withdrawal)
            return 0
        if action == "4":
            revision = _positive_revision("Producer head revision: ")
            if input("Type PUBLISH to confirm: ").strip() != "PUBLISH":
                print("Cancelled: no publication state was created.")
                return 0
            result = publish_scoreform_academic_results(
                root, class_id, assignment_id, manifest_revision=revision
            )
            print(f"Publication {result.disposition}.")
            _summary(result.publication, result.withdrawal, result.catalog.publication)
            return 0
        if action == "5":
            revision = _positive_revision("Successor producer revision: ")
            expected = input("Expected current publication ID: ").strip()
            if input("Type SUPERSEDE to confirm: ").strip() != "SUPERSEDE":
                print("Cancelled: no publication state was created.")
                return 0
            result = supersede_scoreform_academic_results(
                root,
                class_id,
                assignment_id,
                manifest_revision=revision,
                expected_current_publication_id=expected,
            )
            print(f"Supersession {result.disposition}.")
            _summary(result.publication, result.withdrawal, result.catalog.publication)
            return 0
        if action == "6":
            expected = input("Expected withdrawn head publication ID: ").strip()
            if input("Type REPUBLISH to confirm: ").strip() != "REPUBLISH":
                print("Cancelled: no manifest or publication state was created.")
                return 0
            result = republish_scoreform_academic_results_after_withdrawal(
                root,
                class_id,
                assignment_id,
                expected_withdrawn_head_publication_id=expected,
            )
            print(f"Republication {result.disposition}.")
            _summary(result.publication, result.withdrawal, result.catalog.publication)
            return 0
        if action == "7":
            publication_id = input("Publication ID: ").strip()
            reason = input("Withdrawal reason (stored by Core; not echoed): ").strip()
            if input("Type WITHDRAW to confirm: ").strip() != "WITHDRAW":
                print("Cancelled: no withdrawal state was created.")
                return 0
            withdrawal_result = withdraw_scoreform_academic_result_publication(
                root,
                class_id,
                assignment_id,
                publication_id=publication_id,
                reason=reason,
            )
            print(f"Withdrawal {withdrawal_result.disposition}.")
            _summary(
                withdrawal_result.publication,
                withdrawal_result.withdrawal,
                withdrawal_result.catalog.publication,
            )
            if withdrawal_result.manifest_verification != "verified":
                print(
                    "Warning: the publication was withdrawn, but its bound "
                    "manifest could not be verified. No producer bytes were changed."
                )
            return 0
        if action == "8":
            if input("Type REBUILD to confirm: ").strip() != "REBUILD":
                print("Cancelled: the catalog was not rebuilt.")
                return 0
            build = rebuild_full_academic_catalog(root)
            print("Full Core catalog rebuilt and verified.")
            print(f"Publication count: {build.metadata.publication_count}")
            print(f"Withdrawal count: {build.metadata.withdrawal_count}")
            return 0
        print("Cancelled: no publication state was changed.")
        return 0
    except ScoreFormAcademicResultPublicationPartialSuccessError as error:
        print(
            "Error: Publication operation left durable state but did not "
            "complete verification or reconciliation."
        )
        if error.state.canonical_state_confirmed:
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
            error.state.withdrawal_manifest_verification is not None
            and error.state.withdrawal_manifest_verification != "verified"
        ):
            print(
                "Warning: the bound manifest could not be verified. "
                "No producer bytes were changed."
            )
        print(f"Recommended next action: {error.state.recommended_next_action}")
        return 1
    except ScoreFormAcademicResultPublicationError as error:
        print(f"Error: {_publication_error_summary(error)}")
        return 1
    except AcademicCatalogError:
        print("Error: Academic catalog operation failed safely.")
        return 1
    except (ValueError, TypeError) as error:
        print(f"Error: {error}")
        return 1


__all__ = ["launch_academic_result_publications_menu"]
