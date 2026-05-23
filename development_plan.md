# OMR Program Iterative Development Plan

## Completed

The project currently supports:

- Modular `scoreform/` package structure
- Root-level `main.py` as CLI entry point
- Minimal `scoreform/__init__.py`
- `requirements.txt` for Python package dependencies
- Portable PowerShell regression test script: `run_tests.ps1`
- Printable generic `template.pdf`
- Debug `template.png`
- Image scoring
- Scanned PDF scoring
- Multi-page PDF batch scoring
- Corner registration detection
- Blank detection
- Ambiguous/double-mark detection
- Legacy top-level CSV export
- External bare `answer_key.json` validation
- Assignment JSON validation through `validate-assignment`
- Roster CSV validation through `validate-roster`
- Class/assignment folder setup through `setup-assignment`
- Multi-roster `generate` command
- Individual personalized student PDFs
- Class packet PDF generation
- QR code generation on individual student PDFs
- QR code generation on class packet pages
- QR payload parsing
- QR decoding from generated PDFs/images through `decode-qr`
- QR decoding from a printed-and-scanned student sheet when scan quality is adequate
- Legacy scoring of a printed, filled, phone-scanned student sheet with QR code present

Current generated folder structure:

```text
classes/
  english9_p2/
    roster.csv
    assignments/
      rj_act1_quiz/
        assignment.json
        templates/
          class_packet.pdf
          individual/
            1001_doe_jane.pdf
            1002_smith_marcus.pdf
            1003_brown_alyssa.pdf
        scans/
        debug/
````

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

# Phase 1: QR-Based Scoring Metadata Extraction

## Goal

Attach student/class/assignment metadata to scored pages.

## Expected Behavior

For each scanned page:

* Detect registration marks.
* Detect and decode QR code.
* Extract:

  * `class_id`
  * `assignment_id`
  * `student_id`
* Locate the matching class/assignment structure.
* Load the assignment’s `assignment.json`.
* Score using that assignment’s answer key.
* Include QR-derived metadata in returned result data.

## Notes

* This phase may still write to legacy top-level `results.csv`.
* Full assignment-folder routing should happen in the next phase.
* Keep legacy/manual scoring available if needed.
* `decode-qr` should remain available as a diagnostic command.

## Design Consideration

The existing `score` command currently uses a user-supplied answer key. QR-based scoring will need to choose an answer key automatically by using the QR payload to locate:

```text
classes/<class_id>/assignments/<assignment_id>/assignment.json
```

---

# Phase 2: QR-Based Mixed Scan Scoring

## Goal

Allow mixed scans.

## Preferred Command

```powershell
python main.py score mixed_scan.pdf
```

## Expected Behavior

A single scanned PDF may contain pages from:

* different students
* different classes
* different assignments

For each page, the program should:

* decode the QR payload,
* identify the correct assignment,
* load the correct answer key,
* score the page,
* preserve the associated metadata.

## Notes

This phase should make mixed scans functionally possible, even if result routing is still basic.

## Possible Compatibility Approach

Keep both scoring modes:

```powershell
python main.py score scanned_file.pdf
```

QR-aware scoring when QR codes are present.

```powershell
python main.py score scanned_file.pdf results.csv answer_key.json
```

Legacy/manual scoring when an answer key is explicitly provided.

---

# Phase 3: Result Routing

## Goal

Store results in the correct class/assignment folder.

## Target Output

```text
classes/
  english9_p2/
    assignments/
      rj_act1_quiz/
        results.csv
```

## Result Row Should Include

```csv
class_id,assignment_id,student_id,last_name,first_name,period,score,total,Q1,Q1_Correct,Q2,Q2_Correct
```

## Requirements

* Results should route to the assignment folder identified by the QR code.
* Top-level `results.csv` may remain for legacy/manual scoring mode.
* Routed results should include source scan filename when possible.
* Routed results should include enough information to match rows back to the roster.

## Future Cleanup

* Make `export_to_csv()` question-count-aware instead of hardcoding Q1–Q10.
* Eventually separate legacy CSV export from routed assignment CSV export if the formats diverge.

---

# Phase 4: Basic Terminal Menu Interface

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

This should happen after result routing because the core teacher workflow will be clearer once scanned results land in the right assignment folders.

---

# Phase 5: Installable Command / Launcher

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

---

# Phase 6: Roster and Assignment Creation/Management

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

---

# Phase 7: Scan Storage

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

## Decision Needed Later

Decide whether to:

* move scans from inbox,
* copy scans into assignment folders,
* or leave scans in inbox and record source filename in results.

Initial preference:

* Keep original scans in `scans_inbox/`.
* Record source filename in `results.csv`.
* Optionally copy scans later if needed.

## Debug Image Routing

Currently, debug images are saved to the project root:

```text
debug_corners_page_1.png
debug_warped_page_1.png
```

Future behavior should route debug images to:

```text
classes/
  english9_p2/
    assignments/
      rj_act1_quiz/
        debug/
```

---

# Phase 8: Duplicate and Attempt Handling

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

---

# Phase 9: Overwrite and Collision Protection

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

---

# Phase 10: Variable Question Counts

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

---

# Phase 11: Optional Roster Enhancements

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

---

# Phase 12: Test and CLI Robustness

## Goals

Make the program and regression tests more reliable across machines.

## Completed

* `run_tests.ps1` was updated to avoid relying on ignored/local-only test PDFs.
* `run_tests.ps1` now scores generated `template.pdf` so the test suite is portable across machines.
* `run_tests.ps1` includes a QR decode regression test.

## Needed Fix

The `score` command currently prints an error when the input file is missing, but may still exit with status code `0`.

## Requirement

If a requested score file is missing or no pages are scored, the program should exit with status code `1`.

Example:

```powershell
python main.py score missing_file.pdf
```

should fail with a nonzero exit code.

## Notes

This is important because `run_tests.ps1` depends on process exit codes to determine whether a command passed or failed.

## Future Test Improvements

* Add a proper scoring-accuracy fixture or programmatically generated filled answer sheet.
* Add tests for malformed QR payloads.
* Add tests for missing QR codes.
* Add tests for missing input files once score exit codes are corrected.
* Add tests for menu workflows once the menu exists.
* Add QR reliability tests or manual checklist guidance for scan quality.

---

# Phase 13: General Code Cleanup

## Goals

Keep the codebase maintainable as features expand.

## Cleanup Items

* Keep `scoreform/__init__.py` as a minimal package marker.
* Remove unused imports where present:

  * `CORNERS` / `CORNER_SIZE` in `scoring.py`
  * `os` and `PDF_WIDTH` in `templates.py`
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

# Suggested Implementation Order From Here

1. Add QR-based scoring metadata extraction.
2. Support mixed-scan scoring.
3. Route results into the correct class/assignment folder.
4. Add a basic terminal menu interface.
5. Add installable command / launcher support with `scoreform`.
6. Add roster and assignment creation/management through the menu.
7. Add scan source tracking and scan storage behavior.
8. Add duplicate/attempt handling.
9. Add overwrite/collision protection.
10. Add variable question count support up to 15.
11. Add optional roster column preservation.
12. Fix score command exit status for missing/unscored files.
13. Perform general cleanup:

    * unused imports
    * shared validation helpers
    * possible `pathlib` migration
    * cleaner QR import/dependency handling
    * shared PDF/image loading helper
    * possible `scoreform/cli.py`
    * QR preprocessing/reliability improvements if needed
14. Later: support multi-page forms.