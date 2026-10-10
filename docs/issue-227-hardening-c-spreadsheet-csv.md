# Issue #227 — Hardening C: spreadsheet-safe CSV presentation

Human-facing CSV exports are **not** the canonical ScoreForm result history. When
opened by a spreadsheet program, a text cell beginning with `=`, `+`, `-`, or
`@` (potentially after whitespace or invisible Unicode prefix characters) may
be interpreted as a formula rather than a literal student name, title, label,
or response. CSV quoting does not prevent this behavior.

## Scope

- `scoreform.csv_spreadsheet_safety.spreadsheet_safe_cell` adds a **leading
  apostrophe in presentation CSV only**, when a string has a formula-like
  prefix, or a leading ASCII control character that can affect spreadsheet
  interpretation. Non-string numeric/Boolean inputs remain their original
  types. Ordinary strings are byte-for-byte unchanged until CSV encoding.
- `scoreform.results_report_csv._csv_bytes` applies this protection to each
  textual cell in report-set CSVs, including assignment metadata, students,
  response values, and Standards display labels. It does **not** change
  numbers, column layouts, report filenames, or non-CSV renderers.
- `scoreform.results.export_to_csv` applies the same protection to the legacy
  manual-image-scoring **export**, including identity and source-file columns.
- **Excluded on purpose:** durable routed `results.csv` histories, source
  rosters, native assignment definitions, publication manifests, academic-result
  readers, Standards identity records, JSON/PDF reports, and stored evidence.
  Those data contracts must preserve their exact values.

## Compatibility and limitations

This is a presentation encoding. A spreadsheet-safe CSV cell such as an
assignment title `=SUM(1,2)` is exported as `'=SUM(1,2)`. Applications that
need unaltered text should use the corresponding JSON report or native
canonical data, rather than treating presentation CSV as a lossless input.
Apostrophe handling varies by spreadsheet import/export settings and versions;
consumers must not rely on re-exporting a CSV from a spreadsheet to preserve
this protection. Supported threat boundary is opening ScoreForm-produced CSV
in conventional spreadsheet applications, not arbitrary transformations or
user modification after export.

## Acceptance

- Adversarial `=`, `+`, `-`, `@`, whitespace, BOM, zero-width, and control-prefix
  cases receive deterministic, idempotent text protection.
- Class/student reports escape problematic student display names and assignment
  titles without mutating original models or JSON reports.
- Legacy manual-scoring CSV exports protect textual cells without modifying
  canonical routed-results CSV writers.
- Ordinary student text, Standards IDs, numbers, booleans, columns, and report
  artifact ordering stay unchanged.
- Existing reporting, results, installed acceptance, CI and release-compatibility
  tests continue to pass against Core >=0.6.5,<0.7.

No package-version bump, schema change, or release authorized by this slice.
