# Issue #217 — Results Analysis Foundation

## Slice 1 scope

Slice 1 establishes the shared, read-only descriptive analysis layer for
ScoreForm Review Results.

The new `scoreform.results_analysis` module owns immutable projections for:

- the existing most-recent display-attempt selection rule;
- explicit preserved-attempt selection for one student;
- question-by-question student detail;
- correct / incorrect-selected / blank / ambiguous outcome classification;
- response distributions in assignment choice order followed by `BLANK` and
  `AMBIGUOUS`;
- student Standard correct/response summaries;
- class question analysis;
- class Standard correct/response summaries; and
- unaligned-question reconciliation without inventing a Core Standard.

No menu surface or export writer is added in this slice.

## Authority boundary

The analysis consumes only:

```text
strict schema-v2 ScoreForm result history
+
current validated managed assignment
```

Persisted `ScoredAnswer.correct` values remain historical scored facts. Slice 1
does not rescore historical attempts.

Standard arithmetic uses the assignment's current question alignment:

```text
Standards basis: current assignment alignment
```

A multi-Standard question contributes one response to every attached Standard.
Blank and ambiguous responses remain in the denominator and contribute zero to
`correct`.

`Unaligned` is represented separately as a descriptive reconciliation summary.
It is never fabricated as a Core Standard ID.

## Attempt basis

Class analysis uses exactly the existing Assignment Overview rule:

```text
most recent scored attempt per student for display
```

This is not:

- the highest attempt;
- the best attempt;
- an official attempt;
- a Grade-bearing attempt; or
- a reassessment policy.

`results_viewer.summarize_assignment_results()` now delegates its attempt
selection to the same shared helper used by the new analysis layer.

## Percentage rule

Raw counts remain primary.

When a percentage is requested, Slice 1 uses:

```text
nearest whole percent, halves rounded up
```

Examples:

```text
1 / 8 -> 13%
2 / 3 -> 67%
1 / 2 -> 50%
```

A zero denominator yields no percentage (`None` in the analysis model).

Future terminal, CSV, JSON, and PDF renderers should consume this shared
calculation rather than implementing independent rounding.

## Read-only guarantee

Slice 1 performs no filesystem writes and does not modify:

- `results.csv`;
- assignment JSON;
- answer keys;
- Standards alignment;
- scan/review state;
- Academic Work Registration;
- publication state; or
- Core Standards state.

The existing result schema and publication contracts are unchanged.

## Deliberately deferred

Later #217 slices own:

- interactive Student Detail;
- historical-attempt menu selection;
- Question Analysis menus;
- response-distribution drill-down;
- Standards menus and friendly Core labels;
- report snapshots;
- CSV/JSON/PDF renderers;
- output custody and confirmation;
- installed-wheel acceptance; and
- release/version transition for the combined ScoreForm 0.12.0 line.
