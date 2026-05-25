# ScoreForm

ScoreForm is a Python-based classroom OMR system for generating printable answer sheets and scoring scanned student responses.

It is being developed as a local-first tool for teachers who want a lightweight, customizable alternative to commercial scan sheet systems.

## Project Status

**Early prototype / active development**

ScoreForm currently works for controlled testing and development use, but it is not yet recommended for high-stakes grading without manual verification.

The project is currently focused on:

* printable answer-sheet generation
* QR-coded student/assignment metadata
* scanned PDF/image scoring
* assignment-based answer keys
* class roster integration
* CSV result output
* eventually, a teacher-friendly terminal menu

## Current Features

ScoreForm currently supports:

* Modular `scoreform/` package structure
* Root-level `main.py` command-line entry point
* Printable generic answer-sheet template generation
* Image scoring
* Scanned PDF scoring
* Multi-page PDF batch scoring
* Corner registration detection
* Blank answer detection
* Ambiguous/double-mark detection
* CSV result export
* External `answer_key.json` validation
* Assignment JSON validation
* Roster CSV validation
* Class/assignment folder setup
* Multi-roster answer-sheet generation
* Individual personalized student PDFs
* Class packet PDF generation
* QR code generation on individual student PDFs
* QR code generation on class packet pages
* QR payload parsing
* QR decoding from generated PDFs/images
* QR decoding from printed-and-scanned sheets when scan quality is adequate
* Legacy scoring of printed, filled, phone-scanned student sheets with QR code present
* QR-aware scoring metadata extraction and automatic assignment lookup from QR payloads
* Mixed-scan QR-aware scoring (multi-page class packet processing)
* Result routing into class/assignment folders with roster-enriched routed results
* Duplicate/attempt handling for repeated QR-aware scans with per-attempt metadata
* Per-result `source_file` tracking (preserves user-supplied input path)
* Project-level `scans_inbox/` creation to support scan workflow

## Important Limitations

ScoreForm is still under active development.

Current limitations include:

* QR detection depends on scan quality, lighting, alignment, and camera/scanner behavior.
* Poor-quality phone scans may fail QR detection.
* Result routing works for QR-aware scoring. Duplicate/attempt handling is now implemented; scan storage behavior is still being developed.
* Question count support is currently limited.
* The terminal menu interface has not yet been implemented.
* The installable `scoreform` command has not yet been implemented.
* Manual verification is recommended before using results for actual grades.

## Student Data and Privacy

All example names, classes, rosters, assignments, and sample files in this repository are synthetic and for testing/demo purposes only.

Do not commit real student data to this repository.

Do not commit:

* real student names
* real student IDs
* real rosters
* scanned student work
* graded answer sheets
* identifiable classroom records
* private school documents
* production result CSV files

ScoreForm is intended to run locally. Teachers using this project are responsible for following their school, district, state, and federal student-data privacy requirements.

## Repository Structure

The current project structure is evolving, but the intended direction is:

```text
examples/
  answer_key.json
  sample_assignment.json
  sample_roster_english9_p2.csv
scoreform/
  __init__.py
  assignment.py
  folders.py
  roster.py
  scoring.py
  templates.py

scans_inbox/
main.py
requirements.txt
run_tests.ps1
README.md
LICENSE
development_plan.md
```

Generated classroom files are organized using a structure like:

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

**Note:** `scans_inbox/` is the recommended location for scanned PDFs and images awaiting scoring. Files in `scans_inbox/` are ignored by Git and are not moved or deleted automatically.

Generated files, scans, debug images, results, and local-only test files should generally not be committed to Git.

## Data Model

### Roster CSV Format

```csv
class_id,student_id,last_name,first_name,period
english9_p2,1001,Doe,Jane,2
english9_p2,1002,Smith,Marcus,2
```

Required columns:

* `class_id`
* `student_id`
* `last_name`
* `first_name`
* `period`

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

ScoreForm currently uses a compact QR payload format:

```text
OMR1|class=english9_p2|aid=rj_act1_quiz|sid=1001
```

This identifies:

* the class
* the assignment
* the student

The QR code is intended to allow ScoreForm to automatically connect a scanned answer sheet to the correct class, assignment, roster entry, and answer key.

## Requirements

### Python Dependencies

Python package dependencies are listed in:

```text
requirements.txt
```

Current dependencies include:

```text
opencv-python
numpy
pdf2image
reportlab
qrcode[pil]
```

Install them with:

```powershell
python -m pip install -r requirements.txt
```

### External Dependency

ScoreForm also requires Poppler for PDF conversion through `pdf2image`.

Poppler is not installed by `pip`.

On Windows, Poppler can be installed separately. After installation, make sure the Poppler `bin` directory is available on your system `PATH`.

## Basic Usage

The command-line interface is still evolving. Current commands may change before the first stable release.

### Scan Workflow

Scanned PDFs and images should be placed in the `scans_inbox/` folder:

```text
scans_inbox/
  class_packet_2026_05_24.pdf
  mixed_scan.pdf
```

The program will create this folder automatically when you generate or set up assignment materials. Results include the source path or filename in the `source_file` column for audit and verification purposes.

Legacy/manual scoring still writes debug images to the project root, while QR-aware scoring routes debug images into the assignment `debug/` folder.

### Validate an Assignment File

```powershell
python main.py validate-assignment examples\sample_assignment.json
```

### Validate a Roster File

```powershell
python main.py validate-roster examples\sample_roster_english9_p2.csv
```

### Set Up Assignment Folders

```powershell
python main.py setup-assignment examples\sample_assignment.json examples\sample_roster_english9_p2.csv
```

### Generate Student Answer Sheets

```powershell
python main.py generate examples\sample_assignment.json --rosters examples\sample_roster_english9_p2.csv
```

### Decode a QR Code From a File

```powershell
python main.py decode-qr path\to\file.pdf
```

### Score a Scanned File

```powershell
python main.py score path\to\scan.pdf
```

Some legacy/manual scoring modes may still require an explicit results file and answer key, depending on the current development state:

```powershell
python main.py score scanned_file.pdf results.csv examples\answer_key.json
```

## Development Roadmap

The current development plan focuses the next work on scan workflow, storage, and robustness.

Upcoming focus areas (not exhaustive):

- Scan source tracking / scan workflow
- Scan storage behavior
- Debug image routing
- Duplicate and attempt handling
- Overwrite and collision protection
- Basic terminal menu
- Installable scoreform command
- Roster and assignment creation/management
- Variable question counts
- Optional roster enhancements
- Test/CLI robustness
- General cleanup
- Future multi-page forms

## Planned Version Milestones

Planned versions may change as the project develops.

```text
v0.1.0  QR-aware scoring with routed, roster-enriched results
v0.2.0  Scan workflow and auditability
v0.3.0  Basic teacher-friendly terminal menu
v0.4.0  Installable scoreform command
v0.5.0  Roster and assignment creation/management
v0.6.0  Variable question counts and optional roster enhancements
v0.7.0  Test robustness, CLI reliability, cleanup, and public-readiness work
v1.0.0  Stable classroom-ready release
```

## Testing

A portable PowerShell regression script is included:

```powershell
.\run_tests.ps1
```

The test script is intended to verify core development behaviors without relying on private or local-only scan files.

Future test improvements may include:

* programmatically generated filled answer sheets
* malformed QR payload tests
* missing QR code tests
* missing input file tests
* menu workflow tests
* QR reliability tests
* scan-quality guidance checks

## Known Issues

* Poor scan quality may prevent QR detection.
* Some scoring and CSV-export logic still assumes fixed question counts.
* Legacy/manual scoring still writes debug images to the project root, while QR-aware scoring routes debug images into assignment debug folders.
* Duplicate/attempt handling preserves repeated routed scans, but gradebook export rules for latest/highest/selected attempts are not implemented yet.
* Overwrite/collision protection is not implemented yet.
* QR preprocessing may be needed for more reliable real-world scanning.

## Design Principles

ScoreForm is being designed around the following principles:

* Keep the tool local-first.
* Avoid requiring paid services.
* Keep classroom data under the teacher’s control.
* Make generated files predictable and organized.
* Preserve legacy/manual scoring while newer QR-aware workflows are developed.
* Prefer simple, inspectable file formats such as CSV and JSON.
* Build toward a teacher-friendly workflow without adding unnecessary complexity too early.
* Avoid hardcoded assumptions that would prevent future multi-page forms.

## Contributing

This project is currently in early solo development.

If the repository becomes public, contributions should follow these expectations:

* Use synthetic test data only.
* Do not submit real student data.
* Open an issue before major feature changes.
* Keep changes focused and testable.
* Update documentation when behavior changes.
* Include or update tests when possible.

## License

This project is licensed under the MIT License.
