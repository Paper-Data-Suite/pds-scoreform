"""Direct CLI commands for persistent ScoreForm scan filing settings."""

from scoreform.scan_filing_settings import (
    MODE_EXPLANATIONS,
    ScoreFormSettingsError,
    inspect_scan_filing_settings,
    reset_scan_filing_mode,
    set_scan_filing_mode,
)


def print_scan_filing_help():
    print("Usage:")
    print("  scoreform scan-filing show")
    print("  scoreform scan-filing set <copy|move|off>")
    print("  scoreform scan-filing reset")


def print_scan_filing_settings(settings):
    if settings.warning:
        print(f"Warning: {settings.warning}")
        if settings.configured_mode is not None:
            print(f"Configured scan filing mode: {settings.configured_mode}")
        print(f"Effective scan filing mode: {settings.effective_mode}")
    else:
        print(f"ScoreForm scan filing mode: {settings.effective_mode}")
    print(f"Settings file: {settings.path}")
    if not settings.exists:
        print("No ScoreForm settings file exists yet. Using the default mode.")
    elif settings.configured_mode is None and not settings.warning:
        print("No explicit scan filing mode is set. Using the default mode.")
    print()
    print(MODE_EXPLANATIONS[settings.effective_mode])


def run_scan_filing(args):
    if not args:
        print_scan_filing_help()
        return 1

    command = args[0]
    if command == "show" and len(args) == 1:
        print_scan_filing_settings(inspect_scan_filing_settings())
        return 0

    if command == "set":
        if len(args) != 2:
            print("Usage: scoreform scan-filing set <copy|move|off>")
            return 1
        try:
            settings = set_scan_filing_mode(args[1])
        except ScoreFormSettingsError as error:
            print(f"Error: Could not update ScoreForm settings safely: {error}")
            return 1
        print(f"ScoreForm scan filing mode set to: {settings.effective_mode}")
        print(MODE_EXPLANATIONS[settings.effective_mode])
        return 0

    if command == "reset" and len(args) == 1:
        try:
            settings = reset_scan_filing_mode()
        except ScoreFormSettingsError as error:
            print(f"Error: Could not update ScoreForm settings safely: {error}")
            return 1
        print("ScoreForm scan filing mode reset to default.")
        print(f"Effective scan filing mode: {settings.effective_mode}")
        return 0

    print(f"Unknown or invalid scan-filing command: {' '.join(args)}")
    print_scan_filing_help()
    return 1
