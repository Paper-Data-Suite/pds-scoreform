# ScoreForm Roadmap

## Project Status

ScoreForm is an early prototype and active-development local-first OMR tool for generating printable answer sheets and scoring scanned responses.

It works for controlled testing and development use, but it is not yet recommended for high-stakes grading without manual verification. Current work is focused on improving reliability, test coverage, documentation, and public-readiness while keeping example data synthetic.

## Completed Milestones

### v0.1.0 - QR-Aware Scoring With Routed Results

ScoreForm can generate QR-coded student sheets and class packets, decode QR payloads, score QR-aware scans, route results into class and assignment folders, enrich routed results with roster data, and preserve legacy/manual scoring workflows. Regression coverage exists for QR decoding, QR-aware scoring, mixed scans, routed results, and roster-enriched results.

### v0.2.0 - Scan Workflow and Auditability

ScoreForm tracks scan source files in result rows, creates a project-level `scans_inbox/`, routes QR-aware debug output into assignment folders, handles duplicate scan attempts with attempt metadata, and protects existing assignment folders from mismatched assignment JSON collisions.

### v0.3.0 - Teacher-Friendly Terminal Menu

A basic terminal menu wraps the main workflows so users can generate sheets, score scans, decode QR codes, and validate files without memorizing every command. Assignment-folder setup remains available through the direct CLI.

### v0.4.0 - Installable Command

ScoreForm supports editable installation, a `scoreform` console command, a `scoreform/cli.py` entry point, `pyproject.toml` packaging metadata, and backward-compatible `python main.py` commands.

### v0.5.0 - Roster and Assignment Management

The terminal menu supports creating rosters and assignments without manually editing CSV or JSON files. These workflows include parent-directory creation, overwrite confirmation, validation after save, and support for assignments with configurable question counts.

### v0.6.0 - Flexible Form Configuration and Standards Metadata

ScoreForm includes a pytest foundation, supports single-page assignments with 1-15 questions, validates optional question-level standards metadata, preserves optional roster columns when loading rosters, and keeps existing assignment files without standards metadata valid.

### v0.7.0 - Robustness, Cleanup, and Public Readiness

ScoreForm added deterministic scoring accuracy coverage, CLI failure-mode tests, ignored `local_outputs/` routing for generated local artifacts, PowerShell helper cleanup, clearer score command help, and initial public-facing roadmap and changelog files while preserving `docs/development_plan.md` as the detailed working document.

### v0.8.0 - Menu Workflow Polish and Release Documentation

ScoreForm completed interactive menu clear/pause behavior, read-only roster viewing, the `scans_inbox/` picker, QR-aware routed scoring as the recommended/default menu scoring workflow, QR-aware batch summaries, non-overwriting debug image filenames, fast development checks through `run_fast_tests.ps1`, and documentation/version closeout for the `0.8.0` release.

## Current Direction

The `v0.8.0` milestone is complete. Current near-term work is organized around `v0.8.1` menu refinement and `v0.9.0` project-organization / data-lifecycle planning, while avoiding unnecessary scoring-schema or generated-form changes.

The terminal menu is organized around teacher workflows: Assignment Management, Roster Management, Help, and Exit. Assignment creation, validation, generation, scoring, and QR decoding live under Assignment Management. Stable path-oriented primitives such as `setup-assignment` remain available through the direct CLI without appearing in the normal teacher-facing menu.

## Near-Term Priorities

* Complete the post-public repository audit.
* Run senior-developer review.
* Run project-manager / release-readiness review.
* Keep `README.md` current.
* Keep all examples synthetic.
* Continue improving tests and documentation.

## Future Work

Planned and possible future work includes:

* Keep CLI help, version output, and terminal menu help current as commands evolve.
* Add menu-driven standards editing.
* Add standards performance reporting.
* Add roster editing.
* Add roster import column mapping.
* Add roster summaries.
* Add optional report/export field selection.
* Add a manual answer entry workflow.
* Add a scan storage or archive workflow separate from the current `scans_inbox/` picker.
* Add project root/home directory configuration as future architecture work.
* Add structured logging.
* Improve QR and scan reliability.
* Add malformed and missing QR test coverage.
* Support multi-page forms.
* Broaden CLI/parser cleanup if needed.
* Consolidate CSV-writing logic.
* Clean up roster enrichment behavior.
* Extract shared validation helpers.
* Consider a `pathlib` migration.
* Consider splitting menu and command-dispatch modules as the CLI grows.

## Longer-Term Direction

ScoreForm should remain standalone and local-first.

ScoreForm may eventually become one module in a larger Paper Data Suite, but that suite does not exist yet. Longer-term ideas may include scanned essay tagging or scoring, reporting, data visualization, and email/export workflows.

Future schema and module-boundary decisions should preserve standalone ScoreForm functionality while allowing later interoperability if a larger suite becomes useful.

## Public-Readiness Notes

* Repository examples must remain synthetic.
* Real student data, scanned student work, and private classroom records should not be committed.
* `README.md` should clearly identify current limitations.
* `SECURITY.md` and audit work may be needed before broader classroom use or a stable release.
* Detailed working planning notes are preserved in `docs/development_plan.md`.
* A post-public repository audit should happen before recommending ScoreForm for broader classroom use or treating it as classroom-ready.
