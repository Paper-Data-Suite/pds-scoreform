# Academic Result Reader

`scoreform.academic_result_reader` is the stable consumer-neutral reader for
`scoreform_academic_result_manifest_v1`.

It accepts immutable bytes already obtained by an authorized consumer, delegates
all producer semantics to ScoreForm's existing manifest contract, requires exact
canonical ScoreForm bytes, and returns the existing frozen manifest models. It
does not discover a workspace, open files, query Core, select a publication,
authorize access, or apply grading or portfolio policy.

## Dependency direction

```text
consumer
  -> scoreform.academic_result_reader
      -> scoreform.academic_result_manifest

ScoreForm
  -X-> consumer-specific policy
```

A Core-backed consumer should first perform its own authorized Core workflow:

```text
discover candidate
-> reload canonical Core state
-> authorize source access
-> verify the Publication Record path and SHA-256 through Core
-> obtain immutable manifest bytes
-> call the ScoreForm reader
-> apply consumer-owned policy
```

The reader does not replace Core's publication-envelope or digest verification.

## Public import

```python
from scoreform.academic_result_reader import (
    lookup_academic_result_attempt,
    read_academic_result_manifest,
)

manifest = read_academic_result_manifest(manifest_bytes)
attempt = lookup_academic_result_attempt(
    manifest,
    student_id="student_alpha",
    attempt_number=2,
)
```

The example requests attempt 2 exactly. It does not imply that attempt 2 is
official, current, best, latest for grading, Grade-bearing, or portfolio-selected.

The module exports exact source, student, attempt, question, and response lookup
functions plus the immutable ScoreForm models required to type those results.

## Exact bytes

`read_academic_result_manifest(value)` accepts only `bytes`.

It:

1. invokes the existing strict ScoreForm manifest decoder;
2. receives a fully validated `AcademicResultManifest`;
3. serializes that model with the existing canonical serializer;
4. requires byte-for-byte equality with the supplied bytes;
5. returns the immutable model.

Semantically equivalent but noncanonical JSON fails closed. Alternate whitespace,
key order, timestamp rendering, missing final newline, or trailing whitespace are
not silently normalized.

Malformed UTF-8, malformed JSON, duplicate object keys, nonfinite values, and
manifest-contract violations are rejected by the existing ScoreForm decoder.
There is no second reader schema or copied validator.

## Reader errors

The public hierarchy is:

```text
ScoreFormAcademicResultReaderError
  ScoreFormAcademicResultReaderValidationError
    ScoreFormAcademicResultReaderDecodeError
  ScoreFormAcademicResultReaderNotFoundError
```

Reader messages are bounded and do not echo manifest JSON, searched student IDs,
selected answers, retained source paths, source bytes, or workstation paths.
Underlying producer exceptions remain available through exception chaining.

## Source snapshots

`lookup_academic_result_source()` accepts exactly:

```text
assignment
results_history
```

and returns the corresponding embedded `AssignmentSourceSnapshot` or
`ResultsHistorySourceSnapshot`.

This is metadata lookup. The reader never opens `assignment.json`, `results.csv`,
a retained scan, or another source path. A manifest source snapshot does not grant
filesystem access and does not create a Core `ModuleRecordRef`.

## Student and attempt identity

Within one exact manifest, represented academic-attempt identity is:

```text
work.module_id
+ work.class_id
+ work.work_id
+ student_id
+ attempt_number
```

The lookup API therefore requests `student_id + attempt_number` inside the exact
manifest. Every represented attempt remains separately accessible.

No timestamp, score, array position, filename, provenance value, or greatest
attempt number substitutes for that identity. Missing students and attempts fail
explicitly; the reader never fabricates zero, missing, incomplete, excused, or
not-submitted states.

## Questions and responses

Questions are looked up by exact `question_number`. Their ordered `standard_ids`
remain ScoreForm assignment alignment metadata, not standards ratings,
proficiency, mastery, or Grade evidence selection.

Responses are looked up by exact student, attempt, and question. The reader
preserves:

```text
selected
blank
ambiguous
```

as distinct native states and returns `selected_answer` and `correct` exactly as
represented. It does not infer an answer key or calculate another score.

A consumer may later choose to omit a native field from its own output. That is
consumer policy, not reader behavior.

## Provenance

Attempts retain their existing producer models unchanged:

```text
Pds2ScanProvenance
PlainPaperManualProvenance
ScanReviewManualProvenance
```

A `retained_source_path` remains provenance data only. The public reader does not
open, sanitize, render, or authorize retained source bytes.

## Consumer boundaries

The reader does not:

- choose an official, latest, best, replacement, or Grade-bearing attempt;
- calculate a Grade, percentage policy, mastery, or proficiency;
- turn question alignment into a standards rating;
- create a Meridian evidence inventory;
- define a portfolio projection or Candidate;
- decide whether selected answers may be exposed;
- authorize student-record access;
- discover or select a Core publication;
- inspect publication withdrawal/current-head state;
- verify a Core Publication Record digest;
- allocate, generate, publish, supersede, or withdraw producer state;
- fabricate durable IDs for `results.csv` rows.

Meridian adapters and portfolio consumers may import this producer-owned reader
and then apply their own explicit policies. ScoreForm does not import those
consumers.

## Installed package

The reader is ordinary package code and requires no new entry point or dependency.
Wheel and source-distribution validation require the module to be present, and
clean-install validation imports it without creating workspace or registry state.

The complete clean-wheel producer lifecycle is verified by
[`installed_producer_acceptance.md`](installed_producer_acceptance.md). That
acceptance feeds Core-verified immutable bytes through this public reader while
preserving separate attempts and keeping consumer policy out of ScoreForm.
