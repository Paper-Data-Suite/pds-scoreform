# Issue #217 — First-Class PDF Renderer

## Slice 6 scope

Slice 6 adds first-class human-readable PDF rendering from the immutable report
snapshot established in Slice 4.

The renderer uses ScoreForm's existing ReportLab dependency.

It produces PDF bytes in memory and performs no filesystem writes.

## Shared artifact contract

The renderer returns the Slice 5 `RenderedResultsReport` contract:

```text
output_format = pdf
scope = class_analysis | student_detail
artifact filename = results_analysis.pdf
media type = application/pdf
content = PDF bytes
```

The default logical filename contains no student name.

Actual destination naming and create-only custody remain deferred to Slice 7.

## Layout

The renderer uses US Letter pages with:

- bounded margins;
- built-in Helvetica fonts only;
- repeated table header rows;
- natural ReportLab pagination;
- a small header on every page;
- a footer with the page number on every page; and
- no network resources or remote assets.

Large assessments paginate rather than shrinking to unreadable text.

## Determinism

PDF rendering uses an invariant ReportLab canvas and uncompressed content
streams.

For one frozen report snapshot, repeated rendering produces byte-identical PDF
content.

The snapshot-generated timestamp remains the report timestamp. The renderer
does not consult the current clock.

## Class Analysis PDF

The class report includes:

```text
report title
class
assignment
generated timestamp
students represented
attempt-display basis
current Standards basis
Assignment Overview
Question Analysis
Response Distributions
Standards Analysis
Unaligned reconciliation when needed
Report Basis statements
```

The class report intentionally does not include every student's
question-by-question response rows.

## Student Detail PDF

The student report includes only the exact selected attempt:

```text
student identity
assignment
attempt number/count
recorded timestamp
overall score
Question-by-Question Detail
response state
answer key
correct/incorrect/blank/ambiguous state
question Standards
Student Standards Breakdown
Unaligned reconciliation when needed
Report Basis statements
```

No cross-assignment or cross-class history is added.

## Standards boundary

Friendly label resolution is still optional.

The durable Standard ID remains the safe display fallback.

Unaligned questions remain a separate reconciliation note and are never
fabricated as a Standard.

## Analytical boundary

Human-readable reports preserve the Slice 4 report-basis statements, including:

> ScoreForm Results Analysis reports descriptive assessment data. Standards
> summaries reflect question alignment and response correctness and are not
> proficiency or Grade determinations.

Class reports also state the recent-display attempt basis.

Standards reports state the current assignment-alignment basis.

## Deferred

Slice 6 does not add:

- filesystem destination selection;
- class/assignment output tokens;
- report directories;
- create-only persistence;
- conflict handling;
- Review Results export menu integration; or
- installed-wheel acceptance.
