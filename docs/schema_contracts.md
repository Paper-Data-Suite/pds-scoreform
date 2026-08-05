# ScoreForm Schema and File Contract

The active immutable publication projection is specified separately in
[`academic_result_manifest_v1.md`](academic_result_manifest_v1.md). That pure
ScoreForm-owned contract is implemented, but workspace manifest generation and
Core publication are not yet implemented.
Its stable production identity and immutable revision-transition rules are in
[`publication_revision_policy.md`](publication_revision_policy.md). The policy
is active and pure; manifest generation and Core publication, supersession, and
withdrawal commands remain future work.

ScoreForm Academic Work Registration is defined in
[`academic_work_registration.md`](academic_work_registration.md). Its exact
mapping fixes `module_id="scoreform"`, producer contract
`scoreform_academic_work_v1`, work kind `assignment`, and one source record with
`record_kind="assignment"` and `contract_version=None`. The title is a snapshot
from canonical `assignment.json`; academic intent and lifecycle are explicit.
The native assignment JSON remains unversioned and its shape is unchanged.

> v0.9.1 current-only boundary: managed work is module-qualified, generated and
> scanned routed sheets use PDS2, routed results use schema version 2, and Core
> failure/resolution metadata uses schema version 2. Historical PDS1/OMR1 and
> schema-v1 routed-result data is unsupported and is not migrated.

## Status categories

This document describes the files and metadata that ScoreForm currently reads or
writes. The labels below distinguish interoperability commitments from current
implementation choices during pre-1.0 development.

* **Stable-enough current contract**: relied on by current workflows and should
  change only with an explicit compatibility decision.
* **Provisional pre-1.0 contract**: useful current behavior that may change before
  1.0 with documentation and migration consideration.
* **Shared pds-core-owned contract**: defined by PDS Core and consumed by
  ScoreForm rather than independently specified here.
* **Internal implementation detail**: not an integration surface.
* **Future / not yet implemented**: a possible contract that does not exist yet.

## 1. Scope and ownership

This is the ScoreForm-specific contract for assessment files, generated answer
sheets, scoring results, and the metadata connecting them. It documents how
ScoreForm consumes shared records without redefining their shared schemas.

PDS Core owns workspace-root configuration and resolution, canonical class and
assignment routes, shared roster validation, standards-library and standards-
profile definitions, strict PDS2 parsing/serialization, route locators, dispatch
requests/outcomes, and retained-source provenance. Those are **shared
pds-core-owned contracts**.

ScoreForm owns its assignment JSON expectations, answer-key representation,
question-level use of standards metadata, answer-sheet layout used by its scorer,
result output, QR routing requirements, and `source_file` and attempt metadata.
These ownership boundaries do not authorize ScoreForm to create or edit shared
standards.

## 2. Assignment JSON contract

**Status: Stable-enough current shape; versioning is provisional pre-1.0.**

```json
{
  "assignment_id": "coming_of_age_quiz",
  "title": "Coming-of-Age Short Story Quiz",
  "question_count": 5,
  "choices": ["A", "B", "C", "D"],
  "layout_id": "standard_15q_abcd_v1",
  "answer_key": {
    "1": "A",
    "2": "C",
    "3": "D",
    "4": "B",
    "5": "A"
  },
  "standards_profile_id": "english10_2023_njsls_ela",
  "standards": {
    "1": ["njsls-ela:RL.CR.9-10.1"],
    "2": [
      "njsls-ela:RL.CR.9-10.1",
      "njsls-ela:RL.CI.9-10.2"
    ],
    "3": [],
    "4": ["njsls-ela:L.VI.9-10.4"],
    "5": []
  }
}
```

The required fields are `assignment_id`, `title`, `question_count`, `choices`,
and `answer_key`. `layout_id`, `standards_profile_id`, and `standards` are
optional input metadata; normalized assignments always include `layout_id`.

* `assignment_id` must be a safe identifier accepted by ScoreForm validation.
* `title` must be a non-empty string.
* `question_count` must be an integer from 1 through `MAX_QUESTION_COUNT`,
  currently 75.
* `choices` must equal exactly `["A", "B", "C", "D"]`.
* Missing `layout_id` normalizes to `standard_15q_abcd_v1`. When present it must
  be a non-empty supported layout ID, and `choices` must match that layout.
* `answer_key` must have exactly one entry for every question from 1 through
  `question_count`. Values are trimmed, normalized to uppercase, and must be A,
  B, C, or D.
* Missing `standards`, and missing question keys within it, normalize to an empty
  standards list for every affected question. Explicit empty lists are valid.
* Each non-empty standard ID must be a non-empty string. Duplicate standard IDs
  on one question are invalid.
* Standards-aware shared-library validation requires `standards_profile_id` when
  any non-empty standards list is attached.

ScoreForm assignment JSON is currently unversioned. Validation is shape-based,
not schema-version-based. Adding `schema_version` requires a separate migration
and compatibility decision. Normalization discards unknown fields; they are not
part of this contract and must not be used for interoperability or assumed to be
preserved.

## 3. Answer key JSON contract

**Status: Stable-enough current contract for manual answer-key scoring.**

```json
{
  "1": "A",
  "2": "C",
  "3": "D",
  "4": "B",
  "5": "A"
}
```

The file must contain a JSON object. Keys are question numbers contiguous from 1
through the highest question (no gaps), with no more than 15 questions. Values
are trimmed, normalized to uppercase, and must be A, B, C, or D. This format has
no assignment metadata. It supports the separate manual scorer; validated
assignment JSON is authoritative for routed PDS2 workflows.

## 4. Roster CSV contract

**Status: Core validation is shared pds-core-owned; ScoreForm consumption is
stable-enough current behavior.**

```csv
class_id,student_id,last_name,first_name,period
english10_p2,01001,Rivera,Avery,2
english10_p2,01002,Patel,Mina,2
```

PDS Core requires the five displayed columns, non-empty required values, one
consistent `class_id`, and unique `student_id` values within the roster. Extra
columns may be present and are preserved in ScoreForm's loaded student
dictionaries. ScoreForm uses `student_id` to match routed results and writes only
`last_name`, `first_name`, and `period` as roster enrichment; extra roster columns
are not automatically exported.

Roster CSV validation is shared PDS Core behavior. ScoreForm documents only how
it consumes validated roster data for sheet generation and results.

## 5. Standards metadata contract

**Status: ScoreForm attachment shape is stable-enough; definitions and profiles
are shared pds-core-owned contracts.**

Standards attach to individual questions. A question may have multiple standards,
and the same standard may appear on multiple questions. ScoreForm persists durable
`standard_id` strings in `standards` and the selected `standards_profile_id`;
shared definitions and profiles remain in the PDS Core standards library.
ScoreForm does not create or edit shared standards.

When all question lists are empty, `standards_profile_id` may be absent. When any
standard is attached, standards-aware validation requires a profile, and every
attached ID must belong to it. Standards metadata does not affect scoring, QR
payloads, sheet generation, result routing or headers, or roster CSVs.

## 6. Answer-sheet issuance and physical-page records

**Status: Stable, versioned ScoreForm-owned v1 contract.**

A **generation** is one user-invoked operation. An **artifact** is one intended
PDF file. An **issuance** is one printable copy for one class, assignment, and
student. A **page** is one physical page within that issuance. Their independent,
nonsemantic identifiers are:

```text
generation_id: gen_<32 lowercase hexadecimal characters>
artifact_id:   art_<32 lowercase hexadecimal characters>
issuance_id:   iss_<32 lowercase hexadecimal characters>
page_id:       pg_<32 lowercase hexadecimal characters>
```

Each suffix contains 128 bits of cryptographically secure random material. IDs
encode no names, timestamps, filenames, or logical page numbers and are never
reused. Existing destinations are collisions even when their contents match.

Records are direct descendants of the exact module-qualified work root:

```text
classes/<class_id>/modules/scoreform/work/<assignment_id>/answer_sheets/
  issuances/<issuance_id>.json
  pages/<page_id>.json
```

Core owns `routes/`; ScoreForm page records never live there.

The exact issuance v1 shape is:

```json
{
  "schema_version": "1",
  "issuance_id": "iss_0123456789abcdef0123456789abcdef",
  "generation_id": "gen_0123456789abcdef0123456789abcdef",
  "artifact_id": "art_0123456789abcdef0123456789abcdef",
  "class_id": "english9_p2",
  "assignment_id": "rj_act1_quiz",
  "student_id": "1001",
  "generation_context": {
    "output_kind": "individual_pdf",
    "reason": "initial",
    "predecessor_issuance_id": null
  },
  "assignment_snapshot": {
    "title": "Romeo and Juliet Act 1 Quiz",
    "question_count": 20,
    "layout_id": "standard_15q_abcd_v1",
    "choices": ["A", "B", "C", "D"]
  },
  "student_snapshot": {
    "last_name": "Doe",
    "first_name": "Jane",
    "period": "2"
  },
  "page_count": 2,
  "page_ids": [
    "pg_0123456789abcdef0123456789abcdef",
    "pg_fedcba9876543210fedcba9876543210"
  ],
  "lifecycle": {
    "status": "prepared",
    "revision": 1,
    "created_at": "2026-07-15T01:30:00+00:00",
    "updated_at": "2026-07-15T01:30:00+00:00",
    "issued_at": null,
    "ended_at": null,
    "reason": null,
    "replacement_issuance_id": null
  }
}
```

`output_kind` is `individual_pdf` or `class_packet_pdf`. Generation reason is
`initial`, `additional_copy`, or `regeneration`. Only regeneration names a
different predecessor issuance. Preparing a regeneration does not mutate or
supersede its predecessor.

The exact immutable page v1 shape is:

```json
{
  "schema_version": "1",
  "page_id": "pg_0123456789abcdef0123456789abcdef",
  "issuance_id": "iss_0123456789abcdef0123456789abcdef",
  "generation_id": "gen_0123456789abcdef0123456789abcdef",
  "artifact_id": "art_0123456789abcdef0123456789abcdef",
  "class_id": "english9_p2",
  "assignment_id": "rj_act1_quiz",
  "student_id": "1001",
  "logical_page": 1,
  "total_pages": 2,
  "question_start": 1,
  "question_end": 15,
  "assignment_question_count": 20,
  "layout_id": "standard_15q_abcd_v1",
  "created_at": "2026-07-15T01:30:00+00:00"
}
```

The issuance orders unique page IDs by 1-based logical page. Page count and
question ranges are derived from the versioned layout. All duplicated identity
and structural context must match across the complete record set. Timestamps
include an offset. Strict loading rejects missing or unknown fields, duplicate
JSON keys, non-standard numbers, wrong versions, path/identity mismatches, and
incomplete or inconsistent aggregates.

Pages are exclusively created and never updated. The issuance lifecycle is the
single mutable authority for every member page. It starts as `prepared` at
revision 1. The only transitions are:

```text
prepared -> issued
prepared -> cancelled
prepared -> invalidated
issued   -> superseded
issued   -> invalidated
```

Every transition increments the revision and uses an expected-revision guard.
Entering `issued` sets `issued_at`. Terminal states set `ended_at` and require a
reason. `superseded` additionally requires a different, already-issued
replacement for the same class, assignment, and student. Issuance updates are
same-directory atomic replacements; page files do not change.

Individual and packet copies for the same student may share a generation but
have different artifacts, issuances, and pages. All students in one class packet
may share an artifact. An additional copy gets fresh issuance and page IDs and
does not supersede an earlier copy. Regeneration gets fresh generation, artifact,
issuance, and page IDs, links its predecessor, and preserves every old record.

The future Core route target for a validated page is exactly:

```python
ModuleRecordRef(
    module_id="scoreform",
    record_kind="answer_sheet_page",
    record_id=page_id,
    contract_version="1",
)
```

These records contain no route IDs, locators, route registrations, QR payloads,
PDF data, answer keys, standards or profile data, results, or attempts. Managed
generation persists each page before registering its independent Core route.

## 7. QR payload versioning contract

### PDS2 generated-page locator

**Status: Active generation contract.**

```text
PDS2|m=scoreform|c=<class_id>|w=<assignment_id>|r=<route_id>
```

ScoreForm delegates serialization to Core. The QR contains exactly module,
class, work, and a fresh `rt_` plus 32-lowercase-hex route ID. It never contains
student identity, logical page, page ID, issuance ID, title, layout, answers,
standards, paths, or lifecycle state. The route registration targets:

```text
ModuleRecordRef(scoreform, answer_sheet_page, <page_id>, contract version 1)
```

Registration status is `active`, and `created_at` equals the page record time.
The exact ScoreForm v1 `module_details` keys are `issuance_id`, `logical_page`,
and `total_pages`. Diagnostic `human_fallback` is:

```text
ScoreForm | class=<class_id> | assignment=<assignment_id> | student=<student_id> | page=<logical_page>/<total_pages> | page_id=<page_id>
```

Neither diagnostic field is routing authority. The future handler must load the
target page and require its issuance lifecycle to be `issued`; an active Core
registration alone is insufficient.

Each PDF is rendered to a same-directory temporary file only after every page
record and route for that artifact is persisted and reloaded. New issuances are
finalized before atomic PDF installation. Route/render/install failures preserve
immutable evidence and invalidate affected issuances; Core route files are never
removed or repointed. Individual and packet copies have distinct artifact,
issuance, page, and route IDs even when they share a command generation ID.

Artifact result state distinguishes successful installation from clean lifecycle
completion. `installed=true` means canonical PDF replacement succeeded. A later
predecessor-supersession failure leaves the new PDF installed and new issuances
issued, but reports non-clean partial success. Route diagnostics separately
report planned, durably created, and reload-verified registration counts; a
planned route is never counted as created merely because its ID was allocated.
Temporary-file cleanup warnings are additive diagnostics and never mask the
primary planning, persistence, rendering, finalization, or installation error.

### PDS2-only payload policy

ScoreForm generates and parses only canonical Core PDS2 locators:

```text
PDS2|m=<module_id>|c=<class_id>|w=<work_id>|r=<route_id>
```

PDS1 and OMR1 are unsupported: they are not parsed, generated, migrated, or
converted. A non-PDS2 decoded string remains available as raw review evidence,
but produces no locator, dispatch request, route lookup, page or issuance
record, route registration, or result row. Previously printed historical sheets
cannot enter routed scoring; teachers must generate new managed PDS2 sheets or
use the separate manual workflow without fabricated route identity.

Only Core parses and serializes PDS2. Its locator carries no student identity,
logical page, question range, answer key, or result destination. Those values
come only from the registered route and immutable authoritative records.

## 8. Generated template and answer-sheet layout contract

**Status: Core scoring assumptions are stable-enough; exact visual layout and
generic output paths are provisional pre-1.0.**

Current constants are:

```text
IMG_WIDTH = 1275
IMG_HEIGHT = 1650
PDF_WIDTH = 612
PDF_HEIGHT = 792
QUESTIONS_PER_PAGE = 15
MAX_ASSIGNMENT_QUESTION_COUNT = 75
choices = A-D
```

The current/default versioned layout is `standard_15q_abcd_v1`; it holds 15
questions per page. `compact_25q_abcd_v1` is also registered and holds 25 A-D
questions in two columns. Layouts own page capacity, image/PDF dimensions,
registration and perspective geometry, QR placement, labels, answer-box
coordinates, rendering details, and mark-classification settings.

Both layouts are supported in assignment creation after compact 50-question
physical scan validation and a standard 15-question regression test. Standard
remains the default, and layout is immutable after creation. The generated PDS2
locator does not carry `layout_id`; the page record and assignment JSON remain
the source of truth. The `results.csv`
format is unchanged. Local `.scan-test-workspace/` and `scan_test/` folders are
ignored and must not be committed.

Sheets may span multiple pages. Each physical page contains up to 15 or 25
questions according to layout, uses A-D choices and registration marks for perspective correction,
and places a page-aware QR code for routing. Existing PDFs
should be treated as coupled to the scoring layout that generated them. Generated
PDFs do not embed a separate layout marker in the locator: the immutable page
record and assignment carry layout context. A change that can break old
scans needs a separate template-versioning and deprecation decision.

## 9. Routed results CSV contract

**Status: Routed-results schema version 2 is active for PDS2 and manual attempts.**

The current routed exporter targets:

```text
<PDS workspace root>/classes/<class_id>/modules/scoreform/work/<assignment_id>/results.csv
```

For ScoreForm, `assignment_id` is the module-owned `work_id`; complete identity
is `module_id="scoreform" + class_id + work_id`. The shared roster remains at
`classes/<class_id>/roster.csv`. `assignment.json`, `templates/`, `scans/`,
`results.csv`, and `debug/` are direct ScoreForm work descendants. Core owns any
immutable `routes/` registrations. Active discovery is direct-child-only within
the ScoreForm collection. An unqualified `classes/<class_id>/assignments/` tree
is outside the managed contract and is neither inspected nor modified.

New schema-v2 histories use this exact logical order. The `Qn`,
`Qn_Correct` pairs are contiguous and dynamic through the assignment total:

```csv
class_id,assignment_id,student_id,last_name,first_name,period,Score,Total,Q1,Q1_Correct,Q2,Q2_Correct,...,Page,attempt_number,scan_timestamp,source_file,result_schema_version,result_origin,issuance_id,generation_id,artifact_id,page_ids,route_ids,logical_pages,source_scan_id,source_pages,retained_source_path,source_sha256
```

The reader recognizes exactly this teacher-first layout and the earlier
pre-release schema-v2 metadata-first layout. It does not accept arbitrary
permutations. Reading is nonmutating. The next successful export transaction
against an old-order history preserves every row and value while atomically
normalizing the header to teacher-first order, including when the incoming
attempt is already present.

The collection fields are compact canonical JSON arrays in authoritative logical
page order. `Page` displays retained source-page numbers and is not authoritative
logical-page identity. PDS2 pages assemble only by `issuance_id`; every expected
page must occur exactly once in the current intake. ScoreForm never groups by
student or filename, merges print copies, or reconciles across retained scans.
Missing, duplicate, conflicting, and inconsistent sets produce no partial row.

Routed results are append-preserving and audit-log oriented. Existing rows are
preserved and new attempts appended; ScoreForm does not choose which attempt is
the grade. Before any target is changed, every existing file, header, row,
timestamp, origin, identifier, answer, score, total, attempt number, and canonical
JSON array is validated. Managed rows must match their exact class, assignment,
and question total. Incompatible history aborts export without changing bytes.

All target images are written and fsynced to same-directory temporary files
before any replacement begins. A staging failure replaces no target. Replacements
then proceed sequentially; a later failure can leave earlier targets committed,
and the export result distinguishes persisted, failed, and not-attempted targets.
Cleanup failures retain the temporary path, target path, and cleanup exception.
An attempt is reported appended only after its target replacement succeeds.

PDS2 export identity is `source_sha256 + issuance_id`. Equivalent incoming
duplicates are coalesced even when filename, Core `source_scan_id`, or retained
path differs. A different digest for the same issuance is a new attempt. The
semantic comparison includes student and assignment identity, displayed student
fields, issuance/generation/artifact identity, page/route/logical/source-page
arrays, score, total, every answer and correctness value, and the source digest.
It excludes ingestion-only filename, source-scan ID, and retained path.
Contradictory reuse of a content key fails the transaction.

Equivalent historical duplicate rows produced by the earlier pre-release
behavior remain valid and are preserved; the lowest existing attempt number is
the canonical already-present match, and future identical intake appends
nothing. Conflicting historical rows for one content key are invalid. Result
deduplication does not delete Core retained-source records or assignment-level
filed copies: those remain evidence of each intake under their respective Core
retention and ScoreForm filing contracts.

Teacher-entered plain-paper results use this same routed contract, not the
provisional explicit-output contract in section 9. They set `Page` to `manual`
and `source_file` to `plain_paper_manual_entry`; all `Qn` and `Qn_Correct`
fields are present. A-D responses match the assignment key normally, while
`BLANK` and `AMBIGUOUS` are incorrect. The existing exporter supplies roster
fields and the next attempt number. No columns are added, and the workflow
creates no scan artifacts, review evidence, or routed identity.

## 10. Manual and explicit-output results CSV contract

**Status: Provisional pre-1.0.**

Manual answer-key scoring remains separate. QR-aware explicit output runs the
same PDS2 assembly and schema-v2 serializer. Manual output contains `Page`, `Score`,
`Total`, and repeated `Qn`, `Qn_Correct` fields. If any result contains routing
metadata, it also contains `class_id`, `assignment_id`, and `student_id`; if any
result contains source metadata, it contains `source_file`. Column presence thus
depends on the available result records and scoring mode.

Manual explicit-output CSV remains available and provisional.

## 11. `source_file` semantics

**Status: Stable-enough current privacy contract.**

When a source is inside the workspace root, ScoreForm stores a workspace-relative
path with forward slashes. An outside-workspace absolute path, or a path that
cannot be safely relativized, becomes basename-only. A safe relative path is
preserved with forward slashes, while one containing `..` falls back to its
basename. Blank or invalid values become an empty string. Arbitrary external
absolute paths must not be written to results.

For active PDS2 processing, retained provenance is preserved from immutable
runtime requests through schema-v2 result rows. `source_file` is the validated
original filename; `retained_source_path` is the safe workspace-relative Core
copy. The canonical copy under `scans/source/YYYY-MM-DD/` is never altered.
Every supported schema-v2 row must satisfy the current source-field contract.

## 12. Attempt metadata

**Status: Active shared attempt numbering.**

Attempts are keyed by (`class_id`, `assignment_id`, `student_id`). The first row
is attempt 1, and each additional routed row for that key increments it. Numeric
text is canonical decimal (`1`, not `01`) and is otherwise rejected rather than
silently normalized. Every supported origin (`pds2_scan`,
`plain_paper_manual`, and `scan_review_manual`) requires a nonempty,
timezone-aware ISO 8601 timestamp. Schema-v1 histories and naive timestamps are
incompatible and are rejected without mutation.
`scan_timestamp` records when the routed batch was prepared, so
rows in one batch may share it. Attempt number does not select an official grade.

## 13. Scan filing contract

**Status: Active only after eligible managed full success.**

Canonical retained sources live under `scans/source/YYYY-MM-DD/` and are never
altered. Assignment-local filing is limited to managed, full-success,
ScoreForm-only, single-target batches with no assembly or export failure.
Explicit, mixed-module, multi-target, incomplete, duplicate, and partial batches
skip filing. The `copy`, `move`, and `off` setting remains in force.

## 14. In-memory PDS2 dispatch summaries and diagnostics

**Status: Internal/current operational outputs, not stable interoperability
schemas.**

The #143 summary is printed from the immutable runtime result and is not saved.
Diagnostic paths and write warnings are preserved structurally per source page.
Their prose, paths, crops, and filenames may change. External integrations must
not depend on exact wording or diagnostic names unless a later issue formalizes
them. Debug image names, helper names, terminal prose, and temporary write files
are likewise internal implementation details.

## 15. Compatibility and versioning policy

Before v1.0, ScoreForm contracts may evolve, but compatibility-sensitive changes
must be documented before or alongside implementation. Breaking changes to
assignment fields, standards structure, QR version, routed header order, attempt
semantics, `source_file` privacy, roster required columns, or scoring-sensitive
layout assumptions require an explicit compatibility issue.

Formal assignment `schema_version`, embedded template/layout versioning, and QR
versions beyond PDS2 remain future work. Routed results use schema version 2 and
strictly migrate compatible v1 histories on first append.

## 16. Core-v2 ScoreForm scan review metadata

Legacy ScoreForm failures may exist in the shared Core
`RoutingFailureMetadata` schema at:

```text
<PDS workspace root>/scans/review/<failure_id>.json
```

Active records use Core's exact 17-key `RoutingFailureMetadata` schema version
`"2"`. The shared category and stage remain generic; ScoreForm ownership and
diagnostics are nested under versioned `module_details.scoreform`. When retention succeeded,
the record includes the source scan ID, SHA-256 digest, original filename,
workspace-relative retained path, and page number. Safe QR identity is included
only when it was actually decoded. Failure records are immutable.

Teacher decisions use Core's exact 18-key `ScanResolutionMetadata` schema version
`"2"` at:

```text
<PDS workspace root>/scans/review/resolutions/<resolution_id>.json
```

Resolution records are also immutable. The latest valid record determines the
current view: resolved items are hidden by default, while deferred items stay
visible. Older records remain part of the review trail.

Canonical sources remain under `scans/source/YYYY-MM-DD/`. Assignment-local
`scans/` files are routed scoring or resolution evidence copies. Manual-entry
and manual-marks evidence names carry readable status tags and never overwrite
an existing file. The source must be a non-symlink regular file inside the
workspace and the destination must belong to a validated managed assignment.
The copy is flushed, closed, SHA-256 verified, and removed if verification
fails; the source is always preserved. Actions with no Core evidence contract
reject an evidence argument.

The routed-scoring workflow writes one immutable occurrence record for each
actionable intake, page, dispatch, ScoreForm validation, assembly, and export
failure after export is known. Actual `RouteDispatchFailure` values use Core's
mapper. Raw decoded payload text is preserved exactly; locators and targets are
stored only when validated at the occurrence. Historical v1 files are left
untouched and excluded by strict discovery. Discovery reports separate counts
for invalid failures, invalid resolutions, unsupported-v1 failures,
unsupported-v1 resolutions, orphan resolutions, provenance mismatches,
malformed ScoreForm details, and foreign records.

Manual entry uses the schema-v2 routed-results header with
`result_origin=plain_paper_manual`, `Page=manual`, and
`source_file=plain_paper_manual_entry`. It fabricates no PDS2 provenance and
creates no Core resolution record.

### Exact ScoreForm module-detail contracts

Failure `module_details` has exactly one `scoreform` object with exactly these
keys: `details_schema_version="1"`, `record_kind="failure"`, one closed
`failure_origin`, `scoreform_category`, ordered unique `diagnostic_paths`,
ordered `diagnostic_errors`, and deeply immutable JSON-native `context`.
`failure_origin` is one of `scan_intake`, `page_decode`, `core_dispatch`,
`scoreform_handling`, `invalid_page_observation`, `attempt_assembly`, or
`result_export`. Paths are safe workspace-relative strings and numbers are
finite. Strings, nulls, Booleans, integers, finite floats, mappings with safe
string keys, and list/tuple sequences are preserved (with mappings and
sequences stored immutably). Non-finite floats and invalid mapping keys are
rejected. Other context values—including path objects, exceptions, and
dataclasses—become a bounded `{value_type, display}` record without invoking
their `repr` or `str`. Diagnostic paths remain a separate strict string-only
field and reject path objects.

Resolution `module_details` has exactly one `scoreform` object containing
exactly `details_schema_version="1"`, `record_kind="resolution"`,
`resolution_origin="scoreform_scan_review"`, `teacher_action`,
`identity_source`, validated `identity`, validated nullable `result`, and
validated nullable `evidence`. A malformed marker is not ownership: discovery
counts it as malformed and leaves the valid Core record unchanged.

`identity_source=none` requires an empty identity. `validated_locator` contains
exactly class, assignment/work, and route identity. `validated_target` contains
the complete class, assignment, student, route, page, issuance, logical-page,
and total-page identity with positive ordered page numbers. `teacher_verified`
contains the identifiers consumed by the action; manual entry requires class,
assignment, and student. A manual result is allowed only for `manual_entry`,
uses the exact `scan_review_manual` shape, has bounded integer score/total and a
positive attempt, and names the canonical managed `results.csv` for the same
identity. Evidence is allowed only for manual entry, manual marks, and
evidence-filed actions, carries exact safe paths/status/full SHA-256 fields, and
must satisfy the action's source/destination relationship. Nested identity,
result, evidence, context, and diagnostic-error state is deeply immutable.

ScoreForm owns a failure when a validated locator names module `scoreform`, a
validated target names module `scoreform`, or valid ScoreForm failure details
identify a pre/post-route occurrence. Foreign records remain separate. A
resolution must match the canonical failure metadata path and all of
`source_filename`, `source_scan_id`, `source_sha256`, `retained_source_path`,
`review_copy_path`, and `source_page_number`. A mismatch cannot change status.
Valid history is ordered by aware timestamps normalized to UTC and then by
resolution ID.

Identity projection is immutable and labeled `validated_target`,
`validated_locator`, `scoreform_diagnostic`, or `none`. A validated answer-sheet
target is reloaded and cross-checked against its route registration, page, and
issuance before authoritative fields are exposed. Locator-only identity exposes
class, assignment/work, and route only. Diagnostic values remain separately
labeled as observed; teacher-verified identity lives in resolution history.

### Pipeline mappings

| Pipeline layer | Core stage/category |
| --- | --- |
| missing source / unsupported type / unreadable preflight | `intake` / `source_missing`, `source_type_unsupported`, or `source_unreadable` |
| typed retention failure | `retention` / `source_retention_failed` |
| registry infrastructure / actual profile incompatibility | `module_resolution` / `processing_error` or `module_profile_incompatible` |
| no QR / unreadable detector result | `payload` / `payload_missing` or `payload_unreadable` |
| payload parser | `payload` / `payload_schema_unsupported`, `payload_too_large`, `identifier_invalid`, or `payload_invalid` |
| retained page loading | `decoding` / `source_unreadable` |
| typed request identifier failure / other request construction failure | `route_resolution` / `identifier_invalid` or `processing_error` |
| locator/profile/registration/target/page outcome contradiction | `module_validation` / `target_incompatible` |
| malformed handler output or scoring failure | `module_handling` / `processing_error` |
| diagnostic write failure | `evidence` / `evidence_write_failed` |
| missing, duplicate, conflicting, order, or coverage assembly failure | `review` / `page_conflict` |
| unexpected page, inconsistent issuance, or invalid result identity | `review` / `target_incompatible` (or typed `processing_error`) |
| export history contradiction | `review` / `processing_error` |
| export preflight, staging, replacement, or not-attempted target | `evidence` / `evidence_write_failed` |

Each occurrence is converted, Core-validated, and written independently.
Failures report `conversion`, `validation`, `write`, or `collision_exhausted`
while retaining the original exception in memory, and later occurrences
continue. An independently valid occurrence-time page locator survives later
request, resolution, registration, profile, or target contradictions. The
target is then null unless independently trusted, and all competing values
remain in ScoreForm context rather than one contradictory target being selected.

Teacher action `mixed_assignment` maps to Core `resolved/cannot_route`; manual
entry and manual marks map to `resolved/other`; defer maps to
`deferred/deferred`. Manual entry writes or recognizes its idempotent result
before appending a resolution. If that append fails, a typed partial-operation
error reports the failure, result path, attempt, append state, and underlying
error and explains that retrying will not create another attempt. Retry then
recognizes the row and appends only the missing resolution.

The `scan_review_manual:<failure_id>` link is globally unique across canonical
`classes/<class_id>/modules/scoreform/work/<assignment_id>/results.csv`
histories. Exact replay returns the original attempt; any different class,
assignment, student, answers, score, or total is an integrity failure before a
new row is written. Review evidence uses a deterministic failure/action
destination, rejects symlink escapes at every managed boundary, verifies full
source/destination digests, preserves the source, reports cleanup failures, and
reuses only an already verified matching copy on resolution retry.

## Core 0.6 ScoreForm module dispatch contract

Installed discovery uses `paper_data_suite.modules` with entry-point name
`scoreform`. The profile supports exactly Core routing contract `1`, `PDS2`,
route-registration schema `1`, and dispatchable status `active`.

A valid ScoreForm registration targets module `scoreform`, record kind
`answer_sheet_page`, contract version `1`, and a valid `pg_` page ID. Its
`module_details` object has exactly `issuance_id`, `logical_page`, and
`total_pages`; page numbers are positive non-Boolean integers and logical page
does not exceed total pages. The fallback grammar is exactly:

```text
ScoreForm | class=<class_id> | assignment=<assignment_id> | student=<student_id> | page=<logical_page>/<total_pages> | page_id=<page_id>
```

The structural validator is pure. The handler owns target reads and compares
all diagnostics to the immutable page and complete issuance. An active Core
route is not sufficient authorization: issuance lifecycle must be `issued`.
The current assignment must preserve question count, layout, and choices, while
its current answer key remains authoritative; title drift alone is accepted.

Runtime output is one immutable physical-page score with authoritative record
identities, exact question range, ordered immutable answers, retained-source
provenance, and diagnostic paths. It contains no answer key. Source page number
selects a page in the retained scan and is not the logical answer-sheet page.

Retained-source validation reconstructs Core's exact canonical
`scans/source/<intake_date>/<retained_filename>` path. `intake_date` is an
independent Core routing value and may differ from the timezone-aware intake
timestamp's calendar date; the canonical date bucket must match `intake_date`.
The original source filename is validated only as trimmed, control-free
provenance with a supported extension matching the retained file. It is never
used as path material. Numeric page-result fields reject Booleans explicitly.
If strict OMR fails after creating managed diagnostics, the typed scoring error
carries their immutable paths for later review without directory searching.
# Multi-page ScoreForm sheets

Sheets may span multiple pages. `question_count` is an integer from 1 through 75,
and the current optical layout supports up to 15 questions per physical page.
Visible question labels and exported answer fields use global assignment question
numbers. The active PDS2 locator has no page field; logical page identity comes
only from the registered target and immutable page record.

The active PDS2 workflow preserves independent physical-page outcomes, then
assembles only complete authoritative issuances. It never chooses among
duplicates; those occurrences are persisted for review without discarding
unrelated valid attempts.
