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
* a teacher-friendly terminal menu

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
* Basic terminal menu via `python main.py menu` or `scoreform`
* Menu-driven roster creation without manual CSV editing
* Menu-driven assignment creation without manual JSON editing
* Single-page assignments with 1-15 questions
* Optional question-level standards metadata in assignment JSON
* Optional roster columns preserved when roster CSV files are loaded
* Editable install support with the `scoreform` command

## Important Limitations

ScoreForm is still under active development.

Current limitations include:

* QR detection depends on scan quality, lighting, alignment, and camera/scanner behavior.
* Poor-quality phone scans may fail QR detection.
* Result routing works for QR-aware scoring. Duplicate/attempt handling is now implemented; scan storage behavior is still being developed.
* Question count support is currently limited to 1-15 questions on a single page.
* The terminal menu interface is available via `scoreform` or `python main.py menu`.
* The installable `scoreform` command is available after editable installation, but standalone executable packaging has not yet been implemented.
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
  cli.py
  folders.py
  results.py
  roster.py
  scoring.py
  templates.py
  workflows.py
tests/
  test_assignment_validation.py
  test_folders.py
  test_qr_validation.py
  test_roster_validation.py
  test_templates.py

pyproject.toml

scans_inbox/
local_outputs/
main.py
requirements.txt
run_tests.ps1
README.md
ROADMAP.md
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

Generic/manual development outputs are organized under `local_outputs/` when ScoreForm chooses the default path:

```text
local_outputs/
  templates/
    template.pdf
    template.png
  results/
    results.csv
  debug/
    debug_corners_page_1.png
    debug_warped_page_1.png
  temp/
```

`local_outputs/` is ignored by Git. Explicit output paths supplied by the user are still honored as written.

Generated files, scans, debug images, results, and local-only test files should generally not be committed to Git.

## Launch the Terminal Menu

A simple terminal menu is available through the CLI:

```powershell
scoreform
```

For direct Python invocation, `python main.py menu` remains supported.

The menu wraps existing workflows while preserving direct CLI commands such as `generate`, `setup-assignment`, `score`, `decode-qr`, `validate-assignment`, and `validate-roster`.

### Create a Roster from the Menu

ScoreForm now includes menu-driven roster creation, so you can create valid roster CSV files without manually editing CSV:

1. Launch the terminal menu:

   ```powershell
   scoreform
   ```

2. Select **7. Roster management**

3. Select **1. Create a new roster**

4. Provide the output CSV path, for example:

   ```
   my_class_rosters/english9_p2.csv
   ```

   (Parent directories are created automatically if needed)

5. Enter the class ID and period (applied to all students in this roster)

6. Enter students one at a time with:

   * student_id
   * last_name
   * first_name

7. After adding all students, the roster is saved and validated automatically

Example roster created this way:

```csv
class_id,student_id,last_name,first_name,period
english9_p2,1001,Doe,Jane,2
english9_p2,1002,Smith,Marcus,2
english9_p2,1003,Brown,Alyssa,2
```

Features:

* **Overwrite protection**: If the file already exists, you must explicitly confirm before overwriting.
* **Validation after save**: The roster is validated using built-in validation logic before reporting success.
* **Parent directory creation**: Output directories are created automatically if needed.
* **Exit/cancel support**: Press Ctrl+C to cancel, or leave `student_id` blank after entering at least one student to finish the roster.

### Create an Assignment from the Menu

ScoreForm now includes menu-driven assignment creation so you can create valid assignment JSON files without hand-editing JSON.

1. Launch the terminal menu:

   ```powershell
   scoreform
   ```

2. Select **8. Assignment management**

3. Select **1. Create a new assignment**

4. Provide the output JSON path. Parent directories are created if needed.

5. Enter `assignment_id` and `title`.

6. Enter the assignment `question_count` (1-15), then enter answers for Q1 through Q{question_count}. Current choices are A-D only.

7. The tool saves the assignment JSON and validates it automatically.

Notes:

* Supported `question_count` range is 1-15 and choices remain fixed at A-D.
* New assignments include an empty `standards` list for each question. The menu does not prompt for standards yet.
* Overwrite protection requires `y` or `yes` to overwrite existing files.

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

Roster CSV files may include additional optional columns, such as `preferred_name`, `email`, or local workflow fields. Optional columns are preserved in each loaded student dictionary, and empty optional values are allowed. The roster creation menu currently writes only the required columns.

Optional roster fields are not automatically added to `results.csv` or routed result CSVs. Routed results continue to include only roster fields needed for scoring context: `last_name`, `first_name`, and `period`. Avoid storing sensitive or private student information in optional columns unless it is necessary and appropriate under local school or district policy.

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
  },
  "standards": {
    "1": [],
    "2": ["RL.CI.11-12.2"],
    "3": ["RL.IT.11-12.3", "L.VI.11-12.4"],
    "4": [],
    "5": ["RL.CR.11-12.1"]
  }
}
```

The top-level `standards` object is optional assignment metadata. Existing assignment JSON files without `standards` remain valid. When present, standards keys must be valid question numbers for the assignment's `question_count`, and each value must be a list of non-empty strings. Empty lists and missing question keys are allowed.

Standards metadata is preserved when assignments are loaded, but it is not written to `results.csv` and does not change scoring behavior, QR payloads, result routing, or roster CSVs. Menu-driven standards editing and standards performance reporting are future work.

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

ScoreForm validates QR payload fields before using them to build file paths, and rejects malformed or unsafe QR metadata.

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

## Installation and Setup

For development use, install ScoreForm in editable mode within your virtual environment:

```powershell
python -m pip install -r requirements.txt
python -m pip install -e .
```

To include development/test dependencies such as `pytest`, install with the `dev` extra:

```powershell
python -m pip install -e .[dev]
```

Then launch the interactive menu with:

```powershell
scoreform
```

or use individual commands:

```powershell
scoreform menu
scoreform validate-assignment examples\sample_assignment.json
scoreform validate-roster examples\sample_roster_english9_p2.csv
scoreform generate
scoreform generate examples\sample_assignment.json --rosters examples\sample_roster_english9_p2.csv
scoreform score path\to\scan.pdf
scoreform decode-qr path\to\file.pdf
scoreform setup-assignment examples\sample_assignment.json examples\sample_roster_english9_p2.csv
```

For backward compatibility, direct `python main.py` commands continue to work:

```powershell
python main.py menu
python main.py validate-assignment examples\sample_assignment.json
python main.py generate examples\sample_assignment.json --rosters examples\sample_roster_english9_p2.csv
python main.py score path\to\scan.pdf
```

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

Legacy/manual default results and debug images are written under `local_outputs/results/` and `local_outputs/debug/`. QR-aware routed scoring still writes results and debug images into the assignment folder under `classes/`.

### Validate an Assignment File

With editable install (preferred for development):

```powershell
scoreform validate-assignment examples\sample_assignment.json
```

Or with direct Python invocation:

```powershell
python main.py validate-assignment examples\sample_assignment.json
```

### Validate a Roster File

```powershell
scoreform validate-roster examples\sample_roster_english9_p2.csv
```

### Set Up Assignment Folders

```powershell
scoreform setup-assignment examples\sample_assignment.json examples\sample_roster_english9_p2.csv
```

### Generate Student Answer Sheets

```powershell
scoreform generate examples\sample_assignment.json --rosters examples\sample_roster_english9_p2.csv
```

Generic template generation without an assignment writes to `local_outputs/templates/` by default:

```powershell
scoreform generate
```

### Decode a QR Code From a File

```powershell
scoreform decode-qr path\to\file.pdf
```

### Score a Scanned File

```powershell
scoreform score path\to\scan.pdf
```

QR-aware scoring without an output CSV routes results to `classes/<class_id>/assignments/<assignment_id>/results.csv`.

QR-aware scoring with an explicit output CSV writes the QR-aware results to that file instead of routing:

```powershell
scoreform score scanned_file.pdf qr_metadata_results.csv
```

Legacy/manual scoring can use the default local results path when only an answer key is supplied:

```powershell
scoreform score scanned_file.pdf examples\answer_key.json
```

Explicit output paths are honored:

```powershell
scoreform score scanned_file.pdf results.csv examples\answer_key.json
```

## Development Roadmap

The public roadmap is maintained in [`ROADMAP.md`](ROADMAP.md). The detailed `development_plan.md` remains a working planning document for now.

The current development plan focuses the next work on test robustness, cleanup, documentation, and public-readiness work.

Upcoming focus areas (not exhaustive):

* Menu-driven standards editing
* Standards reporting
* Optional roster enhancements
* Manual answer entry workflow
* Assignment and roster editing/listing/summaries
* Test/CLI robustness
* General cleanup
* Future multi-page forms

## Planned Version Milestones

Planned versions may change as the project develops.

```text
v0.1.0  QR-aware scoring with routed, roster-enriched results
v0.2.0  Scan workflow and auditability
v0.3.0  Basic teacher-friendly terminal menu
v0.4.0  Installable scoreform command
v0.5.0  Roster and assignment creation/management
v0.6.0  Flexible form configuration and standards metadata
v0.7.0  Test robustness, CLI reliability, cleanup, and public-readiness work
v1.0.0  Stable classroom-ready release
```

## Testing

ScoreForm now includes two layers of tests.

Run the focused Python test suite with:

```powershell
python -m pytest
```

The pytest suite is intended for focused module-level checks such as QR payload validation, assignment validation, roster validation, folder helpers, and filename helpers.

A portable PowerShell regression script is also included:

```powershell
.\run_tests.ps1
```

The PowerShell script installs the package in editable mode with development extras, runs the pytest suite, and then verifies full workflow behaviors such as generation, validation, QR-aware scoring, routed results, duplicate/attempt handling, and menu workflows.

The test scripts are intended to verify core development behaviors without relying on private or local-only scan files.

Future test improvements may include:

* programmatically generated filled answer sheets
* malformed QR payload tests
* missing QR code tests
* missing input file tests
* additional menu workflow tests
* QR reliability tests
* scan-quality guidance checks

## Known Issues

* Poor scan quality may prevent QR detection.
* Multi-page forms are not implemented yet; assignments are currently limited to 1-15 questions on a single page.
* Legacy/manual scoring writes default debug images to `local_outputs/debug/`, while QR-aware scoring routes debug images into assignment debug folders.
* Duplicate/attempt handling preserves repeated routed scans, but gradebook export rules for latest/highest/selected attempts are not implemented yet.
* Overwrite/collision protection prevents mismatched assignment JSON files from overwriting existing assignment folders, but an explicit overwrite/archive workflow has not been implemented yet.
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
