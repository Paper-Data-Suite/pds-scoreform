# Issue #217 — Export Menu Integration and Output Custody

## Slice 7 scope

Slice 7 connects the completed analysis/rendering layers to Review Results and
adds the only filesystem-writing boundary for Issue #217.

The Review Results landing view now includes:

```text
1. Student Detail
2. Question Analysis
3. Standards Analysis
4. Export Results Report
```

The ordinary overview remains the landing orientation surface.

## Export workflow

The teacher explicitly selects:

```text
scope
    Class Analysis
    Student Detail

format
    CSV
    JSON
    PDF
```

Student Detail additionally requires an explicit student and preserved attempt.
When several attempts exist, Enter defaults to the same recent-display attempt
used by the overview, while any preserved attempt can be selected explicitly.

Before writing, the workflow freezes the report snapshot and shows:

```text
class
assignment
scope
attempt basis or exact student attempt
identity inclusion
format
generated timestamp
workspace-relative destination
create-only warning
```

The exact confirmation token remains:

```text
GENERATE
```

Any other input cancels with no report write.

## Canonical local destination

Reports are stored below the selected assignment's existing ScoreForm-managed
`exports/` path:

```text
classes/<class>/modules/scoreform/work/<assignment>/
  exports/
    results_analysis/
      <scope>_<UTC timestamp>/
```

Examples:

```text
class_analysis_20260930T234500Z/
student_detail_20260930T234500Z/
```

The class and assignment identity already exist in the canonical directory
hierarchy, so default report-directory names do not repeat them.

Student names are never placed in default paths.

Student IDs are also unnecessary in the default path.

## Format contents

A PDF directory contains:

```text
results_analysis.pdf
```

A JSON directory contains:

```text
results_analysis.json
```

A CSV directory contains the bounded report set produced by Slice 5.

## Create-only behavior

The final report directory is created exclusively.

If it already exists, export fails safely.

Existing report artifacts are never overwritten.

All renderer artifact filenames are validated as simple basenames before they
reach output custody.

## Failure cleanup

Output custody creates the report directory first and installs every artifact
using exclusive binary creation.

If any artifact installation fails:

- files created by the current operation are removed;
- the current report directory is removed when empty; and
- parent directories created solely for the failed operation are removed when
  they remain empty.

Unrelated prior exports are never deleted.

## Mutation boundary

Viewing remains write-free.

Cancel/back before `GENERATE` writes nothing.

Successful export mutates only the requested assignment-local report
destination.

It does not modify:

```text
assignment.json
results.csv
answer key
Standards alignment
scans
retained source
attempt numbering
manifest/publication state
Core Standards
Meridian state
```

## Language boundary

Successful output is described as:

```text
Results Report Created
Report directory: ...
Created files: ...
```

ScoreForm does not claim the report was sent, shared, delivered, received, or
approved.

## Deferred to Slice 8

Slice 8 remains responsible for final qualification:

- full pytest;
- repository-wide Ruff;
- mypy;
- documentation/package/repository validation;
- installed-wheel acceptance;
- release/version decisions;
- final validation record.
