# Fast Answer-Key and Standards Alignment Entry Contract

Issue #185 implements `SF-AC04` from
`docs/v0.11.0_usability_acceptance_cases.md`: teachers can replace a complete
answer key or standards alignment without answering one prompt per question,
while ScoreForm preserves an explicit preview/commit boundary.

The central invariant is:

```text
fast input
+ complete normalization
+ complete validation
+ complete preview
+ explicit commit
= one valid staged assignment change
```

A parser never mutates an assignment. A validation failure never leaves a
partial key or alignment. Existing results, generated sheets, registration,
manifests, publications, scans, and attempt history are not regenerated or
rescored when an assignment definition changes.

## Supported answer-key inputs

Bulk answer-key entry is a **full replacement** for questions `1..N`.

### Concise paste

Whitespace-separated and comma-separated forms are supported:

```text
A B C D A
A,B,C,D,A
```

Input is case-insensitive and normalizes to the assignment's canonical choice
labels. The number of answers must equal `question_count` exactly. Empty
comma-separated fields are significant errors rather than silently skipped
positions.

`B` is always valid answer data when `B` belongs to the choice set. In guided
per-question input, cancellation uses the explicit word `BACK`; navigation must
not steal the valid answer `B`.

### CSV

The header is exact:

```csv
question,answer
3,D
1,B
2,A
```

Rows may be in any order, but every question `1..N` must occur exactly once.
Duplicate, missing, out-of-range, blank-answer, extra-column, or malformed rows
fail validation. UTF-8 with an optional BOM is accepted.

### JSON

The top-level object maps question numbers to answers:

```json
{"1":"B","2":"A","3":"D"}
```

Every question `1..N` must occur exactly once. Duplicate object keys,
non-finite constants, unsupported wrappers, missing questions, extra questions,
and invalid choices are rejected.

## Supported standards-alignment inputs

Bulk standards alignment is also a **full replacement**. Every question must be
covered exactly once, either with one or more durable Core standard IDs or as
explicitly unaligned.

### Concise paste

Each group is:

```text
<question-selector> = <standard-list>
```

Groups may be separated by newlines or semicolons:

```text
1-5 = standard_a
6-10 = standard_b, standard_c
11-15 = -
```

or:

```text
1-5=standard_a;6-10=standard_b,standard_c;11-15=-
```

Selectors support single questions, ranges, and mixed selectors such as
`1-3,7,10-12`. `-` and `none` mean explicitly unaligned. Reversed ranges,
overlap, duplicate coverage, missing coverage, duplicate standard IDs, and
out-of-range questions are errors.

### CSV

The header is exact:

```csv
question,standards
1,standard_a
2,standard_a;standard_b
3,
```

The `standards` field uses semicolon-separated durable IDs. A blank field means
explicitly unaligned. Every question must occur exactly once.

### JSON

The top-level object maps question numbers to arrays of durable IDs:

```json
{"1":["standard_a"],"2":["standard_b"],"3":[]}
```

Values must be arrays. Empty arrays mean explicitly unaligned. Duplicate object
keys, duplicate IDs, unsupported wrappers, missing questions, and extra
questions are rejected.

## Core standards authority

ScoreForm stores durable Core standard IDs; it does not copy or redefine
standards authority.

A non-empty alignment requires a standards profile and the current Core
standards library. Every selected ID must exist and belong to the selected
profile. A supplied profile change is therefore a deliberate **full alignment
replacement**, never an implicit remap of existing IDs.

When direct CLI alignment input omits `--standards-profile-id`, ScoreForm retains
an existing assignment profile if one is already present. Invalid or stale
profile membership fails closed.

An all-unaligned assignment may omit `standards_profile_id`.

## Diagnostics

Bulk parsing is terminal-independent. Parser results contain deterministic,
bounded diagnostics with source/category information and, where available,
row/line, field, selector, or question context.

For structurally parseable input, ScoreForm reports the independently detectable
problems rather than failing at the first unrelated item. Normal teacher input
errors are reported without a traceback.

No raw imported file contents are written to logs, telemetry, or another
workspace record.

## Teacher-facing creation and editing

Assignment creation offers answer-key methods for:

```text
paste
CSV
JSON
per-question entry
```

Standards setup offers the corresponding bulk alignment methods while retaining
the pre-existing fine-grained Core standards editor.

A successful bulk parse is shown as a complete normalized preview. The teacher
must type `USE` before that value becomes part of the staged assignment.

Before initial assignment creation becomes durable, ScoreForm shows the complete
assignment definition and requires `SAVE`. Existing assignment editing stages
changes in memory and requires `SAVE` before replacing the canonical
`assignment.json`.

Cancellation before `USE` leaves the staged value unchanged. Cancellation before
final `SAVE` leaves the durable assignment unchanged.

## Guarded assignment replacement

Existing managed assignments are edited against an exact snapshot containing:

```text
canonical class/assignment identity
canonical assignment path
exact original bytes
SHA-256 of those bytes
strictly normalized assignment
```

Commit requires the reviewed original to remain byte-identical. The replacement
path is:

1. revalidate the reviewed candidate and current Core standards authority;
2. verify the canonical assignment still matches the exact snapshot;
3. serialize the intended replacement;
4. write a same-directory temporary file;
5. flush and `fsync` the temporary file;
6. strictly reload/validate the temporary bytes;
7. recheck the original exact snapshot immediately before replacement;
8. install with `os.replace`;
9. strictly reload the canonical assignment; and
10. verify the persisted normalized value and bytes/digest match the reviewed
    candidate.

Temporary-file cleanup is best-effort on failure. Stale state, unsafe path/link
state, temp-write failure, validation failure, and replacement failure do not
blindly overwrite a newer assignment.

The bulk-only mutation API can change only:

```text
answer_key
standards
standards_profile_id
```

The interactive editor may stage a title change in the same session; its final
whole-editor plan still preserves assignment identity, question count, choices,
and layout and commits the complete staged definition through the same guarded
replacement mechanism.

## Preset integration

Issue #185 extends issue #184 presets without changing preset ownership.

Manual preset creation uses the shared bulk answer-key UI. Preset editing and
staged editing during preset application reuse the same assignment bulk key and
alignment helpers.

Editing a preset never propagates into assignments previously created from that
preset. Editing a staged assignment derived from a preset never changes the
saved preset. #184's exact preset plan/commit concurrency checks remain in force.

## Direct CLI

The prompt-free command is:

```powershell
scoreform bulk-edit-assignment `
  --class-id <class_id> `
  --assignment-id <assignment_id> `
  [answer-key source] `
  [alignment source] `
  [--standards-profile-id <profile_id>] `
  [--apply]
```

Choose at most one answer-key source:

```text
--answer-key-text <text>
--answer-key-csv <path>
--answer-key-json <path>
```

Choose at most one alignment source:

```text
--alignment-text <text>
--alignment-csv <path>
--alignment-json <path>
```

At least one key or alignment source is required. CSV/JSON paths are explicit,
read-only regular files with the expected suffix; directories and symlinks are
rejected and file size is bounded to 1 MiB.

Without `--apply`, the command is **plan-only**. It prints the complete normalized
key, complete normalized alignment, original and candidate digests, changed
assignment fields, and downstream state that will remain untouched. It writes
nothing.

`--apply` is the only mutation switch and invokes the guarded replacement
service. There is no `--force` or `--overwrite` mode.

Example:

```powershell
scoreform bulk-edit-assignment `
  --class-id english10_p2 `
  --assignment-id unit_1_quiz `
  --answer-key-text "A B C D" `
  --apply
```

## Authority and non-effects

Bulk setup remains teacher-authored assignment definition, not grading policy.

The workflow does **not**:

- rescore or select an attempt;
- choose an official/best/latest attempt;
- calculate proficiency, mastery, or a course Grade;
- generate or regenerate answer sheets;
- modify page, issuance, route, scan, or scan-review identity;
- register Academic Work;
- generate or publish manifests;
- mutate Core Publication Records/catalog state; or
- introduce a Meridian runtime dependency.

Core continues to own shared standards authority, routing/retention, Academic
Work Registration, and Publication Records/catalogs. ScoreForm owns its
assessment definition and producer evidence. Meridian owns attempt-selection and
grade/proficiency policy.

## Acceptance

Automatable coverage includes parser, staging, path safety, stale-state,
atomic-replacement, creation/edit, preset, direct CLI, and cancellation tests.

Clean installed-wheel acceptance is:

```text
scripts/verify_installed_assignment_bulk_entry_acceptance.py
```

The verifier runs the installed `scoreform` entry point outside the source tree
against the exact supported Core baseline and proves:

- installed ScoreForm and Core versions/provenance are correct;
- `pip check` succeeds;
- the installed bulk command/help is discoverable;
- explicit CSV key and JSON alignment inputs remain byte-identical;
- plan-only output contains the complete normalized key/alignment and writes
  nothing;
- `--apply` persists one validated combined key/alignment replacement;
- current Core profile membership is enforced;
- a bad alignment supplied with a new key cannot partially apply the key;
- alignment-only planning retains the current profile when no replacement
  profile is requested;
- result/sheet/scan/debug/export sentinels remain byte-identical;
- no Academic Work Registration or Publication Record state is created; and
- no assignment replacement temp file is left behind.

Physical print/scan behavior is not part of #185 and remains qualified by the
later physical acceptance issue.
