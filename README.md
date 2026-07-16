# ScoreForm

ScoreForm is a local-first classroom OMR tool for generating printable answer
sheets and scoring scanned multiple-choice responses through Paper Data Suite
Core.

Current version: `0.9.1`.

ScoreForm is pre-1.0. Scan quality affects reliability, and teachers must
manually verify results before recording grades. It is not a gradebook, does not
choose the official attempt or grade, and does not provide LMS export.

## Release contract

- Python: 3.11 or newer
- PDS Core: `pds-core>=0.5,<0.6`
- Core routing contract: `1`
- QR payload schema: `PDS2`
- route-registration schema: `1`
- routing-failure and scan-resolution schemas: `2`
- module entry-point group: `paper_data_suite.modules`
- module ID: `scoreform`
- routed-results schema: `2`

The v0.9.1 release process tests Python 3.11 in CI and the locally reported
interpreter used by the Windows release gate. The package metadata intentionally
retains `requires-python = ">=3.11"`; additional interpreter results must be
reported rather than assumed.

## Installation

PDS Core 0.5.0 is distributed through the verified PDS Core `v0.5.0` GitHub
Release; it was not published to PyPI. Download its wheel and the ScoreForm
wheel, create and activate a Python 3.11+ virtual environment, install Poppler
so `pdftoppm` is available for PDF scans, then install both distributions
noneditably:

```powershell
python -m pip install .\pds_core-0.5.0-py3-none-any.whl
python -m pip install .\scoreform-0.9.1-py3-none-any.whl
python -m pip check
scoreform --version
scoreform --help
```

ScoreForm's dependency metadata enforces `pds-core>=0.5,<0.6`, but pip cannot
download Core 0.5.0 from PyPI. A compatible Core wheel must be available to pip
before ScoreForm is installed. ScoreForm's GitHub Release does not repackage or
bundle Core.

Development installation:

```powershell
python -m pip install -e ".[dev]"
```

A sibling editable Core checkout is optional for development only. A normal
release installation uses noneditable Core and ScoreForm wheels. Coordinated
local release testing builds Core as a separate wheel and validates that
ScoreForm neither imports from the sibling source checkout nor bundles Core.

## Current architecture

### Module-qualified work

The canonical managed-work root is:

```text
classes/<class_id>/modules/scoreform/work/<assignment_id>/
```

ScoreForm never discovers the removed unqualified assignment tree. Work with
the same class and work IDs can coexist beneath another module without
collision.

### Registered PDS2 sheets

Every routable generated page has an immutable issuance record, immutable page
record, unique Core route registration, verified target, and canonical PDS2
locator before the QR is rendered. The QR carries locator identity only.
Student, layout, logical page, question range, answer key, attempt identity, and
result destination are loaded from authoritative records.

Individual sheets and class-packet copies receive separate artifact, issuance,
page, and route identities. Regeneration creates fresh identities, supersedes an
eligible predecessor, and preserves historical records.

### Installed PDS module

ScoreForm exposes:

```text
paper_data_suite.modules
    scoreform = scoreform.pds_module:get_module_profile
```

PDS Core discovers the side-effect-free zero-argument provider. Its profile
supports routing contract `1`, PDS2, registration schema `1`, and active routes.
ScoreForm production code imports no sibling-module implementation; foreign
dispatch results remain opaque.

### Retained scanning and results

Core retains the original source bytes under
`scans/source/YYYY-MM-DD/` before QR parsing or module dispatch. ScoreForm reads
the retained page, validates the registered immutable target, scores it, and
assembles complete attempts by issuance identity. Source page number and logical
page number remain distinct.

Standard and compact layouts are active for one-page and multi-page
assessments. Complete, unambiguous attempts write schema-v2 results with aligned
route, page, logical-page, source-page, retained-path, source-scan, digest, and
intake provenance. Incomplete, duplicate, conflicting, mixed-issuance, or
malformed page sets do not produce invalid rows. Rescanning in a later intake
creates a new attempt; repeating export for the same intake and issuance is
idempotent.

### Scan review and filing

Failures are immutable Core schema-v2 records under `scans/review/`; teacher
decisions are append-only schema-v2 resolutions under
`scans/review/resolutions/`. The workflow supports route correction, manual
entry or marks, rescan-needed, cannot-route, mixed-assignment, evidence-filed,
dismissed-duplicate, other, and defer decisions.

Assignment-local scan filing supports:

- `copy`: verified non-overwriting copy; original and retained source remain.
- `move`: only an eligible selected file directly under `scans_inbox/` may be
  removed after digest verification; the retained source remains.
- `off`: no assignment-local copy; Core retention remains active.

Partial, mixed-module, multi-target, explicit-output, duplicate, conflict, and
export-failure batches do not file automatically.

## Commands

Run `scoreform` with no arguments for the teacher menu. Important direct
commands include:

```text
scoreform generate
scoreform generate <assignment.json> --rosters <roster.csv> [more rosters...]
scoreform regenerate-sheets --class-id <class_id> --assignment-id <assignment_id>
scoreform decode-qr <scan.pdf-or-image>
scoreform score <scan.pdf-or-image>
scoreform list-scan-review [--include-resolved] [--limit <n>]
scoreform resolve-scan-review <failure_id> --action <action>
scoreform validate-assignment <assignment.json>
scoreform validate-roster <roster.csv>
scoreform setup-assignment <assignment.json> <roster.csv>
scoreform workspace show|set|validate|reset
scoreform school-year show|open|close
scoreform scan-filing show|set|reset
scoreform --help
scoreform --version
```

`python main.py` remains a direct-source compatibility wrapper.

### Routed PDS2 scoring

```powershell
scoreform score .\scans_inbox\class_packet.pdf
scoreform score .\scan.pdf .\explicit_results.csv
```

The default routed destination is:

```text
classes/<class_id>/modules/scoreform/work/<assignment_id>/results.csv
```

Full success and foreign-only success exit zero. Partial, zero-success, export,
file, and integration failures exit nonzero. A partial batch may export an
unrelated complete issuance, but no incomplete attempt is written.

### Manual answer-key scoring

Manual scoring is intentionally route-free:

```powershell
scoreform score <scan> <answer_key.json>
scoreform score <scan> <output.csv> <answer_key.json>
```

It supports the image/PDF types reported by `scoreform --help`, including the
documented BMP behavior. It creates no PDS2 locator, route, issuance, retained
routed provenance, or automatic assignment-local filing. Partial successful
rows follow the manual policy; zero successes fail.

### Plain-paper entry

The Assignment Management menu can enter teacher-verified plain-paper results.
These rows use `result_origin=plain_paper_manual`, `Page=manual`, and
`source_file=plain_paper_manual_entry`, share attempt numbering, and contain no
route, page, issuance, source-scan, scan artifact, or review identity.

## Breaking compatibility boundary

PDS1 and OMR1 sheets are unsupported. Historical schema-v1 routed-result files
are not migrated. Previously printed legacy sheets cannot be assigned fabricated
PDS2 routes. Generate new v0.9.1 PDS2 answer sheets for routed scanning.

Unsupported payloads may be preserved as exact evidence in a current Core-v2
review record, but create no locator, request, target, registration, page,
issuance, or result identity.

## Validation

Fast developer precheck:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_fast_tests.ps1
```

Authoritative local release-readiness gate:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_tests.ps1
```

The full gate performs dependency checks, compilation, Ruff, mypy, full and
focused pytest, installed CLI/E2E smoke tests, wheel and source-distribution
builds, `twine check`, artifact-content inspection, noneditable clean installs,
installed profile discovery, import/help/version side-effect checks, and Git
diff hygiene. `.github/workflows/release-readiness.yml` provides nonpublishing
Python 3.11 Linux validation.

A real printed two-page standard-layout test using the reviewed wheel is a
separate mandatory release gate. See `docs/physical_acceptance_test.md`.

## Privacy and generated data

Treat every roster, assignment, generated personalized sheet, packet, source
scan, retained scan, filed copy, result CSV, review record, resolution record,
evidence file, diagnostic image, and local output as potentially sensitive.
Do not commit real student names or IDs, rosters, filled sheets, scans, results,
diagnostics, or private school documents. Public examples and tests must remain
synthetic.

Common sensitive workspace locations include:

```text
classes/
scans_inbox/
scans/source/
scans/review/
classes/<class_id>/modules/scoreform/work/<assignment_id>/templates/
classes/<class_id>/modules/scoreform/work/<assignment_id>/scans/
classes/<class_id>/modules/scoreform/work/<assignment_id>/debug/
classes/<class_id>/modules/scoreform/work/<assignment_id>/results.csv
local_outputs/
```

Follow applicable school, district, state, and federal privacy requirements.

## Release documents

- `CHANGELOG.md` — factual release history
- `ROADMAP.md` — current direction and historical milestone summary
- `docs/cli_contract.md` — command and exit-code contract
- `docs/schema_contracts.md` — persisted schema contract
- `docs/release_checklist.md` — preparation and publication gates
- `docs/physical_acceptance_test.md` — mandatory paper procedure
- `RELEASE_NOTES_v0.9.1.md` — reviewed GitHub Release body
