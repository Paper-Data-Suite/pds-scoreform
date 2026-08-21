# Multi-Class Answer-Sheet Generation

Issue #186 implements `SF-AC05` from the ScoreForm v0.11.0 teacher-workflow
acceptance contract.

The teacher outcome is deliberately narrow:

```text
select exact managed targets
+ read-only readiness planning
+ complete multi-target preview
+ explicit confirmation
+ existing exact per-target generation service
= one truthful multi-class generation session
```

This workflow is orchestration over ScoreForm's existing physical-generation
service. It is not a second PDF renderer, issuance system, route-registration
implementation, assignment-copy mechanism, or batch persistence database.

## Exact targets

A target is the pair:

```text
<class_id, assignment_id>
```

The planner operates on ordinary current managed assignments. It does not depend
on assignment-copy lineage. An assignment created normally, copied through issue
#183, or created from a preset through issue #184 is eligible when its current
canonical assignment and class roster are independently generatable.

Cross-target equality is not required. Selected assignments may have different
titles, layouts, question counts, answer keys, or standards alignment. The
planner never infers that two assignments represent the same assessment.

## Read-only plan

Planning performs no generation mutation and allocates no physical identity.
It reads the current canonical assignment, current Core class roster, supported
layout, expected output paths, generation dependencies, and current issuance
lineage. It stores privacy-minimal file and lineage digests so the reviewed state
can be revalidated before generation.

A plan does **not** create:

- PDF artifacts;
- artifact, issuance, page, or route IDs;
- answer-sheet issuance/page records;
- Core route registrations;
- results;
- Academic Work Registration;
- manifests; or
- Publication Records.

The plan is in-memory only and is not persisted as a new workspace record.

## Preview math

For a target with `S` students and `P` logical pages per student, the preview
reports:

```text
individual PDF count        = S
individual physical pages   = S * P
class-packet PDF count      = 1
class-packet physical pages = S * P
total PDF artifacts         = S + 1
total physical-page copies  = 2 * S * P
expected PDS2 routes        = 2 * S * P
```

The teacher preview also reports class, assignment, title, layout, question
count, current generation/regeneration state, canonical output locations, and
all readiness diagnostics. Normal planning output does not enumerate student
rows or student identifiers.

## Readiness and blocking

The planner collects all independently detectable target blockers before
execution. Examples include a missing/invalid assignment, missing/invalid or
empty roster, unsupported layout, unsafe output path, missing generation
dependency, or ambiguous/prepared issuance state.

A known-blocked batch cannot partially start. The teacher or direct caller must
remove/fix blocked targets and build a new ready plan.

Planning checks existing filesystem components without creating missing output
directories. This distinction is important because the exact generation service
is allowed to initialize the canonical template directories when execution
actually starts.

## Stale-plan protection

The reviewed plan is bound to exact assignment bytes, exact roster bytes, and a
digest of the current issuance JSON collection.

Before target 1 executes, ScoreForm re-inspects the entire selected batch. If any
reviewed target changed or became blocked, generation does not start.

Before every later target executes, that exact target is inspected again. If it
changed after earlier targets completed, it is reported as a stale failed target
and is not generated from unreviewed state. Earlier durable successes remain
valid.

## Execution and physical identity

The batch is not a global filesystem transaction. Execution is ordered:

```text
target 1 exact generation
-> target 2 exact generation
-> target 3 exact generation
```

Each target delegates to the existing managed generation service. That service
continues to own record persistence, Core route registration and verification,
PDF rendering, atomic PDF installation, issuance lifecycle transitions, and
predecessor supersession.

One `generation_id` may correlate the complete batch, but it is not a physical
identity. Every generated physical copy receives fresh:

```text
artifact_id
issuance_id
page_id
route_id
```

The batch uses one ephemeral burned-identity registry across all selected targets
so a collision rejected for one target cannot later be reused by another target
within the same execution. Existing single-target callers retain their normal
default behavior.

Individual PDFs and the corresponding class-packet copies remain distinct
physical artifacts with distinct issuance/page/route identities even when their
logical assessment content is identical.

## Failure isolation

Final outcomes are classified as:

```text
CLEAN SUCCESS
PARTIAL — DURABLE OUTPUT EXISTS
FAILED
NOT ATTEMPTED
```

Predictable blockers are rejected before target 1.

A target-local runtime failure may be followed by later independent targets when
continuing is safe. Existing durable output is never rolled back merely to make
the overall batch look atomic.

An installed partial success means the underlying exact generator installed one
or more new PDFs but did not complete every later lifecycle action. That state is
reported truthfully with its failure stage and warnings.

A shared/unexpected failure that makes continued execution unsafe stops the
remaining batch. Later targets are explicitly `NOT ATTEMPTED`, not falsely
reported as failed generation.

There is no automatic replay of the full batch. A retry begins from a fresh plan
and fresh confirmation so previously successful targets are not regenerated by
accident.

## Teacher workflow

Until the broader Assignment Management redesign in issue #187, the Generate
Answer Sheets submenu includes:

```text
1. Generate answer sheets for an existing class assignment
2. Generate a generic blank template
3. Plan generation for multiple classes/assignments
```

The multi-class path keeps an ordered in-memory target basket. The teacher may
add or remove targets, review the complete plan, and must type exact uppercase:

```text
GENERATE
```

before execution begins. Back/Main/Quit or any other final confirmation does not
generate the batch.

Batch execution does not interrupt after each class to ask whether to open its
packet or folder. The consolidated result screen is shown after execution.

## Direct CLI

The prompt-free companion command is:

```powershell
scoreform generate-batch `
  --target english10_p2/unit_2_quiz `
  --target english10_p4/unit_2_quiz
```

`--target` is repeatable and preserves explicit caller order. Exact duplicate
targets are rejected.

Without `--apply`, the command is plan-only and writes nothing:

```powershell
scoreform generate-batch `
  --target english10_p2/unit_2_quiz `
  --target english10_p4/unit_2_quiz
```

Generation requires explicit:

```powershell
scoreform generate-batch `
  --target english10_p2/unit_2_quiz `
  --target english10_p4/unit_2_quiz `
  --apply
```

The direct command never prompts and never opens a PDF/folder. There is no
`--force`, `--overwrite`, implicit discovery, wildcard, identity-reuse, or blind
retry mode.

Existing direct commands remain available:

```text
scoreform generate
scoreform regenerate-sheets
```

## Privacy and non-effects

The planner keeps only the current session's selected identities and
privacy-minimal snapshots in memory. It does not persist target history,
student identity lists, roster rows, telemetry, or a print-job queue.

Planning and generation do not modify canonical assignment or roster bytes and
do not create or change:

- result history;
- retained scans;
- standards authority;
- Academic Periods;
- Academic Work Registration;
- Academic Result Manifests;
- Publication Records; or
- Meridian policy state.

ScoreForm remains an evidence producer. Meridian owns attempt-selection,
proficiency interpretation, and Grade policy.

## Core ownership

Core remains authoritative for shared class/roster identity and PDS2 route
registration. ScoreForm's existing generation service creates a fresh Core route
for every physical page, persists it at the canonical Core path, reloads and
verifies it, and only then renders the canonical locator into the PDF.

The multi-class planner never writes Core route registrations directly.

No Core API gap was required for issue #186. The supported dependency boundary
remains:

```text
pds-core>=0.6,<0.7
```

Installed qualification uses exact Core `0.6.0`.

## Acceptance

The deterministic installed-wheel acceptance is:

```text
scripts/verify_installed_multi_class_generation_acceptance.py
```

It runs outside the source tree against a noneditable ScoreForm wheel and exact
Core 0.6.0. It exercises an assignment copied through the installed #183 path,
plan-only non-mutation, blocked-batch pre-start rejection, two-class generation,
fresh cross-target artifact/issuance/page/route identities, exact reloaded Core
route targets, native assignment/roster noninterference, and absence of Academic
Work/publication side effects.

Real print/scan qualification remains part of issue #195. Automated acceptance
must not be described as proof of physical printer/scanner behavior.
