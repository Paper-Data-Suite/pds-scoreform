"""School-year command group for the ScoreForm CLI."""

from datetime import datetime

from pds_core.school_years import (
    SchoolYearStateError,
    close_school_year,
    load_school_year_state,
    open_school_year,
    school_year_state_path,
)

from scoreform import workspace


def print_school_year_help():
    """Print help for the school-year command group."""
    print(
        """Usage:
  scoreform school-year show
  scoreform school-year open <school_year> [--overwrite]
  scoreform school-year close

Commands:
  show       Show active school-year state for the current PDS workspace.
  open       Open a school year for the current PDS workspace.
  close      Close the active school year for the current PDS workspace.

Opening or closing a school year does not delete, archive, summarize, or move data."""
    )


def current_local_time():
    """Return a timezone-aware local timestamp."""
    return datetime.now().astimezone()


def _format_school_year_timestamp(value):
    return value.isoformat()


def format_school_year_state(workspace_root):
    """Return teacher-readable school-year state for a workspace."""
    state_path = school_year_state_path(workspace_root)
    state = load_school_year_state(workspace_root)

    if state is None:
        return "\n".join([
            "No school year has been opened for this workspace.",
            f"State file: {state_path}",
        ])

    if state.closed_at is None:
        return "\n".join([
            f"Active school year: {state.active_school_year}",
            f"Opened at: {_format_school_year_timestamp(state.opened_at)}",
            f"State file: {state_path}",
        ])

    return "\n".join([
        "No active school year is open.",
        f"Last school year: {state.active_school_year}",
        f"Opened at: {_format_school_year_timestamp(state.opened_at)}",
        f"Closed at: {_format_school_year_timestamp(state.closed_at)}",
        f"State file: {state_path}",
    ])


def _print_school_year_open_success(
    workspace_root,
    school_year,
    existing_state,
    opened_state,
    overwrite,
):
    state_path = school_year_state_path(workspace_root)
    if (
        existing_state is not None
        and existing_state.closed_at is None
        and existing_state.active_school_year == opened_state.active_school_year
        and existing_state.opened_at == opened_state.opened_at
        and not overwrite
    ):
        print(f"School year is already open: {opened_state.active_school_year}")
        return

    if (
        overwrite
        and existing_state is not None
        and existing_state.closed_at is None
        and existing_state.active_school_year != school_year
    ):
        print(f"Replaced active school year with: {opened_state.active_school_year}")
    else:
        print(f"Opened school year: {opened_state.active_school_year}")
    print(f"Workspace: {workspace_root}")
    print(f"State file: {state_path}")


def run_school_year(args):
    """Run shared active school-year workspace commands."""
    if not args or args[0] in ("help", "--help", "-h"):
        print_school_year_help()
        return 0

    command = args[0]
    command_args = args[1:]

    try:
        if command == "show":
            if command_args:
                print("Usage: scoreform school-year show")
                return 1

            workspace_root = workspace.get_scoreform_workspace_root()
            print(format_school_year_state(workspace_root))
            return 0

        if command == "open":
            overwrite = False
            positional_args = []
            for argument in command_args:
                if argument == "--overwrite":
                    if overwrite:
                        print("Usage: scoreform school-year open <school_year> [--overwrite]")
                        return 1
                    overwrite = True
                elif argument.startswith("-"):
                    print(f"Unknown option: {argument}")
                    print("Usage: scoreform school-year open <school_year> [--overwrite]")
                    return 1
                else:
                    positional_args.append(argument)

            if len(positional_args) != 1:
                print("Usage: scoreform school-year open <school_year> [--overwrite]")
                return 1

            workspace_root = workspace.get_scoreform_workspace_root()
            existing_state = load_school_year_state(workspace_root)
            opened_state = open_school_year(
                workspace_root,
                positional_args[0],
                opened_at=current_local_time(),
                overwrite=overwrite,
            )
            _print_school_year_open_success(
                workspace_root,
                positional_args[0],
                existing_state,
                opened_state,
                overwrite,
            )
            return 0

        if command == "close":
            if command_args:
                print("Usage: scoreform school-year close")
                return 1

            workspace_root = workspace.get_scoreform_workspace_root()
            closed_state = close_school_year(
                workspace_root,
                closed_at=current_local_time(),
            )
            print(f"Closed school year: {closed_state.active_school_year}")
            print(f"Closed at: {_format_school_year_timestamp(closed_state.closed_at)}")
            print(f"State file: {school_year_state_path(workspace_root)}")
            return 0
    except (SchoolYearStateError, workspace.WorkspaceRootError) as exc:
        print(f"Error: {exc}")
        return 1

    print(f"Unknown school-year command: {command}")
    print_school_year_help()
    return 1
