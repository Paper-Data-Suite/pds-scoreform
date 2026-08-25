"""Teacher-facing continuous publication workflow for ScoreForm issue #191."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from pds_core.academic_work_registrations import (
    AcademicWorkIntent,
    AcademicWorkRegistrationLifecycle,
)

from scoreform import workflows, workspace
from scoreform.academic_work_registration import (
    SUPPORTED_ACADEMIC_INTENTS,
    SUPPORTED_ACADEMIC_WORK_LIFECYCLES,
)
from scoreform.assignment_context import AssignmentContextSession
from scoreform.guided_share_results import (
    ScoreFormShareResultsManifestError,
    ScoreFormShareResultsManifestPartialSuccessError,
    ScoreFormShareResultsPlanningError,
    ScoreFormShareResultsPublicationError,
    ScoreFormShareResultsPublicationPartialSuccessError,
    ScoreFormShareResultsPublicationPostCommitStateError,
    ScoreFormShareResultsRegistrationError,
    ScoreFormShareResultsRegistrationPartialSuccessError,
    ShareResultsNextStep,
    ShareResultsPublicationOutcome,
    ShareResultsReadiness,
    commit_share_results_manifest,
    commit_share_results_publication,
    commit_share_results_registration,
    commit_share_results_supersession,
    plan_share_results_readiness,
    prepare_share_results_manifest,
    prepare_share_results_publication,
    prepare_share_results_registration,
    prepare_share_results_supersession,
)
from scoreform.menu_assignment_context import select_assignment_for_workflow
from scoreform.menu_navigation import (
    parse_scoreform_navigation,
    print_scoreform_navigation_options,
)
from scoreform.workflows import print_menu_header

UiCallback = Callable[[], None]


@dataclass(slots=True)
class _GuidedShareProgress:
    registration_revision_written: int | None = None
    manifest_revision: int | None = None
    manifest_created: bool = False


def _title_for_record(record: dict[str, object]) -> str:
    assignment = record.get("assignment")
    if isinstance(assignment, dict):
        title = assignment.get("title")
        if isinstance(title, str) and title.strip():
            return title
    return ""


def _header(clear_screen_fn: UiCallback, title: str) -> None:
    clear_screen_fn()
    print_menu_header(title)


def _choose_value(label: str, values: Sequence[str]) -> str | None:
    while True:
        print(f"Select {label.replace('_', ' ')}:")
        for index, value in enumerate(values, start=1):
            print(f"{index}. {value}")
        print_scoreform_navigation_options()
        print()
        choice = input(f"{label.replace('_', ' ').title()}: ").strip()
        navigation = parse_scoreform_navigation(choice)
        if navigation is not None:
            return None
        if choice.isdecimal() and 1 <= int(choice) <= len(values):
            return values[int(choice) - 1]
        print(f"Error: Select a listed {label}.")
        print()


def _confirm(token: str) -> bool:
    print_scoreform_navigation_options()
    print()
    choice = input(f"Type {token} to confirm: ").strip()
    navigation = parse_scoreform_navigation(choice)
    if navigation is not None:
        return False
    return choice == token


def _print_pause(
    readiness: ShareResultsReadiness,
    progress: _GuidedShareProgress,
) -> None:
    print_menu_header("Share Results Paused")
    if readiness.registration_revision is not None:
        print(
            "Academic Work Registration is ready "
            f"(revision {readiness.registration_revision})."
        )

    if progress.registration_revision_written is not None:
        print(
            "Registration revision "
            f"{progress.registration_revision_written} was saved in this guided run."
        )

    if progress.manifest_revision is not None:
        if progress.manifest_created:
            print(f"Manifest revision {progress.manifest_revision} is already stored.")
        else:
            print(
                f"Manifest revision {progress.manifest_revision} was reused as "
                "exact immutable evidence."
            )

    if (
        progress.registration_revision_written is None
        and progress.manifest_revision is None
    ):
        print(
            "No new registration, manifest, or publication state was written "
            "in this guided run."
        )

    if readiness.next_step is ShareResultsNextStep.SUPERSEDE:
        assert readiness.core_head_revision is not None
        print(
            f"Core publication revision {readiness.core_head_revision} remains current."
        )
        print("No supersession was written.")
    elif readiness.core_head_revision is None:
        print("No Core publication was written.")
    else:
        print("No Core publication change was written.")


def _print_registration_partial(
    error: ScoreFormShareResultsRegistrationPartialSuccessError,
) -> None:
    recovery = error.recovery
    print_menu_header("Share Results Stopped")
    print("Academic Work Registration may already be durable.")
    if recovery.durable_registration_revision is not None:
        print(f"Known registration revision: {recovery.durable_registration_revision}")
    if recovery.current_selected is True:
        print("Core reports that revision as the current selection.")
    elif recovery.current_selected is False:
        print("Core does not confirm that revision as the current selection.")
    else:
        print("Current-selection state is uncertain.")
    print(recovery.guidance)
    print("No later guided stage was attempted.")


def _print_manifest_partial(
    error: ScoreFormShareResultsManifestPartialSuccessError,
) -> None:
    recovery = error.recovery
    print_menu_header("Share Results Stopped")
    print(f"Manifest revision {recovery.revision} may already be durable.")
    print(
        "Durable file reported: "
        f"{'yes' if recovery.durable_file_exists else 'uncertain'}"
    )
    if recovery.lock_cleanup_issue:
        print("A manifest-generation lock cleanup issue was also reported.")
    print(recovery.guidance)
    print("No publication step was attempted after this condition.")


def _print_publication_partial(
    error: ScoreFormShareResultsPublicationPartialSuccessError,
) -> None:
    recovery = error.recovery
    print_menu_header("Share Results Stopped")
    print("Core publication state may already be durable.")
    print(f"Canonical state: {recovery.canonical_state}")
    if recovery.manifest_revision is not None:
        print(f"Manifest revision: {recovery.manifest_revision}")
    print(recovery.guidance)
    print("Do not retry the publication operation automatically.")


def _print_safe_stop(error: Exception, *, area: str) -> None:
    print_menu_header("Share Results Stopped")
    print(f"{area}: {error}")
    print("No later guided stage was attempted.")
    print(
        "Use the exact Academic Work Registration, Academic Result Manifests, "
        "or Academic Result Publications workflow for detailed recovery."
    )


def _print_final(
    *,
    class_id: str,
    assignment_id: str,
    title: str,
    outcome: ShareResultsPublicationOutcome,
) -> None:
    print_menu_header("Share Results with Meridian")
    print("Status")
    print("Results are published through Core and available for Meridian to consume.")
    print()
    print("Assignment")
    suffix = f" — {title}" if title else ""
    print(f"{class_id} / {assignment_id}{suffix}")
    print()
    print("Academic Work")
    print("Registered")
    print()
    print("Producer evidence")
    print(f"Manifest revision {outcome.manifest_revision}")
    print()
    print("Publication")
    if outcome.disposition == "already_current":
        print("The current Core publication already represents this producer evidence.")
    else:
        print("Current Core publication updated successfully.")
    if outcome.previous_publication_id is not None:
        print("The previous publication remains in immutable history.")


def _registration_stage(
    workspace_root: str | Path,
    class_id: str,
    assignment_id: str,
    *,
    clear_screen_fn: UiCallback,
    progress: _GuidedShareProgress,
) -> bool:
    _header(clear_screen_fn, "Share Results with Meridian — Registration")
    print("Academic Work Registration is required before results can be published.")
    print("Choose the academic meaning explicitly; ScoreForm will not assume defaults.")
    print()

    intent_raw = _choose_value("academic_intent", SUPPORTED_ACADEMIC_INTENTS)
    if intent_raw is None:
        return False
    lifecycle_raw = _choose_value(
        "lifecycle",
        SUPPORTED_ACADEMIC_WORK_LIFECYCLES,
    )
    if lifecycle_raw is None:
        return False

    preview = prepare_share_results_registration(
        workspace_root,
        class_id,
        assignment_id,
        academic_intent=cast(AcademicWorkIntent, intent_raw),
        lifecycle=cast(AcademicWorkRegistrationLifecycle, lifecycle_raw),
    )
    print()
    print("Academic Work Registration")
    print(f"Assignment: {preview.work.class_id} / {preview.work.work_id}")
    print(f"Title: {preview.title}")
    print(f"Academic intent: {preview.academic_intent}")
    print(f"Lifecycle: {preview.lifecycle}")
    print()
    if not _confirm("REGISTER"):
        return False

    result = commit_share_results_registration(workspace_root, preview)
    if result.disposition == "created":
        progress.registration_revision_written = (
            result.registration.registration_revision
        )
    print(
        "Academic Work Registration ready at revision "
        f"{result.registration.registration_revision}."
    )
    print()
    return True


def _manifest_stage(
    workspace_root: str | Path,
    class_id: str,
    assignment_id: str,
    *,
    clear_screen_fn: UiCallback,
    progress: _GuidedShareProgress,
) -> bool:
    preview = prepare_share_results_manifest(
        workspace_root,
        class_id,
        assignment_id,
    )
    _header(clear_screen_fn, "Share Results with Meridian — Producer Evidence")
    print(
        "ScoreForm will snapshot the current validated assignment and results "
        "into immutable producer evidence."
    )
    if preview.producer_head_revision_before is not None:
        print(
            "Existing producer manifest head: revision "
            f"{preview.producer_head_revision_before}"
        )
    print("The exact generator will choose whether to replay or create a revision.")
    print()
    if not _confirm("GENERATE"):
        return False

    result = commit_share_results_manifest(workspace_root, preview)
    progress.manifest_revision = result.revision
    progress.manifest_created = result.created_new_revision
    if result.created_new_revision:
        print(f"Manifest revision {result.revision} stored.")
    else:
        print(f"Manifest revision {result.revision} reused exactly.")
    print()
    return True


def _publish_first_stage(
    workspace_root: str | Path,
    class_id: str,
    assignment_id: str,
    *,
    clear_screen_fn: UiCallback,
) -> ShareResultsPublicationOutcome | None:
    preview = prepare_share_results_publication(
        workspace_root,
        class_id,
        assignment_id,
    )
    _header(clear_screen_fn, "Share Results with Meridian — First Publication")
    print(f"Producer manifest revision: {preview.manifest_revision}")
    print("No Core publication currently exists for this assignment.")
    print("This will create the first exact Core publication.")
    print()
    if not _confirm("PUBLISH"):
        return None
    return commit_share_results_publication(workspace_root, preview)


def _already_current_stage(
    workspace_root: str | Path,
    class_id: str,
    assignment_id: str,
) -> ShareResultsPublicationOutcome:
    preview = prepare_share_results_publication(
        workspace_root,
        class_id,
        assignment_id,
    )
    return commit_share_results_publication(workspace_root, preview)


def _supersession_stage(
    workspace_root: str | Path,
    class_id: str,
    assignment_id: str,
    *,
    clear_screen_fn: UiCallback,
) -> ShareResultsPublicationOutcome | None:
    preview = prepare_share_results_supersession(
        workspace_root,
        class_id,
        assignment_id,
    )
    _header(clear_screen_fn, "Share Results with Meridian — Supersession")
    print(f"Currently published revision: {preview.predecessor_manifest_revision}")
    print(f"New producer revision: {preview.successor_manifest_revision}")
    print()
    print(
        "This will supersede the current Core head. The previous publication "
        "will remain immutable history."
    )
    print()
    if not _confirm("SUPERSEDE"):
        return None
    return commit_share_results_supersession(workspace_root, preview)


def launch_share_results_with_meridian(
    *,
    clear_screen_fn: UiCallback | None = None,
    context_session: AssignmentContextSession | None = None,
) -> int:
    """Run one continuous exact publication journey for one assignment."""

    clear = workflows.clear_screen if clear_screen_fn is None else clear_screen_fn
    session = (
        AssignmentContextSession() if context_session is None else context_session
    )
    progress = _GuidedShareProgress()

    _header(clear, "Share Results with Meridian")
    print(
        "Publish ScoreForm evidence through Core so Meridian can consume it. "
        "ScoreForm does not invoke Meridian directly."
    )
    print()

    assignment_record = select_assignment_for_workflow(
        session,
        clear_screen_fn=clear,
        offer_switch=False,
        workflow_title="Share Results with Meridian",
    )
    if assignment_record is None:
        print_menu_header("Share Results Cancelled")
        print("No registration, manifest, or publication state was written.")
        return 0

    class_id = str(assignment_record["class_id"])
    assignment_id = str(assignment_record["assignment_id"])
    title = _title_for_record(cast(dict[str, object], assignment_record))
    workspace_root = workspace.get_scoreform_workspace_root()

    while True:
        try:
            readiness = plan_share_results_readiness(
                workspace_root,
                class_id,
                assignment_id,
            )
        except ScoreFormShareResultsPlanningError as error:
            _print_safe_stop(error, area="Readiness")
            return 1

        try:
            if readiness.next_step is ShareResultsNextStep.NOT_READY:
                _header(clear, "Share Results with Meridian")
                print(
                    readiness.blocking_reason
                    or "No publishable ScoreForm results are available."
                )
                print(
                    "No registration, manifest, or publication write was attempted."
                )
                return 0

            if readiness.next_step is ShareResultsNextStep.REPAIR_REQUIRED:
                _header(clear, "Share Results Needs Exact Recovery")
                print(
                    readiness.blocking_reason
                    or "Canonical publication state requires exact inspection."
                )
                print()
                print(
                    "Use the advanced Academic Work Registration, Academic Result "
                    "Manifests, or Academic Result Publications workflow."
                )
                return 1

            if (
                readiness.next_step
                is ShareResultsNextStep.WITHDRAWN_HEAD_REQUIRES_EXACT_RECOVERY
            ):
                _header(clear, "Share Results Needs Exact Recovery")
                print(
                    readiness.blocking_reason
                    or "The current Core publication is withdrawn."
                )
                print()
                print(
                    "Return to Share Results and choose "
                    "'4. Academic Result Publications' to review the exact "
                    "republish-after-withdrawal operation."
                )
                print(
                    "No publication write was attempted by the guided workflow."
                )
                return 0

            if readiness.next_step is ShareResultsNextStep.REGISTER:
                if not _registration_stage(
                    workspace_root,
                    class_id,
                    assignment_id,
                    clear_screen_fn=clear,
                    progress=progress,
                ):
                    _print_pause(readiness, progress)
                    return 0
                continue

            if readiness.next_step is ShareResultsNextStep.GENERATE_MANIFEST:
                if not _manifest_stage(
                    workspace_root,
                    class_id,
                    assignment_id,
                    clear_screen_fn=clear,
                    progress=progress,
                ):
                    _print_pause(readiness, progress)
                    return 0
                continue

            if readiness.next_step is ShareResultsNextStep.PUBLISH_FIRST:
                outcome = _publish_first_stage(
                    workspace_root,
                    class_id,
                    assignment_id,
                    clear_screen_fn=clear,
                )
                if outcome is None:
                    _print_pause(readiness, progress)
                    return 0
                _print_final(
                    class_id=class_id,
                    assignment_id=assignment_id,
                    title=title,
                    outcome=outcome,
                )
                return 0

            if readiness.next_step is ShareResultsNextStep.ALREADY_CURRENT:
                outcome = _already_current_stage(
                    workspace_root,
                    class_id,
                    assignment_id,
                )
                _print_final(
                    class_id=class_id,
                    assignment_id=assignment_id,
                    title=title,
                    outcome=outcome,
                )
                return 0

            if readiness.next_step is ShareResultsNextStep.SUPERSEDE:
                outcome = _supersession_stage(
                    workspace_root,
                    class_id,
                    assignment_id,
                    clear_screen_fn=clear,
                )
                if outcome is None:
                    _print_pause(readiness, progress)
                    return 0
                _print_final(
                    class_id=class_id,
                    assignment_id=assignment_id,
                    title=title,
                    outcome=outcome,
                )
                return 0

            _header(clear, "Share Results Stopped")
            print("Guided publication planning returned an unsupported state.")
            return 1

        except ScoreFormShareResultsRegistrationPartialSuccessError as error:
            _print_registration_partial(error)
            return 1
        except ScoreFormShareResultsManifestPartialSuccessError as error:
            _print_manifest_partial(error)
            return 1
        except ScoreFormShareResultsPublicationPartialSuccessError as error:
            _print_publication_partial(error)
            return 1
        except ScoreFormShareResultsPublicationPostCommitStateError as error:
            _print_safe_stop(error, area="Post-commit verification")
            return 1
        except ScoreFormShareResultsRegistrationError as error:
            _print_safe_stop(error, area="Academic Work Registration")
            return 1
        except ScoreFormShareResultsManifestError as error:
            _print_safe_stop(error, area="Producer evidence")
            return 1
        except ScoreFormShareResultsPublicationError as error:
            _print_safe_stop(error, area="Core publication")
            return 1
