# Changelog

All notable changes to ScoreForm will be documented in this file.

ScoreForm uses milestone-based development while it remains in early active development. It is not yet recommended for high-stakes grading without manual verification.

## Version Policy

While ScoreForm is in active pre-1.0 development, `pyproject.toml` tracks the current active development package version using PEP 440 development versions. For example, `0.7.0.dev0` means active development toward the `v0.7.0` milestone.

When a milestone is formally released/tagged, the package version should move to the final release number, such as `0.8.0`. When development resumes toward the next milestone, the version should move to the next development version, such as `0.9.0.dev0`.

GitHub milestones are project-management buckets. Package versions describe installable application/package state. Making the repository public is a visibility change and does not automatically require changing the package version from a development version to a final release version.

## [Unreleased]

### Added

* Added a read-only Assignment Management workflow for viewing assignment-local
  `results.csv` files. The viewer discovers classes and assignments, displays
  one summary row per student with recent score, total, and attempt count, and
  does not mutate historical result rows or decide grading policy.
* Added an Assignment Management menu workflow for editing existing
  assignments. The workflow stages title, answer-key, and existing-standard-ID
  alignment edits until explicit `SAVE`, requires `DISCARD` for unsaved
  cancellation, keeps `assignment_id`, `question_count`, and `choices` locked,
  writes only the selected `assignment.json`, and does not regenerate answer
  sheets, rescore scans, rewrite historical results, alter rosters, write
  standards usage ledgers, or modify the shared standards library.
* Changed assignment answer-key editing to prompt for one question at a time,
  show the selected question's current answer, and stage each changed answer
  independently instead of accepting comma-separated bulk edits.
* Added a Roster Management menu workflow for editing existing class rosters.
  The workflow loads and writes canonical class rosters through shared
  `pds-core` roster APIs, stages add/edit/remove changes until explicit save,
  preserves existing optional roster columns, disallows `student_id` changes,
  and treats removal as removal from the active roster only without deleting
  generated materials, assignments, results, scans, or scan evidence.
* Added ScoreForm CLI and Workspace Settings menu workflows for showing,
  opening, and closing the shared `pds-core` active school-year state.
  Opening and closing a school year does not delete, archive, migrate,
  summarize, or move classroom data.
* Added a side-effect-free builder for creating shared `pds-core` standards
  usage events from ScoreForm assignment-local standards alignment. The builder
  does not automatically write to the shared standards usage ledger, change
  scoring behavior, or add standards summaries or reports.
* Added an explicit helper for recording ScoreForm assignment standards usage
  to the shared `pds-core` standards usage ledger. Recording is not automatic,
  no CLI or menu command has been added yet, scoring behavior is unchanged, and
  no standards summaries or reports have been added.
* Added standards alignment during menu-driven assignment creation. Teachers can
  skip standards, attach existing shared standards from the `pds-core` workspace
  standards library, or create a new shared standard before attaching its ID to
  selected questions. Assignment files store standard IDs only; empty standards
  lists remain valid, usage recording is not automatic, and scoring/export
  behavior is unchanged.
* Added same-assignment scan filing after successful QR-aware routed scoring.
  When routed result export succeeds and all successfully scored pages resolve
  to one class and assignment, ScoreForm copies the original source scan into
  the assignment `scans/` folder with a timestamped `_scored` filename while
  preserving the original source scan.

### Changed

* Extracted the workspace and school-year CLI command-group implementations
  into focused modules while preserving the existing `scoreform.cli` entry
  point and command dispatch.
* Extracted top-level CLI help, version, and terminal menu help presentation
  into a focused module while preserving the existing `scoreform.cli` entry
  point and command dispatch.
* Extracted scoring command orchestration into a focused module while
  preserving the existing `scoreform.cli` entry point and command dispatch.

### Documentation

* Post-public repository audit remains pending.
* Senior-developer review pass remains pending.
* Project-manager / release-readiness review pass remains pending.
* Future README and documentation organization improvements may continue as the project stabilizes.

## [v0.8.1] - 2026-06-06

### Changed

* Reorganized the terminal menu around teacher-centered workflows.
* Moved generation, scoring, QR decoding, assignment creation, and assignment validation under Assignment Management.
* Kept `setup-assignment` available through direct CLI while removing it from the normal teacher-facing menu.
* Standardized interactive menu headers so `ScoreForm` appears consistently above main menu and submenu screens.
* Added restrained green title styling for supported interactive terminals, with plain-text fallback for captured or non-interactive output.
* Tightened `scripts/update_version.py` so generated version assertions distinguish final release versions from matching development versions.

### Testing

* Updated menu workflow tests for the reorganized menu structure.
* Added tests for menu header formatting and color fallback behavior.
* Added tests for strict version updater assertion generation.

## [v0.8.0] - 2026-06-05

### Added

* Added interactive terminal-menu screen clearing and pauses after important output.
* Added read-only roster viewing through the roster management menu.
* Added a scan picker for supported files in `scans_inbox/`.
* Made QR-aware routed scoring the recommended/default terminal-menu scoring workflow.
* Added QR-aware batch failure summaries.
* Added non-overwriting debug image filenames for repeated scoring runs.
* Added `run_fast_tests.ps1` for fast pytest, whitespace, and generated/private artifact checks.

### Changed

* Kept direct CLI scoring script-friendly with explicit path support and existing scoring modes.
* Clarified that routed `results.csv` files are audit logs, not final gradebook exports.
* Updated README, roadmap, changelog, and development-plan documentation for the completed `v0.8.0` workflow state.
* Finalized the package version at `0.8.0`.

### Testing

* Updated version assertions for `0.8.0`.
* Preserved full regression coverage through `run_tests.ps1` and fast development checks through `run_fast_tests.ps1`.

## [v0.7.0] - Robustness, Cleanup, and Public Readiness

### Added

* Added a synthetic scoring accuracy fixture for deterministic known-answer OMR checks.
* Added CLI failure-mode tests for invalid commands, missing files, invalid assignment files, invalid roster files, and nonexistent score inputs.
* Added public `ROADMAP.md` while preserving `docs/development_plan.md` as the detailed working document.
* Added public `CHANGELOG.md` for milestone history and current work.

### Changed

* Organized generated local artifacts under ignored `local_outputs/` folders.
* Completed an initial general cleanup pass covering PowerShell helper names, score command help text, and confirmed unused imports.
* Configured pytest collection so generated artifact folders are not collected as tests.

### Documentation

* Continued public-readiness documentation work while keeping active-development limitations explicit.

## [v0.6.0] - Flexible Form Configuration and Standards Metadata

### Added

* Added the initial pytest suite for focused module-level checks.
* Added support for single-page assignments with 1-15 questions.
* Added an optional question-level standards metadata foundation in assignment JSON.
* Added preservation of optional roster columns when roster CSV files are loaded.

### Changed

* Kept assignment files without standards metadata valid.
* Kept standards metadata separate from scoring behavior, QR payloads, result routing, and roster CSV output.

### Testing

* Added pytest coverage for QR validation, assignment validation, roster validation, folder helpers, template filename helpers, variable question counts, and CSV export behavior.

## [v0.5.0] - Roster and Assignment Management

### Added

* Added menu-driven roster creation without manual CSV editing.
* Added menu-driven assignment creation without manual JSON editing.
* Added parent-directory creation for roster and assignment output paths.
* Added validation after roster and assignment files are saved.
* Added overwrite confirmation before replacing existing roster or assignment files.

### Changed

* Expanded the terminal menu into basic roster and assignment management workflows.

### Testing

* Added regression coverage for menu-driven roster creation and assignment creation.

## [v0.4.0] - Installable Command

### Added

* Added editable installation support.
* Added the `scoreform` console command.
* Added `scoreform/cli.py` as the package CLI entry point.
* Added `pyproject.toml` packaging metadata.

### Changed

* Preserved backward-compatible `python main.py` commands.
* Made `scoreform` with no arguments launch the terminal menu by default.

### Testing

* Added regression coverage for editable install and the `scoreform` command.

## [v0.3.0] - Teacher-Friendly Terminal Menu

### Added

* Added a basic terminal menu.
* Wrapped existing CLI workflows for generating sheets, scoring scans, decoding QR codes, validating files, and setting up assignment folders.

### Changed

* Preserved direct CLI commands while adding a menu-based workflow.

## [v0.2.0] - Scan Workflow and Auditability

### Added

* Added scan source tracking in result rows.
* Added project-level `scans_inbox/` creation.
* Added QR-aware debug image routing into assignment folders.
* Added duplicate and attempt handling with per-attempt metadata.
* Added assignment collision protection using semantic assignment JSON comparison.

### Changed

* Improved routed result auditability with source file, timestamp, and attempt metadata.
* Preserved generated scan files instead of adding destructive scan movement behavior.

### Fixed

* Prevented mismatched assignment JSON files from silently overwriting existing assignment folders.

### Testing

* Added regression coverage for assignment collision protection and duplicate/attempt handling.

## [v0.1.0] - QR-Aware Scoring With Routed Results

### Added

* Added QR-coded personalized answer sheets.
* Added QR-coded class packet PDFs.
* Added QR-aware scoring metadata extraction.
* Added QR-aware class packet and mixed-scan scoring.
* Added routed results into class and assignment folders.
* Added roster-enriched routed results.

### Changed

* Preserved legacy/manual scoring workflows when an explicit answer key is provided.

### Testing

* Added regression coverage for QR decoding, QR-aware scoring, mixed scans, routed results, and roster-enriched routed results.
