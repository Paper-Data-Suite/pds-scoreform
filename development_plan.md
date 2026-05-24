# OMR Program Iterative Development Plan

## Completed

The project currently supports:

* Modular `scoreform/` package structure
* Root-level `main.py` as CLI entry point
* Minimal `scoreform/__init__.py`
* `requirements.txt` for Python package dependencies
* Portable PowerShell regression test script: `run_tests.ps1`
* Printable generic `template.pdf`
* Debug `template.png`
* Image scoring
* Scanned PDF scoring
* Multi-page PDF batch scoring
* Corner registration detection
* Blank detection
* Ambiguous/double-mark detection
* Legacy top-level CSV export
* External bare `answer_key.json` validation
* Assignment JSON validation through `validate-assignment`
* Roster CSV validation through `validate-roster`
* Class/assignment folder setup through `setup-assignment`
* Multi-roster `generate` command
* Individual personalized student PDFs
* Class packet PDF generation
* QR code generation on individual student PDFs
* QR code generation on class packet pages
* QR payload parsing
* QR decoding from generated PDFs/images through `decode-qr`
* QR decoding from a printed-and-scanned student sheet when scan quality is adequate
* Legacy scoring of a printed, filled, phone-scanned student sheet with QR code present
* QR-aware scoring metadata extraction
* Automatic assignment lookup from QR metadata during scoring
* QR-aware score output with `class_id`, `assignment_id`, and `student_id`
* Legacy/manual scoring preserved when an explicit answer key is provided
* `score` command exits nonzero when no pages are scored successfully
* QR-based mixed-scan scoring for multi-page PDFs
* QR-aware class packet scoring with one row per student page
* Result routing to assignment folders for QR-aware scoring
* Routed result CSV output at `classes/<class_id>/assignments/<assignment_id>/results.csv`
* Routed CSV output containing page, class, assignment, student, roster, score, total, and answer columns
* Roster lookup for routed results using `classes/<class_id>/roster.csv`
* Routed result rows enriched with `last_name`, `first_name`, and `period`
* CSV export functions return success/failure status
* Regression coverage for QR decoding, QR-aware scoring, mixed-scan scoring, routed results, and roster-enriched routed results

## Completed Milestone

### `v0.1.0` — QR-Aware Scoring With Routed Results

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
```

---

## Current Data Model

### Roster CSV Format

```csv
class_id,student_id,last_name,first_name,period
english9_p2,1001,Doe,Jane,2
english9_p2,1002,Smith,Marcus,2
```

### Assignment JSON Format

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
  }
}
```

### Current QR Payload Format

```text
OMR1|class=english9_p2|aid=rj_act1_quiz|sid=1001
```

### Current Routed Results CSV Format

```csv
Page,class_id,assignment_id,student_id,last_name,first_name,period,Score,Total,Q1,Q1_Correct,Q2,Q2_Correct,...
```

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

Then scores each page using that assignment’s answer key and routes results to:

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

Uses the explicitly supplied answer key and writes to the default `results.csv`.

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

Caveat:

* A poor-quality phone scan failed QR detection.
* QR reliability may depend on scan quality, camera quality, lighting, document alignment, and scanner app behavior.
* Future improvements may include larger QR codes, higher QR error correction, preprocessing/cropping before QR detection, or clearer scan-quality guidance for users.

---

# Phase 1: Scan Source Tracking

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

## Goal

Keep scan files organized.

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

## Decision Needed

Decide whether to:

* move scans from inbox,
* copy scans into assignment folders,
* or leave scans in inbox and record source filename in results.

Initial preference:

* Keep original scans in `scans_inbox/`.
* Record source filename in `results.csv`.
* Optionally copy scans later if needed.

## Requirements

* Create or recognize a `scans_inbox/` workflow.
* Keep original scan files organized and separate from generated answer sheets.
* Avoid accidental deletion of scans.
* Preserve enough source information in result rows to connect scores back to original scans.

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

## Goal

Move debug image output out of the project root and into assignment-specific debug folders when possible.

## Current Behavior

Debug images are saved to the project root:

```text
debug_corners_page_1.png
debug_warped_page_1.png
```

## Target Behavior

For QR-aware routed scoring, debug images should route to:

```text
classes/
  english9_p2/
    assignments/
      rj_act1_quiz/
        debug/
```

## Requirements

* Keep root-level debug output available for legacy/manual scoring if needed.
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

## Goal

Prevent accidental data loss when regenerating assignments or reusing assignment IDs.

## Current Risk

`setup_assignment_folder()` currently copies files into existing folders. This is useful during development, but before real classroom use, the program should protect against accidental overwrite.

## Requirements

If this folder already exists:

```text
classes/<class_id>/assignments/<assignment_id>/
```

the program should check whether the existing `assignment.json` differs from the incoming assignment file.

## Possible Behavior

* If the existing assignment matches, allow regeneration.
* If the existing assignment differs, refuse and print a warning.
* Later, allow explicit overwrite with a flag such as:

```powershell
python main.py generate assignment.json --rosters roster.csv --overwrite
```

## Notes

This is especially important if two different assignments accidentally use the same `assignment_id`.

This also matters more once the menu makes regeneration easier.

## Suggested GitHub Issue

Create issue:

```text
Overwrite and collision protection
```

Suggested labels:

```text
feature
safety
roadmap
```

Suggested milestone:

```text
v0.2.0
```

---

# Phase 6: Basic Terminal Menu Interface

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

## Initial Menu Options

```text
ScoreForm

1. Generate answer sheets
2. Score scanned responses
3. Decode QR from a file
4. Validate an assignment file
5. Validate a roster file
6. Set up assignment folders
7. Exit
```

## Requirements

The first version of the menu should mostly call existing functionality rather than reinvent it.

It should support:

* selecting an assignment JSON
* selecting one or more roster CSV files
* generating answer sheets
* selecting a scan/PDF to score
* decoding QR from a file
* validating assignment files
* validating roster files
* exiting cleanly

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

## Goal

Allow ScoreForm to launch from anywhere in PowerShell by typing:

```powershell
scoreform
```

or:

```powershell
ScoreForm
```

## Preferred Long-Term Approach

Use Python packaging with a console script entry point.

Likely future structure:

```text
scoreform/
  __init__.py
  cli.py
  config.py
  templates.py
  scoring.py
  assignment.py
  roster.py
  folders.py
  results.py
```

A future `pyproject.toml` could define:

```toml
[project.scripts]
scoreform = "scoreform.cli:main"
```

Then local editable installation would be:

```powershell
python -m pip install -e .
```

After that, the program could be launched from anywhere with:

```powershell
scoreform
```

## Notes

* Use lowercase `scoreform` as the formal console command.
* On Windows, typing `ScoreForm` will likely also work because command lookup is usually case-insensitive.
* This should happen after the basic menu exists, because the installed command should launch the menu by default.

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

## Goal

Reduce or eliminate manual editing of CSV and JSON files.

Currently, the user must manually create/edit:

* roster CSV files
* assignment JSON files
* answer keys

The menu should eventually help create and manage these.

## Roster Management

Possible menu features:

* create a new roster
* enter `class_id`
* enter period
* add students one by one
* import students from a CSV
* validate roster
* save roster CSV
* list existing rosters
* view roster summary

## Assignment Management

Possible menu features:

* create a new assignment
* enter `assignment_id`
* enter assignment title
* enter question count
* enter answer key
* validate assignment
* save assignment JSON
* list existing assignments
* view assignment summary

## Notes

This phase should come after the basic menu exists, because it expands the menu from “command wrapper” into a real workflow assistant.

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

## Goal

Move beyond fixed 10-question sheets.

## Initial Limit

Support **1–15 questions** on a single page.

## Assignment JSON Controls

```json
"question_count": 15
```

## Current Temporary Restriction

For now, assignment validation intentionally requires:

```json
"question_count": 10
```

This prevents a 15-question assignment from validating before template generation, scoring, and CSV export support variable question counts.

## Requirements

* Assignment validation should allow 1–15 questions.
* Template generation should draw only the required number of question rows.
* Student PDFs should draw only the required number of question rows.
* Class packet PDFs should draw only the required number of question rows.
* Scoring should score only the required number of questions.
* CSV export should create columns only for the required number of questions.
* Validation should check answer key against `question_count`.

## Future-Proofing

Design functions so multi-page layouts can be added later without rewriting the whole scoring system.

## Related Cleanup Items

* Make `score_image()` question-count-aware instead of hardcoding 10.
* Make template generation question-count-aware instead of hardcoding 10.
* Make `export_to_csv()` question-count-aware instead of hardcoding Q1–Q10.
* Extract duplicated answer-key validation from `load_answer_key()` and `load_assignment()`.

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

# Phase 10: Optional Roster Enhancements

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

# Phase 11: Test and CLI Robustness

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

## Future Test Improvements

* Add a proper scoring-accuracy fixture or programmatically generated filled answer sheet.
* Add tests for malformed QR payloads.
* Add tests for missing QR codes.
* Add tests for missing input files.
* Add tests for menu workflows once the menu exists.
* Add QR reliability tests or manual checklist guidance for scan quality.
* Consider a future `pytest` test suite once the architecture stabilizes.

## Suggested GitHub Issues

Create issues:

```text
Add synthetic scoring accuracy fixture
Improve CLI failure-mode tests
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

# Phase 12: General Code Cleanup

## Goals

Keep the codebase maintainable as features expand.

## Cleanup Items

* Keep `scoreform/__init__.py` as a minimal package marker.
* Remove unused imports where present:

  * `CORNERS` / `CORNER_SIZE` in `scoring.py`
  * `os` and `PDF_WIDTH` in `templates.py`
* Clarify `score` command help text for QR-aware vs. legacy/manual scoring modes.
* Rename PowerShell helper `Run-Test` to `Invoke-Test` if we want to satisfy approved-verb linting.
* Consider consolidating duplicated CSV-writing logic between `export_to_csv()` and `export_routed_results()`.
* Consider simplifying roster enrichment return behavior.
* Consider returning enriched result copies instead of mutating result dictionaries in place.
* Consider validating `student_id` in `export_routed_results()`.
* Consider replacing `os.path` with `pathlib` for cleaner path handling.
* Consider extracting shared validation helpers.
* Consider adding a proper CLI parser later, such as `argparse`, once the command set stabilizes.
* Consider moving QR dependencies/import checks into a cleaner helper to avoid redundant `qrcode` imports.
* Move shared PDF/image loading logic out of `main.py` and/or `process_file()` so `score` and `decode-qr` can reuse one helper.
* Consider QR decode preprocessing if scan reliability becomes a problem:

  * crop around expected QR region,
  * threshold/contrast adjustment,
  * larger QR code,
  * higher QR error correction,
  * scanner guidance in the menu/help text.
* Later consider `pyproject.toml`, but `requirements.txt` is currently sufficient.
* Eventually move CLI/menu entry point into `scoreform/cli.py`.

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

# Phase 13: Repository Professionalization

## Goal

Keep the GitHub repository professional, safe, and easy to understand.

## Tasks

* Convert `development_plan.md` into a polished public `ROADMAP.md`.
* Keep detailed tactical planning in local ignored notes.
* Add or update `CHANGELOG.md`.
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
* Before public release, audit for accidental real/private/student data.

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

---

# Phase 14: Future Multi-Page Forms

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

## `v0.2.0` — Scan Workflow and Auditability

Suggested issues:

* Scan source tracking
* Scan storage workflow
* Debug image routing
* Duplicate and attempt handling
* Overwrite and collision protection

## `v0.3.0` — Teacher-Friendly Terminal Menu

Suggested issues:

* Basic terminal menu interface

## `v0.4.0` — Installable Command

Suggested issues:

* Installable `scoreform` command
* Move CLI entry point toward `scoreform/cli.py`
* Add `pyproject.toml`

## `v0.5.0` — Roster and Assignment Management

Suggested issues:

* Roster creation and management
* Assignment creation and management

## `v0.6.0` — Flexible Form Configuration

Suggested issues:

* Variable question count support
* Optional roster columns

## `v0.7.0` — Robustness, Cleanup, and Public Readiness

Suggested issues:

* Add synthetic scoring accuracy fixture
* Improve CLI failure-mode tests
* General cleanup backlog
* Convert `development_plan.md` into `ROADMAP.md`
* Add `CHANGELOG.md`
* Pre-public repository audit

---

# Suggested Implementation Order From Here

1. Add scan source tracking.
2. Add scan storage behavior.
3. Route debug images into assignment-specific debug folders.
4. Add duplicate/attempt handling.
5. Add overwrite/collision protection.
6. Add a basic terminal menu interface.
7. Add installable command / launcher support with `scoreform`.
8. Add roster and assignment creation/management through the menu.
9. Add variable question count support up to 15.
10. Add optional roster column preservation.
11. Perform test and CLI robustness improvements.
12. Perform general cleanup:

    * unused imports
    * clarified score help text
    * PowerShell approved-verb cleanup
    * consolidated CSV-writing helpers
    * roster enrichment cleanup
    * routed-result metadata validation
    * shared validation helpers
    * possible `pathlib` migration
    * cleaner QR import/dependency handling
    * shared PDF/image loading helper
    * possible `scoreform/cli.py`
    * QR preprocessing/reliability improvements if needed
13. Perform repository professionalization:

    * ROADMAP.md
    * CHANGELOG.md
    * public-readiness audit
14. Later: support multi-page forms.