# Issue #216 — Installed and physical qualification

Issue #216 changes the auxiliary scoring-diagnostic boundary. It does not define
a new assignment, result, issuance, route, retained-source, scan-review,
Academic Work, manifest, publication, or reader schema.

## Existing classroom workspace compatibility

The implementation is forward-compatible with the current ScoreForm 0.11.0
workspace data surface.

Issue #216 does not migrate or rewrite existing:

- managed assignment JSON;
- class rosters;
- answer-sheet issuance records;
- answer-sheet page records;
- Core route registrations;
- retained scans;
- schema-v2 results history;
- existing scan-review records or resolutions;
- Academic Work Registration;
- Academic Result manifests;
- publication records.

Existing identity-heavy diagnostic PNGs are not renamed, deleted, or replaced.
New diagnostic writes use bounded opaque names.

The clean-wheel acceptance places a pre-existing legacy diagnostic sentinel in
the managed debug directory and snapshots the assignment, issued issuance,
page, and route-registration bytes before scoring. It requires all of those
pre-existing records to remain byte-for-byte unchanged after successful
fail-soft scoring, idempotent replay, and a substantive registration failure.

New state created by the test is limited to normal state owned by the operation:
retained-source evidence, one result attempt, one substantive review occurrence
for the deliberately invalid page, and privacy-bounded diagnostic events.

## Automated clean-wheel acceptance

Run the exact candidate ScoreForm wheel against the authenticated PDS Core
0.6.3 wheel:

```powershell
python scripts/run_issue216_wheel_acceptance.py `
  --repository . `
  --work "$env:TEMP\pds-scoreform-issue216" `
  --core-wheel "$env:TEMP\pds_core-0.6.3-py3-none-any.whl" `
  --expected-core-version 0.6.3
```

The work directory must be absent or empty.

The harness:

1. copies the source tree without build/VCS residue;
2. builds the exact wheel and sdist;
3. validates release artifacts;
4. creates a clean virtual environment;
5. installs authenticated Core 0.6.3 and the exact candidate ScoreForm wheel;
6. runs acceptance from outside the source checkout;
7. proves imports originate in isolated `site-packages`;
8. constructs canonical ScoreForm assignment, issuance, page, and Core route
   state;
9. demonstrates a representative legacy identity-heavy diagnostic path exceeds
   260 characters while the new opaque diagnostic name remains bounded;
10. verifies a real bounded diagnostic artifact can be created without changing
    Windows registry policy;
11. forces the diagnostic writer to fail deterministically while a valid blank
    page still scores, assembles, exports, and remains out of Scan Review;
12. verifies a privacy-minimal `diagnostic_artifact_write_failed` event and
    aggregate guided warning;
13. replays identical source bytes and verifies result idempotency;
14. combines missing registration marks with forced diagnostic failure and
    verifies the persisted review category remains
    `registration_marks_missing`;
15. verifies pre-existing authoritative workspace records and legacy diagnostic
    evidence remain unchanged.

The automated test must not read or modify
`HKLM\...\LongPathsEnabled`. **Do not change LongPathsEnabled as part of this
qualification.** Correctness must not depend on machine-wide policy.

Automation does not claim physical acceptance.

## Project-owner physical regression

Physical acceptance is an explicit project-owner observation. Run it against
the exact candidate wheel hash emitted by the clean-wheel harness.

Use a **throwaway workspace**, not the existing classroom workspace, for the
physical qualification. This prevents release testing from mixing synthetic
qualification state into live class data.

Minimum successful-paper path:

1. activate the isolated candidate environment;
2. point `PDS_WORKSPACE_ROOT` at a disposable workspace;
3. create a synthetic class and one-question ScoreForm assignment through the
   normal teacher workflow;
4. generate and print a registered sheet at Actual Size / 100%;
5. mark one response;
6. scan the complete page to PDF;
7. process it through the normal retained PDS2 workflow;
8. confirm the automatic response and score are correct;
9. confirm the result is available in Review Results;
10. confirm no Scan Review item exists solely for diagnostic persistence.

Long-path regression:

1. use a realistically deep disposable workspace path;
2. do not shorten the generated source filename merely to help diagnostics;
3. do not change `LongPathsEnabled`;
4. process the physical page normally;
5. inspect the assignment debug directory;
6. confirm new diagnostic files, when present, use bounded names beginning with
   `sfdiag_`;
7. confirm diagnostic persistence failure, if deliberately simulated in a
   developer-only run, does not invalidate the score.

Record:

- exact ScoreForm commit;
- exact candidate wheel SHA-256;
- exact Core wheel/version;
- host OS;
- Python version;
- printer/scanner path used;
- successful-paper result;
- deep-workspace result;
- whether diagnostic artifacts were present;
- physical acceptance decision by the project owner.

## Release sequencing

Completing #216 does not require publishing a standalone ScoreForm release.

The intended sequence is:

1. qualify and merge #216;
2. implement #217 from reconciled post-#216 `main`;
3. keep the #216 installed-wheel CI gate green during #217;
4. perform combined release qualification;
5. publish one ScoreForm **0.12.0** release containing both #216 and #217.

If #217 remains downstream read-only analysis/reporting and does not modify the
physical scoring/generation/runtime path, the project owner may decide whether
the exact #216 physical observation can be carried forward after mechanically
confirming that relevant runtime code is unchanged. Any later change to the
physical scoring path requires repeating the physical regression.

## Recorded owner-operated physical acceptance — 2026-09-29

The project owner completed the bounded physical regression against the exact
committed #216 candidate.

Qualification identity:

```text
ScoreForm commit:
bf8fa73b20bf5595247aa594c8a7d27aa25b3211

Candidate wheel:
scoreform-0.11.0-py3-none-any.whl

Candidate wheel SHA-256:
b45d9e8630ae96f71abc3e1d427b2d343ae293300b680839dd6d691d89ac8dbc

ScoreForm: 0.11.0
PDS Core: 0.6.3
Python: 3.14.1 64-bit AMD64
Host: Windows 11 10.0.26200
LongPathsEnabled: 1
Registry mutation during qualification: none
```

The physical test used a disposable deep workspace. Representative path
measurements before scoring were:

```text
workspace root: 119 characters
assignment debug directory: 203 characters
generated class packet: 224 characters
```

A real generated class-packet page was printed at Actual Size / 100%, Question
1 choice `A` was marked, and the complete page was scanned to PDF.

### Separate pre-dispatch long retained-source observation

The first intake deliberately used a very long source filename. Its original
scan path was 231 characters. Core retention expanded that to a 281-character
retained PDF path:

```text
scans/source/2026-09-30/
20260930T031838064717Z__issue216_physical_regression_scan_with_deliberately_long_source_filename_for_diagnostic_testing__63e3b37316eb.pdf
```

PDF page enumeration then failed before QR detection, routing, OMR, or
ScoreForm diagnostic-artifact persistence. One ordinary unresolved Scan Review
record was created for that pre-dispatch retained-page failure.

This is **not** a #216 diagnostic-persistence failure. It demonstrates a
separate retained-source / third-party PDF path-budget condition: Windows host
policy was enabled, yet the PDF toolchain still could not enumerate the
281-character retained path. Preserve this observation for separate Core/suite
path-readiness follow-up. It does not change the #216 acceptance result.

### Successful physical scoring path

The exact same physical scan bytes were copied to the shorter intake filename:

```text
issue216_physical_scan.pdf
```

The committed candidate then completed the real retained PDS2 workflow:

```text
Batch status: complete_success
Source pages discovered: 1
Pages with decoded QR text: 1
Valid PDS2 locators: 1
Dispatch successes: 1
Dispatch failures: 0
Pre-dispatch failures: 0
Application integration failures: 0
ScoreForm pages scored: 1
Completed attempts: 1
Attempts appended: 1
Export failures: 0
```

Physical OMR result:

```text
Page 1 Final Score: 1/1
Q1: A (Correct)
```

The persisted schema-v2 result recorded:

```text
class_id: issue216_physical_class
assignment_id: issue216_physical_quiz
student_id: issue216_physical_student
Score: 1
Total: 1
Q1: A
Q1_Correct: True
result_origin: pds2_scan
```

### Physical diagnostic-artifact result

The real scoring run persisted only bounded opaque diagnostic names:

```text
sfdiag_corners_ac512b96e65b802d991d.png
full path length: 243

sfdiag_warped_d5cc4b18967b73d18608.png
full path length: 242
```

The fresh workspace contained no diagnostic file whose name failed the
`sfdiag_*` bounded-name contract.

The successful retry created no additional Scan Review item. The only review
item present afterward was the earlier pre-dispatch retained-PDF page-count
failure from the 281-character retained source. No review item was created
solely because of ScoreForm diagnostic persistence.

### Owner acceptance decision

**PASS — Issue #216 physical acceptance satisfied.**

The owner-operated observation confirms that the committed candidate:

- physically prints, scans, routes, and scores a real generated ScoreForm page;
- produces the expected automatic answer and score;
- exports the result through the normal schema-v2 routed-result path;
- uses bounded opaque diagnostic filenames in a deep workspace;
- does not create Scan Review work for successful diagnostic persistence;
- remains consistent with the installed fail-soft diagnostic acceptance already
  exercised outside the source checkout.

The automated harness continues to report `physical_acceptance: not_claimed`
by design. This section records the separate human-operated physical
observation.
