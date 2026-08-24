"""Safe assignment-context continuation for guided scan-to-results."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from pds_core.menu_navigation import NavigationChoice

from scoreform import workspace
from scoreform.assignment_context import (
    AssignmentContextRef,
    AssignmentContextResolution,
    AssignmentContextSession,
    resolve_assignment_context_ref,
)
from scoreform.guided_scan_results import GuidedScanResultTarget
from scoreform.menu_navigation import (
    parse_scoreform_navigation,
    print_invalid_navigation,
    print_scoreform_navigation_options,
)
from scoreform.workflows import (
    clear_screen,
    parse_single_selection,
    print_menu_header,
)

ClearScreen = Callable[[], None]
ResultsLauncher = Callable[..., int]


def select_guided_result_target(
    targets: tuple[GuidedScanResultTarget, ...],
    *,
    clear_screen_fn: ClearScreen | None = None,
) -> GuidedScanResultTarget | None:
    """Return one exact durable target, requiring choice only when ambiguous."""

    if not isinstance(targets, tuple) or any(
        not isinstance(target, GuidedScanResultTarget) for target in targets
    ):
        raise TypeError("targets must be an immutable guided-target tuple.")
    if not targets:
        return None
    if len(targets) == 1:
        return targets[0]

    clear = clear_screen if clear_screen_fn is None else clear_screen_fn
    while True:
        clear()
        print_menu_header("Select Scored Assignment")
        print("This scan recorded results for more than one ScoreForm assignment.")
        print("Choose the assignment whose results you want to review.")
        print()
        for index, target in enumerate(targets, start=1):
            print(
                f"{index}. {target.class_id} / {target.assignment_id} "
                f"({target.appended_attempts} new, "
                f"{target.already_present_attempts} already recorded)"
            )
        print_scoreform_navigation_options()
        print()

        selection = input("Select assignment: ").strip()
        navigation = parse_scoreform_navigation(selection)
        if navigation is NavigationChoice.BACK:
            return None
        try:
            return parse_single_selection(
                selection,
                targets,
                "scored assignment",
            )
        except ValueError as error:
            print(f"Error: {error}")
            print_invalid_navigation()
            print()


def activate_guided_result_target(
    session: AssignmentContextSession,
    target: GuidedScanResultTarget,
    *,
    workspace_root: str | Path | None = None,
) -> AssignmentContextResolution:
    """Canonically re-resolve one durable target before activating context."""

    if not isinstance(session, AssignmentContextSession):
        raise TypeError("session must be an AssignmentContextSession.")
    if not isinstance(target, GuidedScanResultTarget):
        raise TypeError("target must be a GuidedScanResultTarget.")

    root = (
        Path(workspace.get_scoreform_workspace_root()).expanduser().resolve()
        if workspace_root is None
        else Path(workspace_root).expanduser().resolve()
    )
    ref = AssignmentContextRef(
        class_id=target.class_id,
        assignment_id=target.assignment_id,
    )
    resolution = resolve_assignment_context_ref(
        session,
        ref,
        workspace_root=root,
    )
    if resolution.is_valid:
        session.activate(ref, workspace_root=root)
    return resolution


def open_guided_result_target(
    session: AssignmentContextSession,
    target: GuidedScanResultTarget,
    *,
    workspace_root: str | Path | None = None,
    launch_results_fn: ResultsLauncher | None = None,
) -> int:
    """Open canonical Review Results only after exact target re-resolution.

    A stale/invalid scan target never falls through to an unrelated assignment
    that happened to be active earlier in the interactive session.
    """

    resolution = activate_guided_result_target(
        session,
        target,
        workspace_root=workspace_root,
    )
    if (
        not resolution.is_valid
        or resolution.record is None
        or session.active != resolution.ref
    ):
        reason = (
            resolution.stale_reason
            or "The scored assignment could not be validated in the current workspace."
        )
        print(f"Could not open scored assignment results: {reason}")
        print("No different active assignment was substituted.")
        return 1

    if launch_results_fn is None:
        from scoreform.assignment_workflows import launch_view_assignment_results_menu

        launch_results_fn = launch_view_assignment_results_menu

    return launch_results_fn(context_session=session)
