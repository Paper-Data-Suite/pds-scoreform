# OMR Program Iterative Development Plan

## Completed

The project currently supports:

- Printable generic `template.pdf`
- Debug `template.png`
- Image scoring
- Scanned PDF scoring
- Multi-page PDF batch scoring
- Corner registration detection
- Blank detection
- Ambiguous/double-mark detection
- CSV export
- External bare `answer_key.json` validation
- Assignment JSON validation through `validate-assignment`
- Roster CSV validation through `validate-roster`
- Class/assignment folder setup through `setup-assignment`

Current generated folder structure:

```text
classes/
  english9_p2/
    roster.csv
    assignments/
      rj_act1_quiz/
        assignment.json
        templates/
          individual/
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

### Future QR Payload Format

```text
OMR1|class=english9_p2|aid=rj_act1_quiz|sid=1001
```

---

## Phase 1: Multi-Roster Generate Command

### Goal

Allow one command to set up and generate materials for multiple classes.

### Preferred Command

```powershell
python main.py generate assignment.json --rosters english9_p2.csv english9_p4.csv english9_p6.csv
```

### Expected Behavior

For each roster:

* Load and validate the assignment JSON.
* Load and validate the roster CSV.
* Create the class folder if needed.
* Create the assignment folder under that class if needed.
* Copy/save `assignment.json`.
* Copy/save `roster.csv`.
* Generate one class packet PDF.
* Generate individual student PDFs.

### Notes

* The old command should still work:

```powershell
python main.py generate
```

* The old command should continue generating a generic `template.pdf` and `template.png`.

---

## Phase 2: Personalized Student PDFs

### Goal

Generate one answer sheet per student.

### Requirements

Each student sheet should include human-readable metadata:

* Assignment title
* Student name
* Student ID
* Class ID
* Period

### Output Location

```text
classes/
  english9_p2/
    assignments/
      rj_act1_quiz/
        templates/
          individual/
            1001_doe_jane.pdf
            1002_smith_marcus.pdf
```

### Notes

* Do not add QR codes in this phase unless explicitly decided.
* Metadata must not interfere with registration marks or answer boxes.
* Answer box layout should remain scannable.

---

## Phase 3: Class Packet PDF

### Goal

Generate one printable packet per class containing all personalized student sheets.

### Output Location

```text
classes/
  english9_p2/
    assignments/
      rj_act1_quiz/
        templates/
          class_packet.pdf
```

### Requirements

* One page per student.
* Same layout as individual PDFs.
* Same student metadata as individual PDFs.
* Pages should be in roster order.

---

## Phase 4: QR Code Generation

### Goal

Add one QR code to each student sheet.

### QR Payload

```text
OMR1|class=english9_p2|aid=rj_act1_quiz|sid=1001
```

### Requirements

QR code must encode:

* `class_id`
* `assignment_id`
* `student_id`

Student name and assignment title should still be printed as human-readable text.

### Likely Dependency

```powershell
python -m pip install qrcode[pil]
```

### Placement Requirements

* QR code should be placed away from registration marks.
* QR code should be placed away from answer boxes.
* QR code should be large enough for reliable scanning after printing and rescanning.

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

Try OpenCV QR detection first:

```python
cv2.QRCodeDetector()
```

Avoid adding extra dependencies unless OpenCV QR detection is unreliable.

---

## Phase 7: Result Routing

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

### Notes

* Results should no longer default only to top-level `results.csv` once QR routing is active.
* Top-level `results.csv` may remain for legacy/manual scoring mode.

---

## Phase 8: Scan Storage

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

---

## Phase 9: Duplicate and Attempt Handling

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

Then decide later whether gradebook export should use:

* latest attempt,
* highest attempt,
* first attempt,
* manually selected attempt.

---

## Phase 10: Future Multi-Page Forms

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

1. Update `generate` command to accept one assignment and multiple rosters.
2. Generate personalized individual student PDFs.
3. Generate class packet PDFs.
4. Add QR code generation to personalized sheets.
5. Add variable question count support up to 15.
6. Add QR decoding during scoring.
7. Route results into correct class/assignment folder.
8. Add scan source tracking.
9. Add duplicate/attempt handling.
10. Later: support multi-page forms.
