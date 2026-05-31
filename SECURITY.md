# Security Policy

## Project Status

ScoreForm is an early-stage, local-first classroom OMR tool.

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

ScoreForm is currently in early prototype development. No stable production release is available yet.

## Current Limitations

ScoreForm is not yet recommended for high-stakes grading without manual verification.

Implemented areas that are still maturing include:

- QR-aware scoring and scan reliability
- routed result workflows
- duplicate and repeated-attempt handling policy

Known areas still planned or under development include:

- gradebook export attempt-selection rules
- scan archiving or moving workflow
- broader test coverage
- classroom-ready nontechnical user interface
