# ScoreForm

ScoreForm is a Python-based classroom OMR system for generating printable answer sheets and scoring scanned student responses.

It is being developed as a local-first tool for teachers who want a lightweight, customizable alternative to commercial scan sheet systems.

## Project Status

**Early prototype / active development**

Current version: `0.8.1`.

ScoreForm currently works for controlled testing and development use, but it is not yet recommended for high-stakes grading without manual verification.

The project is currently focused on:

* printable answer-sheet generation
* registered PDS2 page routing
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
* Multi-page assignments with 1-75 questions and 15 questions per physical page

### Scoring

* Image scoring
* Scanned PDF scoring
* Multi-page PDF batch scoring
* Corner registration detection
* Blank answer detection
* Ambiguous/double-mark detection
* Manual scoring with explicit answer keys

### PDS2 QR Intake and Page Dispatch

* QR code generation on individual student PDFs
* QR code generation on class packet pages
* Strict Core PDS2 locator parsing and canonical serialization
* Retained-source QR decoding from generated PDFs/images
* QR decoding from printed-and-scanned sheets when scan quality is adequate
* Fresh installed-module registry per top-level scoring operation
* Ordered independent Core dispatch for mixed-module source pages
* Immutable ScoreForm page results and opaque foreign-module results
* Page-level dispatch summaries plus issuance-level assembly and routed export

### Durable routed results and attempt identity

* CSV result export
* Roster-enriched routed results
* Issuance-only assembly with missing/duplicate/conflict rejection
* Per-result `source_file` tracking
* Per-result `attempt_number` and `scan_timestamp` metadata
* Safe routed-results writes that preserve existing rows
* Idempotent schema-v2 export keyed by source scan plus issuance
* Filed scan copies only for eligible full-success, same-assignment managed scoring
* Workspace-level `scans_inbox/` creation to support scan workflow

### Rosters, Assignments, and Validation

* External `answer_key.json` validation
* Assignment JSON validation
* Roster CSV validation
* Class/assignment folder setup through direct CLI workflows
* Menu-driven roster creation without manual CSV editing
* Menu-driven assignment creation without manual JSON editing
* Optional question-level standards alignment in assignment JSON
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
* Retained PDS2 Core page dispatch as the recommended terminal-menu scan workflow

### Project Structure and Development Support

* Modular `scoreform/` package structure
* Fast PowerShell development checks through `run_fast_tests.ps1`
* Local release-readiness gate through `run_tests.ps1`
* Pytest coverage for validation, scoring, QR behavior, routed results, CLI behavior, and workflow helpers
* Synthetic example data for public testing and demonstration
* Git protections for generated classroom files, scans, debug images, local outputs, and private working notes

## Important Limitations

ScoreForm is still under active development.

Current limitations include:

* Retained PDS2 decoding, page dispatch, complete-issuance assembly, routed
  schema-v2 export, Core-v2 failure persistence, and append-only resolution
  review are active. Manual scoring remains available.

* QR detection depends on scan quality, lighting, alignment, and camera/scanner behavior.
* ScoreForm uses full-page and upper-right crop fallbacks, including tight-crop
  scaling, quiet-zone padding, contrast normalization, threshold cleanup, and
  small rotations. Severely blurred, damaged, or obscured QR codes may still fail.
* The active PDS2 path never chooses among duplicates. Partial batches may
  export unrelated complete attempts and persist review records, but are never
  automatically filed into an assignment-local scan folder.
* Question count support is 1-75, paged automatically at 15 questions per sheet.
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

ScoreForm is intended to run locally, but local-first does not mean that its
artifacts are non-sensitive. Scans, diagnostic images, result CSVs and their
`source_file` values, routed results, `local_outputs/`,
and class assignment output folders may contain student or assessment records.
Treat those locations as sensitive and do not share generated artifacts
publicly. Teachers using this project are responsible for following their
school, district, state, and federal student-data privacy requirements.

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

## Paper Data Suite Workspace

ScoreForm-managed data is stored under the shared Paper Data Suite workspace
root defined by `pds-core`. The default root is `~/Paper Data Suite`; a
different root can be selected through the shared PDS workspace configuration
or the `PDS_WORKSPACE_ROOT` environment variable.

The source checkout, installed package, virtual environment, and current
working directory are not implicit data roots. ScoreForm exposes the shared
configuration through direct CLI commands and the terminal menu, while all
workspace resolution, validation, saving, and reset behavior remains provided
by `pds-core`.

Use these commands to inspect or manage the shared workspace:

```powershell
scoreform workspace show
scoreform workspace set "C:\Users\teacher\OneDrive - District Name\Paper Data Suite"
scoreform workspace validate
scoreform workspace reset
```

`workspace set` validates or creates the selected folder and saves it as the
shared preference. It does not migrate files from the previous workspace.
`workspace reset` clears only the saved preference; it does not delete the
workspace folder or any files under `classes/`, `scans_inbox/`,
`local_outputs/`, or `.pds/`. An active `PDS_WORKSPACE_ROOT` environment
variable still takes precedence over the saved preference.

### Active School Year

ScoreForm can show, open, and close the shared Paper Data Suite active school
year stored by `pds-core` under the workspace:

```text
<PDS workspace root>/settings/school_year.json
```

Use these direct CLI commands:

```powershell
scoreform school-year show
scoreform school-year open 2026-2027
scoreform school-year open 2027-2028 --overwrite
scoreform school-year close
```

The same workflows are available from **Workspace Settings** in the terminal
menu under **School Year Settings**. Opening or closing a school year only
updates the shared school-year state file. It does not delete, archive,
migrate, summarize, move, or rewrite classes, assignments, rosters, scans,
reports, results, or templates.

The active school year will support future standards usage workflows. Assignment
creation can attach standards to questions, but creating or attaching standards
during assignment creation does not record standards usage.

ScoreForm-managed assignments use Core 0.5 module-qualified work identity.
For ScoreForm, `assignment_id` is the module-owned `work_id`; another module
may safely reuse the same class/work IDs without collision:

```text
<PDS workspace root>/
  classes/
    english9_p2/
      class.json
      roster.csv
      modules/
        scoreform/
          work/
            rj_act1_quiz/
              assignment.json
              answer_sheets/
                issuances/
                  iss_<32-lowercase-hex>.json
                pages/
                  pg_<32-lowercase-hex>.json
              results.csv
              templates/
                class_packet.pdf
                individual/
                  1001_doe_jane.pdf
                  1002_smith_marcus.pdf
                  1003_brown_alyssa.pdf
              scans/
              debug/
  scans_inbox/
  local_outputs/
```

Assignment discovery inspects only direct children of the exact
`modules/scoreform/work/` collection. It does not recurse, inspect sibling
modules, or fall back to the former unqualified `assignments/` layout. Managed
assignment setup, creation, editing, plain-paper entry, result viewing,
personalized/class-packet generation, and managed regeneration are available.
Generated pages use immutable ScoreForm page records and immutable Core PDS2
route registrations. Retained PDS2 dispatch, issuance assembly, and schema-v2
export and Core-v2 scan-review persistence are active.

**Note:** `<PDS workspace root>/scans_inbox/` is the recommended location for
scans awaiting scoring. Core's canonical retained source is never moved or
deleted. Eligible managed full-success batches may create an assignment-local
copy. In `move` mode, ScoreForm may remove only the verified selected original
that is a direct child of `scans_inbox`; external originals remain untouched.

Generic/manual development outputs are organized under `<PDS workspace root>/local_outputs/` when ScoreForm chooses the default path:

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
      scan_packet_page_2_qr_region.png
      scan_packet_page_2_qr_region_tight.png
      scan_packet_page_2_qr_crop_tight_threshold_padded_5x.png
  qr_batch_summaries/
    YYYY-MM-DD/
      scan_packet_YYYY-MM-DD_HHMM_summary.txt
  temp/
```

Explicit input and output paths supplied by the user are still honored as
written. Workspace routing applies to ScoreForm-managed paths and defaults.

When QR-aware scoring cannot decode a page, ScoreForm saves privacy-minimized
QR-region diagnostic crops under `local_outputs/qr_failures/<date>/` by
default. Full-page QR failure diagnostics are saved only when explicitly
enabled with `PDS_SCOREFORM_FULL_PAGE_DIAGNOSTICS=1`. Each QR-aware scoring run
also saves the terminal batch summary under
`local_outputs/qr_batch_summaries/<date>/` after result-writing status is known.

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
3. Workspace Settings
4. Help
Q. Quit
```

Interactive submenus use the shared Paper Data Suite navigation commands:
`B. Back`, `M. Main Menu`, and `Q. Quit`.

Assignment Management contains assignment creation, editing, and validation,
answer-sheet generation, scanned-response scoring, plain-paper result entry,
read-only routed-results viewing, QR decoding, and scan review. Roster Management
contains roster creation, viewing, editing, and validation.
Workspace Settings can show, set, validate/create, or reset the shared PDS
workspace root using the same `pds-core` operations as the direct CLI. It also
contains School Year Settings for showing, opening, and closing the shared
active school year and **ScoreForm Scan Filing Mode** for choosing `copy`,
`move`, `off`, or the default.

ScoreForm supports two interaction layers:

1. **Direct CLI** exposes stable operations for scripting, testing, automation, development, and power users.
2. **Interactive menu** exposes guided teacher workflows built from those operations.

The layers intentionally do not have one-to-one command parity. Path-oriented setup operations such as `setup-assignment` remain available through `scoreform setup-assignment ...` and `python main.py setup-assignment ...`, but are not shown in the normal teacher-facing menu.

ScoreForm has no historical workspace or result-import feature. Managed work is
discovered only at
`classes/<class_id>/modules/scoreform/work/<assignment_id>/`, and managed
`results.csv` files must already satisfy the exact schema-version-2 contract.
Generation emits PDS2 only; routed scanning parses PDS2 only. PDS1 and OMR1 are
unsupported and cannot produce route identity, page or issuance records, route
registrations, or result rows. Previously printed unsupported sheets must be
replaced with newly generated PDS2 sheets or scored through the separate manual
workflow, which never fabricates route identity.

Select **4. Help** from the menu for a concise workflow guide, routed-results location, and grading-verification reminder.
The interactive menu clears between screens and pauses after important output so generated file paths, validation messages, and scoring summaries remain readable before the next menu redraw.

### Enter Plain-Paper Results

Use **Assignment Management > Enter Plain-Paper Results** when students answered
an A-D assignment on lined, notebook, or other plain paper instead of generated
ScoreForm sheets. Select a class, assignment, and student, then enter `A`-`D`,
`blank`, or `ambiguous` for every response. ScoreForm shows a review and writes
only after `y` or `yes` confirmation; cancellation writes nothing.

Confirmed entries use the assignment answer key and the normal routed
`results.csv`. They receive roster enrichment and the next attempt number from
the existing routed exporter, so scanned and manual attempts can coexist. This
workflow does not create scan evidence, scan artifacts, PDFs, or fabricated
route identity; it is separate from scan review and leaves assignment metadata
and the routed-results header unchanged.

### Resolve QR-Aware Scan Review Items

QR-aware failures are retained as active Core review records under
`scans/review/`. Their canonical source scans remain under
`scans/source/YYYY-MM-DD/`. Teachers can use **Assignment Management > Resolve
Scan Review Items** to view unresolved or deferred items, inspect one item, and
choose manual entry, manual marks, rescan needed, cannot route, mixed assignment,
evidence filed, dismissed duplicate, another documented outcome, or defer.

The direct commands are:

```powershell
scoreform list-scan-review
scoreform list-scan-review --include-resolved
scoreform resolve-scan-review <failure_id> --action rescan_needed
scoreform resolve-scan-review <failure_id> --action cannot_route
scoreform resolve-scan-review <failure_id> --action defer
```

Resolved records are hidden by default; deferred records stay visible. Decisions
are written as immutable Core records under `scans/review/resolutions/`. Failure
records and retained sources are not changed or removed.

Active routed scoring persists exact Core schema-version-2 failure records after
dispatch, assembly, and export are known. Failures are exclusive immutable
occurrences; resolutions are append-only linked events. ScoreForm diagnostics
live under `module_details.scoreform`. Raw decoded payloads are retained exactly,
while route locators and targets are included only when independently validated.
Strict discovery ignores malformed and historical v1 files with warnings and
never rewrites them. Valid attempts remain exported during unrelated partial
failures.

Manual entry is guided by the menu because it requires verified class,
assignment, and student identity plus a complete confirmed answer set. It writes
through the existing routed-results safety path and does not add columns. Its
row uses an immutable review-link marker; the resolution can point to a
non-overwriting assignment-local `_manual_entry` evidence copy. Manual marks
may create a `_manual_marks` copy but do not write a result row. The source must
be a non-symlink regular file
inside the workspace and the assignment must be valid and managed. ScoreForm
flushes the destination, verifies its SHA-256 digest, removes an incomplete
destination on handled failure, and never moves the source. Actions whose Core
contract has no final evidence reject evidence paths. Canonical evidence remains
under `scans/source/YYYY-MM-DD/`.

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
* **Staged editing**: The roster management menu can add students, edit existing non-identity fields, and remove students from the active roster. Changes are staged in memory until you explicitly save them.
* **Validation after save**: The roster is validated using built-in validation logic before reporting success.
* **Exit/cancel support**: Press Ctrl+C to cancel, or leave `student_id` blank after entering at least one student to finish the roster.

### Edit a Roster from the Menu

Select **2. Roster Management**, then **3. Edit class roster** to choose an existing class roster. ScoreForm loads the canonical `classes/<class_id>/roster.csv` through shared `pds-core` roster contracts, displays the current roster, and opens an edit menu for adding a student, editing a student, removing a student from the active roster, viewing staged changes, saving, or canceling.

After editing a roster, existing answer sheets may be out of date. Use **Roster Management > Update generated answer sheets**, or run `scoreform regenerate-sheets`, to rebuild sheets from the current roster and assignment. Regeneration updates print artifacts only: it does not rewrite results or change scans and scan evidence. Older individual PDFs may remain after students are removed or renamed, while the regenerated class packet reflects the current roster.

Roster edits are safe by default:

* Changes are staged in memory until you type `SAVE`.
* Canceling without changes returns directly.
* Canceling with unsaved changes requires typing `DISCARD`; discarded changes are not written.
* Editing does not allow changing `student_id`.
* Removing a student means removing that student from the active roster CSV only. It does not delete generated PDFs, class packets, assignment folders, historical result rows, assignment JSON, scans, or scan evidence.
* Existing optional roster columns are preserved. Add/edit prompts support optional columns already present in the selected roster and do not introduce new optional columns.

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

7. Enter the assignment `question_count` (1-75), then enter answers for Q1 through Q{question_count}. Current choices are A-D only.

8. Choose whether to skip standards or select a PDS Core standards profile, then attach one or more enumerated profile standards to one or more questions.

9. The tool saves the assignment JSON to:

   ```text
   classes/<class_id>/modules/scoreform/work/<assignment_id>/assignment.json
   ```

   and validates it automatically.

Notes:

* Supported `question_count` range is 1-75 and choices remain fixed at A-D.
* Teachers may skip standards during assignment creation. Empty `standards` lists remain valid.
* Standards alignment is profile-first and question-level. A question may have multiple standards, and a standard may be attached to multiple questions.
* Assignment files store durable `standard_id`s only. Shared definitions and profiles are managed in PDS Core; ScoreForm does not author them.
* When `standards_profile_id` is present, shared-library validation checks that the profile exists and that question-level standard IDs belong to that profile.
* Creating or attaching standards during assignment creation does not record standards usage. Usage recording remains future work.
* Overwrite protection requires `y` or `yes` to overwrite existing assignment files.
* Assignment Management also edits and validates assignment JSON files, generates answer sheets, dispatches retained PDS2 pages, displays read-only assignment results, and decodes PDS2 locators.

### Edit an Assignment from the Menu

Select **1. Assignment Management**, then **2. Edit an assignment** to choose an existing class and assignment. ScoreForm loads the selected canonical `classes/<class_id>/modules/scoreform/work/<assignment_id>/assignment.json`, displays a compact summary, and opens an edit menu.

Assignment edits are safe by default:

* Changes are staged in memory until you type `SAVE`.
* Canceling without changes returns directly.
* Canceling with unsaved changes requires typing `DISCARD`; discarded changes are not written.
* Editable fields are `title`, existing answer-key entries, and assignment-local standards alignment.
* Locked fields are `assignment_id`, `question_count`, and `choices`.
* Answer-key editing changes one existing question at a time; it does not add or remove questions.
* Standards editing enumerates the assignment's selected PDS Core profile and can attach or clear IDs on selected questions. ScoreForm does not create shared standards, record standards usage events, write standards usage ledgers, or modify the shared standards library.
* Saving writes only the selected `assignment.json` after validation.
* Editing an assignment does not regenerate answer sheets, rescore scans, rewrite historical results, rewrite QR payloads, delete PDFs, delete scans, alter rosters, or change unrelated assignments.

### View Assignment Results from the Menu

Select **1. Assignment Management**, then **6. View assignment results** to choose a class and assignment and display that assignment's local `results.csv`.

The viewer is read-only. It shows one summary row per student with `Student ID`, `Name`, `Recent`, `Total`, and `Attempts`. If a student has more than one scored row, `Recent` shows the most recent scored attempt by `scan_timestamp` when available, otherwise the last row for that student in `results.csv`; `Attempts` shows how many scored rows exist. ScoreForm does not decide which attempt counts as the grade.

## Schema and File Contracts

ScoreForm-specific artifacts include assignment and answer-key JSON, roster and
result CSVs, QR payload use, generated answer sheets, and question-level standards
metadata. Their current shapes, ownership boundaries, stability, privacy rules,
and versioning policy are documented in
[`docs/schema_contracts.md`](docs/schema_contracts.md).

The examples below are a quick orientation; the contract document is the
authoritative compatibility reference.

## Data Model

Core validates the `module_id`, `class_id`, `work_id`, and `route_id` carried by
PDS2 locators. Student identity is authoritative record data and is never QR
metadata. ScoreForm separately validates roster and workspace path identifiers.

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

Roster CSV files may include additional optional columns, such as `preferred_name`, `email`, or local workflow fields. Optional columns are preserved in each loaded student dictionary, and empty optional values are allowed. The roster creation menu currently writes only the required columns. The roster editing menu preserves existing optional columns and lets teachers update only optional columns already present in the selected roster.

Optional roster fields are not automatically added to `results.csv` or routed result CSVs. Routed results continue to include only roster fields needed for scoring context: `last_name`, `first_name`, and `period`. Avoid storing sensitive or private student information in optional columns unless it is necessary and appropriate under local school or district policy.

### Assignment JSON Format

```json
{
  "assignment_id": "rj_act1_quiz",
  "title": "Romeo and Juliet Act 1 Quiz",
  "question_count": 10,
  "choices": ["A", "B", "C", "D"],
  "layout_id": "standard_15q_abcd_v1",
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
  "standards_profile_id": "english12_2023_njsls",
  "standards": {
    "1": [],
    "2": ["nj_ela_2023_rl_cr_11_12_1"],
    "3": [
      "nj_ela_2023_rl_cr_11_12_1",
      "nj_ela_2023_l_vi_11_12_4"
    ],
    "4": [],
    "5": ["nj_ela_2023_w_aw_11_12_1"]
  }
}
```

The top-level `standards` object is optional assignment metadata. Existing assignment JSON files without `standards` remain valid. When present, standards keys must be valid question numbers for the assignment's `question_count`, and each value must be a list of non-empty shared `standard_id` strings. Empty lists and missing question keys are allowed.

Answer-sheet geometry is selected by the assignment's versioned `layout_id`.
Registered layouts are `standard_15q_abcd_v1` (15 questions per page) and the
supported `compact_25q_abcd_v1` (25 questions per page in 13-left/12-right
columns). Existing assignments without `layout_id` normalize to the standard
default. The layout controls page capacity, registration marks, QR placement,
question boxes, rendering details, and scoring geometry. The generated PDS2
locator does not carry the layout ID; the targeted page record and managed
assignment are the source of truth.

Physical scan validation was completed with a compact 50-question test and a
standard 15-question regression test. Assignment creation offers both layouts
without an environment variable; standard remains the default. Layout is
immutable after assignment creation. Local `.scan-test-workspace/` and
`scan_test/` folders are ignored and must not be committed.

Structural assignment validation checks the assignment shape without loading a standards library. When shared-library validation is requested, `standards_profile_id` must refer to a profile in the `pds-core` workspace standards library, and question-level standard IDs must exist in that library and belong to the selected profile. ScoreForm does not maintain an independent standards universe.

Standards metadata is preserved when assignments are loaded, but it is not written to `results.csv` and does not change scoring behavior, answer-sheet generation, QR payloads, result routing, or roster CSVs. ScoreForm-specific assessment, scoring, reporting, and export behavior remains ScoreForm-owned. Creating or attaching standards during assignment creation does not record standards usage. Usage-event emission and Codex-assisted standards ingestion are future work in the broader Paper Data Suite standards pipeline.

### QR Payload Format

New ScoreForm answer sheets use the shared Paper Data Suite PDS2 locator format:

```text
PDS2|m=scoreform|c=english9_p2|w=rj_act1_quiz|r=rt_0123456789abcdef0123456789abcdef
```

The QR identifies only:

* the Paper Data Suite module
* the class
* the module-owned work (the ScoreForm assignment)
* one fresh, nonsemantic Core route

Student, logical-page, issuance, page-record, layout, and answer-key data are not
encoded. They remain in the immutable ScoreForm page record targeted by the Core
registration. Student name/ID, assignment title, page/question range, full page
ID, and full route ID are printed visibly outside the QR.

Every physical page receives a fresh `pg_...` page ID and independent fresh
`rt_...` route ID. ScoreForm persists the page first, writes and reloads the
immutable Core registration second, and draws Core's canonical serialized
locator only after registration verification. Active scan intake now retains the
source before decoding, parses only Core PDS2 locators, and dispatches each
source page independently through an application-owned installed-module registry.

## Requirements

### Python Dependencies

ScoreForm requires Python 3.11 or newer. Package metadata in `pyproject.toml`
is the authoritative dependency contract, including:

```text
pds-core>=0.5,<0.6
opencv-python
numpy
pdf2image
reportlab
qrcode[pil]
```

`requirements.txt` installs the normal package contract and
`requirements-dev.txt` installs ScoreForm editable with its `dev` extra. They
do not duplicate or override the runtime dependency versions from package
metadata.

For a normal package installation, run:

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

`pds-core>=0.5,<0.6` is a required runtime dependency of ScoreForm. A sibling
repository checkout is not required: pip resolves the compatible Core
distribution through ScoreForm's package metadata.

On Windows, open PowerShell from the `pds-scoreform` repository root. Create
and activate the repo-local virtual environment, then install development
dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

This installs ScoreForm editable, its runtime dependencies (including the
compatible Core distribution), and development tools such as `pytest`, Ruff,
and mypy.

Developers who have a compatible Core checkout may optionally override the
resolved distribution before installing ScoreForm:

```powershell
.venv\Scripts\python.exe -m pip install -e ..\pds-core
.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

The editable checkout must still report a version in `>=0.5,<0.6`.

Install Poppler separately using the Windows method appropriate for the
machine, then confirm `pdftoppm` is available:

```powershell
pdftoppm -h
```

Verify the setup with:

```powershell
.\check_dependencies.ps1
```

If PowerShell blocks script execution, run:

```powershell
powershell -ExecutionPolicy Bypass -File .\check_dependencies.ps1
```

`check_dependencies.ps1` is the local dependency and environment verification
script. It checks Python 3.11+, the installed ScoreForm and Core packages, the
Core version range, `pip check`, third-party imports, and Poppler/`pdftoppm`.
It reports problems but does not install or repair dependencies.

Before treating changes as release-ready, run:

```powershell
.\run_tests.ps1
```

`run_tests.ps1` is the local release-readiness gate. It should pass before a
branch is treated as ready for merge or release-track work. A failing
`run_tests.ps1` means the branch is not release-ready.

### Classroom-Trial Machine Setup

On a classroom-trial machine, activate ScoreForm's virtual environment and run:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

Poppler must also be installed separately as described above.

### Troubleshooting Setup

Run `.\check_dependencies.ps1` from the repository root to confirm the current
runtime/install contract. The script is diagnostic only: it does not install
packages, create virtual environments, clone repositories, or repair files.

If `pds_core` is not importable or its installed distribution version is
outside `>=0.5,<0.6`, rerun the development installation using
`.venv\Scripts\python.exe`. No particular parent-directory layout is required.

If ScoreForm starts with the wrong Python interpreter, confirm that commands
are using `.venv\Scripts\python.exe` or the `scoreform` command installed into
that virtual environment. The dependency check intentionally uses the repo-local
virtual environment directly.

If Poppler or `pdftoppm` is missing, PDF scoring and conversion will fail.
Install Poppler separately and make sure its `bin` directory is on `PATH`.

If a third-party import such as `cv2`, `numpy`, `reportlab`, `PIL`, or
`pdf2image` is missing, rerun the development install command above. If
PowerShell blocks scripts, use:

```powershell
powershell -ExecutionPolicy Bypass -File .\check_dependencies.ps1
```

## Basic Usage

The command-line interface is still evolving. Current commands may change before the first stable release.

Use `scoreform --help`, `scoreform -h`, or `scoreform help` to show available commands, examples, and scoring mode notes. Use `scoreform --version` or `scoreform version` to print the installed package version.

The current direct-CLI, menu, workspace, path, exit-code, packaging, and
backward-compatibility expectations are defined in
[`docs/cli_contract.md`](docs/cli_contract.md).

### Workspace Commands

Show the resolved root, resolution source, filesystem status, shared config
path, and default root:

```powershell
scoreform workspace show
```

Set a preferred workspace folder:

```powershell
scoreform workspace set "C:\Users\teacher\OneDrive - District Name\Paper Data Suite"
```

Validate the current root, creating it and its workspace metadata when needed:

```powershell
scoreform workspace validate
```

Clear the saved preference without deleting user data:

```powershell
scoreform workspace reset
```

Explicit input and output paths supplied to other ScoreForm commands remain
honored. Changing the shared workspace affects ScoreForm-managed defaults and
routed data only; it does not move existing files.

### Scan Workflow

Scanned PDFs and images should be placed in the workspace `scans_inbox/` folder:

```text
scans_inbox/
  class_packet_2026_05_24.pdf
  mixed_scan.pdf
```

The program creates this folder under the resolved PDS workspace root. From the
terminal menu, **Score scanned responses** can select a scan for retained PDS2
dispatch. The workflow accepts `.pdf`, `.png`, `.jpg`, `.jpeg`, `.tif`, and
`.tiff` (not BMP), retains the source once, assembles complete issuances, and
exports schema-v2 results and persists actionable Core-v2 scan-review failures.

Core creates one canonical retained copy for each invocation and never alters
it. Eligible single-target managed full-success batches follow the configured
`copy`, `move`, or `off` filing policy. Partial, mixed-module, multi-target,
explicit-output, missing, duplicate, conflicting, and export-failure batches do
not auto-file. Manual scoring remains available and may accept BMP by custom
path even though the PDS2 inbox picker excludes BMP.

ScoreForm module handlers may write their documented module-owned diagnostic
images. Missing-QR diagnostics use collision-safe retained provenance names;
successful paths and diagnostic-write warnings are preserved in the immutable
page outcome. Manual answer-key output remains under `local_outputs/`.

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

Supported retained PDS2 input file types are:

```text
PDF
PNG
JPG/JPEG
TIFF/TIF
```

Recommended workflow:

1. Place scanned files in `scans_inbox/`.
2. Use generated class packets or individual student PDFs when possible.
3. Prefer retained PDS2 page dispatch for generated sheets.
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

ScoreForm saves module-owned debug images during page handling. Manual answer-key
scoring writes under `local_outputs/debug/`; the ScoreForm PDS2 handler may
write scoring diagnostics under its authoritative work `debug/` directory.
This does not imply that routed results were exported.

ScoreForm is local-first, but scans, diagnostic images, result CSVs, files under
`local_outputs/`, and class assignment
output folders may still contain student records and should not be shared
publicly. QR failure diagnostics default to cropped QR-region images rather
than full-page scans. Developers can explicitly enable a full-page failure
image for troubleshooting by setting
`PDS_SCOREFORM_FULL_PAGE_DIAGNOSTICS=1`; this debug option is not intended for
normal classroom use. Result CSV `source_file` values are privacy-minimized as
described above, but result files still contain student and assessment data.
Treat all generated artifacts and output folders as sensitive.

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

Generic template generation without an assignment writes to
`<PDS workspace root>/local_outputs/templates/` by default:

```powershell
scoreform generate
```

### Decode a QR Code From a File

```powershell
scoreform decode-qr path\to\file.pdf
```

The command retains the source first, enumerates retained pages, and parses raw
QR text only with Core's strict PDS2 parser. It reports module, class, work, and
route plus Core's canonical serialization. PDS2 carries no student, logical
page, question range, layout, answer key, or result destination. A locator for
an uninstalled module is still a valid decode because this command does not
build a registry or dispatch.

For scoring, the application builds a fresh installed-module registry and
requires the ScoreForm profile before retention. Every valid locator becomes an
exact Core `RouteDispatchRequest`; Core dispatches them in source-page order.
ScoreForm preserves its immutable page results, while successes belonging to
other installed modules remain opaque. Unknown modules remain normal Core
dispatch failures and do not stop later valid pages.

### Score a Scanned File

```powershell
scoreform score path\to\scan.pdf
```

QR-aware one-argument scoring retains and dispatches PDS2 pages, groups successful
ScoreForm pages only by authoritative issuance ID, and appends one schema-v2 row
for every complete and unambiguous print copy. Missing or duplicate pages never
produce a partial row. Core retained sources remain under
`scans/source/YYYY-MM-DD/`; eligible full-success managed batches may also file
an assignment-local copy according to the `copy`, `move`, or `off` preference.

QR-aware scoring uses these batch outcomes and exit codes:

* **Full success** means every page dispatched, every ScoreForm issuance assembled,
  and every attempt was appended or already present; it exits `0`.
* **Dispatch-only success** means every page belongs to foreign modules; it exits `0`.
* **Partial success** means at least one but not all pages dispatched
  successfully; it exits nonzero.
* **Zero success** means no page dispatched successfully; it exits `1`.
* **Integration failure** means Core returned outcomes that contradicted their
  requests or ScoreForm returned the wrong result type; it exits `1`.
* **File or registry failure** exits `1`; after retention, exact retained
  provenance remains present in the immutable result.

The terminal summary reports dispatch, assembly, appended/already-present
attempts, and export failures. Assembly and export failures remain immutable in
memory; the complete routed-scoring batch persists reviewable occurrences afterward.

QR-aware scoring supports an explicit schema-v2 output history:

```powershell
scoreform score scanned_file.pdf qr_metadata_results.csv
```

Manual answer-key scoring can use the default local results path:

```powershell
scoreform score scanned_file.pdf examples\answer_key.json
```

Explicit output paths are honored:

```powershell
scoreform score scanned_file.pdf results.csv examples\answer_key.json
```

Manual scoring reports pages processed, pages scored, and pages
failed/skipped when failures occur or a multi-page batch is processed. A
partial manual batch may export successful rows, but ScoreForm warns that the
results may be incomplete. A zero-success manual batch fails clearly. Manual
scoring never files a scan copy automatically.

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
v0.9.0  Project organization, project-root planning, scan filing, and data-lifecycle design
v1.0.0  Stable classroom-ready release
```

## Testing

ScoreForm now includes fast development checks and a full packaging/regression workflow.

### Fast Development Checks

Use this during normal development:

```powershell
.\run_fast_tests.ps1
```

This runs Ruff, the pytest suite, `git diff --check`, and a Git tracking check
that verifies generated/private artifact paths such as `classes/`,
`local_outputs/`, and `scans_inbox/` are not tracked.

Run linting directly with:

```powershell
python -m ruff check .
```

### Type Checking

ScoreForm includes initial mypy tooling for gradual typing. The configuration
is intentionally cautious while the older operational codebase is brought
under type checking incrementally; stricter typing is future incremental work.

After installing `requirements-dev.txt`, run the repository helper:

```powershell
.\run_type_checks.ps1
```

Or run the same check directly with the repository virtual environment:

```powershell
.\.venv\Scripts\python.exe -m mypy scoreform
```

Mypy is development tooling only and is not required for ordinary ScoreForm
use. Type checking remains separate from `run_tests.ps1`; the full regression
gate does not currently run mypy.

### Full Regression Checks

`run_tests.ps1` is the local release-readiness gate. Run it before opening a
PR, merging, releasing, or treating release-track work as ready:

```powershell
.\run_tests.ps1
```

This installs ScoreForm in editable mode with development extras, runs the
pytest suite, and verifies the full packaging, CLI, generation, validation,
QR-aware scoring, routed results, duplicate/attempt handling, and menu workflow
behavior. A failing run means the branch is not release-ready. The current
passing test count is reported by pytest rather than hardcoded here.

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
* The current optical layout remains fixed at 15 questions per physical page; compact 25-question pages are not implemented.
* Manual answer-key scoring writes default debug images to `local_outputs/debug/`, while routed PDS2 scoring uses assignment debug folders.
* Duplicate/attempt handling preserves repeated routed scans, but gradebook export rules for latest/highest/selected attempts are not implemented yet.
* Overwrite/collision protection prevents mismatched assignment JSON files from overwriting existing assignment folders, but an explicit replacement workflow has not been implemented yet.
* QR preprocessing improves many real-world phone scans, but severe blur, glare,
  cropping, or rotation can still prevent detection.

## Design Principles

ScoreForm is being designed around the following principles:

* Keep the tool local-first.
* Avoid requiring paid services.
* Keep classroom data under the teacher's control.
* Make generated files predictable and organized.
* Keep explicit manual scoring separate from registered PDS2 routing identity.
* Prefer simple, inspectable file formats such as CSV and JSON.
* Build toward a teacher-friendly workflow without adding unnecessary complexity too early.
* Avoid hardcoded assumptions that would prevent future multi-page forms.

### Interactive Menu Screen Policy

ScoreForm's terminal menu is designed for teacher use during classroom and
preparation workflows. Screen clearing is the default between interactive
workflow steps. ScoreForm keeps information on screen only when it is essential
for the teacher to complete the current action.

Menus redraw with the current workflow title, relevant selected context, current
options, and short status messages. Long lists appear when the teacher is
selecting from them, rather than after every completed action. Generated file
paths, scoring summaries, warnings, and destructive-action confirmations remain
visible until the teacher has had a chance to read or respond to them.

Selection lists are temporary screens. After a valid selection, ScoreForm clears
the terminal before displaying the next object, list, confirmation, result, or
detail screen. The selected item is carried forward as compact context instead
of leaving the prior list and prompt visible as terminal transcript.

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

## Installed Core 0.5 module boundary

The distribution contributes the zero-argument entry point
`paper_data_suite.modules: scoreform = scoreform.pds_module:get_module_profile`.
Its immutable profile advertises Core routing contract `1`, QR schema `PDS2`,
route-registration schema `1`, and only the `active` route status. Discovery
does not resolve a workspace, build a global registry, or import sibling PDS
modules.

The profile's pure registration validator requires an `answer_sheet_page` v1
target, exact `issuance_id`/`logical_page`/`total_pages` module details, and the
exact ScoreForm human-fallback line. It performs no record or filesystem reads.
The handler separately verifies canonical Core roots, loads the authoritative
page and complete issuance, permits only lifecycle status `issued`, and checks
the current managed assignment against the printed layout. The current answer
key is scoring authority; assignment-title-only changes are allowed.

Each dispatch extracts only the requested retained image or PDF source page and
returns one immutable page result. A retained source page number is independent
of the answer sheet's logical page. PDS2 batch page dispatch is active; attempt
assembly/export and review persistence are active.
# Multi-page assessments

ScoreForm generates 1-75-question assignments with the registered 15-question
standard or 25-question compact physical layout. Student PDFs and class packets
contain as many pages as needed, in student-then-page order. Each generated PDS2
QR identifies a fresh route to an immutable page record whose `logical_page` and
question range provide page context. Multi-page scans are dispatched in
source-page order without assembling attempts.
