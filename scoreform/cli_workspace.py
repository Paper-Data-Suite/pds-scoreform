"""Workspace command group for the ScoreForm CLI."""

from scoreform import workspace


def _format_bool(value: bool) -> str:
    return "yes" if value else "no"


def print_workspace_help():
    """Print help for the workspace command group."""
    print(
        """Usage:
  scoreform workspace show
  scoreform workspace set <path>
  scoreform workspace validate
  scoreform workspace reset

Commands:
  show       Show the resolved workspace root and configuration paths.
  set        Validate/create and save a workspace root.
  validate   Validate/create the currently resolved workspace root.
  reset      Clear the saved preference without deleting workspace files.

Setting a new workspace does not move existing ScoreForm files."""
    )


def run_workspace(args):
    """Run shared Paper Data Suite workspace commands."""
    if not args or args[0] in ("help", "--help", "-h"):
        print_workspace_help()
        return 0

    command = args[0]
    command_args = args[1:]

    try:
        if command == "show":
            if command_args:
                print("Usage: scoreform workspace show")
                return 1

            status = workspace.inspect_workspace_root()
            print("Current PDS workspace root:")
            print(status.root)
            print()
            print("Source:")
            print(status.source)
            print()
            print("Exists:")
            print(_format_bool(status.exists))
            print()
            print("Directory:")
            print(_format_bool(status.is_dir))
            print()
            print("Writable:")
            print(_format_bool(status.is_writable))
            print()
            print("Config file:")
            print(status.config_path)
            print()
            print("Default workspace root:")
            print(status.default_root)
            return 0

        if command == "set":
            if len(command_args) != 1:
                print("Usage: scoreform workspace set <path>")
                return 1

            saved_root = workspace.set_scoreform_workspace_root(command_args[0])
            print("Saved PDS workspace root:")
            print(saved_root)
            print()
            print("This does not move existing ScoreForm files.")
            return 0

        if command == "validate":
            if command_args:
                print("Usage: scoreform workspace validate")
                return 1

            validated_root = workspace.validate_scoreform_workspace_root()
            print("Workspace is valid:")
            print(validated_root)
            return 0

        if command == "reset":
            if command_args:
                print("Usage: scoreform workspace reset")
                return 1

            cleared, resolved_root = workspace.reset_scoreform_workspace_root()
            if cleared:
                print("Cleared saved PDS workspace root preference.")
            else:
                print("No saved PDS workspace root preference was set.")
            print()
            print("No workspace files were deleted.")
            print()
            print("Current resolved workspace root:")
            print(resolved_root)
            return 0
    except workspace.WorkspaceRootError as exc:
        print(f"Error: {exc}")
        return 1

    print(f"Unknown workspace command: {command}")
    print_workspace_help()
    return 1
