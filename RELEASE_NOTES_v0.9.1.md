# ScoreForm v0.9.1

ScoreForm v0.9.1 completes the PDS Core 0.5/PDS2 migration. Managed work is now
module-qualified, every routable physical page has durable issuance/page/route
identity, retained scans dispatch through Core's installed module registry, and
complete attempts export routed-results schema version 2.

> **Compatibility warning**
>
> PDS1 and OMR1 sheets are unsupported. Historical schema-v1 routed-result
> files are not migrated. Previously printed legacy sheets cannot be assigned
> fabricated PDS2 routes. Generate new v0.9.1 PDS2 answer sheets for routed
> scanning.

## Highlights

- Canonical work lives under
  `classes/<class_id>/modules/scoreform/work/<assignment_id>/`.
- Immutable page and issuance records plus unique Core registrations exist
  before PDS2 locators are rendered.
- The installed `paper_data_suite.modules` entry point supplies ScoreForm's
  side-effect-free profile and route handler.
- Core retains source bytes before QR decoding and dispatches source pages in
  order; ScoreForm does not inspect foreign-module semantics.
- Standard and compact one-page and multi-page sheets are active.
- Complete pages assemble by issuance identity; missing, duplicate,
  conflicting, or mixed-issuance sets produce no invalid attempt.
- Schema-v2 results preserve aligned route, page, logical-page, source-page,
  retained-path, source-scan, digest, and intake provenance.
- New managed results place teacher identity, score, total, and contiguous
  question pairs before audit metadata. Earlier pre-release v2 column order is
  read exactly and normalizes atomically on the next successful export.
- Byte-identical PDS2 intake is idempotent by `source_sha256 + issuance_id`,
  even after rename or a new retention event; retained and filed source copies
  remain audit evidence rather than result-attempt identity.
- Core schema-v2 failure records and append-only resolutions support the scan
  review workflow.
- Manual answer-key scoring and plain-paper entry remain available as separate,
  route-free workflows.
- Copy, move, and off filing modes preserve Core's retained source.

## Additional teacher workflows and hardening

- Assignment Management now supports staged assignment editing, per-question
  answer-key changes, standards alignment, read-only results viewing, and
  plain-paper result entry without silently regenerating sheets or rewriting
  historical attempts.
- Roster Management supports staged add, edit, and remove operations through
  shared Core roster APIs while preserving optional columns and historical
  classroom artifacts.
- Workspace controls can show, open, and close the shared active school year.
- Successful interactive generation can open the class packet or individual
  sheet folder after asking; regeneration and blank-template workflows expose
  corresponding local-output actions. Direct commands remain noninteractive.
- Assignment creation and editing integrate with the shared standards library;
  ScoreForm also provides side-effect-free standards-usage event construction
  and a separate explicit recording helper.
- Scan-review workflows persist actionable Core schema-v2 failures and support
  append-only defer and resolution records.
- Copy, move, and off filing modes apply only their documented safe operations,
  preserve Core's retained source, and avoid filing partial or mixed-target
  batches.
- Diagnostics and exported source values are privacy-minimized by default, and
  routed/manual failure accounting distinguishes complete, partial, zero-result,
  and export-failure outcomes.
- Packaging and release validation now cover dependency consistency, static and
  regression checks, artifact contents and metadata, clean noneditable wheel
  and source-distribution installs, installed profile discovery, and end-to-end
  release smokes.

## Breaking removals and upgrade guidance

This release removes active PDS1/OMR1 handling, QR-carried ScoreForm semantics,
unqualified work-root discovery, schema-v1 result migration, `legacy_scan`,
generic migration gates, and obsolete QR compatibility APIs. Move current
assignment configuration into canonical module-qualified work through supported
setup workflows and generate new v0.9.1 PDS2 sheets. Keep historical files as
read-only records; ScoreForm will not fabricate new identity for them.

## Installation

Obtain `pds_core-0.5.0-py3-none-any.whl` from the verified PDS Core `v0.5.0`
GitHub Release and obtain `scoreform-0.9.1-py3-none-any.whl` from the ScoreForm
release. Install both noneditably in a fresh Python 3.11+ environment:

```powershell
python -m pip install .\pds_core-0.5.0-py3-none-any.whl
python -m pip install .\scoreform-0.9.1-py3-none-any.whl
python -m pip check
```

ScoreForm declares `pds-core>=0.5,<0.6`, but pip cannot download Core 0.5.0
from PyPI because Core was not published there. A sibling editable Core checkout
is optional for development only. Normal release installation uses the two
independent wheels, and the ScoreForm release neither repackages nor bundles
Core.

## Known limitations

ScoreForm remains pre-1.0. Physical scan quality, printer scaling, lighting,
focus, alignment, and camera/scanner processing affect detection reliability.
Teachers must manually verify results before recording grades. ScoreForm does
not choose an official attempt or grade. This release does not add a gradebook
or LMS export.

## Privacy

Generated sheets, packets, rosters, assignments, original and retained scans,
filed copies, results, review metadata, evidence, and diagnostics may contain
sensitive student information. Keep them out of source control and follow
applicable school, district, state, and federal privacy requirements.

## Validation status

The prior candidate validation predates these teacher-workflow corrections and
is not the final release gate. The required order is focused automated testing,
complete diff review, project-owner normal-use menu rehearsal from source,
generated-PDF visual inspection, merge, authoritative release gate, clean build
and hashes, clean noneditable installation, installed-menu smoke, and then the
project-owner physical paper test. Python 3.11 validates the minimum supported
version; owner menu and paper testing may use any interpreter satisfying
`Python >=3.11`, with the exact version recorded.

Physical-paper acceptance remains pending. The project owner—not Codex—must
complete and adjudicate the documented real printed workflow with the exact
reviewed wheel and explicitly authorize publication. Release publication is
blocked until then.
