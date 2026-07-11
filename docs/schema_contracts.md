# ScoreForm Schema and File Contract

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
profile definitions, and the PDS1/OMR1 QR building and parsing primitives used by
ScoreForm. Those are **shared pds-core-owned contracts**.

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
and `answer_key`. `standards_profile_id` and `standards` are optional metadata.

* `assignment_id` must be a safe identifier accepted by ScoreForm validation.
* `title` must be a non-empty string.
* `question_count` must be an integer from 1 through `MAX_QUESTION_COUNT`,
  currently 15.
* `choices` must equal exactly `["A", "B", "C", "D"]`.
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

**Status: Stable-enough current contract for manual/legacy scoring.**

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
no assignment metadata. It primarily supports manual/legacy scoring; assignment
JSON is preferred for routed, QR-aware workflows.

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

## 6. QR payload versioning contract

### PDS1

**Status: Stable-enough current ScoreForm payload; construction and parsing
primitives are shared pds-core-owned contracts.**

```text
PDS1|module=scoreform|class=<class_id>|aid=<assignment_id>|sid=<student_id>|page=1
```

PDS1 is the default for newly generated personalized sheets. ScoreForm requires
`module=scoreform`; `class`, `aid`, and `sid` must pass safe identifier validation;
and `page=1` represents the current single-page sheet model.

### OMR1

**Status: Stable-enough legacy parsing fallback.**

```text
OMR1|class=<class_id>|aid=<assignment_id>|sid=<student_id>
```

New sheets must not use OMR1. It lacks a module marker, but compatibility should
not be removed without a documented deprecation decision.

Neither payload currently carries standards, answer-key data, roster names,
result paths, attempt numbers, school year, or template version. Adding any of
these requires a separate QR-versioning decision.

## 7. Generated template and answer-sheet layout contract

**Status: Core scoring assumptions are stable-enough; exact visual layout and
generic output paths are provisional pre-1.0.**

Current constants are:

```text
IMG_WIDTH = 1275
IMG_HEIGHT = 1650
PDF_WIDTH = 612
PDF_HEIGHT = 792
MAX_QUESTION_COUNT = 15
choices = A-D
```

Sheets are single-page, contain 1-15 questions with A-D choices, use registration
marks for perspective correction, and place a QR code for routing. Existing PDFs
should be treated as coupled to the scoring layout that generated them. Generated
template layout is currently versioned only by ScoreForm release/code behavior,
not by an embedded template marker. A change that can break old scans needs a
separate template-versioning and deprecation decision.

## 8. Routed results CSV contract

**Status: Stable-enough current audit-log contract.**

PDS Core supplies the canonical route; ScoreForm writes:

```text
<PDS workspace root>/classes/<class_id>/assignments/<assignment_id>/results.csv
```

The exact header order is:

```csv
Page,class_id,assignment_id,student_id,last_name,first_name,period,source_file,attempt_number,scan_timestamp,Score,Total,Q1,Q1_Correct,Q2,Q2_Correct,...
```

The fixed fields are `Page`, `class_id`, `assignment_id`, `student_id`,
`last_name`, `first_name`, `period`, `source_file`, `attempt_number`,
`scan_timestamp`, `Score`, and `Total`, followed by `Qn`, `Qn_Correct` pairs.

One row is one scored page/student sheet. `Page` is its page number in the input;
the three identifiers come from QR metadata; names and period come from roster
enrichment; `Score` counts correct responses; `Total` is the number scored; `Qn`
is the detected response or classification; and `Qn_Correct` records whether it
matched the key. Standards metadata is not exported.

Routed results are append-preserving and audit-log oriented. Existing rows are
preserved and new attempts appended; ScoreForm does not choose which attempt is
the grade. Before any target is changed, existing files and headers are validated.
Incompatible headers abort export. Writes use a same-directory temporary file and
replace operation.

## 9. Manual and explicit-output results CSV contract

**Status: Provisional pre-1.0.**

This shape is distinct from routed results. It always contains `Page`, `Score`,
`Total`, and repeated `Qn`, `Qn_Correct` fields. If any result contains routing
metadata, it also contains `class_id`, `assignment_id`, and `student_id`; if any
result contains source metadata, it contains `source_file`. Column presence thus
depends on the available result records and scoring mode.

The routed results CSV is the primary ScoreForm audit-log contract. Manual and
explicit-output CSVs are useful current outputs but remain more provisional.

## 10. `source_file` semantics

**Status: Stable-enough current privacy contract.**

When a source is inside the workspace root, ScoreForm stores a workspace-relative
path with forward slashes. An outside-workspace absolute path, or a path that
cannot be safely relativized, becomes basename-only. A safe relative path is
preserved with forward slashes, while one containing `..` falls back to its
basename. Blank or invalid values become an empty string. Arbitrary external
absolute paths must not be written to results.

For QR-aware scoring, this field identifies the canonical retained source scan,
normally as `scans/source/YYYY-MM-DD/<retained-source-filename>`. ScoreForm
retains that source before conversion, image loading, QR decoding, or scoring.
Separately, post-success scan filing may copy the teacher-selected original into
an assignment `scans/` directory; it never removes the original.

## 11. Attempt metadata

**Status: Stable-enough current routed-results contract.**

Attempts are keyed by (`class_id`, `assignment_id`, `student_id`). The first row
is attempt 1, and each additional routed row for that key increments it. When a
preserved legacy row has no valid attempt number, ScoreForm conservatively treats
it as attempt 1. `scan_timestamp` records when the routed batch was prepared, so
rows in one batch may share it. Attempt number does not select an official grade.

## 12. Scan filing contract

**Status: Provisional operational behavior.**

Canonical active retained source scans live under `scans/source/YYYY-MM-DD/` and
are created before QR-aware scoring. After QR-aware routed scoring without an
explicit output CSV, ScoreForm may also file a copy under the resolved
assignment's `scans/` folder. This assignment-local copy is a provisional
post-success scored-copy convenience, not canonical source retention.

Assignment-local filing occurs only after a full-success, single-target routed
batch. Partial or zero success, export failure, explicit-output or manual
scoring, and multi-target batches are not automatically filed. The original
remains in place; copies use timestamped, non-overwriting names. Routed results
and QR batch summaries remain the audit trail.

## 13. QR batch summaries and diagnostics

**Status: Internal/current operational outputs, not stable interoperability
schemas.**

Summaries and diagnostic images support teacher review and failure diagnosis.
Their prose, paths, crops, and filenames may change. External integrations must
not depend on exact wording or diagnostic names unless a later issue formalizes
them. Debug image names, helper names, terminal prose, and temporary write files
are likewise internal implementation details.

## 14. Compatibility and versioning policy

Before v1.0, ScoreForm contracts may evolve, but compatibility-sensitive changes
must be documented before or alongside implementation. Breaking changes to
assignment fields, standards structure, QR version, routed header order, attempt
semantics, `source_file` privacy, roster required columns, or scoring-sensitive
layout assumptions require an explicit compatibility issue.

Formal assignment `schema_version`, embedded template/layout versioning, QR
versions beyond PDS1, and results schema versioning or migrations are **future /
not yet implemented**. This document does not introduce them.

## 15. Active ScoreForm scan review metadata

QR-aware ScoreForm failures are preserved through the shared Core
`RoutingFailureMetadata` schema at:

```text
<PDS workspace root>/scans/review/<failure_id>.json
```

The shared failure category is stored in `failure_category`; the original
ScoreForm category and reason remain in `module_details`. Records use
`module="scoreform"` and `stage="scoreform_qr_review"`. When retention succeeded,
the record includes the source scan ID, SHA-256 digest, original filename,
workspace-relative retained path, and page number. Safe QR identity is included
only when it was actually decoded. Failure records are immutable.

Teacher decisions use Core `ScanResolutionMetadata` records at:

```text
<PDS workspace root>/scans/review/resolutions/<resolution_id>.json
```

Resolution records are also immutable. The latest valid record determines the
current view: resolved items are hidden by default, while deferred items stay
visible. Older records remain part of the review trail.

Canonical sources remain under `scans/source/YYYY-MM-DD/`. Assignment-local
`scans/` files are routed scoring or resolution evidence copies. Manual-entry,
manual-marks, and rescan-needed evidence names carry readable status tags and
never overwrite an existing file. Source evidence is copied, never moved.

Manual entry keeps the routed-results header in section 8 unchanged. Its row is
distinguished by a `source_file` path containing `_manual_entry` and by the
linked Core resolution record; no result-source or resolution columns are added.
