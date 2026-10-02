# Issue #219 Slice 1 — Standard label-resolution projection

## Scope

Slice 1 adds a read-only, fail-soft presentation projection for Standards used
by Results Analysis and Results Reporting.

The authoritative identity remains the durable `standard_id` stored in the
current assignment alignment and referenced by the descriptive analysis model.

The projection adds current teacher-facing display metadata only.

## Core authority

ScoreForm does not define another Standard-label grammar.

When the current workspace Standards Library resolves a durable ID, ScoreForm
uses the label returned by Core's `resolve_standard_selection()` /
`StandardSelectionItem.label` contract.

That preserves Core's existing display convention:

```text
code | short_name | source
```

Inactive definitions retain Core's existing `[inactive]` marker.

## Fail-soft boundary

Label resolution is optional presentation metadata.

If:

- there is no workspace Standards Library;
- the library cannot be read or validated safely; or
- an individual Standard ID cannot be resolved,

ScoreForm falls back to:

```text
display_label = standard_id
```

Analysis and reporting continue normally.

No scoring result, percentage, question aggregation, Standard aggregation, or
attempt-selection rule depends on display metadata.

Reading display metadata creates no workspace state.

## Analysis boundary

The Issue #217 analysis dataclasses remain unchanged.

In particular:

- `StandardPerformance.standard_id` remains authoritative;
- Student Detail and class analysis continue to use deterministic durable-ID
  ordering in Slice 1;
- question alignment is still the assignment's current alignment;
- `results.csv` is unchanged.

Profile-order presentation is deliberately deferred to Slice 2.

## Interactive views

Student and class Standards views may now display Core-resolved labels.

Selection still returns the underlying durable Standard ID, so a label never
becomes an identifier.

If callers omit a workspace root, presentation falls back to the durable IDs.
This preserves the pure/testable formatter behavior used by existing callers.

## Frozen report snapshots

When the interactive export workflow prepares a report, it resolves the
current Standard display projection and freezes it into the immutable
`ResultsReportSnapshot`.

Renderers do not reopen the Standards Library.

Therefore a report confirmed from one snapshot cannot change its display labels
because the workspace Standards Library changes between preview and rendering.

## CSV / JSON compatibility

Issue #217 already reserved a `display_label` field in Standards reporting:

- `standards_analysis.csv` already has `standard_id` and `display_label`;
- JSON Standard objects already have `standard_id` and `display_label`.

Slice 1 populates those existing fields with current Core labels when available.

The version remains:

```text
scoreform_results_analysis_v1
```

No CSV column is added or removed and no JSON schema field is added or removed.

Machine-readable output continues to preserve `standard_id` separately.

## PDF

PDF Standards tables use the frozen report projection for the Standard display
cell. The durable identity continues to exist in the underlying analysis and
the corresponding CSV/JSON representations.

## Mutation boundary

Slice 1 performs no writes to:

```text
standards/library.json
assignment.json
results.csv
scans
routes
publications
Meridian state
```

The only new filesystem access is a read of the current Core Standards Library
when a workspace root is explicitly supplied.

## Deferred

Slice 2 remains responsible for current Standards-profile ordering.

Slice 1 intentionally leaves the order of `StandardPerformance` models and all
descriptive calculations unchanged.
