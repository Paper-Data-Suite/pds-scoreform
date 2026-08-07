# Academic Result Manifest Generation

## Status and boundary

ScoreForm explicitly generates immutable
`scoreform_academic_result_manifest_v1` revisions for an existing canonical
managed assignment. Generation is producer storage only: it does not register
Academic Work, discover or invoke the installed publication producer profile,
create a Core Publication
Record, supersede or withdraw a publication, rebuild the catalog, select an
attempt, calculate proficiency, or create a Grade.

The canonical bytes generated here satisfy the profile's declared
`scoreform_academic_result_manifest_v1` contract. That compatibility declaration
does not turn generation into publication.

## Eligible native state

The work identity is exactly
`classes/<class_id>/modules/scoreform/work/<assignment_id>`. The work root must
be an existing nonsymlink directory and its validated `assignment.json` identity
must match the requested work. Generation requires existing nonsymlink regular
files `assignment.json` and `results.csv`; it never creates an empty history.
Only strict routed-results schema version 2 headers and rows are accepted. A
valid header-only history produces `students: []`. The validated question width
declared by the CSV header must exactly equal `assignment.json`'s
`question_count`, including for header-only histories and histories whose wider
trailing question cells are blank. An incompatible native history fails closed
with an integrity error; generation does not truncate, pad, reinterpret,
migrate, or rewrite it.

Each native source is opened in binary mode, checked as a regular file through
the opened descriptor, read to immutable `bytes`, checked for stability, and
hashed with SHA-256. The same bytes are parsed. JSON formatting, CSV formatting,
line endings, BOMs, and the final newline are therefore significant. Generation
never rewrites, normalizes, or touches either source.

Assignment JSON decoding requires UTF-8, one JSON object, unique object keys,
and finite numeric values, then uses ScoreForm's native assignment validation.
CSV decoding requires UTF-8 and the existing strict schema-v2 parser and typed
`ScoreFormRoutedResult` validation.

## Mapping and evidence

The assignment snapshot includes identity, current title, question count,
layout, exact layout choices, total points, optional standards profile, and one
ordered one-point question per native question. Standard IDs preserve native
order and are checked against the current Core workspace standards library via
ScoreForm's existing validation boundary. The answer key is excluded.

Every history row must match the requested work and assignment structure.
Students sort by `student_id`; attempts sort by their native positive number.
Duplicate identities are rejected. Recorded score and correctness are preserved
without rescoring against the current answer key. Selected answers remain
selected; `BLANK` and `AMBIGUOUS` become null-selected incorrect states. Names
and periods are excluded.

PDS2 attempts preserve complete native provenance. Every retained path must use
`scans/source/YYYY-MM-DD/<filename>`, resolve beneath the workspace retained
source root to a nonsymlink regular file, and reproduce the recorded SHA-256.
Repeated path/digest validation is cached and contradictory claims fail.
Plain-paper provenance is `{}`. Scan-review manual provenance contains only the
validated failure ID in `review_reference`.

## Immutable storage and replay

Revisions live only at:

```text
classes/<class_id>/modules/scoreform/work/<assignment_id>/
  exports/manifests/academic_results/<positive_revision>.json
```

Only canonical positive decimal filenames are accepted. There is no mutable
alias, overwrite, delete, rename, move, repair, or forced-revision operation.
History loading validates every exact canonical byte sequence, work and record
set identity, and filename/revision agreement. Gaps remain allocated and the
greatest revision is the predecessor.

Generation holds
`exports/manifests/academic_results/.write.lock` across history reload, source
validation, planning, and creation. The existing policy selects initial revision
1, exact replay, or a successor one greater than the highest allocation. Replay
returns the predecessor's exact stored bytes and original `generated_at` without
touching the file.

After planning, retained evidence is revalidated and both native files are
reopened through the safe binary snapshot boundary. Their newly read exact bytes
and SHA-256 values must equal the original immutable snapshots before either an
exact replay may return or a new target path is handled. Concurrent mutation is
classified as `ScoreFormManifestGenerationConflictError`; metadata equality
alone cannot satisfy this gate. The final target is
opened exclusively, written completely, flushed and synced where supported,
closed, reloaded, decoded, and compared to the candidate. The returned digest is
lowercase SHA-256 of the exact stored canonical bytes, including the trailing
newline. Before durability, only an incomplete file created by the operation may
be cleaned up. After durability, the revision is never deleted or rewritten;
later verification or cleanup failures report partial success.

Every failure to remove the generation lock is retained as a public structured
cleanup record containing the lock path, workspace-relative path, message, and
original cleanup exception. It is user-visible even when another validation,
conflict, write, or partial-success error is already active. Before confirmed
durability, an accompanying warning states that no revision was confirmed
durable; an incomplete target created by this operation is removed when
possible and any target-cleanup failure is also preserved. After confirmed
durability, the immutable revision remains allocated and untouched, and the
partial-success state reports both its revision/path/digest and the lock-cleanup
failure. Exact replay also becomes partial success rather than ordinary success
when its newly acquired lock cannot be removed. A pre-existing lock is never
removed by a later invocation.

## User surfaces and privacy

Direct commands are `scoreform manifest list`, `show`, `validate`, and
`generate`. Assignment Management provides **Academic Result Manifests** and
requires typing `GENERATE`. Registration status is informational only.

Routine output never prints full manifest JSON, student IDs, responses,
provenance arrays, names, periods, or answer keys. Generation is not invoked by
registration, assignment setup/editing, sheet generation, scoring, manual entry,
scan-review resolution, result viewing, import, help, version, or profile
discovery. Ordinary generation never publishes automatically. The sole
publication workflow allowed to invoke generation is explicit
`republish-after-withdrawal`, which allocates one successor only when no durable
unpublished producer successor already exists. All other publication operations
select existing immutable producer bytes.
