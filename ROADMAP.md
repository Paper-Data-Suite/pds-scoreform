# ScoreForm Roadmap

## Project Status

ScoreForm is an early prototype and active-development local-first OMR tool for generating printable answer sheets and scoring scanned responses.

It works for controlled testing and development use, but it is not yet recommended for high-stakes grading without manual verification. Current work is focused on improving reliability, test coverage, documentation, and public-readiness while keeping example data synthetic.

## Completed Milestones

### v0.1.0 — QR-Aware Scoring With Routed Results

ScoreForm can generate QR-coded student sheets and class packets, decode QR payloads, score QR-aware scans, route results into class and assignment folders, enrich routed results with roster data, and preserve legacy/manual scoring workflows. Regression coverage exists for QR decoding, QR-aware scoring, mixed scans, routed results, and roster-enriched results.

### v0.2.0 — Scan Workflow and Auditability

ScoreForm tracks scan source files in result rows, creates a project-level `scans_inbox/`, routes QR-aware debug output into assignment folders, handles duplicate scan attempts with attempt metadata, and protects existing assignment folders from mismatched assignment JSON collisions.

### v0.3.0 — Teacher-Friendly Terminal Menu

A basic terminal menu wraps the main workflows so users can generate sheets, score scans, decode QR codes, validate files, and set up assignment folders without memorizing every command.

### v0.4.0 — Installable Command

ScoreForm supports editable installation, a `scoreform` console command, a `scoreform/cli.py` entry point, `pyproject.toml` packaging metadata, and backward-compatible `python main.py` commands.

### v0.5.0 — Roster and Assignment Management

The terminal menu supports creating rosters and assignments without manually editing CSV or JSON files. These workflows include parent-directory creation, overwrite confirmation, validation after save, and support for assignments with configurable question counts.

### v0.6.0 — Flexible Form Configuration and Standards Metadata

ScoreForm includes a pytest foundation, supports single-page assignments with 1-15 questions, validates optional question-level standards metadata, preserves optional roster columns when loading rosters, and keeps existing assignment files without standards metadata valid.

## Current Milestone

### v0.7.0 — Robustness, Cleanup, and Public Readiness

Completed so far:

* Synthetic scoring accuracy fixture for deterministic known-answer OMR detection.
* CLI failure-mode tests for invalid commands, missing files, invalid assignment files, invalid roster files, and nonexistent score inputs.
* Generated local artifacts organized under ignored `local_outputs/` folders.
* Phase 1 general cleanup for PowerShell helper names, score command help text, and confirmed unused imports.
* Public-facing `ROADMAP.md` created while preserving `development_plan.md` as the detailed working document.
* Public-facing `CHANGELOG.md` created for milestone history and current work.

Remaining v0.7.0 work:

* Complete a pre-public repository audit.
* Run a senior developer review pass.
* Run a project manager / release-readiness review pass.

## Near-Term Priorities

* Complete the pre-public repository audit.
* Run senior-developer review.
* Run project-manager / release-readiness review.
* Keep `README.md` current.
* Keep all examples synthetic.
* Continue improving tests and documentation.

## Future Work

Planned and possible future work includes:

* Add a `scoreform --help` flag and terminal menu help option.
* Consider `scoreform --version`.
* Add menu-driven standards editing.
* Add standards performance reporting.
* Add roster editing.
* Add roster import column mapping.
* Add roster summaries.
* Add optional report/export field selection.
* Add a manual answer entry workflow.
* Add a scan storage or archive workflow.
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
* `SECURITY.md` and audit work may be needed before public release.
* Detailed working planning notes are preserved in `docs/development_plan.md`.
* A pre-public audit should happen before making the repository public.
