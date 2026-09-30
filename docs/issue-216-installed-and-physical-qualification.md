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
