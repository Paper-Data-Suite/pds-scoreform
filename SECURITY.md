# Security Policy

## Project Status

ScoreForm v0.9.1 is a pre-1.0, local-first classroom OMR tool.

It is intended to run on a teacher's local machine and is not currently designed as a hosted service.

## Student Data and Privacy

Do not commit real student data to this repository.

Do not commit:

- real student names
- real student IDs
- real rosters
- scanned student work
- graded answer sheets
- production result CSV files
- private school or district documents

All example files in this repository should use synthetic data only.

Teachers and users are responsible for following their school, district, state, and federal student-data privacy requirements.

## Reporting Security or Privacy Concerns

If you find a security, privacy, or student-data safety concern, please open a GitHub Issue with a clear description.

Do not include private student data, scanned student work, or sensitive school information in the issue.

If the concern involves sensitive details, describe the issue generally and request a private follow-up channel.

## Supported Versions

ScoreForm remains pre-1.0. Supported package releases require Python 3.11 or
newer and a compatible `pds-core>=0.5,<0.6` installation.

## Current Limitations

ScoreForm is not yet recommended for high-stakes grading without manual verification.

Implemented areas that still require manual verification include:

- PDS2 QR detection and physical scan reliability
- routed schema-v2 result workflows
- duplicate, repeated-attempt, and scan-review decisions

ScoreForm does not select an official attempt or grade and does not provide a
gradebook or LMS export. Generated sheets, packets, retained scans, filed scan
copies, results, review records, evidence, and diagnostics may all contain
sensitive student data and must be protected accordingly.

Known areas outside the v0.9.1 release include:

- gradebook export attempt-selection rules
- long-term scan archival and data-lifecycle management beyond current scan filing
- broader test coverage
- classroom-ready nontechnical user interface
