# Issue #217 — Deterministic CSV and JSON Renderers

## Slice 5 scope

Slice 5 adds pure in-memory renderers for the immutable report snapshots created
by Slice 4.

No renderer writes to the filesystem.

The output-custody layer remains deferred to Slice 7.

## Shared rendered-artifact contract

`scoreform.results_report_artifacts` defines immutable rendered artifacts:

```text
filename
media_type
content bytes
sha256
```

A rendered report contains a bounded tuple of these artifacts plus its explicit
format and report scope.

Logical artifact filenames are privacy-minimized basenames. They do not contain
student names.

This contract is also suitable for the later PDF renderer.

## CSV

CSV output is a bounded report set rather than one denormalized table.

### Class Analysis CSV

The class scope produces:

```text
report_metadata.csv
assignment_overview.csv
question_analysis.csv
response_distribution.csv
standards_analysis.csv
unaligned_analysis.csv
```

It intentionally does **not** emit `student_responses.csv`.

This enforces the Issue #217 default:

```text
Class report does not include every student's full response rows by default.
```

`assignment_overview.csv` still includes the represented student's compact
result summary because that is part of the ordinary Assignment Overview.

### Student Detail CSV

The student scope produces:

```text
report_metadata.csv
assignment_overview.csv
student_responses.csv
standards_analysis.csv
unaligned_analysis.csv
```

It contains only the exact student attempt selected in the report snapshot.

### Student response state

For selected A/B/C/D responses:

```text
response_state = SELECTED
selected_answer = A | B | C | D
```

For blank/ambiguous responses:

```text
response_state = BLANK | AMBIGUOUS
selected_answer = empty CSV cell
```

Correctness remains an independent Boolean column.

### Standard labels

Slice 5 uses the durable Standard ID as `display_label`.

This is the required safe fallback when no authoritative friendly label has
been resolved.

Arithmetic never depends on a friendly label.

### Unaligned questions

`Unaligned` is not fabricated as a Standard.

It is emitted separately in:

```text
unaligned_analysis.csv
```

### CSV determinism

CSV uses Python's standard `csv` writer with:

```text
UTF-8
LF record endings
deterministic row order
safe CSV quoting
```

Question order, response order, student order, and Standard order come directly
from the immutable analysis models.

## JSON

JSON is the richest machine-readable ScoreForm-native report.

The root preserves:

```text
schema_version
generated_at
scope
class_id
assignment snapshot
report basis
selected analysis scope
```

The schema identity remains:

```text
scoreform_results_analysis_v1
```

Serialization uses:

```text
UTF-8
indent = 2
sort_keys = true
trailing newline
```

so identical snapshots render byte-identically.

### Class JSON privacy boundary

Class JSON contains:

```text
assignment overview summaries
question analysis
response distributions
Standards analysis
unaligned summary
```

It does not expose each represented student's question list by default.

### Student JSON

Student JSON contains the complete exact selected attempt, including:

```text
identity
attempt metadata
score
question responses
BLANK / AMBIGUOUS
answer key
correctness
question Standards
student Standards analysis
unaligned summary
```

It does not create a cross-assignment or cross-class dossier.

## No independent semantics

Neither renderer rescoring answers or recomputes grading policy.

They only flatten/serialize immutable Slice 4 report snapshots and the analysis
models those snapshots contain.

Percent values come from the shared analysis models.

## Deferred

Slice 5 does not add:

- PDF rendering;
- output directories;
- class/assignment filename tokens;
- create-only filesystem behavior;
- conflict handling;
- Review Results menu export integration; or
- installed-wheel qualification.
