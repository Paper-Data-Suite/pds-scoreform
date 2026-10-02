# Issue #217 — Interactive Class Analysis

## Slice 3 scope

Slice 3 adds the class-level interactive analysis surfaces beneath Review
Results:

```text
Question Analysis
Standards Analysis
```

Both consume the immutable Slice 1 `ClassResultsAnalysis` model. No terminal
formatter recalculates assessment semantics.

## Question Analysis

Question Analysis uses exactly one most-recent scored display attempt per
student and states that basis in the view.

For each question it shows:

```text
Correct
Incorrect
Blank
Ambiguous
Total
% Correct
```

with the invariant:

```text
Total = Correct + Incorrect + Blank + Ambiguous
```

Selecting a question shows the response distribution in deterministic order:

```text
assignment choices
BLANK
AMBIGUOUS
```

and identifies the keyed answer.

The view is descriptive only. It does not diagnose misconceptions, item
validity, or instructional cause.

## Class Standards Analysis

Standards Analysis uses the same represented student attempts and the
assignment's current question alignment.

For each actual Standard it shows:

```text
Correct
Responses
Percent
```

`Responses` is intentionally not labelled `Students`: several aligned questions
may contribute for one represented student.

A multi-Standard question contributes once to every attached Standard.

Selecting a Standard shows the exact assignment questions that contribute to
that Standard and their class-level correct/response counts.

Unaligned questions remain separately reconcilable and do not become a
fabricated Standard.

## Boundaries

Slice 3 remains read-only and does not:

- change `results.csv`;
- choose a Grade-bearing attempt;
- infer proficiency/mastery;
- alter assignment alignment;
- publish data;
- write report artifacts; or
- add export behavior.
