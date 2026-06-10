# ScoreForm

ScoreForm is a Python-based classroom OMR system for generating printable answer sheets and scoring scanned student responses.

It is being developed as a local-first tool for teachers who want a lightweight, customizable alternative to commercial scan sheet systems.

## Project Status

**Early prototype / active development**

Current version: `0.8.1`.

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

ScoreForm currently supports the following major workflows and capabilities.

### Answer Sheet Generation

* Printable generic answer-sheet template generation
* Assignment-based answer-sheet generation
* Multi-roster answer-sheet generation
* Individual personalized student PDFs
* Class packet PDF generation
* Single-page assignments with 1-15 questions

### Scoring

* Image scoring
* Scanned PDF scoring
* Multi-page PDF batch scoring
* Corner registration detection
* Blank answer detection
* Ambiguous/double-mark detection
* Legacy/manual scoring with explicit answer keys
* Legacy scoring of printed, filled, phone-scanned student sheets when scan quality is adequate

### QR Metadata and Routing

* QR code generation on individual student PDFs
* QR code generation on class packet pages
* QR payload parsing and validation
* QR decoding from generated PDFs/images
* QR decoding from printed-and-scanned sheets when scan quality is adequate
* QR-aware scoring metadata extraction
* Automatic assignment lookup from QR payloads
* Mixed-scan QR-aware scoring for multi-page class packets
* Result routing into class/assignment folders

### Results and Auditability

* CSV result export
* Roster-enriched routed results
* Duplicate/attempt handling for repeated QR-aware scans
* Per-result `source_file` tracking
* Per-result `attempt_number` and `scan_timestamp` metadata
* Safe routed-results writes that preserve existing rows
* Project-level `scans_inbox/` creation to support scan workflow

### Rosters, Assignments, and Validation

* External `answer_key.json` validation
* Assignment JSON validation
* Roster CSV validation
* Class/assignment folder setup through direct CLI workflows
* Menu-driven roster creation without manual CSV editing
* Menu-driven assignment creation without manual JSON editing
* Optional question-level standards metadata in assignment JSON
* Optional roster columns preserved when roster CSV files are loaded

### CLI and Menu Workflows

* Basic terminal menu via `python main.py menu` or `scoreform`
* Editable install support with the `scoreform` command
* Backward-compatible root-level `main.py` command-line entry point
* Direct CLI commands for generation, scoring, validation, setup, and QR decoding
* CLI help and version commands through `scoreform --help`, `scoreform help`, `scoreform --version`, and `scoreform version`
* Terminal menu help for common workflows and routed-results guidance
* Terminal menu screen clearing between workflows and pauses after important output
* Menu scoring picker for supported files in `scans_inbox/`, with custom path fallback
* QR-aware routed scoring as the recommended/default terminal-menu scoring workflow

### Project Structure and Development Support

* Modular `scoreform/` package structure
* Fast PowerShell development checks through `run_fast_tests.ps1`
* Portable PowerShell regression script through `run_tests.ps1`
* Pytest coverage for validation, scoring, QR behavior, routed results, CLI behavior, and workflow helpers
* Synthetic example data for public testing and demonstration
* Git protections for generated classroom files, scans, debug images, local outputs, and private working notes

## Important Limitations

ScoreForm is still under active development.

Current limitations include:

* QR detection depends on scan quality, lighting, alignment, and camera/scanner behavior.
* ScoreForm uses full-page and upper-right crop fallbacks, including tight-crop
  scaling, quiet-zone padding, contrast normalization, threshold cleanup, and
  small rotations. Severely blurred, damaged, or obscured QR codes may still fail.
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
run_fast_tests.ps1
run_tests.ps1
README.md
ROADMAP.md
CHANGELOG.md
LICENSE
docs/
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
  qr_failures/
    YYYY-MM-DD/
      scan_packet_page_2.png
      scan_packet_page_2_qr_crop_tight.png
  qr_batch_summaries/
    YYYY-MM-DD/
      scan_packet_YYYY-MM-DD_HHMM_summary.txt
  temp/
```

`local_outputs/` is ignored by Git. Explicit output paths supplied by the user are still honored as written.

When QR-aware scoring cannot decode a page, ScoreForm saves the failed page and
a bounded set of attempted QR-region images under
`local_outputs/qr_failures/<date>/`. Each QR-aware scoring run also saves the
terminal batch summary under `local_outputs/qr_batch_summaries/<date>/` after
result-writing status is known.

Generated files, scans, debug images, results, and local-only test files should generally not be committed to Git.

## Launch the Terminal Menu

A simple terminal menu is available through the CLI:

```powershell
scoreform
```

For direct Python invocation, `python main.py menu` remains supported.

The teacher-centered main menu is:

```text
ScoreForm

1. Assignment Management
2. Roster Management
3. Help
4. Exit
```

Assignment Management contains assignment creation and validation, answer-sheet generation, scoring, and QR decoding. Roster Management contains roster creation, viewing, and validation.

ScoreForm supports two interaction layers:

1. **Direct CLI** exposes stable operations for scripting, testing, automation, development, and power users.
2. **Interactive menu** exposes guided teacher workflows built from those operations.

The layers intentionally do not have one-to-one command parity. Path-oriented setup operations such as `setup-assignment` remain available through `scoreform setup-assignment ...` and `python main.py setup-assignment ...`, but are not shown in the normal teacher-facing menu.

Select **3. Help** from the menu for a concise workflow guide, routed-results location, and grading-verification reminder.
The interactive menu clears between screens and pauses after important output so generated file paths, validation messages, and scoring summaries remain readable before the next menu redraw.

### Create a Roster from the Menu

ScoreForm now includes menu-driven roster creation, so you can create valid roster CSV files without manually editing CSV:

1. Launch the terminal menu:

   ```powershell
   scoreform
   ```

2. Select **2. Roster Management**

3. Select **1. Create a class roster**

4. Enter a class name.

5. Accept or edit the suggested `class_id`.

6. Enter the period.

7. Enter students one at a time with:

   * student_id
   * last_name
   * first_name

8. After adding all students, the roster is saved to:

   ```text
   classes/<class_id>/roster.csv
   ```

   and validated automatically.

Example roster created this way:

```csv
class_id,student_id,last_name,first_name,period
english9_p2,1001,Doe,Jane,2
english9_p2,1002,Smith,Marcus,2
english9_p2,1003,Brown,Alyssa,2
```

Features:

* **Overwrite protection**: If the class roster already exists, you must explicitly confirm before overwriting.
* **Read-only viewing**: The roster management menu can display an existing roster without editing it.
* **Validation after save**: The roster is validated using built-in validation logic before reporting success.
* **Exit/cancel support**: Press Ctrl+C to cancel, or leave `student_id` blank after entering at least one student to finish the roster.

### Create an Assignment from the Menu

ScoreForm now includes menu-driven assignment creation so you can create valid assignment JSON files without hand-editing JSON.

1. Launch the terminal menu:

   ```powershell
   scoreform
   ```

2. Select **1. Assignment Management**

3. Select **1. Create an assignment**

4. Select one or more existing classes.

5. Enter an assignment title.

6. Accept or edit the suggested `assignment_id`.

7. Enter the assignment `question_count` (1-15), then enter answers for Q1 through Q{question_count}. Current choices are A-D only.

8. The tool saves the assignment JSON to:

   ```text
   classes/<class_id>/assignments/<assignment_id>/assignment.json
   ```

   and validates it automatically.

Notes:

* Supported `question_count` range is 1-15 and choices remain fixed at A-D.
* New assignments include an empty `standards` list for each question. The menu does not prompt for standards yet.
* Overwrite protection requires `y` or `yes` to overwrite existing assignment files.
* Assignment Management also validates assignment JSON files, generates answer sheets, scores scanned responses, and decodes QR metadata; assignment editing and standards editing remain future work.

## Data Model

Identifiers used in paths and QR metadata must contain only letters, numbers, underscores, and hyphens. This applies to `class_id`, `assignment_id`, and `student_id`.

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

New ScoreForm answer sheets use the shared Paper Data Suite PDS1 payload format:

```text
PDS1|module=scoreform|class=english9_p2|aid=rj_act1_quiz|sid=1001|page=1
```

This identifies:

* the Paper Data Suite module
* the class
* the assignment
* the student
* the answer-sheet page

The QR code is intended to allow ScoreForm to automatically connect a scanned answer sheet to the correct class, assignment, roster entry, and answer key.

ScoreForm validates QR payload fields before using them to build file paths, rejects malformed or unsafe QR metadata, and rejects PDS1 payloads for modules other than `scoreform`.

Legacy answer sheets using the earlier OMR1 format remain supported as a parsing fallback:

```text
OMR1|class=english9_p2|aid=rj_act1_quiz|sid=1001
```

## Requirements

### Python Dependencies

Ordinary third-party Python dependencies are listed in:

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

Installing this file alone does not produce a working local ScoreForm
installation. ScoreForm also requires `pds-core`, which is currently installed
from a sibling repository checkout for Paper Data Suite development.

To install only the third-party packages, run:

```powershell
python -m pip install -r requirements.txt
```

For a working local ScoreForm development or classroom-trial installation, use
the complete setup under [Installation and Setup](#installation-and-setup).

### External Dependency

ScoreForm also requires Poppler for PDF conversion through `pdf2image`.

Poppler is not installed by `pip`.

On Windows, install Poppler separately using a package manager such as winget, Chocolatey, or Scoop, or by downloading a Windows build of Poppler. After installation, make sure the Poppler `bin` directory is on your system `PATH` so `pdf2image` can find tools such as `pdftoppm`.

On macOS, Homebrew users can install Poppler with:

```bash
brew install poppler
```

On Linux, install the Poppler utilities package for your distribution. For example, on Debian or Ubuntu:

```bash
sudo apt install poppler-utils
```

Package names vary by distribution.

## Installation and Setup

`pds-core` is a required runtime dependency of ScoreForm. It provides shared
identifier validation, route and scan-inbox helpers, legacy OMR1 parsing, and
PDS1 QR payload generation and parsing.

For the current local Paper Data Suite workflow, clone `pds-core` and
`pds-scoreform` as sibling repositories under any parent directory:

```text
Paper-Data-Suite/
  pds-core/
  pds-scoreform/
```

The parent directory name and location may vary. Do not replace the relative
sibling setup with a machine-specific absolute path.

From inside `pds-scoreform`, with the intended virtual environment activated,
run:

```powershell
python -m pip install -r requirements-dev.txt
```

This is the correct install command for local Paper Data Suite development. It
installs:

* the ordinary third-party dependencies from `requirements.txt`;
* the sibling `../pds-core` checkout in editable mode;
* ScoreForm itself in editable mode with development/test dependencies such as
  `pytest`.

`requirements.txt` remains useful as the list of ordinary third-party
dependencies, but it does not install the local `pds-core` checkout and is not
the complete setup command for the current application.

If installation reports that `../pds-core` does not exist, check that both
repositories are present as siblings in the layout above, then rerun the
command from inside `pds-scoreform`.

### Classroom-Trial Machine Setup

Every classroom-trial machine must have both `pds-core` and `pds-scoreform`
checked out as sibling repositories. Activate the machine's ScoreForm virtual
environment and run the same complete install command from inside
`pds-scoreform`:

```powershell
python -m pip install -r requirements-dev.txt
```

Do not prepare a classroom-trial machine with `requirements.txt` alone; that
leaves the required local `pds-core` package uninstalled and ScoreForm will not
start. Poppler must also be installed separately as described above.

## Basic Usage

The command-line interface is still evolving. Current commands may change before the first stable release.

Use `scoreform --help`, `scoreform -h`, or `scoreform help` to show available commands, examples, and scoring mode notes. Use `scoreform --version` or `scoreform version` to print the installed package version.

### Scan Workflow

Scanned PDFs and images should be placed in the `scans_inbox/` folder:

```text
scans_inbox/
  class_packet_2026_05_24.pdf
  mixed_scan.pdf
```

The program will create this folder automatically when you generate or set up assignment materials. From the terminal menu, **Score scanned responses** can list supported files directly inside `scans_inbox/` and let you choose one by number. After you select a scan, the recommended menu mode is QR-aware routed scoring: ScoreForm reads the QR metadata, finds the matching assignment, and writes routed results to `classes/<class_id>/assignments/<assignment_id>/results.csv`. Supported picker file types are `.pdf`, `.png`, `.jpg`, `.jpeg`, `.bmp`, `.tiff`, and `.tif`; unsupported files are ignored.

The picker only selects the input file. It does not move, copy, rename, delete, archive, or route scan files. Manual scoring with an answer key remains available from the menu for non-QR sheets or exceptional workflows. You can still enter a custom path from Downloads, Desktop, or another scanner export folder, and direct CLI scoring continues to accept explicit paths such as `scoreform score path\to\scan.pdf`.

Results include the source path or filename in the `source_file` column for audit and verification purposes.

Legacy/manual default results and debug images are written under `local_outputs/results/` and `local_outputs/debug/`. QR-aware routed scoring still writes results and debug images into the assignment folder under `classes/`.

### Scan Quality Guidance

ScoreForm depends on clear scans for QR detection, corner registration, and answer-box scoring. For best results, scan completed sheets with:

* good, even lighting
* no glare or shadows over QR codes, corner marks, or answer boxes
* the entire page visible
* all four corner registration squares visible
* the QR code clearly visible
* paper as flat as possible
* dark, complete student marks
* no heavy stray marks near answer boxes
* enough resolution for QR and box detection

Supported input file types are:

```text
PDF
PNG
JPG/JPEG
BMP
TIFF/TIF
```

Recommended workflow:

1. Place scanned files in `scans_inbox/`.
2. Use generated class packets or individual student PDFs when possible.
3. Prefer QR-aware routed scoring for generated sheets.
4. Review debug images when scoring fails.
5. Manually verify results before using them for grades.

Common causes of scan failure include:

* missing or cropped corner registration marks
* cropped or cut-off QR codes
* blurry images
* shadows or glare
* very light pencil marks
* forms photographed at a steep angle
* paper not lying flat
* scan apps that warp, crop, enhance, or resize the page aggressively
* using a sheet that does not match the assignment being scored
* printing or scanning at unusual scaling settings

If scoring fails or results look suspicious, try:

* rescanning the page with better lighting
* keeping the page flat
* making sure all four corner squares are visible
* avoiding cropped page edges
* avoiding extreme camera angles
* using a scanner when possible
* trying a higher-resolution scan
* checking that the QR code is not damaged or covered
* verifying that the correct generated sheet was used
* inspecting generated debug images
* manually verifying results before recording grades

ScoreForm saves debug images during scoring. Legacy/manual scoring writes debug images to `local_outputs/debug/`; QR-aware routed scoring writes them to `classes/<class_id>/assignments/<assignment_id>/debug/`. Corner debug images help show whether registration marks were detected. Warped debug images show the normalized page used for scoring. Repeated scoring runs preserve existing debug images by adding numeric suffixes such as `_2` or `_3` when a filename already exists.

ScoreForm is still under active development. Because scan quality directly affects grading reliability, manually verify results before using them for actual grades.

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
Routed result writes preserve existing rows and use a temporary file before replacing `results.csv`.

Routed `results.csv` is an audit log, not a finalized gradebook export. If a student sheet is scanned more than once, ScoreForm preserves each successful scan as a separate row instead of overwriting earlier results. The `attempt_number` column increments for repeated scans of the same student and assignment, while `scan_timestamp` and `source_file` identify when the row was created and which scan, PDF, or image produced it. Makeup or separate scans append to the existing class-assignment results file when the QR metadata matches. ScoreForm does not yet decide which attempt is the official grade, so teachers should manually verify which row to use until gradebook export rules are implemented.

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

The public roadmap is maintained in [`ROADMAP.md`](ROADMAP.md). Development history is summarized in [`CHANGELOG.md`](CHANGELOG.md). Detailed working planning notes are preserved in [`docs/development_plan.md`](docs/development_plan.md).

The `v0.8.1` milestone is complete. Active development is moving toward `v0.9.0` project-organization and data-lifecycle planning.

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
v0.8.0  Completed menu workflow polish, scan inbox picker, QR-aware routed menu scoring, and release documentation
v0.8.1  Manual run-through fixes, teacher-centered menu refinement, persistent menu headers, and stricter version-update assertions
v0.9.0  Project organization, project-root planning, scan archiving, and data-lifecycle design
v1.0.0  Stable classroom-ready release
```

## Testing

ScoreForm now includes fast development checks and a full packaging/regression workflow.

### Fast Development Checks

Use this during normal development:

```powershell
.\run_fast_tests.ps1
```

This runs the pytest suite, `git diff --check`, and a Git tracking check that verifies generated/private artifact paths such as `classes/`, `local_outputs/`, and `scans_inbox/` are not tracked.

### Full Regression Checks

Use this before opening a PR, merging, releasing, or making broad workflow changes:

```powershell
.\run_tests.ps1
```

This installs ScoreForm in editable mode with development extras, runs the pytest suite, and verifies the full packaging, CLI, generation, validation, QR-aware scoring, routed results, duplicate/attempt handling, and menu workflow behavior.

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

* Poor scan quality may still prevent QR detection, though ScoreForm now retries
  with QR preprocessing fallbacks before giving up.
* Multi-page forms are not implemented yet; assignments are currently limited to 1-15 questions on a single page.
* Legacy/manual scoring writes default debug images to `local_outputs/debug/`, while QR-aware scoring routes debug images into assignment debug folders.
* Duplicate/attempt handling preserves repeated routed scans, but gradebook export rules for latest/highest/selected attempts are not implemented yet.
* Overwrite/collision protection prevents mismatched assignment JSON files from overwriting existing assignment folders, but an explicit overwrite/archive workflow has not been implemented yet.
* QR preprocessing improves many real-world phone scans, but severe blur, glare,
  cropping, or rotation can still prevent detection.

## Design Principles

ScoreForm is being designed around the following principles:

* Keep the tool local-first.
* Avoid requiring paid services.
* Keep classroom data under the teacher's control.
* Make generated files predictable and organized.
* Preserve legacy/manual scoring while newer QR-aware workflows are developed.
* Prefer simple, inspectable file formats such as CSV and JSON.
* Build toward a teacher-friendly workflow without adding unnecessary complexity too early.
* Avoid hardcoded assumptions that would prevent future multi-page forms.

## Contributing

This project is currently in early solo development.

Contributions should follow these expectations:

* Use synthetic test data only.
* Do not submit real student data.
* Open an issue before major feature changes.
* Keep changes focused and testable.
* Update documentation when behavior changes.
* Include or update tests when possible.

## License

This project is licensed under the MIT License.
