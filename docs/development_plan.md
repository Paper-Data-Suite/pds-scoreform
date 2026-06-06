# OMR Program Iterative Development Plan

> Note: This document preserves detailed working and historical planning notes. For a cleaner public summary of project direction, see `ROADMAP.md`.

## Completed

The project currently supports:

* CLI workflow helpers split from command dispatch into `scoreform/workflows.py`
* Modular `scoreform/` package structure
* Root-level `main.py` as CLI entry point
* Minimal `scoreform/__init__.py`
* `requirements.txt` for Python package dependencies
* Portable PowerShell regression test script: `run_tests.ps1`
* Printable generic `local_outputs/templates/template.pdf`
* Debug `local_outputs/templates/template.png`
* Image scoring
* Scanned PDF scoring
* Multi-page PDF batch scoring
* Corner registration detection
* Blank detection
* Ambiguous/double-mark detection
* Legacy top-level CSV export
* External bare `answer_key.json` validation
* Assignment JSON validation through `validate-assignment`
* Assignment validation supports `question_count` from 1 to 15
* Assignment JSON supports optional question-level `standards` metadata
* Assignment validation checks standards metadata against the configured `question_count`
* Roster CSV validation through `validate-roster`
* Roster CSV validation allows additional optional columns beyond the required schema
* Loaded roster student dictionaries preserve optional columns
* Class/assignment folder setup through `setup-assignment`
* Multi-roster `generate` command
* Individual personalized student PDFs
* Class packet PDF generation
* Student PDFs and class packet PDFs render only the configured number of question rows
* QR code generation on individual student PDFs
* QR code generation on class packet pages
* QR payload parsing
* QR decoding from generated PDFs/images through `decode-qr`
* QR decoding from a printed-and-scanned student sheet when scan quality is adequate
* Legacy scoring of a printed, filled, phone-scanned student sheet with QR code present
* QR-aware scoring metadata extraction
* Automatic assignment lookup from QR metadata during scoring
* QR payload field validation / path traversal protection
* Shared identifier validation for `class_id`, `assignment_id`, and `student_id` before path use, QR payload generation, folder setup, and menu-created file writing
* QR-aware score output with `class_id`, `assignment_id`, and `student_id`
* Legacy/manual scoring preserved when an explicit answer key is provided
* Scoring uses assignment question count for QR-aware scoring and inferred answer-key count for legacy/manual scoring
* Registration mark detection searches expected corner zones with tolerant dark-component selection so filled answer boxes near Q15 cannot be selected as perspective corners while imperfect true markers can still be recovered
* 15-question synthetic scoring, Q15 corner-conflict, and imperfect bottom-left marker regression coverage
* `score` command exits nonzero when no pages are scored successfully
* QR-based mixed-scan scoring for multi-page PDFs
* QR-aware class packet scoring with one row per student page
* Result routing to assignment folders for QR-aware scoring
* QR decode preprocessing fallbacks for phone-scan reliability, including grayscale,
  thresholding, upscaling, and generous upper-right QR-region crops
* Routed result CSV output at `classes/<class_id>/assignments/<assignment_id>/results.csv`
* Routed result CSV writes use same-directory temporary files and replacement so existing results remain intact if a write or replace fails
* Routed result export validates existing CSV headers before preserving rows and appending new attempts
* Routed CSV output containing page, class, assignment, student, roster, score, total, and answer columns
* CSV export creates dynamic question columns based on result question count
* Roster lookup for routed results using `classes/<class_id>/roster.csv`
* Routed result rows enriched with `last_name`, `first_name`, and `period`
* CSV export functions return success/failure status
* Regression coverage for QR decoding, QR-aware scoring, mixed-scan scoring, routed results, and roster-enriched routed results
* Scan source file tracking in all result rows
* Project-level `scans_inbox/` folder creation and setup
* Scan inbox automatically created during assignment setup
* Assignment collision protection with semantic JSON comparison
* Collision detection prevents overwrite of mismatched assignments
* Regression test coverage for collision protection
* Menu-driven roster creation
* Roster management submenu with create, view, validate, and return options
* Roster CSV writing with required schema
* Roster overwrite confirmation
* Roster parent-directory creation when needed
* Roster validation after save
* Regression test coverage for menu-driven roster creation
* Menu-driven assignment creation
* Menu-driven assignment creation prompts for `question_count`
* Menu-driven assignment creation writes empty standards lists for each question
* Assignment management submenu with create, validate, generate, score, decode QR, and return options
* Assignment JSON writing with current required schema
* Assignment overwrite confirmation
* Assignment parent-directory creation when needed
* Assignment validation after save
* Regression test coverage for menu-driven assignment creation
* Basic terminal menu interface through `python main.py menu` and `scoreform menu`
* Teacher-centered main menu organized around Assignment Management, Roster Management, Help, and Exit
* Menu wraps guided teacher workflows while preserving direct CLI commands
* Direct CLI and interactive menu intentionally do not require one-to-one command parity
* Path-oriented setup primitives such as `setup-assignment` may remain direct-CLI-only
* Editable package installation with `python -m pip install -e .`
* Installable `scoreform` console command
* `scoreform` command with no args launches menu by default
* `scoreform <subcommand>` maps to existing workflows (generate, score, validate-*, setup-assignment, decode-qr, menu)
* CLI help support through `scoreform --help`, `scoreform -h`, and `scoreform help`
* CLI version support through `scoreform --version` and `scoreform version`
* Version reporting reads installed package metadata with a local `pyproject.toml` fallback
* Terminal menu help option with workflow, routed-results, audit-log, and manual-verification guidance
* `scoreform/cli.py` module with main entry point
* `pyproject.toml` with setuptools configuration
* Backward-compatible `python main.py` commands preserved
* Regression test coverage for editable install and scoreform command
* Initial pytest suite added
* Pytest coverage for QR validation, assignment validation, roster validation, folder helpers, and template filename helpers
* Pytest coverage for variable question count assignment validation and CSV export
* `run_tests.ps1` now installs development extras and runs pytest before full workflow regression checks
* Local generated development/test artifacts are organized under ignored `local_outputs/` folders
* Public `CHANGELOG.md` created while preserving `development_plan.md` as the detailed working/planning document
* Interactive menu clears between screens and pauses after important output
* Roster management submenu supports read-only roster viewing
* Menu scoring can select supported scans from `scans_inbox/`
* QR-aware routed scoring is the recommended/default terminal-menu scoring workflow
* QR-aware batch scoring reports failure summaries
* Debug image filenames avoid overwriting earlier debug output from repeated runs
* Fast development checks are available through `run_fast_tests.ps1`
* Version finalized at `0.8.0` for the completed v0.8.0 release

## Completed Milestone

### `v0.1.0` - QR-Aware Scoring With Routed Results

This milestone is complete.

Completed scope:

* QR-coded personalized answer sheets
* QR-coded class packet PDFs
* QR decoding diagnostic command
* QR-aware scoring metadata extraction
* Mixed-scan QR-aware scoring
* Automatic assignment lookup from QR metadata
* Routed assignment-level results
* Roster-enriched routed results
* Legacy/manual scoring preserved
* Regression test coverage through `run_tests.ps1`

---

## Current Generated Folder Structure

```text
classes/
  english9_p2/
    roster.csv
    assignments/
      rj_act1_quiz/
        assignment.json
        results.csv
        templates/
          class_packet.pdf
          individual/
            1001_doe_jane.pdf
            1002_smith_marcus.pdf
            1003_brown_alyssa.pdf
        scans/
        debug/

local_outputs/
  templates/
    template.pdf
    template.png
  results/
    results.csv
    qr_metadata_results.csv
    mixed_scan_results.csv
  debug/
    debug_corners_page_1.png
    debug_warped_page_1.png
  temp/
    temp_test_assignment.json
    temp_test_roster.csv
```

The `classes/` structure is the classroom assignment output model. `local_outputs/` is for generic templates, legacy/manual default results, manual debug images, and regression-test scratch files. User-provided explicit output paths are still honored.

---

## Current Data Model

### Roster CSV Format

```csv
class_id,student_id,last_name,first_name,period
english9_p2,1001,Doe,Jane,2
english9_p2,1002,Smith,Marcus,2
```

Required columns remain `class_id`, `student_id`, `last_name`, `first_name`, and `period`. Additional optional columns are allowed and preserved when rosters are loaded, but optional roster fields are not automatically exported to `results.csv` or routed result CSVs.

### Assignment JSON Format

`question_count` currently supports values from 1 to 15 for single-page forms.

```json
{
  "assignment_id": "rj_act1_quiz",
  "title": "Romeo and Juliet Act 1 Quiz",
  "question_count": 10,
  "choices": ["A", "B", "C", "D"],
  "answer_key": {
    "1": "A",
    "2": "C",
    "3": "D",
    "4": "B",
    "5": "A",
    "6": "C",
    "7": "C",
    "8": "A",
    "9": "D",
    "10": "B"
  },
  "standards": {
    "1": [],
    "2": ["RL.CI.11-12.2"],
    "3": ["RL.IT.11-12.3", "L.VI.11-12.4"]
  }
}
```

The `standards` object is optional assignment metadata. When present, its keys are question numbers validated against `question_count`, and values are lists of non-empty standard-code strings. Missing question keys and empty lists are valid. Standards metadata is not included in `results.csv` and does not affect scoring, QR payloads, result routing, or roster CSVs.

### Current QR Payload Format

```text
OMR1|class=english9_p2|aid=rj_act1_quiz|sid=1001
```

### Current Routed Results CSV Format

```csv
Page,class_id,assignment_id,student_id,last_name,first_name,period,source_file,attempt_number,scan_timestamp,Score,Total,Q1,Q1_Correct,Q2,Q2_Correct,...
```

Routed `results.csv` is documented as an audit log of successful scoring events. Repeated scans and makeup/separate scans append rows, `attempt_number` increments per student/assignment, and `source_file` plus `scan_timestamp` support auditability. ScoreForm still does not choose the official grade attempt; one-row-per-student gradebook export and attempt-selection rules remain future work.

### Runtime Dependencies

Python package dependencies are listed in:

```text
requirements.txt
```

Current dependencies:

```text
opencv-python
numpy
pdf2image
reportlab
qrcode[pil]
```

External system dependency:

```text
Poppler
```

Poppler is required by `pdf2image` for PDF conversion but is not installed by `pip`.

---

## Current Scoring Modes

### QR-Aware Scoring With Automatic Result Routing

```powershell
python main.py score scanned_file.pdf
```

Uses QR metadata to locate:

```text
classes/<class_id>/assignments/<assignment_id>/assignment.json
```

Then scores each page using that assignment's answer key and routes results to:

```text
classes/<class_id>/assignments/<assignment_id>/results.csv
```

Routed results include roster fields when `classes/<class_id>/roster.csv` is available.

### QR-Aware Scoring With Custom Output

```powershell
python main.py score scanned_file.pdf qr_metadata_results.csv
```

Uses QR-aware scoring and writes to the specified CSV file.

### Legacy / Manual Scoring

```powershell
python main.py score scanned_file.pdf results.csv examples\answer_key.json
```

Uses the explicitly supplied answer key and preserves the legacy/manual scoring workflow.

### Legacy / Manual Scoring With Answer Key Only

```powershell
python main.py score scanned_file.pdf examples\answer_key.json
```

Uses the explicitly supplied answer key and writes to the default local results path:

```text
local_outputs/results/results.csv
```

Legacy/manual debug images are written to:

```text
local_outputs/debug/
```

---

## Manual Testing Results

Manual QR and scoring tests passed using printed student sheets.

Confirmed:

* Generated student PDFs visually contain QR codes in a safe location.
* Class packet PDF pages visually contain QR codes.
* Phone camera can read QR payload directly from a generated PDF displayed on screen.
* Printed-and-scanned student sheet can be decoded by `decode-qr` when scan quality is adequate.
* Printed, filled, and scanned student sheet scored correctly at `10/10`.
* QR code placement does not interfere with corner registration detection or answer scoring.
* A field-reported 15-question failure mode was addressed by searching each expected corner zone for registration-sized dark components; synthetic regression coverage verifies that filled Q15 answer boxes do not corrupt corner selection and that an imperfect bottom-left marker is still selected.

Caveat:

* A poor-quality phone scan failed QR detection.
* QR reliability may depend on scan quality, camera quality, lighting, document alignment, and scanner app behavior.
* Future improvements may include larger QR codes, higher QR error correction, rotation/skew-specific preprocessing, or clearer scan-quality guidance for users.

---

# Phase 1: Scan Source Tracking

## Status

Completed.

## Goal

Track the source scan file for each routed result row.

## Target Behavior

Routed results should include a source file column, such as:

```csv
source_file
```

Possible routed results format:

```csv
Page,class_id,assignment_id,student_id,last_name,first_name,period,source_file,Score,Total,Q1,Q1_Correct,...
```

## Requirements

* When scoring a PDF/image, include the source file path or filename in each result row.
* Routed results should preserve this source file value.
* QR-aware custom-output CSVs may also include source file if available.
* Legacy/manual scoring may optionally include source file if available, but primary focus is routed QR-aware results.
* Do not move or copy scans yet.

## Notes

This phase prepares for later scan storage and duplicate/attempt handling.

## Suggested GitHub Issue

Create issue:

```text
Scan source tracking
```

Suggested labels:

```text
feature
roadmap
```

Suggested milestone:

```text
v0.2.0
```

---

# Phase 2: Scan Storage

## Status

Implemented for the current picker workflow: project-level scan inbox setup is implemented, and the terminal menu can select supported scans from `scans_inbox/`. Other scan storage behaviors such as moving, copying, archiving, or deleting scans are not implemented yet.

## Goal

Keep scan files organized.

## Implemented Features

* Project-level `scans_inbox/` folder auto-created when assignment setup/generation runs.
* `ensure_scan_inbox()` helper in `scoreform/folders.py`.
* Interactive menu scoring can pick supported `.pdf`, `.png`, `.jpg`, `.jpeg`, `.bmp`, `.tiff`, and `.tif` files directly from `scans_inbox/`.
* After scan selection, the default recommended menu mode is QR-aware routed scoring, which uses QR metadata to route results to `classes/<class_id>/assignments/<assignment_id>/results.csv`.
* Manual menu scoring with an answer key remains available for non-QR sheets, generic templates, testing, and exceptional workflows.
* Unsupported inbox files are ignored, and custom path entry remains available.
* Source file tracking already enabled in routed results.

## Possible Structure

```text
scans_inbox/
  mixed_scan_2026_09_15.pdf

classes/
  english9_p2/
    assignments/
      rj_act1_quiz/
        scans/
          mixed_scan_2026_09_15.pdf
```

## Decision Needed (Future Phase)

Decide whether to:

* move scans from inbox,
* copy scans into assignment folders,
* or leave scans in inbox and record source filename in results.

Initial preference:

* Keep original scans in `scans_inbox/`.
* Let the menu select scans from `scans_inbox/` without moving, copying, renaming, or deleting them.
* Record source filename in `results.csv`.
* Optionally copy scans later if needed.

## Future Requirements

* Support copying or moving scans into assignment folders (not yet implemented).
* Avoid accidental deletion of scans.
* Preserve enough source information in result rows to connect scores back to original scans (already implemented via `source_file`).

## Suggested GitHub Issue

Create issue:

```text
Scan storage workflow
```

Suggested labels:

```text
feature
roadmap
```

Suggested milestone:

```text
v0.2.0
```

---

# Phase 3: Debug Image Routing

## Status

Completed.

## Goal

Move debug image output out of the project root and into assignment-specific debug folders when possible.

## Current Behavior

Legacy/manual debug images are saved under:

```text
local_outputs/debug/
```

For QR-aware routed scoring, debug images should route to:

```text
classes/
  english9_p2/
    assignments/
      rj_act1_quiz/
        debug/
```

## Requirements

* Keep legacy/manual debug output available under `local_outputs/debug/`.
* For QR-aware scoring, use QR metadata to identify the assignment debug folder.
* Avoid overwriting useful debug output where practical.
* Consider including page number, student ID, or timestamp in debug filenames.

## Suggested GitHub Issue

Create issue:

```text
Debug image routing
```

Suggested labels:

```text
feature
cleanup
roadmap
```

Suggested milestone:

```text
v0.2.0
```

---

# Phase 4: Duplicate and Attempt Handling

## Status

Completed.

## Goal

Handle rescans, makeups, late work, and accidental duplicate scans.

## Unique Key

```text
class_id + assignment_id + student_id
```

## Policy Options

1. Overwrite old result.
2. Keep both attempts.
3. Keep both attempts but mark latest.
4. Flag duplicates for review.

## Initial Recommendation

Keep both attempts and include:

```csv
scan_timestamp,source_file,attempt_number
```

Then decide later whether gradebook export should use:

* latest attempt,
* highest attempt,
* first attempt,
* manually selected attempt.

## Requirements

* Detect when the same student/assignment combination appears more than once.
* Preserve multiple attempts instead of silently overwriting data.
* Add enough metadata to distinguish attempts.
* Avoid destructive behavior.

## Suggested GitHub Issue

Create issue:

```text
Duplicate and attempt handling
```

Suggested labels:

```text
feature
roadmap
```

Suggested milestone:

```text
v0.2.0
```

---

# Phase 5: Overwrite and Collision Protection

## Status

Completed.

## Goal

Prevent accidental data loss when regenerating assignments or reusing assignment IDs.

## Implementation Summary

Assignment collision protection has been implemented in `scoreform/folders.py` with semantic JSON comparison.

### Helper Functions

* `load_json_for_comparison(path)`: Loads a JSON file for comparison and returns the parsed object or `None` on error.
* `assignments_match(existing_assignment_path, incoming_assignment_path)`: Compares two assignment JSON files semantically.

### Updated Function

* `setup_assignment_folder()`: Now checks for an existing `assignment.json` and compares it with the incoming assignment before copying.

### Behavior

* **Match**: Existing and incoming assignments are semantically equivalent. Setup continues normally.
* **Differ**: Existing and incoming assignments differ. Setup refuses to proceed and returns `None`.

  * Prints a clear error message explaining the collision.
  * Does not copy or overwrite the incoming assignment file.
  * Does not regenerate templates.
  * `main.py` exits with nonzero status.

### Error Output

```text
Error: Assignment folder already exists for class '<class_id>' and assignment '<assignment_id>', but the existing assignment.json differs from the incoming assignment file.
Refusing to overwrite to prevent assignment/results mismatch.
Use a different assignment_id or remove/archive the existing assignment folder.
```

### Regression Test Coverage

Added to `run_tests.ps1`:

* `Invoke-TestExpectFailure` helper function
* `Assert-FileDoesNotContain` helper function
* Collision protection test that creates a valid conflicting assignment and verifies:

  * The conflicting assignment file validates successfully.
  * Setup command fails with nonzero exit code.
  * Original `assignment.json` is not overwritten.
  * Conflicting content is not present in the protected file.

## Notes

* Roster collision protection is deferred to future phases.
* `--overwrite` flag is not implemented yet.
* Menu interface is implemented.

---

# Phase 6: Basic Terminal Menu Interface

## Status

Completed.

## Goal

Make ScoreForm usable without memorizing command names.

The current CLI commands are useful for development, but not convenient for everyday classroom use. A simple terminal menu should wrap the stable workflow.

## Initial Interface Type

Use a simple text menu in PowerShell/terminal.

Avoid GUI dependencies for now.

## Possible Command During Development

```powershell
python main.py menu
```

or eventually:

```powershell
python main.py
```

## Current Menu Options

```text
ScoreForm

1. Assignment Management
2. Roster Management
3. Help
4. Exit
```

```text
Assignment Management

1. Create an assignment
2. Validate an assignment file
3. Generate answer sheets
4. Score scanned responses
5. Decode QR from a file
6. Return to main menu
```

## Requirements

The first version of the menu should mostly call existing functionality rather than reinvent it.

It should support:

* creating and validating assignments
* generating answer sheets
* selecting a scan/PDF to score
* decoding QR from a file
* creating, viewing, and validating rosters
* exiting cleanly

The direct CLI remains the stable primitive layer for scripting, testing, automation,
development, and power users. The interactive menu is the guided teacher-workflow
layer and does not need one-to-one parity with every command. Operations requiring
pre-existing file paths or advanced setup knowledge, including `setup-assignment`,
may remain CLI-only until a clear teacher-facing workflow emerges.

## Notes

This should happen after routed results are stable enough to support a practical teacher workflow.

## Suggested GitHub Issue

Create issue:

```text
Basic terminal menu interface
```

Suggested labels:

```text
feature
roadmap
ux
```

Suggested milestone:

```text
v0.3.0
```

---

# Phase 7: Installable Command / Launcher

## Status

Completed.

## Goal

Provide an editable install path and console script for the existing ScoreForm CLI.

## Current Behavior

ScoreForm now supports:

* editable installation with `python -m pip install -e .`
* a console script command: `scoreform`
* `scoreform` with no arguments launching the terminal menu
* `scoreform <subcommand>` mapping to existing workflows
* a `scoreform/cli.py` command entry point
* a `pyproject.toml` setuptools configuration
* a thin backward-compatible `main.py` wrapper for `python main.py <command>`

## Notes

* Use lowercase `scoreform` as the formal console command.
* On Windows, typing `ScoreForm` will likely also work because command lookup is usually case-insensitive.
* Existing `python main.py` workflows remain supported for backward compatibility.

## Later Possibility

Eventually consider a standalone Windows executable or shortcut using a packaging tool such as:

* PyInstaller
* Nuitka
* Briefcase

This is not needed yet.

## Suggested GitHub Issue

Create issue:

```text
Installable scoreform command
```

Suggested labels:

```text
feature
packaging
roadmap
```

Suggested milestone:

```text
v0.4.0
```

---

# Phase 8: Roster and Assignment Creation/Management

## Status

Completed for initial v0.5.0 scope.

Eventually, a teacher should be able to complete normal ScoreForm setup and management workflows from inside the application without hand-editing roster CSV files, assignment JSON files, or answer keys.

The menu should eventually help create, edit, validate, save, and manage these files.

## Roster Creation/Management

Status: Completed initial menu-driven roster creation (v0.5.0).

The terminal menu now includes a submenu for roster management with:

* Create a class roster (interactive prompts for class name, class_id, period, and students)
* View a class roster
* Validate a roster file
* Return to main menu

Roster creation workflow:

1. Launch with `scoreform` or `python main.py menu`
2. Select option 2 (Roster Management)
3. Select option 1 (Create a class roster)
4. Enter a class name
5. Accept or edit the suggested class_id
6. Enter period and student roster data
7. ScoreForm writes the roster to `classes/<class_id>/roster.csv`

Features:

* Prompts for required fields: student_id, last_name, first_name
* Parent directory creation if needed
* Overwrite protection (requires explicit confirmation)
* Validation after save using existing `load_roster()` logic
* Rejects rosters with fewer than one student
* Clean cancellation with Ctrl+C
* Blank `student_id` finishes student entry after at least one student has been added

## Assignment Creation/Management

Status: Completed initial menu-driven assignment creation (v0.5.0).

### Variable Question Count Support

Status: Completed support for `question_count` from 1 to 15.

The terminal menu now includes a submenu for assignment management with:

* Create an assignment
* Validate an assignment file
* Generate answer sheets
* Score scanned responses
* Decode QR from a file
* Return to main menu

Assignment creation workflow:

1. Launch with `scoreform` or `python main.py menu`
2. Select option 1 (Assignment Management)
3. Select option 1 (Create an assignment)
4. Select one or more existing classes
5. Enter an assignment title
6. Accept or edit the suggested assignment_id
7. Enter question count and answer key
8. ScoreForm writes assignment JSON to `classes/<class_id>/assignments/<assignment_id>/assignment.json`

Features:

* Uses the existing assignment schema
* Supports `question_count` from 1 to 15
* Uses fixed choices: A, B, C, D
* Re-prompts invalid answers until A, B, C, or D is entered
* Stores answer key values uppercase
* Parent directory creation if needed
* Overwrite protection requires explicit confirmation
* Validation after save using existing `load_assignment()` logic

## Potential Future Roster Features

* import students from a CSV
* list existing rosters
* view roster summary
* edit existing roster metadata
* add, remove, or update students in an existing roster

## Potential Assignment Features

* optionally attach standards metadata to questions
* list existing assignments
* view assignment summary
* edit existing assignment metadata
* update answer keys before materials are generated

## Notes

This phase should come after the basic menu exists, because it expands the menu from "command wrapper" into a real workflow assistant.

Standards tagging may begin as assignment metadata but is tracked separately because it also affects reporting and analytics.

## Suggested GitHub Issues

Create issues:

```text
Roster creation and management
Assignment creation and management
```

Suggested labels:

```text
feature
roadmap
ux
```

Suggested milestone:

```text
v0.5.0
```

---

# Phase 9: Variable Question Counts

## Status

Completed for single-page assignments with 1-15 questions.

## Goal

Move beyond fixed 10-question sheets.

## Initial Limit

Support **1-15 questions** on a single page.

## Assignment JSON Controls

```json
"question_count": 15
```

## Requirements

* Assignment validation allows 1-15 questions.
* Student PDFs draw only the required number of question rows.
* Class packet PDFs draw only the required number of question rows.
* QR-aware scoring scores only the assignment's configured question count.
* Legacy/manual scoring infers question count from a contiguous bare answer key when possible.
* CSV export creates columns only for the required number of questions.
* Validation checks answer keys against `question_count`.
* Extra answer key entries beyond `question_count` are rejected.

## Future-Proofing

Design functions so multi-page layouts can be added later without rewriting the whole scoring system.

## Related Cleanup Items

* Extract duplicated answer-key validation from `load_answer_key()` and `load_assignment()`.
* Consider adding more pytest coverage for routed CSV export with existing rows across mixed question-count histories.
* Consider introducing a shared maximum question count constant instead of repeating the limit across modules.

## Suggested GitHub Issue

Create issue:

```text
Variable question count support
```

Suggested labels:

```text
feature
roadmap
```

Suggested milestone:

```text
v0.6.0
```

---

# Phase 10: Question Standards Tagging

## Status

Completed for the assignment metadata foundation.

Menu-driven standards editing and standards performance reporting remain future work.

## Goal

Allow assignment questions to be tagged with one or more relevant standards so future reports can analyze performance by standard.

This is especially important for classroom assessment workflows where teachers may want to see:

* class performance by standard
* student performance by standard
* question performance by standard
* standards that need reteaching
* standards that individual students have not yet mastered

## Possible Assignment JSON Shape

```json
{
  "assignment_id": "rj_act1_quiz",
  "title": "Romeo and Juliet Act 1 Quiz",
  "question_count": 10,
  "choices": ["A", "B", "C", "D"],
  "answer_key": {
    "1": "A",
    "2": "C"
  },
  "standards": {
    "1": ["RL.CR.11-12.1"],
    "2": ["RL.CI.11-12.2", "RL.IT.11-12.3"]
  }
}
```

## Requirements

* Allow each question to have zero, one, or multiple standards.
* Standards should be optional so simple assignments remain easy to create.
* Assignment validation should verify standards metadata when present.
* Standards metadata should not break existing assignment files.
* Completed: newly menu-created assignments include an empty standards list for each question.
* Future reports should be able to group results by standard.
* Future menu workflows should support editing standards without manually editing JSON.

## Notes

This phase affects both assignment configuration and future reporting.

Implemented foundation: assignment data model, validation, load preservation, menu-created empty standards lists, and tests.

Future work remains: menu-driven standards editing and standards performance reporting.

## Suggested GitHub Issue

Create issue:

```text
Question standards tagging
```

Suggested labels:

```text
feature
reporting
roadmap
```

Suggested milestone:

```text
v0.6.0
```

---

# Phase 11: Optional Roster Enhancements

## Status

Completed for Phase 1 optional roster column preservation.

Menu-driven roster editing, roster import column mapping, roster summaries, and report field selection remain future work.

## Goal

Allow richer roster data without disrupting current validation.

## Possible Optional Columns

* `preferred_name`
* `email`
* `google_classroom_id`
* `accommodations`
* `notes`

## Requirements

* Required columns should remain:

  * `class_id`
  * `student_id`
  * `last_name`
  * `first_name`
  * `period`
* Optional columns should be preserved in student dictionaries if present.
* Optional columns should not be required for validation.
* Optional columns should not be automatically included in results CSVs.

## Implemented Phase 1

* Roster CSV files may include additional columns beyond the required schema.
* `load_roster()` preserves optional fields generically in loaded student dictionaries.
* Empty optional values are allowed.
* Required-column and required-field validation remain unchanged.
* Routed results continue to export only `last_name`, `first_name`, and `period` from roster data.

## Future Work

* Menu-driven roster editing.
* Add, remove, or update students.
* List existing rosters.
* View roster summaries.
* Import students from CSV with column mapping.
* Choose which optional fields should be included in reports.

## Suggested GitHub Issue

Create issue:

```text
Optional roster columns
```

Suggested labels:

```text
feature
roadmap
```

Suggested milestone:

```text
v0.6.0
```

---

# Phase 12: Test and CLI Robustness

## Goals

Make the program and regression tests more reliable across machines.

## Completed

* `run_tests.ps1` was updated to avoid relying on ignored/local-only test PDFs.
* `run_tests.ps1` now scores generated `template.pdf` so the test suite is portable across machines.
* `run_tests.ps1` includes a QR decode regression test.
* `run_tests.ps1` includes a QR-aware scoring metadata extraction test.
* `run_tests.ps1` includes mixed-scan regression coverage.
* `run_tests.ps1` includes routed-results regression coverage.
* `run_tests.ps1` includes roster lookup regression coverage for routed results.
* `score` exits nonzero when no pages are scored successfully.
* CSV export functions report success/failure to the CLI.
* Routed-results pytest coverage verifies preserved rows, append behavior, attempt numbering, makeup/separate scan append behavior, dynamic question columns through Q15, safe replace failure behavior, and header mismatch failure.
* Initial Python-native pytest suite added.
* Pytest suite covers QR payload parsing/validation, assignment validation, roster validation, assignment comparison helpers, and template filename helpers.
* Pytest suite covers CLI help/version behavior and menu help exit flow.
* `run_tests.ps1` now installs the package with development extras and runs pytest before the full workflow regression checks.
* Synthetic scoring accuracy fixture added for deterministic known-answer OMR detection.
* CLI failure-mode pytest coverage added for invalid commands, missing files, malformed/invalid assignment files, invalid roster files, and nonexistent score inputs.
* `run_tests.ps1` routes generic templates, manual/default results, explicit QR-aware result CSVs, and temporary fixtures under `local_outputs/`.
* `run_fast_tests.ps1` added for fast development checks: pytest, `git diff --check`, and generated/private artifact tracking checks without package installation or generated-file workflow checks.
* Phase 1 general cleanup pass completed for approved PowerShell helper names, score command help text, and confirmed unused imports.
* QR-aware batch scoring now reports summary information for failed pages.
* Menu workflow tests cover clear/pause behavior, scan inbox selection, QR-aware default menu scoring, manual menu scoring, and direct CLI scoring remaining picker-free.

## Future Test Improvements

* Add tests for malformed QR payloads.
* Add tests for missing QR codes.
* Add tests for menu workflows once the menu exists.
* Add QR reliability tests or manual checklist guidance for scan quality.
* Add real-world scan reliability tests or manual checklist guidance for phone/scanner capture quality.
* Add coverage for future scan archiving/storage if that workflow is implemented.
* Expand pytest coverage as the architecture stabilizes.

## Suggested GitHub Issues

Create issues:

```text
Add synthetic scoring accuracy fixture - completed
Improve CLI failure-mode tests - completed
```

Suggested labels:

```text
testing
cleanup
roadmap
```

Suggested milestone:

```text
v0.7.0
```

---

# Phase 13: General Code Cleanup

## Status

Phase 1 cleanup pass completed.

## Goals

Keep the codebase maintainable as features expand.

## Completed Phase 1 Cleanup

* Renamed PowerShell regression helpers from `Run-Test` to `Invoke-Test` and from `Run-TestExpectFailure` to `Invoke-TestExpectFailure`.
* Updated all `run_tests.ps1` helper call sites to use the approved-verb names.
* Clarified `score` command usage text for QR-aware routed scoring, QR-aware explicit-output scoring, legacy/manual default-output scoring, and legacy/manual explicit-output scoring.
* Removed confirmed unused `CORNERS` and `CORNER_SIZE` imports from `scoreform/scoring.py`.

## Cleanup Items

* Keep `scoreform/__init__.py` as a minimal package marker.
* Consider consolidating duplicated CSV-writing logic between `export_to_csv()` and `export_routed_results()`.
* Consider simplifying roster enrichment return behavior.
* Consider returning enriched result copies instead of mutating result dictionaries in place.
* Consider validating `student_id` in `export_routed_results()`.
* Consider replacing `os.path` with `pathlib` for cleaner path handling.
* Consider extracting shared validation helpers.
* Consider adding a proper CLI parser later, such as `argparse`, once the command set stabilizes.
* Consider moving QR dependencies/import checks into a cleaner helper to avoid redundant `qrcode` imports.
* Move shared PDF/image loading logic out of `main.py` and/or `process_file()` so `score` and `decode-qr` can reuse one helper.
* Organize generated local artifacts so project-root clutter is reduced. Generated templates, debug images, verification CSVs, manual-test PDFs, and scratch outputs should eventually be routed into predictable ignored folders rather than accumulating in the project root.
* Consider further QR decode reliability improvements if field scans still fail:

  * rotation/skew-specific preprocessing,
  * larger QR code,
  * higher QR error correction,
  * scanner guidance in the menu/help text.
* Later consider `pyproject.toml`, but `requirements.txt` is currently sufficient.
* Consider splitting interactive menu code into `scoreform/menu.py` if `scoreform/cli.py` grows too large.

## Additional Tracked Cleanup Items

* Decide whether `source_file` should store the user-supplied path, an absolute path, a project-relative path, or only the basename.
* Consider shared CSV schema/header helpers so `export_to_csv()` and `export_routed_results()` do not duplicate CSV-writing logic.
* Consider simplifying `_enrich_results_with_roster()` so it returns `None` or a warning count instead of returning `False` while export continues anyway.
* Consider returning enriched result copies instead of mutating result dictionaries in place.
* Consider extracting debug-output path construction/writing out of `score_image()`.
* Consider defining project-level path constants, such as `SCANS_INBOX_DIR = "scans_inbox"`.
* Consider making JSON comparison helpers distinguish unreadable or malformed JSON from valid JSON values such as `null`.
* Replace broad CSV text matching in `run_tests.ps1` with parsed CSV assertions later.
* Reduce hardcoded sample class/assignment paths in `run_tests.ps1` when moving toward a more isolated test framework.
* Consider moving inline temporary fixture generation in `run_tests.ps1` into reusable helpers or future pytest fixtures.
* Keep CLI help current as commands evolve.
* Consider separating interactive menu code from command-dispatch code if `scoreform/cli.py` grows too large.
* `python main.py ...` compatibility works, but usage text now emphasizes `scoreform ...`; acceptable for now, but revisit if user confusion appears.
* `main.py` is now a compatibility wrapper; future CLI work should happen in `scoreform/cli.py` or a split menu module.
* Fast development checks are separated into `run_fast_tests.ps1`; `run_tests.ps1` remains the full packaging/regression workflow for PRs, merges, releases, and broad workflow changes.
* Project root/home directory configuration remains future architecture work.
* Structured logging remains future work.
* Scan archiving/storage remains future work separate from the current `scans_inbox/` picker.

## Suggested GitHub Issue

Create issue:

```text
General cleanup backlog
```

Suggested labels:

```text
cleanup
roadmap
```

Suggested milestone:

```text
v0.7.0
```

---

# Phase 14: Repository Professionalization

## Goal

Keep the GitHub repository professional, safe, and easy to understand.

## Tasks

* Convert `development_plan.md` into a polished public `ROADMAP.md` - completed; `development_plan.md` remains the detailed working/planning document for now.
* Keep detailed tactical planning in local ignored notes.
* Add or update `CHANGELOG.md` - completed initial public changelog; keep it current as milestones change.
* Maintain GitHub Issues and Milestones.
* Maintain Kanban board columns:

  * `Backlog`
  * `Ready`
  * `In Progress`
  * `Testing`
  * `Done`
* Keep README current as features change.
* Keep examples synthetic.
* Keep `.gitignore` effective.
* Keep the repository root tidy by moving or routing local generated artifacts into ignored folders such as `local_outputs/`, `scratch/`, or assignment-specific folders. Initial `local_outputs/` routing is complete for generic templates, legacy/manual default results, manual debug images, and broad regression-test scratch files.
* Perform a post-public repository audit before recommending ScoreForm for broader classroom use or treating it as classroom-ready.
* `v0.8.0` documentation and version closeout is complete; package version is `0.8.0`.

## Suggested GitHub Issues

Create issues:

```text
Convert development_plan.md into ROADMAP.md
Add CHANGELOG.md
Pre-public repository audit
```

Suggested labels:

```text
documentation
privacy
roadmap
```

Suggested milestones:

```text
v0.2.0 or v0.7.0, depending on priority
```

Create issue:

```text
Organize generated local artifacts
```

Suggested labels:

```text
cleanup
ux
roadmap
```

Suggested milestone:

```text
v0.7.0
```

---

# Phase 15: Future Multi-Page Forms

## Goal

Eventually support assignments longer than 15 questions.

## Not for Initial Implementation

Delay this until the single-page variable-count version is stable.

## Future Direction

Assignment JSON might eventually include:

```json
"pages": [
  {
    "page": 1,
    "questions": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]
  },
  {
    "page": 2,
    "questions": [16, 17, 18, 19, 20, 21, 22, 23, 24, 25]
  }
]
```

## Important Design Principle

Do not hardcode assumptions that prevent multi-page forms later.

---

# Suggested Milestones From Here

## `v0.2.0` - Scan Workflow and Auditability

Suggested issues:

* Scan source tracking - completed
* Scan storage workflow - in progress (scan inbox created; storage behavior pending)
* Debug image routing - completed
* Duplicate and attempt handling - completed
* Overwrite and collision protection - completed

## `v0.3.0` - Teacher-Friendly Terminal Menu

Suggested issues:

* Basic terminal menu interface - completed

## `v0.4.0` - Installable Command

Suggested issues:

* Installable `scoreform` command - completed
* Move CLI entry point toward `scoreform/cli.py` - completed
* Add `pyproject.toml` - completed

## `v0.5.0` - Roster and Assignment Management

Suggested issues:

* Roster creation and management - completed
* Assignment creation and management - completed

## `v0.5.1` - Stabilization Before Flexible Forms

Suggested issues:

* Sanitize QR payload fields before building paths - completed
* Split CLI workflow helpers from command dispatch - completed

## `v0.6.0` - Flexible Form Configuration and Standards Metadata

Suggested issues:

* Add initial pytest test suite - completed
* Variable question count support - completed
* Question standards tagging foundation - completed
* Optional roster column preservation - completed

## `v0.7.0` - Robustness, Cleanup, and Public Readiness

Suggested issues:

* Add synthetic scoring accuracy fixture - completed
* Improve CLI failure-mode tests - completed
* General cleanup backlog
* Convert `development_plan.md` into `ROADMAP.md` - completed; `development_plan.md` preserved
* Add `CHANGELOG.md` - completed
* Pre-public repository audit

## `v0.8.0` - Menu Workflow Polish and Release Documentation

Suggested issues:

* Interactive menu clear/pause behavior - completed
* Read-only roster viewing - completed
* `scans_inbox/` picker for menu scoring - completed
* QR-aware routed scoring as recommended/default menu scoring - completed
* QR-aware batch summaries - completed
* Non-overwriting debug image filenames - completed
* Fast test script - completed
* Documentation and version closeout - completed

---

# Suggested Implementation Order From Here

1. Complete public-readiness audit and review passes.
2. Add menu workflow for assignment standards editing.
3. Add standards performance reporting.
4. Add broader roster management enhancements such as editing, summaries, imports, and report field selection.
5. Perform general cleanup and future architecture work:

   * consolidated CSV-writing helpers
   * roster enrichment cleanup
   * routed-result metadata validation
   * shared validation helpers
   * possible `pathlib` migration
   * cleaner QR import/dependency handling
   * shared PDF/image loading helper
   * possible further CLI/module split
   * QR preprocessing/reliability improvements if needed
   * project root/home directory configuration
   * structured logging
   * future scan archiving/storage beyond the current `scans_inbox/` picker
   * Organize generated local artifacts into ignored folders or assignment-specific folders to reduce project-root clutter.
6. Continue repository professionalization:

    * keep ROADMAP.md current
    * keep CHANGELOG.md current
    * complete public-readiness audit
7. Later: support multi-page forms.
