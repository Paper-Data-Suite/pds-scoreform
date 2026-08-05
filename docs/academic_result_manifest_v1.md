# ScoreForm Academic Result Manifest v1

## Status, purpose, and ownership

`scoreform_academic_result_manifest_v1` is the exact, active ScoreForm-owned
contract for one immutable record-set revision of the academic results published
for one managed ScoreForm assignment. It is a publication projection of
producer-native evidence, not a mutable view of `results.csv` and not a gradebook.

The ownership boundary is:

> ScoreForm publishes producer-native evidence.  
> Core registers and verifies publication envelopes.  
> Meridian or another authorized consumer applies grading and reporting policy.

The pure implementation is `scoreform.academic_result_manifest`. It constructs,
validates, converts, and serializes in-memory values without resolving a
workspace, reading native files, writing a manifest, importing another producer,
or accessing Core registry state. Workspace construction and publication are
future work. The checked-in fixture is a normative byte example, not evidence
that Core publication or Meridian consumption is implemented.

Academic Work Registration is now a separate explicit workflow. Manifest
generation remains future work under #165. Later publication must reference the
exact current registration revision. Registration metadata is not added to this
approved manifest v1 contract.

## Exact envelope

Every JSON object has the exact keys documented below. Missing or extension keys
are invalid. JSON arrays are ordered as specified.

```text
manifest
  record_type: "scoreform_academic_result_manifest"
  contract_version: "scoreform_academic_result_manifest_v1"
  producer_module_id: "scoreform"
  generated_at: timezone-aware ISO 8601 timestamp
  record_set
    record_set_id: safe identifier
    revision: positive integer
  work
    module_id: "scoreform"
    class_id: safe identifier
    work_id: safe identifier
  source_snapshot
    assignment
      relative_path: "assignment.json"
      sha256: lowercase SHA-256
      contract_version: null
    results_history
      relative_path: "results.csv"
      sha256: lowercase SHA-256
      result_schema_version: "2"
  assignment
    assignment_id: safe identifier
    title: nonempty trimmed control-free text
    question_count: integer from 1 through 75
    layout_id: supported ScoreForm layout identifier
    choices: exact choices registered by that layout
    total_points: question_count
    standards_profile_id: safe identifier or null
    questions: question[]
  students: student[]
```

All safe identifiers use the existing Core identifier contract. Boolean values
are not integers. `generated_at` identifies creation of these manifest bytes; it
does not select a current or latest revision. Canonical serialization renders
timestamps in UTC.

`work.work_id` equals `assignment.assignment_id`. The work module and producer
module are both exactly `scoreform`. For ScoreForm, the complete work identity is
`module_id + class_id + work_id`, and `work_id` is the native assignment ID.

## Record-set and source identity

Production uses the stable record-set ID `academic_results`; synthetic contract
fixtures may use clearly synthetic IDs. `revision` is a positive producer
revision for the manifest as a whole. It is not the
routed-results schema version, attempt count, highest attempt number, question
count, Core Academic Work Registration revision, Core Publication Record schema
version, Core publication record-set revision, Publication Record identity, or
ScoreForm package version. The schema deliberately does not infer a latest
revision or series head. ScoreForm's active allocation, exact replay,
append-preserving transition, correction, supersession, withdrawal, and recovery
rules are defined in
[`publication_revision_policy.md`](publication_revision_policy.md); those rules
do not add fields to this exact v1 contract.

The source snapshot binds the exact native bytes used to construct a future
manifest. Its paths are relative to the exact ScoreForm work root. Only the
canonical filenames `assignment.json` and `results.csv` are valid; absolute,
drive-qualified, backslash, traversal, empty-component, or alternate symlink
spellings are not representable. The assignment source is explicitly
unversioned (`contract_version: null`). The routed result history is schema `"2"`.

These byte snapshots are distinct from Core's optional publication
`ModuleRecordRef`. A future registration or publication may refer to the native
assignment as `module_id=scoreform`, `record_kind=assignment`,
`record_id=assignment_id`, with null/unversioned contract version. A
`results.csv` row has no durable native record ID and must not be advertised as a
Core `ModuleRecordRef`.

## Assignment and question evidence

Questions have exactly:

```text
question
  question_number: positive integer
  points_possible: 1
  standard_ids: safe identifier[]
```

The questions cover `1..question_count` exactly once and in that order. ScoreForm
v1 assigns one point to each question, so `total_points == question_count`.
`standard_ids` preserves the authoritative assignment mapping in its native
order; an empty list is explicit and valid, and duplicates within a question are
invalid.

`standards_profile_id` is nullable. It is required if any question has a standard
ID and may be null when all alignments are empty. Native construction must have
validated each ID against that Core standards profile. The mappings are question
alignment metadata only. They are not ratings, proficiency, rubric scores,
mastery, Grades, or selected cumulative evidence. No alignment may be inferred
from text or another assignment. A future producer profile may advertise
`points`, `question_evidence`, and `multiple_attempts`; it must not advertise
`standards_ratings` for this contract.

The assignment answer key is deliberately absent. Per-response correctness is
sufficient to interpret the result and avoids unnecessary exposure of assessment
material.

## Students, attempts, and responses

Students and attempts have exactly:

```text
student
  student_id: safe identifier
  attempts: attempt[]

attempt
  attempt_number: positive integer
  result_origin: "pds2_scan" | "plain_paper_manual" | "scan_review_manual"
  recorded_at: timezone-aware ISO 8601 timestamp
  points_earned: nonnegative integer
  points_possible: assignment.total_points
  responses: response[]
  provenance: origin-specific object

response
  question_number: positive integer
  response_state: "selected" | "blank" | "ambiguous"
  selected_answer: layout choice or null
  correct: Boolean
```

Students are unique and sorted by `student_id`; only students represented by an
authoritative published attempt appear. Attempts are unique within a student and
sorted by their unchanged native `attempt_number`. Their identity is the complete
work identity plus `student_id + attempt_number`; v1 creates no second attempt ID.
Every attempt is preserved and has one ordered response for every assignment
question. `points_earned` is the number of `correct: true` responses, and
`points_possible` equals the assignment total.

A `selected` response requires exactly one assignment choice. `blank` and
`ambiguous` require `selected_answer: null`. They remain distinct and are never
converted to an arbitrary choice. `correct` is always a real Boolean reflecting
the authoritative routed result.

No attempt is labeled official, selected, current, best, latest for grading,
replacement, summative, dropped, excluded, or Grade-bearing. Absence of a student
or result does not imply a zero, missing-work state, or incomplete state.
Operational observations such as incomplete issuances, missing pages, duplicate
conflicts, unreadable scans, unresolved review failures, rescan decisions,
dismissed duplicates, and export failures are not completed academic attempts
and do not produce placeholders.

## Origin-specific provenance

`pds2_scan` provenance has exactly:

```text
issuance_id: safe identifier
generation_id: safe identifier
artifact_id: safe identifier
page_ids: nonempty unique safe identifier[]
route_ids: nonempty unique safe identifier[]
logical_pages: positive integer[]
source_scan_id: safe identifier
source_page_numbers: positive integer[]
retained_source_path: canonical scans/source/YYYY-MM-DD/<filename>
source_sha256: lowercase SHA-256
```

The four page, route, logical-page, and source-page arrays have equal nonzero
lengths. Logical pages are exactly `1..N` in order. Issuance identity distinguishes
printed copies; source digest identity preserves the native duplicate-content
boundary. No manual-review identity or absolute/diagnostic path is present.

`plain_paper_manual` provenance is exactly an empty object. Its typed immutable
model explicitly records the absence of fabricated issuance, route, scan,
retained-path, digest, or review-failure identity.

`scan_review_manual` provenance has exactly:

```text
review_reference
  failure_id: safe failure identifier
```

This typed reference preserves the native failure link without making consumers
parse the routed-result display marker `scan_review_manual:<failure_id>`. It does
not copy the review record or fabricate PDS2 provenance.

## Immutability and validation

Models are frozen and slotted; collections are tuples and constructor inputs are
defensively copied. Public failures use the ScoreForm-specific manifest error
hierarchy. Whole-manifest validation checks fixed identities, exact types and key
sets, work/assignment agreement, layout choices, totals, question and response
coverage, score/correctness agreement, standards/profile relationships, ordering
and uniqueness, response-state relationships, origin discrimination, PDS2 array
alignment, retained paths, hashes, timestamps, identifiers, and display text.

Strict JSON decoding rejects malformed UTF-8, malformed JSON, a non-object root,
duplicate keys at any depth, and `NaN` or infinities. Error messages identify the
failed field or invariant without dumping the manifest or student data.

## Canonical JSON and fixture

Canonical bytes are UTF-8, standards-compliant JSON with lexicographically sorted
object keys, deterministic array order, two-space indentation, no nonfinite
numbers, and exactly one trailing newline. Aware timestamps are normalized to UTC
with six fractional digits and `Z`. Conversion APIs are:

```python
manifest_to_mapping(model)
manifest_from_mapping(mapping)
manifest_to_canonical_json_bytes(model)
manifest_from_json_bytes(data)
```

Round trips preserve every semantic value, repeated serialization is byte-stable,
and parsing then serializing the normative fixture reproduces it exactly. The
privacy-safe synthetic fixture is:

`tests/fixtures/publication/scoreform_academic_result_manifest_v1.json`

It demonstrates two students, multiple attempts, all three origins, standards
alignments, selected/blank/ambiguous responses, and deterministic ordering.

## Privacy, security, and consumer obligations

The manifest contains student-level educational data and scan provenance. It is
not suitable for public logs, unrestricted diagnostics, or Core audit output.
It excludes names, emails, guardian and demographic data, accommodations, roster
extensions, network identifiers, unrelated class metadata, answer keys, raw QR
payloads, confidence/fill/threshold values, image coordinates or crops,
handwriting guesses, detector output, review notes, exception text, and absolute,
home, temporary, debug, or username-bearing paths.

An authorized consumer must verify the Core publication envelope and digest,
parse through this ScoreForm contract, resolve roster display data separately,
preserve attempts and non-score response states, and apply an explicit
consumer-owned attempt-selection, grading, proficiency, period, and reporting
policy. This contract does not register Academic Work, create or query Core
Publication Records, write workspace manifests, calculate digests from workspace
state, publish or withdraw records, implement a producer entry point, infer Grades
or proficiency, or depend on Meridian.
