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
  scoreform generate-batch --target <class_id>/<assignment_id> [--target <class_id>/<assignment_id> ...] [--apply]
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
  scoreform bulk-edit-assignment --class-id <class_id> --assignment-id <assignment_id> [--answer-key-text <text> | --answer-key-csv <path> | --answer-key-json <path>] [--alignment-text <text> | --alignment-csv <path> | --alignment-json <path>] [--standards-profile-id <profile_id>] [--apply]
  scoreform copy-assignment --source-class-id <class_id> --source-assignment-id <assignment_id> --target-assignment-id <assignment_id> --target-class-id <class_id> [--target-class-id <class_id> ...] [--title <title>] [--apply]
  scoreform preset list
  scoreform preset show --preset-id <preset_id>
  scoreform preset save --preset-id <preset_id> --source-class-id <class_id> --source-assignment-id <assignment_id> [--label <label>] [--apply]
  scoreform preset apply --preset-id <preset_id> --target-assignment-id <assignment_id> --title <title> --target-class-id <class_id> [--target-class-id <class_id> ...] [--apply]
  scoreform preset delete --preset-id <preset_id> [--apply]
  scoreform academic-work show --class-id <class_id> --assignment-id <assignment_id>
  scoreform academic-work register --class-id <class_id> --assignment-id <assignment_id> --academic-intent <intent> --lifecycle <lifecycle>
  scoreform academic-work update --class-id <class_id> --assignment-id <assignment_id> --academic-intent <intent> --lifecycle <lifecycle> --expected-current-revision <revision>
  scoreform manifest list --class-id <class_id> --assignment-id <assignment_id>
  scoreform manifest show --class-id <class_id> --assignment-id <assignment_id> --revision <revision>
  scoreform manifest validate --class-id <class_id> --assignment-id <assignment_id> --revision <revision>
  scoreform manifest generate --class-id <class_id> --assignment-id <assignment_id>
  scoreform publication status --class-id <class_id> --assignment-id <assignment_id>
  scoreform publication list --class-id <class_id> --assignment-id <assignment_id>
  scoreform publication show --class-id <class_id> --assignment-id <assignment_id> --publication-id <publication_id>
  scoreform publication publish --class-id <class_id> --assignment-id <assignment_id> --revision <revision>
  scoreform publication supersede --class-id <class_id> --assignment-id <assignment_id> --revision <revision> --expected-current-publication-id <publication_id>
  scoreform publication republish-after-withdrawal --class-id <class_id> --assignment-id <assignment_id> --expected-current-publication-id <publication_id>
  scoreform publication withdraw --class-id <class_id> --assignment-id <assignment_id> --publication-id <publication_id> --reason <reason>
  scoreform publication rebuild-catalog
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
  scoreform diagnostics list [--limit <n>] [--format <text|json>]
  scoreform diagnostics show --event-id <event_id> [--format <text|json>]
  scoreform help
  scoreform --help
  scoreform version
  scoreform --version

Commands:
  menu                  Launch the terminal menu.
  manifest              Generate, list, show, or validate immutable result manifests.
  publication           Manage Core publication, supersession, withdrawal, and catalog workflows.
  generate              Generate a generic template or assignment-based answer sheets.
  generate-batch        Plan or explicitly execute answer-sheet generation for exact managed targets.
  regenerate-sheets     Regenerate managed answer sheets from the current roster.
  score                 Score scanned responses.
  list-scan-review      List unresolved and deferred ScoreForm scan review items.
  resolve-scan-review   Resolve or defer one ScoreForm scan review item.
  decode-qr             Retain a PDF/image and decode Core PDS2 locators.
  validate-assignment   Validate an assignment JSON file.
  validate-roster       Validate a roster CSV file.
  setup-assignment      Create class and assignment folders.
  bulk-edit-assignment  Plan or atomically apply complete answer-key/alignment replacements.
  copy-assignment       Plan or explicitly create safe assignment copies across classes.
  preset                List, save, inspect, apply, or delete reusable setup presets.
  academic-work         Show, register, or explicitly update Academic Work metadata.
  workspace             View or configure the shared PDS workspace root.
  school-year           View, open, or close the active PDS school year.
  scan-filing           View or configure ScoreForm scored-copy filing.
  diagnostics           Read retained privacy-minimal ScoreForm diagnostic events.
  help                  Show this help text.
  version               Show the installed ScoreForm version.

Core 0.6/PDS2 scan intake:
  Personalized PDFs, class packets, and managed regeneration use immutable page
  records and Core PDS2 route registrations. The installed one-page module
  handler is available to Core. Active scans are retained before QR detection,
  parsed only as PDS2, and dispatched one source page at a time through a fresh
  installed-module registry. Complete ScoreForm pages are assembled by immutable
  issuance identity and exported through routed-results schema version 2.
  Core-v2 failure persistence and append-only resolution review are active. Managed assignment
  setup, discovery, creation, editing, plain-paper result entry, and result
  viewing use module-qualified ScoreForm work storage and are available.

Scoring modes:
  QR-aware scoring means retained PDS2 dispatch, issuance assembly, and export.
  scoreform score scanned_file.pdf
      Retains and dispatches each Core-valid PDS2 page, then appends one attempt
      for every complete, unambiguous ScoreForm issuance. Foreign results remain opaque.

  scoreform score scanned_file.pdf output.csv
      Runs the same assembly and writes schema-v2 history to the explicit CSV.

  Full and foreign-only success exit 0. Partial, zero-success, export, file, and
  integration failures exit nonzero. Missing or duplicate page sets write no
  partial attempt. Actionable failures are persisted under scans/review/.

  scoreform score scanned_file.pdf answer_key.json
      Manual scoring with an explicit answer key and default local results path.

  scoreform score scanned_file.pdf output.csv answer_key.json
      Manual scoring with an explicit answer key and explicit output CSV.

  Manual multi-page or failed batches report processed, scored, and
  failed/skipped page counts. Partial exports warn; zero-success batches fail.

Examples:
  scoreform
  scoreform generate examples\\sample_assignment.json --rosters examples\\sample_roster_english9_p2.csv
  scoreform generate-batch --target english10_p2/unit_2_quiz --target english10_p4/unit_2_quiz
  scoreform score scans_inbox\\class_packet.pdf
  scoreform decode-qr classes\\english9_p2\\modules\\scoreform\\work\\rj_act1_quiz\\templates\\class_packet.pdf
  scoreform validate-assignment examples\\sample_assignment.json
  scoreform validate-roster examples\\sample_roster_english9_p2.csv
  scoreform bulk-edit-assignment --class-id english10_p2 --assignment-id unit_1_quiz --answer-key-text "A B C D"
  scoreform copy-assignment --source-class-id english10_p2 --source-assignment-id unit_1_quiz --target-assignment-id unit_1_quiz --target-class-id english10_p4
  scoreform preset save --preset-id short_quiz --source-class-id english10_p2 --source-assignment-id unit_1_quiz
  scoreform preset apply --preset-id short_quiz --target-assignment-id unit_2_quiz --title "Unit 2 Quiz" --target-class-id english10_p4
  scoreform workspace show
  scoreform workspace set "C:\\Users\\teacher\\Paper Data Suite"
  scoreform workspace validate
  scoreform workspace reset
  scoreform school-year show
  scoreform school-year open 2026-2027
  scoreform school-year close
  scoreform scan-filing show
  scoreform scan-filing set move
  scoreform diagnostics list --limit 20

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
    print("Assignment Management:")
    print("  1. Create / Copy / Edit Assessments")
    print("  2. Print Answer Sheets")
    print("  3. Process Scans")
    print("  4. Review Results")
    print("  5. Enter Plain-Paper Results")
    print("  6. Share Results")
    print("  7. Advanced Tools")
    print("  C. Assignment Context")
    print("  Active/recent assignment identity is retained only for this session,")
    print("  revalidated before reuse, and may be switched or cleared explicitly.")
    print("  Direct CLI commands do not consume interactive assignment context.")
    print("  Share Results starts with Share Results with Meridian.")
    print("  It publishes exact ScoreForm evidence through Core and reports when")
    print("  results are available for Meridian to consume; it does not invoke Meridian.")
    print("  It does not automatically send results to Meridian.")
    print("  Exact registration, manifest, and publication workflows remain available.")
    print()
    print("Typical workflow:")
    print("  1. Create or validate a roster CSV.")
    print("  2. Create, copy, or validate an assignment.")
    print("     Question-level standards use enumerated PDS Core standards profiles.")
    print("  3. Generate answer sheets.")
    print("  4. Scan completed sheets.")
    print("  5. Score scanned responses.")
    print("  6. Review the page-dispatch summary.")
    print()
    print("PDS2 scan intake:")
    print("  Sources are retained before QR detection and dispatched through Core.")
    print("  ScoreForm pages are scored independently; source page is not logical page.")
    print("  Complete print copies are assembled only by issuance identity.")
    print("  Missing, duplicate, or conflicting page sets are not exported.")
    print("  Routed result destination:")
    print("  classes/<class_id>/modules/scoreform/work/<assignment_id>/results.csv")
    print()
    print("  Review failures use immutable Core-v2 records under scans/review/.")
    print("  Teacher decisions append records under scans/review/resolutions/.")
    print("Manually verify page scores before using them for grades.")
    print()
