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

## Important Limitations

ScoreForm is still under active development.

Current limitations include:

* QR detection depends on scan quality, lighting, alignment, and camera/scanner behavior.
* Poor-quality phone scans may fail QR detection.
* The scoring workflow is still evolving.
* Result routing is not yet fully finalized.
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
scoreform/
  __init__.py
  assignment.py
  folders.py
  qr.py
  roster.py
  scoring.py
  templates.py

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
        templates/
          class_packet.pdf
          individual/
            1001_doe_jane.pdf
            1002_smith_marcus.pdf
            1003_brown_alyssa.pdf
        scans/
        debug/
```

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

### Validate an Assignment File

```powershell
python main.py validate-assignment assignment.json
```

### Validate a Roster File

```powershell
python main.py validate-roster roster.csv
```

### Set Up Assignment Folders

```powershell
python main.py setup-assignment assignment.json roster.csv
```

### Generate Student Answer Sheets

```powershell
python main.py generate assignment.json --rosters roster.csv
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
python main.py score scanned_file.pdf results.csv answer_key.json
```

## Development Roadmap

The current development plan is organized around these major phases:

1. QR-based scoring metadata extraction
2. QR-based mixed scan scoring
3. Result routing into class/assignment folders
4. Basic terminal menu interface
5. Installable `scoreform` command / launcher
6. Roster and assignment creation/management
7. Scan storage
8. Duplicate and attempt handling
9. Overwrite and collision protection
10. Variable question counts
11. Optional roster enhancements
12. Test and CLI robustness
13. General code cleanup
14. Future multi-page forms

## Planned Version Milestones

Planned versions may change as the project develops.

```text
v0.1.0  QR-aware scoring with routed results
v0.2.0  Basic teacher-friendly terminal menu
v0.3.0  Installable scoreform command
v0.4.0  Roster and assignment creation/management
v0.5.0  Scan storage, duplicate handling, and overwrite protection
v0.6.0  Variable question counts and optional roster enhancements
v0.7.0  Test robustness, CLI reliability, and cleanup
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
* The `score` command may need stronger nonzero exit behavior when files are missing or no pages are scored.
* Some scoring and CSV-export logic may still assume fixed question counts.
* Debug image routing is still being refined.
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
