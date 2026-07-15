"""Help and version presentation for the ScoreForm CLI."""

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from scoreform.workflows import print_menu_header


def get_version():
    """Return the local source version, with installed package metadata fallback."""
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    try:
        in_project_section = False
        for line in pyproject_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped == "[project]":
                in_project_section = True
                continue
            if in_project_section and stripped.startswith("["):
                break
            if in_project_section and stripped.startswith("version"):
                key, separator, value = stripped.partition("=")
                value = value.strip()
                if key.strip() == "version" and separator and len(value) >= 2:
                    if value[0] == value[-1] and value[0] in ("'", '"'):
                        return value[1:-1]
    except OSError:
        pass

    try:
        return version("scoreform")
    except PackageNotFoundError:
        return "unknown"


def print_version():
    print(f"ScoreForm {get_version()}")


def print_help():
    print(
        """ScoreForm
A local-first classroom OMR tool for generating printable answer sheets and scoring scanned responses.

Usage:
  scoreform
  scoreform menu
  scoreform generate
  scoreform generate <assignment.json> --rosters <roster.csv> [more rosters...]
  scoreform regenerate-sheets --class-id <class_id> --assignment-id <assignment_id>
  scoreform regenerate-sheets --class-id <class_id> --all-assignments
  scoreform score <scan.pdf>
  scoreform score <scan.pdf> <output.csv>
  scoreform score <scan.pdf> <answer_key.json>
  scoreform score <scan.pdf> <output.csv> <answer_key.json>
  scoreform list-scan-review [--include-resolved] [--limit <n>]
  scoreform resolve-scan-review <failure_id> --action <action>
  scoreform decode-qr <file.pdf-or-image>
  scoreform validate-assignment <assignment.json>
  scoreform validate-roster <roster.csv>
  scoreform setup-assignment <assignment.json> <roster.csv>
  scoreform workspace show
  scoreform workspace set <path>
  scoreform workspace validate
  scoreform workspace reset
  scoreform school-year show
  scoreform school-year open <school_year> [--overwrite]
  scoreform school-year close
  scoreform scan-filing show
  scoreform scan-filing set <copy|move|off>
  scoreform scan-filing reset
  scoreform help
  scoreform --help
  scoreform version
  scoreform --version

Commands:
  menu                  Launch the terminal menu.
  generate              Generate a generic template or assignment-based answer sheets.
  regenerate-sheets     Regenerate managed answer sheets from the current roster.
  score                 Score scanned responses.
  list-scan-review      List unresolved and deferred ScoreForm scan review items.
  resolve-scan-review   Resolve or defer one ScoreForm scan review item.
  decode-qr             Decode QR metadata from a PDF or image.
  validate-assignment   Validate an assignment JSON file.
  validate-roster       Validate a roster CSV file.
  setup-assignment      Create class and assignment folders.
  workspace             View or configure the shared PDS workspace root.
  school-year           View, open, or close the active PDS school year.
  scan-filing           View or configure ScoreForm scored-copy filing.
  help                  Show this help text.
  version               Show the installed ScoreForm version.

Core 0.5/PDS2 migration notice:
  Personalized/class-packet generation and sheet regeneration remain gated on
  route registration and PDS2 rendering (#141). QR decoding/routed scoring
  and scan-review mutation remain gated on their later PDS2 work. Managed
  assignment setup, discovery, creation, editing, plain-paper result entry, and
  result viewing use module-qualified ScoreForm work storage and are available.

Scoring modes:
  scoreform score scanned_file.pdf
      QR-aware scoring. Uses QR metadata to locate the assignment and routes results to
      classes/<class_id>/modules/scoreform/work/<assignment_id>/results.csv.

  scoreform score scanned_file.pdf output.csv
      QR-aware scoring with an explicit output CSV instead of routed results.

  QR-aware full and partial success exit 0; zero success and export failure exit 1.
  The saved QR batch summary is the source of truth for completeness.
  Automatic scan filing occurs only for full-success, single-target routed batches.
  Partial, failed, multi-target, explicit-output, and manual batches are not filed.
  The persistent mode is copy (default), move, or off. Move removes an original
  only when it is a direct child of the active workspace scans_inbox.

  scoreform score scanned_file.pdf answer_key.json
      Legacy/manual scoring with an explicit answer key and default local results path.

  scoreform score scanned_file.pdf output.csv answer_key.json
      Legacy/manual scoring with an explicit answer key and explicit output CSV.

  Manual/legacy multi-page or failed batches report processed, scored, and
  failed/skipped page counts. Partial exports warn; zero-success batches fail.

Examples:
  scoreform
  scoreform generate examples\\sample_assignment.json --rosters examples\\sample_roster_english9_p2.csv
  scoreform score scans_inbox\\class_packet.pdf
  scoreform decode-qr classes\\english9_p2\\modules\\scoreform\\work\\rj_act1_quiz\\templates\\class_packet.pdf
  scoreform validate-assignment examples\\sample_assignment.json
  scoreform validate-roster examples\\sample_roster_english9_p2.csv
  scoreform workspace show
  scoreform workspace set "C:\\Users\\teacher\\Paper Data Suite"
  scoreform workspace validate
  scoreform workspace reset
  scoreform school-year show
  scoreform school-year open 2026-2027
  scoreform school-year close
  scoreform scan-filing show
  scoreform scan-filing set move

Notes:
  Running scoreform with no arguments launches the terminal menu.
  python main.py remains supported for backward compatibility."""
    )


def print_menu_help():
    print_menu_header("Help")
    print("ScoreForm generates printable answer sheets and scores scanned responses.")
    print("Menus clear between workflow steps and retain only the context needed")
    print("for the teacher's current action; warnings and results remain readable.")
    print()
    print("Typical workflow:")
    print("  1. Create or validate a roster CSV.")
    print("  2. Create or validate an assignment JSON file.")
    print("     Question-level standards use enumerated PDS Core standards profiles.")
    print("  3. Generate answer sheets.")
    print("  4. Scan completed sheets.")
    print("  5. Score scanned responses.")
    print("  6. Inspect routed results.")
    print()
    print("QR-aware routed scoring writes to:")
    print("  classes/<class_id>/modules/scoreform/work/<assignment_id>/results.csv")
    print("  QR-aware scoring remains unavailable pending later PDS2 routing work.")
    print()
    print("Routed results are an audit log, not a finalized gradebook export.")
    print("Manually verify scores before using them for grades.")
    print()
