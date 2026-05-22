Here’s an updated version you can paste over the current development plan. I removed completed QR generation work, added the portable test-script improvement, noted `requirements.txt`, and added the missing-file score exit-code issue we discovered on the MSI. 

````markdown
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

## Phase 1: QR Decoding

### Goal

Read the QR code from scanned pages.

### Preferred Tool

Try OpenCV QR detection first:

```python
cv2.QRCodeDetector()
```

Avoid adding extra dependencies unless OpenCV QR detection is unreliable.

### Requirements

For each scanned page:

* Detect registration marks as currently implemented.
* Detect and decode QR code.
* Extract:

  * `class_id`
  * `assignment_id`
  * `student_id`
* Validate QR payload format.
* Print a clear error if QR is missing, unreadable, or malformed.

### Notes

* This phase should decode QR data only.
* Do not route results yet.
* Do not change CSV output yet.
* Keep legacy score behavior working.

### Test Plan

* Generate PDFs with QR codes.
* Print one personalized sheet.
* Scan it.
* Confirm QR payload can be decoded from the scan.
* Confirm legacy scoring still works.

---

## Phase 2: QR-Based Scoring Metadata Extraction

### Goal

Attach student/class/assignment metadata to scored pages.

### Expected Behavior

For each page:

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

### Notes

* This phase may still write to legacy `results.csv`.
* Full assignment-folder routing should happen in the next phase.
* Keep legacy manual scoring available if needed.

---

## Phase 3: QR-Based Mixed Scan Scoring

### Goal

Allow mixed scans.

### Preferred Command

```powershell
python main.py score mixed_scan.pdf
```

### Expected Behavior

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

### Notes

This phase should make mixed scans functionally possible, even if result routing is still basic.

---

## Phase 4: Result Routing

### Goal

Store results in the correct class/assignment folder.

### Target Output

```text
classes/
  english9_p2/
    assignments/
      rj_act1_quiz/
        results.csv
```

### Result Row Should Include

```csv
class_id,assignment_id,student_id,last_name,first_name,period,score,total,Q1,Q1_Correct,Q2,Q2_Correct
```

### Requirements

* Results should route to the assignment folder identified by the QR code.
* Top-level `results.csv` may remain for legacy/manual scoring mode.
* Routed results should include source scan filename when possible.
* Routed results should include enough information to match rows back to the roster.

### Future Cleanup

* Make `export_to_csv()` question-count-aware instead of hardcoding Q1–Q10.
* Eventually separate legacy CSV export from routed assignment CSV export if the formats diverge.

---

## Phase 5: Scan Storage

### Goal

Keep scan files organized.

### Possible Structure

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

### Decision Needed Later

Decide whether to:

* move scans from inbox,
* copy scans into assignment folders,
* or leave scans in inbox and record source filename in results.

Initial preference:

* Keep original scans in `scans_inbox/`.
* Record source filename in `results.csv`.
* Optionally copy scans later if needed.

### Debug Image Routing

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

## Phase 6: Duplicate and Attempt Handling

### Goal

Handle rescans, makeups, late work, and accidental duplicate scans.

### Unique Key

```text
class_id + assignment_id + student_id
```

### Policy Options

1. Overwrite old result.
2. Keep both attempts.
3. Keep both attempts but mark latest.
4. Flag duplicates for review.

### Initial Recommendation

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

## Phase 7: Overwrite and Collision Protection

### Goal

Prevent accidental data loss when regenerating assignments or reusing assignment IDs.

### Current Risk

`setup_assignment_folder()` currently copies files into existing folders. This is useful during development, but before real classroom use, the program should protect against accidental overwrite.

### Requirements

If this folder already exists:

```text
classes/<class_id>/assignments/<assignment_id>/
```

the program should check whether the existing `assignment.json` differs from the incoming assignment file.

### Possible Behavior

* If the existing assignment matches, allow regeneration.
* If the existing assignment differs, refuse and print a warning.
* Later, allow explicit overwrite with a flag such as:

```powershell
python main.py generate assignment.json --rosters roster.csv --overwrite
```

### Notes

This is especially important if two different assignments accidentally use the same `assignment_id`.

---

## Phase 8: Variable Question Counts

### Goal

Move beyond fixed 10-question sheets.

### Initial Limit

Support **1–15 questions** on a single page.

### Assignment JSON Controls

```json
"question_count": 15
```

### Current Temporary Restriction

For now, assignment validation intentionally requires:

```json
"question_count": 10
```

This prevents a 15-question assignment from validating before template generation, scoring, and CSV export support variable question counts.

### Requirements

* Assignment validation should allow 1–15 questions.
* Template generation should draw only the required number of question rows.
* Student PDFs should draw only the required number of question rows.
* Class packet PDFs should draw only the required number of question rows.
* Scoring should score only the required number of questions.
* CSV export should create columns only for the required number of questions.
* Validation should check answer key against `question_count`.

### Future-Proofing

Design functions so multi-page layouts can be added later without rewriting the whole scoring system.

### Related Cleanup Items

* Make `score_image()` question-count-aware instead of hardcoding 10.
* Make template generation question-count-aware instead of hardcoding 10.
* Make `export_to_csv()` question-count-aware instead of hardcoding Q1–Q10.
* Extract duplicated answer-key validation from `load_answer_key()` and `load_assignment()`.

---

## Phase 9: Optional Roster Enhancements

### Goal

Allow richer roster data without disrupting current validation.

### Possible Optional Columns

* `preferred_name`
* `email`
* `google_classroom_id`
* `accommodations`
* `notes`

### Requirements

* Required columns should remain:

  * `class_id`
  * `student_id`
  * `last_name`
  * `first_name`
  * `period`
* Optional columns should be preserved in student dictionaries if present.
* Optional columns should not be required for validation.

---

## Phase 10: Test and CLI Robustness

### Goals

Make the program and regression tests more reliable across machines.

### Completed

* `run_tests.ps1` was updated to avoid relying on ignored/local-only test PDFs.
* `run_tests.ps1` now scores generated `template.pdf` so the test suite is portable across machines.

### Needed Fix

The `score` command currently prints an error when the input file is missing, but may still exit with status code `0`.

### Requirement

If a requested score file is missing or no pages are scored, the program should exit with status code `1`.

Example:

```powershell
python main.py score missing_file.pdf
```

should fail with a nonzero exit code.

### Notes

This is important because `run_tests.ps1` depends on process exit codes to determine whether a command passed or failed.

---

## Phase 11: General Code Cleanup

### Goals

Keep the codebase maintainable as features expand.

### Cleanup Items

* Keep `scoreform/__init__.py` as a minimal package marker.
* Remove unused imports where present:

  * `CORNERS` / `CORNER_SIZE` in `scoring.py`
  * `os` and `PDF_WIDTH` in `templates.py`
* Consider replacing `os.path` with `pathlib` for cleaner path handling.
* Consider extracting shared validation helpers.
* Consider adding a proper CLI parser later, such as `argparse`, once the command set stabilizes.
* Consider moving QR dependencies/import checks into a cleaner helper to avoid redundant `qrcode` imports.
* Later consider `pyproject.toml`, but `requirements.txt` is currently sufficient.

---

## Phase 12: Future Multi-Page Forms

### Goal

Eventually support assignments longer than 15 questions.

### Not for Initial Implementation

Delay this until the single-page variable-count version is stable.

### Future Direction

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

### Important Design Principle

Do not hardcode assumptions that prevent multi-page forms later.

---

## Suggested Implementation Order From Here

1. Add QR decoding during scoring.
2. Add QR-based scoring metadata extraction.
3. Support mixed-scan scoring.
4. Route results into the correct class/assignment folder.
5. Add scan source tracking.
6. Add duplicate/attempt handling.
7. Add overwrite/collision protection.
8. Add variable question count support up to 15.
9. Add optional roster column preservation.
10. Fix score command exit status for missing/unscored files.
11. Perform general cleanup:

    * unused imports
    * shared validation helpers
    * possible `pathlib` migration
    * cleaner QR import/dependency handling
12. Later: support multi-page forms.