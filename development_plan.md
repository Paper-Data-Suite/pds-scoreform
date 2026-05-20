# OMR Program Iterative Development Plan

## Current Status

Working MVP includes:

- Printable `template.pdf`
- Image scoring
- Scanned PDF scoring
- Multi-page PDF batch scoring
- Corner registration detection
- Blank detection
- Ambiguous/double-mark detection
- CSV export
- External assignment/answer key JSON validation

---

## Phase 1: Redesign Data Model

### Goal

Prepare the program for class-based folders, rosters, assignments, QR codes, and variable question counts.

### Decisions

- Use CSV for rosters.
- Use JSON for assignments.
- Keep duplicate assignment folders under each class.
- Use one QR code per student sheet.
- QR code should include:
  - `class_id`
  - `assignment_id`
  - `student_id`

### Roster CSV Format

```csv
class_id,student_id,last_name,first_name,period
english9_p2,1001,Doe,Jane,2
english9_p2,1002,Smith,Marcus,2
````

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

### QR Payload Format

```text
OMR1|class=english9_p2|aid=rj_act1_quiz|sid=1001
```

---

## Phase 2: Assignment Folder Structure

### Goal

Generate organized folders for each class and assignment.

### Target Structure

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
        scans/
        debug/
        results.csv

  english9_p4/
    roster.csv
    assignments/
      rj_act1_quiz/
        assignment.json
        templates/
        scans/
        debug/
        results.csv
```

### Notes

* Each class gets its own copy of the assignment folder.
* Each assignment folder stores its own results.
* Scans can be stored later in the relevant `scans/` folder.

---

## Phase 3: Multi-Roster Generate Command

### Goal

Allow one command to generate sheets for multiple classes.

### Preferred Command

```powershell
python main.py generate assignment.json --rosters english9_p2.csv english9_p4.csv english9_p6.csv
```

### Expected Behavior

For each roster:

* Read `class_id` from the roster.
* Create class folder if needed.
* Create assignment folder under that class.
* Copy/save `assignment.json`.
* Copy/save roster into the class folder.
* Generate individual student PDFs.
* Generate one class packet PDF.

---

## Phase 4: QR Code Generation

### Goal

Add one QR code to each student sheet.

### Requirements

* QR code must encode:

  * `class_id`
  * `assignment_id`
  * `student_id`
* Student name and assignment title should still be printed as human-readable text.
* QR code should be placed away from answer boxes and registration marks.
* QR payload should be compact and deterministic.

### Likely Dependency

```powershell
python -m pip install qrcode[pil]
```

---

## Phase 5: Variable Question Counts

### Goal

Move beyond fixed 10-question sheets.

### Initial Limit

Support **1–15 questions** on a single page.

### Assignment JSON Controls

```json
"question_count": 15
```

### Requirements

* Generator draws only the required number of question rows.
* Scorer scores only the required number of questions.
* CSV export creates columns only for the required number of questions.
* Validation checks answer key against `question_count`.

### Future-Proofing

Design functions so multi-page layouts can be added later without rewriting the whole scoring system.

---

## Phase 6: QR-Based Scoring

### Goal

Allow mixed scans.

### Preferred Command

```powershell
python main.py score mixed_scan.pdf
```

### Expected Behavior

For each page:

* Detect registration marks.
* Detect and decode QR code.
* Extract:

  * `class_id`
  * `assignment_id`
  * `student_id`
* Locate the correct assignment folder.
* Load that assignment’s `assignment.json`.
* Score using that assignment’s answer key.
* Append or update the correct `results.csv`.

### Likely Dependency

Use OpenCV QR detection first:

```python
cv2.QRCodeDetector()
```

Avoid adding extra dependencies unless OpenCV QR detection is unreliable.

---

## Phase 7: Scan Storage

### Goal

Keep scan files organized.

### Behavior

When scoring a scan, optionally copy the scanned PDF into the appropriate folder.

For mixed scans, store the original scan in a general intake folder or duplicate it into each affected assignment folder.

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

---

## Phase 8: Duplicate Handling

### Goal

Handle rescans, makeups, and late work.

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

Then decide later whether the gradebook export should use latest, highest, or manually selected.

---

## Phase 9: Future Multi-Page Forms

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

## Suggested Implementation Order

1. Refactor assignment JSON to include metadata and answer key.
2. Add roster CSV loading.
3. Add class/assignment folder creation.
4. Update `generate` command to accept multiple rosters.
5. Generate class packets and individual PDFs.
6. Add QR code generation to templates.
7. Add variable question count support up to 15.
8. Add QR decoding during scoring.
9. Route results into the correct class/assignment folder.
10. Add duplicate/attempt handling.
11. Add scan storage behavior.
12. Later: support multi-page forms.