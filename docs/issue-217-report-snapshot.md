# Issue #217 — Report Snapshot and Export Preparation

## Slice 4 scope

Slice 4 establishes the immutable report boundary consumed by future CSV, JSON,
and PDF renderers.

It deliberately writes no report files.

The new `scoreform.results_reporting` module owns:

- immutable assignment interpretation snapshots;
- immutable Class Analysis report snapshots;
- immutable Student Detail report snapshots;
- explicit `csv` / `json` / `pdf` output intent;
- teacher-facing preview text; and
- exact `GENERATE` confirmation producing a confirmed in-memory plan.

## Why snapshot assignment context

Interactive analysis is derived from:

```text
persisted strict result history
+
current managed assignment
```

A teacher may later edit the assignment's answer key or Standards alignment.
Once an export is previewed, downstream renderers should not reopen mutable
assignment state and accidentally render a different interpretation.

The report snapshot therefore freezes:

```text
assignment_id
title
question_count
choice order
answer key
standards_profile_id
question -> Standard IDs
```

together with the already-derived immutable analysis model.

This does not create academic state and is not persisted in Slice 4.

## Report scopes

Two explicit scopes exist:

```text
class_analysis
student_detail
```

Class Analysis uses:

```text
most recent scored attempt per student for display
```

and records:

```text
include_individual_response_rows = false
```

The in-memory analysis may contain the represented student projections needed
for deterministic rendering, but class renderers must honor the report contract
and not emit every student's response rows by default.

Student Detail requires an exact:

```text
student_id
attempt_number
```

and never silently substitutes the recent, highest, or best attempt.

## Versioned report identity

The shared report snapshot identifies its machine-readable contract as:

```text
scoreform_results_analysis_v1
```

This is a local ScoreForm reporting contract.

It is not:

- an Academic Result Manifest;
- a Core publication;
- a Meridian cache;
- a Grade export; or
- an SIS contract.

## Generated timestamp

Snapshot preparation requires an explicit timezone-aware datetime.

The snapshot canonicalizes it to UTC:

```text
YYYY-MM-DDTHH:MM:SSZ
```

This keeps later renderers deterministic for one prepared snapshot.

## Preview and confirmation

A `ResultsReportPlan` attaches one explicit format:

```text
csv
json
pdf
```

Preview text exposes the selected class, assignment, scope, attempt basis or
exact student attempt, identity inclusion, format, and generated timestamp.

Confirmation is exact:

```text
GENERATE
```

Any other input returns no confirmed plan.

Neither preparation nor confirmation performs filesystem writes.

## Report-basis statements

Snapshots carry the required human-readable analytical boundaries, including:

- descriptive assessment data is not proficiency or Grade determination;
- class aggregates use the most recent scored display attempt per student; and
- Standards summaries use current assignment alignment.

Future renderers consume these statements instead of inventing their own
semantic disclaimers.

## Deferred

Later slices own:

- CSV rendering;
- versioned JSON serialization;
- ReportLab PDF rendering;
- filenames and destination paths;
- create-only/conflict behavior;
- live Review Results export menu integration; and
- installed-wheel qualification.
