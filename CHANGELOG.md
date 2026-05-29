# Changelog

All notable changes to ScoreForm will be documented in this file.

ScoreForm uses milestone-based development while it remains in early active development. It is not yet recommended for high-stakes grading without manual verification.

## [Unreleased]

### Documentation

* Pre-public repository audit remains pending.
* Senior-developer review pass remains pending.
* Project-manager / release-readiness review pass remains pending.
* Future README and documentation organization improvements may continue as the project stabilizes.

## [v0.7.0] — In Progress

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

## [v0.6.0] — Flexible Form Configuration and Standards Metadata

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

## [v0.5.0] — Roster and Assignment Management

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

## [v0.4.0] — Installable Command

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

## [v0.3.0] — Teacher-Friendly Terminal Menu

### Added

* Added a basic terminal menu.
* Wrapped existing CLI workflows for generating sheets, scoring scans, decoding QR codes, validating files, and setting up assignment folders.

### Changed

* Preserved direct CLI commands while adding a menu-based workflow.

## [v0.2.0] — Scan Workflow and Auditability

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

## [v0.1.0] — QR-Aware Scoring With Routed Results

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
