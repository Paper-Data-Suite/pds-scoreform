# ScoreForm v0.12.0

ScoreForm v0.12.0 is the descriptive Results Analysis and reporting release
built across Issues #216, #217, and #219. It adds richer teacher-facing review
and export surfaces without changing ScoreForm's evidence authority: ScoreForm
still preserves attempts and response evidence, but does not select an official
attempt, infer proficiency/mastery, or calculate a Grade.

## Highlights

- Expanded **Review Results** with Assignment Overview, exact Student Detail,
  Question Analysis, and Standards Analysis.
- Class views use the **most recent scored attempt per student for display**.
  This is a display basis only, not a best/highest/official/Grade-bearing
  attempt policy.
- Blank and ambiguous responses remain distinct and are visible after scoring.
- Question analysis includes correct/incorrect/blank/ambiguous totals and
  per-response distributions.
- Standards analysis remains descriptive, supports multi-Standard questions,
  keeps unaligned responses separate, and uses the assignment's current
  Standards alignment.
- Standards display uses Core teacher-readable labels, current profile order
  when available, inactive markers, and durable-ID fallback for stale/unknown
  aligned Standards.
- Results Analysis exports CSV, deterministic versioned JSON, and PDF.
- Report destinations are format-aware and create-only; same-second CSV/JSON/PDF
  exports no longer collide.
- Successful exports offer explicit local-open actions through the existing
  bounded Core local-open boundary. Open failures are fail-soft and never undo
  a successfully created report.
- Diagnostic persistence from Issue #216 remains non-authoritative and
  fail-soft.
- The active Core floor is now `pds-core>=0.6.4,<0.7`, qualifying against the
  exact released Core v0.6.4 wheel.

## Release contract

```text
distribution:          scoreform
version:               0.12.0
Python:                 >=3.11
Core dependency:       pds-core>=0.6.4,<0.7
full Core reference:   0.6.4
Core wheel SHA-256:     48cea9317f2967bdc0f2d4c14349a56677c7c3f8211f0f33978ccb1a1c75859b
module ID:              scoreform
Academic Work:         scoreform_academic_work_v1
publication kind:      academic_result_set
manifest contract:     scoreform_academic_result_manifest_v1
record set:            academic_results
results report schema: scoreform_results_analysis_v1
capabilities:          points, question_evidence, multiple_attempts
attempt policy:        preserve all; select none
```

The distribution-version change does not create a new Academic Result manifest,
reader, Academic Work, Publication Record, or module-operations contract.

## Results authority

Results Analysis is deliberately descriptive. ScoreForm does not select the
latest/highest/best/official/replacement/Grade-bearing attempt, infer
proficiency or mastery, calculate a course Grade, determine portfolio/Candidate
eligibility, or invoke Meridian as a runtime dependency.

The class display basis is one most-recent scored attempt per student. Every
preserved attempt remains independently addressable through Student Detail and
the existing consumer-neutral reader.

## Reporting and privacy

Class CSV and JSON reports include assignment-overview student identity and
attempt summary. They do not include full per-question student response rows by
default. Student Detail reports intentionally contain the selected student's
exact attempt evidence.

Generated report paths are assignment-local, format-aware, create-only, and do
not embed student identity.

## Installed qualification

The release candidate has dedicated clean-wheel qualification for the combined
installed ScoreForm workflow and for Results Analysis semantics, Standard
projection/profile ordering, frozen CSV/JSON/PDF rendering, format-aware output
custody, partial-output cleanup, and bounded local-open actions.

Automation reports physical printer/scanner acceptance as `not_claimed`.

## Physical qualification boundary

The v0.11.0 physical-equivalence bridge cannot be reused for v0.12.0 because
the shipped ScoreForm runtime changed in Issues #216/#217/#219 and the Core
dependency floor changed to 0.6.4.

Before publication, the project owner must separately resolve the physical
printer/scanner release gate. Automation must not reinterpret installed or
synthetic acceptance as a physical pass.

## Installation

```powershell
python -m pip install .\pds_core-0.6.4-py3-none-any.whl
python -m pip install .\scoreform-0.12.0-py3-none-any.whl
python -m pip check
scoreform --version
```

GitHub Release assets remain the release distribution mechanism. Do not infer
PyPI availability.

## Known limitations

ScoreForm remains pre-1.0. Scan quality, printing scale, registration-mark
visibility, lighting, focus, and imaging can affect OMR. Teachers must manually
verify scored results before recording grades. Exported reports and other
classroom artifacts may contain sensitive student information.
