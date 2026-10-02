# Issue #217 — Interactive Student Detail

## Slice 2 scope

Slice 2 adds the first interactive analysis surface beneath Review Results:
**Student Detail**.

The Review Results landing view still begins with the compact Assignment
Overview. It now offers:

```text
1. Student Detail
```

Question Analysis, class Standards Analysis, and export remain deferred to later
slices.

## Student selection and attempts

Student Detail uses the strict schema-v2 history already loaded for the selected
assignment.

For a selected student:

- every preserved scored attempt remains independently available;
- the default is the same most-recent display attempt used by Assignment
  Overview;
- the highest score is never chosen automatically;
- selecting a historical attempt is explicit and read-only.

No attempt is labelled official, Grade-bearing, best, preferred, or superseded.

## Question detail

The selected attempt displays:

```text
Question
Response
Key
Result
Standard(s)
```

The Result column preserves the four descriptive states:

```text
Correct
Incorrect
Blank
Ambiguous
```

`BLANK` and `AMBIGUOUS` remain visible as exact recorded response states.

## Student Standards breakdown

The same selected attempt displays descriptive:

```text
Standard
Correct
Asked
Percent
```

and reconciles unaligned questions separately.

The view states:

```text
Standards basis: current assignment alignment.
```

The teacher may select an aligned Standard and inspect only the exact questions
that contributed to that Standard's count.

No friendly-label resolution is required in this slice; durable Standard IDs
are the safe fallback and remain the calculation identity.

## Boundary

This remains a read-only ScoreForm view.

Slice 2 does not:

- rescore attempts;
- modify `results.csv`;
- change assignment alignment;
- infer proficiency/mastery;
- choose a Grade-bearing attempt;
- publish to Core or Meridian;
- write report files; or
- add export behavior.
