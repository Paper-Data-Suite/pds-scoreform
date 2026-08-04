# ScoreForm academic-result publication revision policy

## Status and ownership

This is the active producer policy for the unchanged
`scoreform_academic_result_manifest_v1` contract. The pure implementation is
`scoreform.publication_revision_policy`. It compares immutable manifest values,
validates append-preserving transitions, allocates producer revisions, and
returns immutable decisions for later generation and publication workflows.

ScoreForm owns record-set identity, producer revision allocation, native-evidence
comparison, and transition validity. Core owns Academic Work Registration,
immutable Publication Records, canonical publication-series state, explicit
supersession and withdrawal records, and catalog derivation. Consumers own
attempt selection, grading, Academic Period membership, and proficiency policy.
This module does not read or write a workspace, generate a manifest, inspect a
Core registry, or publish, supersede, or withdraw anything.

## Stable production identity

Every managed ScoreForm assignment uses the literal producer record-set ID
`academic_results`, exposed as
`SCOREFORM_ACADEMIC_RESULT_RECORD_SET_ID`. A complete series is:

```text
ModuleWorkRef("scoreform", <class_id>, <assignment_id>)
+ publication_kind="academic_result_set"
+ record_set_id="academic_results"
```

The ID remains unchanged across attempts, corrections, revisions, withdrawal,
and republication. It is independent of title, time, hashes, attempt and revision
numbers, package versions, and Core record IDs. It is not generated from a UUID,
class, assignment, digest, date, or random value. The complete work reference
already separates assignments and classes. Changing `assignment_id` therefore
creates a different work and series, not a successor. Contract examples may
continue to use clearly synthetic record-set IDs; production planning rejects
them.

## Independent concepts

These values are intentionally independent: ScoreForm attempt number, routed
results schema version, manifest contract version, record-set revision,
source-file byte revision, Core Academic Work Registration revision, Core
Publication Record schema version and ID, Core series head, and ScoreForm and
Core package versions. In particular, attempt numbers do not allocate manifest
revisions, registration updates do not automatically republish evidence, and a
Core record ID or package release is not a producer revision.

## Allocation and decision matrix

The first durably allocated manifest is revision 1. Normal later allocation is
one greater than the highest producer revision ever allocated. Existing gaps are
preserved, but normal allocation does not create a new gap. A durable unpublished
manifest, a withdrawn revision, and a missing historical file all continue to
consume their numbers. A failure before durable immutable creation consumes no
number; #165 owns that filesystem boundary.

| State or event | Producer decision |
| --- | --- |
| no allocated manifest | `create_initial`, revision 1 |
| unchanged complete publication content and usable bytes | `reuse_existing` with the exact bytes |
| exact assignment or results source SHA-256 changes | `create_successor` |
| authoritative attempt is appended | `create_successor`, complete snapshot |
| title, standards profile, or question alignment changes | `create_successor` |
| current state intentionally matches an older non-head revision | `create_successor`, never reuse the old revision |
| withdrawn head is explicitly republished unchanged | `create_successor` |
| catalog, package, release, registration-only, period, consumer, or report change | no new revision |

Calling policy again, retrying identical work, repeated canonical serialization,
catalog repair, compatibility discovery, package upgrades, releases, independent
registration changes, school-year changes, consumer grading choices, and report
regeneration do not create a manifest revision. Exact native byte changes do,
even when parsed educational results are unchanged, because the source SHA-256
values are publication content.

## Publication-content comparison and exact replay

`manifests_have_same_publication_content` ignores only `generated_at` and
`record_set.revision`. It compares record-set ID, complete work identity, source
paths, hashes and contract versions, assignment snapshot, students, attempts,
responses, correctness, alignments, origins, provenance, and every other field.

An exact replay selects the existing logical revision and its exact canonical
bytes. It preserves generated time, manifest digest and path, source snapshots,
Core publication ID and time, predecessor, and withdrawal state. A no-op never
updates `generated_at`, writes equivalent new bytes, increments a revision, or
creates another logical Core revision. Reusing a logical revision with different
manifest bytes, source hashes, identity, digest, path, registration revision,
capabilities, source record, or predecessor is an integrity conflict.

## Append-preserving attempt history and corrections

Attempt identity is complete work identity plus `student_id` plus
`attempt_number`. Every predecessor student and attempt remains present, and the
complete attempt value—origin, recorded timestamp, score, possible points,
responses, correctness, and provenance—remains unchanged. New students and
attempts may be appended. For an existing student, every new attempt number must
be greater than the student's greatest published number; historical gaps cannot
be filled.

A correction is a new authoritative native attempt with a new number. The old
attempt remains evidence. History is never renumbered, collapsed, deleted,
selected, or rewritten. The manifest adds no `official`, `selected`,
`replacement`, `best`, `latest_for_grading`, or similar grading field. Consumers
may later select evidence under an explicit policy.

## Assignment-change boundary

Title, standards-profile and alignment corrections, nonstructural source-byte
corrections, and answer-key corrections accompanied by append-preserved corrected
attempts may remain in the series. Question count, layout, answer-choice
vocabulary, total points, question numbering, or per-question possible points
redefine the assessment and require a new assignment/work identity. Existing
attempts are never truncated, padded, reinterpreted, or silently rescored to fit
a structural change.

## Historical reversion, supersession, and withdrawal

When current native state returns to older content but differs from the head, a
new greater revision records that restoration. ScoreForm never republishes or
mutates the old revision, restores its Publication Record as current, branches
from it, or reuses its number.

A later selectable publication explicitly supersedes the exact expected current
Core Publication Record ID. It retains the complete work identity,
`publication_kind="academic_result_set"`, `record_set_id="academic_results"`,
and a greater producer revision. The predecessor is never inferred from revision,
time, filename, directory order, or opaque IDs. #167 must reload canonical Core
state and stop on a changed expected head. A withdrawn head remains the chain
head and can be explicitly superseded; supersession makes a predecessor
historical but does not withdraw it.

Withdrawal targets one exact publication when it must no longer be selectable,
such as accidental publication, wrong work identity, unrecoverable source or
manifest integrity, privacy/authorization concern, or nonauthoritative evidence.
It is a separate immutable Core record with a privacy-minimized reason. It does
not delete or rewrite a Publication Record, manifest, native result, digest,
timestamp, attempt, or supersession history, and it does not restore a prior
revision. Normal updates and corrections use supersession, not withdrawal.

Republishing after withdrawal is explicit. Preserve the withdrawn record,
withdrawal, and manifest; allocate a new greater revision (even when native
hashes are unchanged); create new immutable bytes; and later explicitly
supersede the withdrawn head. An ordinary retry never creates this replacement.

## Missing or altered manifest recovery

If trusted exact bytes reproduce the recorded digest, restore only those bytes at
the original canonical path. This is recovery, not a revision. Do not change its
bytes, revision, digest, path, or Publication Record.

If exact bytes cannot be recovered, never reconstruct different bytes under the
old revision. Treat the publication as unverifiable, withdraw it when
appropriate, preserve remaining history, allocate a later complete manifest from
current authoritative native state, and explicitly supersede through #167. A
missing or corrupt derived catalog is unrelated and never triggers a producer
revision.

## Worked sequence

```text
revision 1
  initial attempts published

revision 2
  additional PDS2 attempt appended
  explicitly supersedes publication for revision 1

revision 3
  corrected manual attempt appended; original attempt remains
  explicitly supersedes publication for revision 2

publication for revision 3 withdrawn
  publication and manifest remain immutable
  revision 2 does not become current again

revision 4
  unchanged native state intentionally republished
  explicitly supersedes the withdrawn publication for revision 3
```

## Later-issue boundary

#163 upgrades Core without changing this policy. #164 registers Academic Work.
#165 reads and hashes native files, constructs complete manifests, durably writes
revision-addressed immutable bytes, and enforces allocation failure boundaries.
#166 advertises producer capability. #167 reconciles exact Core state and creates
Publication Records, explicit supersessions, and withdrawals. #168–#170 add the
consumer reader and release acceptance. None of those workflows is implemented
by this policy module.
