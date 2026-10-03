# Issue #219 Slice 3 — Format-aware report destination identity

## Scope

Slice 3 makes Results Analysis export destinations include the selected report
format.

The assignment-local export root remains:

```text
classes/<class_id>/modules/scoreform/work/<assignment_id>/
  exports/results_analysis/
```

The report directory identity becomes:

```text
<class-or-student-scope>_<format>_<UTC timestamp>
```

Examples:

```text
class_analysis_csv_20261001T220000Z
class_analysis_json_20261001T220000Z
class_analysis_pdf_20261001T220000Z
student_detail_pdf_20261001T220000Z
```

## Why

Issue #217 used only scope and timestamp:

```text
class_analysis_20261001T220000Z
```

That meant two different formats prepared during the same second targeted the
same create-only directory.

Format is part of the teacher-confirmed report plan, so it belongs in the
destination identity.

## Create-only behavior

Format awareness removes only cross-format collisions.

It does not weaken replay protection.

For the same:

- assignment;
- scope;
- format; and
- frozen generated timestamp,

the destination is identical and a second export still fails safely if that
directory already exists.

ScoreForm does not:

- overwrite;
- append a random suffix;
- increment a counter;
- alter the frozen timestamp after confirmation; or
- silently choose another destination.

## Destination contract

`ResultsReportDestination` now records `output_format` in addition to scope and
generated timestamp.

Installation validates both:

```text
rendered.scope == destination.scope
rendered.output_format == destination.output_format
```

A renderer result cannot therefore be installed into a destination planned for
another format.

## Privacy and containment

The path still contains no:

- student name;
- student ID;
- response data; or
- Standard identity.

The existing workspace-containment and managed-work-root checks remain in
force.

## Mutation boundary

Destination planning remains zero-write.

Installation remains create-only and retains the existing partial-failure
cleanup behavior.

No assignment, result, scan, Standard, route, publication, or Meridian state is
modified.

## Deferred

Post-export local-open actions remain Slice 4.

Core v0.6.4 dependency-floor adoption and ScoreForm v0.12.0 release work remain
later #219 slices.
