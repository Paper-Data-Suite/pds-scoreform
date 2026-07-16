# Changelog

All notable changes to ScoreForm will be documented in this file.

ScoreForm uses milestone-based development while it remains in early active development. It is not yet recommended for high-stakes grading without manual verification.

## Version Policy

While ScoreForm is in active pre-1.0 development, `pyproject.toml` tracks the current active development package version using PEP 440 development versions. For example, `0.7.0.dev0` means active development toward the `v0.7.0` milestone.

When a milestone is formally released/tagged, the package version should move to the final release number, such as `0.8.0`. When development resumes toward the next milestone, the version should move to the next development version, such as `0.9.0.dev0`.

GitHub milestones are project-management buckets. Package versions describe installable application/package state. Making the repository public is a visibility change and does not automatically require changing the package version from a development version to a final release version.

## [Unreleased]

No changes yet.

## [v0.9.1] - release date pending

### Added

* Added assignment and per-question standards-alignment validation against the
  shared PDS Core standards-library contract.
* Added `check_dependencies.ps1` to verify the repository-local environment,
  the `pds-core>=0.5,<0.6` package contract, third-party imports, and Poppler
  availability.
* Added read-only assignment-results viewing with per-student recent score,
  total, and attempt-count summaries without changing grading policy or
  historical rows.
* Added staged assignment editing for title, per-question answer keys, and
  existing-standard-ID alignment. Identity, question count, and choices remain
  locked, and editing does not regenerate sheets, rescore scans, or rewrite
  results.
* Added staged roster editing through shared Core roster APIs, preserving
  optional columns, immutable student IDs, and historical generated materials.
* Added CLI and menu controls for showing, opening, and closing the shared
  active school year without moving, archiving, or rewriting classroom data.
* Added side-effect-free standards-usage event construction plus a separate
  explicit recording helper. Usage recording remains opt-in.
* Added standards alignment during assignment creation, including selection
  from and creation within the shared standards library; assignments store
  standard IDs only.
* Added plain-paper result entry as a separate route-free workflow.
* Added copy, move, and off scan-filing modes with full-success,
  single-assignment eligibility, retained-source preservation, safe original
  handling, and assignment-local scored copies.
* Added module-qualified ScoreForm work under
  `classes/<class_id>/modules/scoreform/work/<assignment_id>/`.
* Added immutable answer-sheet issuance and page records, unique Core PDS2 route
  registrations created before rendering, and separate identities for
  individual and class-packet print copies.
* Added the installed `paper_data_suite.modules` ScoreForm profile and
  defensive route handler for PDS Core 0.5.
* Added retained-source Core dispatch, issuance-based multi-page attempt
  assembly, and routed-results schema version 2.
* Added Core schema-v2 scan-review failure persistence and append-only
  resolution workflows.
* Added active standard and compact registered layouts plus managed
  regeneration with fresh immutable identities.

### Changed

* Extracted workspace, school-year, help/version, scoring, scan-menu, roster,
  assignment, standards, generation, and QR workflows into focused modules
  while preserving the public CLI entry point and teacher-facing behavior.
* Removed transitional monkeypatch and synchronization bridges after workflow
  ownership moved to the focused modules.
* Replaced signature-inspection-based scoring dispatch with explicit call
  paths.
* Hardened routed and manual scoring failure accounting so full success,
  partial success, zero success, export failure, processed pages, scored pages,
  and failed/skipped pages are reported explicitly.
* Hardened routed-result writes with destination preflight checks,
  idempotent schema-v2 identity, and failure-aware export reporting.
* Privacy-minimized QR diagnostics and result `source_file` values by default
  while retaining enough provenance for audit and review.
* QR payloads now contain only canonical PDS2 locator identity. Student,
  logical-page, question-range, layout, answer-key, attempt, and result
  semantics come from authoritative records.
* Routed results now preserve aligned route, page, logical-page, source-page,
  retained-path, source-scan, digest, and intake provenance.
* Manual answer-key scoring, plain-paper entry, and routed PDS2 scoring are
  explicitly separate workflows.
* Current routed histories and persisted Core metadata require aware
  timestamps.

### Removed

* Removed active PDS1 and OMR1 parsing and generation.
* Removed QR-carried ScoreForm semantics and obsolete QR compatibility APIs.
* Removed unqualified work-root discovery and universal assignment paths.
* Removed schema-v1 routed-results migration, `legacy_scan`, generic migration
  gates, and obsolete schema-v1 scan-review creation paths.
* Removed remaining transitional CLI/workflow compatibility bridges that no
  longer owned behavior.

### Documentation

* Documented the development and release Core dependency contracts, including
  separate noneditable Core and ScoreForm wheels.
* Established `run_tests.ps1` as the authoritative local release-readiness
  gate.
* Updated Windows, PowerShell, Poppler, setup, teacher workflow, QR outcome,
  scan filing, privacy, diagnostics, and local-output guidance.
* Added release packaging, artifact inspection, clean-install, installed
  profile, and physical-paper acceptance procedures.

### Compatibility

PDS1 and OMR1 sheets are unsupported. Historical schema-v1 routed-result files
are not migrated. Assignments must use canonical module-qualified work.
Previously printed legacy sheets cannot be assigned fabricated PDS2 routes;
generate new v0.9.1 PDS2 sheets for routed scoring.

### Testing

* Added coverage for assignment and roster editing, result viewing, school-year
  controls, standards alignment and usage helpers, scan-filing safeguards,
  explicit failure accounting, privacy boundaries, and release metadata.
* Added coverage for registered one-page and multi-page generation and scoring,
  compact layout, regeneration, duplicate/conflict/missing observations,
  rescan idempotence, manual workflows, scan review and resolution, module
  isolation, retained provenance, mixed-module dispatch, unsupported schemas,
  schema-v1 rejection, and filing modes.
* Added nonpublishing Python 3.11 release-readiness CI, deterministic artifact
  checks, clean wheel/sdist install validation, and installed end-to-end smoke
  tests.
* The mandatory real printed two-page acceptance test remains pending until the
  project owner records its result; publication is blocked until it passes.

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
