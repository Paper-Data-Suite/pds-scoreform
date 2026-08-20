# Assignment Copying Contract

Assignment copying is a ScoreForm v0.11 teacher-workflow capability introduced
by issue #183. It implements `SF-AC02` from
`docs/v0.11.0_usability_acceptance_cases.md`.

The operation exists for the common teacher task:

> I already created this assessment for one class or period; use the same
> assessment configuration in another class without making me re-enter it.

The safety invariant is:

```text
copy assignment configuration
!=
copy assignment state
```

A copy is a **new independent managed ScoreForm assignment** under a fresh
class-qualified work identity. It is not a filesystem clone and it is not a
live link back to the source.

## Canonical identity

ScoreForm work remains class-qualified through Core:

```text
module_id = scoreform
class_id  = <Core class>
work_id   = <assignment_id>
```

Canonical storage is:

```text
classes/<class_id>/modules/scoreform/work/<assignment_id>/
```

Therefore the same assignment ID can legitimately exist in several classes:

```text
english10_p2/unit_1_quiz
english10_p4/unit_1_quiz
```

A same-class copy is also allowed when the teacher chooses a different unused
assignment ID:

```text
english10_p2/unit_1_quiz
->
english10_p2/unit_1_quiz_makeup
```

The exact source work identity can never be its own target.

## Source contract

The source is selected by exact:

```text
source class_id
source assignment_id
```

and must resolve to the canonical managed:

```text
assignment.json
```

ScoreForm validates:

- canonical path/work identity;
- regular-file and symlink safety;
- strict JSON bytes, including duplicate-key rejection;
- assignment schema/content;
- assignment ID equality with the work identity; and
- current Core standards/profile references when the assignment uses standards.

The source snapshot binds the exact reviewed bytes and SHA-256. Commit
revalidates those bytes before any target is written. If the source changes
after preview, the operation stops and requires a new plan.

The source is never modified by the copy operation.

## Positive reusable-field allowlist

A target candidate is constructed from an explicit positive allowlist:

```text
assignment_id
title
question_count
choices
layout_id
answer_key
standards
standards_profile_id  # only when present
```

The target assignment ID is teacher-selected. The title defaults to the source
title and may be changed before commit.

The implementation does not copy an arbitrary source dictionary and then delete
known-dangerous fields. Unknown or future assignment fields therefore do not
become copyable automatically.

Nested answer-key and standards values are independent copies. Later editing of
one assignment does not mutate or synchronize the other.

## Core roster and period authority

Core owns class rosters and period data.

The copy operation resolves every target class through the current canonical
Core roster and shows a privacy-minimal summary:

```text
class_id
student count
period value(s)
school year when valid metadata is available
```

It does not copy:

```text
roster.csv
student rows
student IDs as assignment state
period values
Core class metadata
```

The target's future generation/scoring behavior continues to derive students
from that target class's current Core roster.

A change to the reviewed target roster/class summary before commit invalidates
the plan rather than silently applying stale context.

## Standards authority

When the assignment contains standards/profile references, those references are
revalidated against the current Core standards library.

Copying fails closed for stale or invalid profile/standard references. ScoreForm
does not silently:

- remove stale standards;
- replace the profile;
- map by display label;
- drop invalid alignments; or
- create new Core standards state.

No standards library or profile is copied into assignment-local storage.

## Create-only destination rule

Assignment copying has **no overwrite mode**.

A target is eligible only when its complete canonical ScoreForm work root does
not already exist.

An existing work root is a collision even when `assignment.json` is absent,
because the work identity could contain partial, legacy, corrupted, generated,
evidence, or future operational state.

The copy workflow never:

```text
--overwrite
--force
merge
adopt
clean
delete-and-recreate
```

an existing target.

Where public Core APIs expose existing Academic Work Registration or Publication
history for the proposed target identity, that state is also treated as a
conflict requiring investigation.

## State that is never inherited

Copying does not carry source classroom/evidence history.

It never copies or creates source-derived:

- rosters or student rows;
- generated answer-sheet PDFs/templates;
- answer-sheet records;
- issuance IDs;
- page IDs;
- PDS2 route IDs or registrations;
- QR payloads;
- retained scans;
- scan-review/resolution history;
- `results.csv`;
- attempts, answers, scores, or totals;
- plain-paper/manual scoring history;
- Academic Work Registration;
- academic-result manifests;
- Publication Records, supersession, withdrawal, or catalog state;
- debug/export artifacts; or
- unknown/future work descendants.

A successful normal copy creates only:

```text
fresh managed ScoreForm work layout
fresh assignment.json
```

No sheets are generated automatically.

No academic result is registered, manifested, or published automatically.

## Planning and commit

Both the direct CLI and teacher menu use the same application service.

Planning is non-mutating. It validates:

- source snapshot;
- copied definition;
- target assignment ID/title;
- target Core rosters;
- target path safety;
- duplicate targets;
- source/target identity conflicts;
- destination cleanliness;
- standards validity; and
- known shared Core registration/publication conflicts.

Before the first write, commit revalidates the complete plan, including:

- source bytes/digest;
- candidate digest;
- target roster/class summaries;
- standards;
- target path safety; and
- target absence.

A target that appears after preview is not overwritten.

## Multi-target semantics

One operation may target several classes.

All predictable validation and collision failures are found before the first
write. A known-invalid target prevents the confirmed batch from starting.

Filesystem operations are not falsely presented as globally transactional.

If an unexpected runtime/I/O failure occurs after one target has already been
durably created:

1. the successful target remains;
2. the failed target is reported;
3. later targets are not attempted;
4. successful state is not rolled back; and
5. the overall operation returns failure/partial-success status.

Cleanup is conservative and may remove only provably operation-created empty
directories. Unexpected residue is reported instead of recursively deleting
unknown state.

## Teacher workflow

Until issue #187 reorganizes Assignment Management, copying is exposed as the
temporary menu entry:

```text
13. Copy an assignment
```

Existing options 1-12 remain unchanged.

The guided workflow asks the teacher to:

1. select a source class;
2. select one exact source assignment;
3. select one or more target classes;
4. keep or change the target assignment ID;
5. keep or change the target title;
6. review the complete copied definition;
7. review every target's class/roster context;
8. review the explicit list of state that will not be copied; and
9. type exact `COPY` to commit.

The preview includes the **complete answer key** and **complete standards
alignment**. It deliberately does not use the older compact/truncated assignment
summary for this mutation boundary.

Before exact `COPY`, ordinary Back/Main/Quit navigation remains available.
Anything other than exact `COPY` creates no target assignment state.

## Direct CLI

The prompt-free command is:

```powershell
scoreform copy-assignment `
  --source-class-id <class_id> `
  --source-assignment-id <assignment_id> `
  --target-assignment-id <assignment_id> `
  --target-class-id <class_id> `
  [--target-class-id <class_id> ...] `
  [--title <title>] `
  [--apply]
```

Without `--apply`, the command is plan-only and writes nothing.

With `--apply`, ScoreForm revalidates and performs the create-only copy.

`--target-class-id` is repeatable and preserves caller order.

There is intentionally no:

```text
--overwrite
--force
```

option.

Expected validation, collision, stale-state, write, and partial-success
failures return nonzero without silently weakening the safety rules.

## Privacy

Copying reads only:

- the source assignment definition;
- bounded target Core roster/class context;
- current standards authority when needed; and
- bounded Core registration/publication state needed to prove a clean target.

Teacher-facing output may show class IDs, assignment IDs, title, student count,
period summary, school year, and workspace-relative target paths.

It does not print or persist roster student rows merely to preview a copy.

No telemetry is introduced by #183.

## Ownership boundaries

Assignment copying remains a ScoreForm setup operation.

Core continues to own:

- class/roster authority;
- standards authority;
- shared work/route identity contracts;
- Academic Work Registration; and
- Publication Records/catalog authority.

ScoreForm owns its assignment definition and copy workflow.

The operation does not:

- select an official/best/latest attempt;
- compute proficiency/mastery;
- compute a Grade; or
- introduce a Meridian runtime dependency.

Those policy decisions remain outside ScoreForm.

## Relationship to later v0.11 work

Issue #183 intentionally does not implement:

- #184 reusable setup presets;
- #185 bulk/paste/CSV/JSON key and alignment entry;
- #186 multi-class answer-sheet generation planning;
- #187 task-oriented Assignment Management redesign;
- #188 recent/active context;
- #189 guided scan-to-results;
- #190 scan diagnostics;
- #191 guided sharing/publication; or
- later suite integration work.

A copy is a one-time transformation from one exact assignment snapshot into one
or more independent assignments. It is not a preset/template inheritance system.

## Acceptance

`SF-AC02` is covered at three levels:

1. focused service tests;
2. focused direct-CLI and menu tests; and
3. clean installed-wheel acceptance through:

```text
scripts/verify_installed_assignment_copy_acceptance.py
```

The installed acceptance runs the real installed `scoreform` console script
outside the source tree. It proves plan-only is non-mutating, `--apply` creates
the fresh class-qualified assignment, target Core roster state is not replaced,
and no sheets/routes/results/manifests/publications are inherited or created.
