# Issue #219 Slice 2 — Standards-profile presentation ordering

## Scope

Slice 2 adds current Standards-profile ordering to the Results Analysis
presentation projection created in Slice 1.

It does not change the underlying descriptive analysis models.

## Authority

`StandardPerformance.standard_id` remains the authoritative Standard identity.

`StudentAttemptAnalysis.standards` and `ClassResultsAnalysis.standards` retain
their existing deterministic lexical durable-ID order and validation
invariants.

Profile ordering is applied only when presenting or rendering those immutable
analysis values.

## Core profile order

When an assignment has a current `standards_profile_id`, ScoreForm asks Core
for that profile's Standard members using:

```text
list_standards_for_profile_selection(..., active=None)
```

Core therefore remains authoritative for the profile's stored member order.

`active=None` is deliberate: an inactive Standard can still be part of the
assignment's current alignment and should retain its profile position. Its
teacher-facing label continues to carry Core's `[inactive]` marker.

## Ordering precedence

For the aligned Standard IDs in the assignment:

```text
1. current resolved profile order
2. aligned IDs not represented by that current profile, in lexical durable-ID order
3. lexical durable-ID order for all aligned Standards when the profile is unavailable
```

The lexical tail matters for stale-but-readable assignments. A current profile
may have changed since the assignment was created; ScoreForm must not drop an
aligned Standard merely because that ID is no longer a member of the profile.

## Fail-soft profile boundary

Profile resolution is independent from label resolution.

If the Standards Library is readable but the assignment's current profile no
longer exists:

- Standard labels may still resolve normally;
- Standard order falls back to deterministic lexical durable-ID order.

If the library itself cannot be read safely, Slice 1's ID-only fallback remains
in force.

## Presentation surfaces

The same frozen presentation order is used by:

```text
Student Standards Breakdown
Student Standard selection
Class Standards Analysis
Class Standard selection
CSV standards_analysis.csv
JSON standards_analysis arrays
PDF Standards tables
```

A numeric Standard selection therefore refers to exactly the row the teacher
sees.

## Reports

Report snapshot preparation freezes both:

- current Standard display labels; and
- current profile-derived presentation order.

CSV, JSON, and PDF renderers consume that frozen projection and do not reopen
the Standards Library.

A later edit to the current profile cannot change a report after its snapshot
has been prepared.

The report schema remains:

```text
scoreform_results_analysis_v1
```

No CSV columns or JSON fields change in Slice 2.

## Non-goals

Slice 2 does not:

- reorder `StandardPerformance` analysis models;
- change correct/response counts;
- change multi-Standard counting;
- infer performance or proficiency ordering;
- snapshot historical scoring-time profiles;
- mutate assignment alignment;
- mutate the Core Standards Library;
- change `results.csv`;
- change the Core dependency floor or ScoreForm version.

Those release changes remain for later #219 slices.
