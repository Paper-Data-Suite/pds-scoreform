# Installed Producer Acceptance

Issue #169 adds the release-readiness proof that the built ScoreForm wheel and
released PDS Core 0.6 wheel can complete the academic-result producer lifecycle
together from an isolated, noneditable installation.

The authoritative harness is:

```text
scripts/verify_installed_producer_acceptance.py
```

It is invoked by `scripts/validate_release_install.ps1` only for the clean wheel
environment. The source-distribution environment keeps the existing install,
metadata, profile, import, and CLI smoke checks; the mutation-heavy producer
lifecycle is not duplicated.

## Isolation

The release harness creates a fresh virtual environment and installs:

```text
pds-core 0.6.0 wheel
ScoreForm 0.10.0 wheel
```

noneditably. The acceptance script runs from an outside working directory and
checks that ScoreForm/Core runtime modules resolve from the isolated environment's
`site-packages`, not from the repository checkout.

The existing side-effect-free installed metadata/profile/import verification runs
first against a workspace path that must remain absent. Producer acceptance then
uses a different fresh workspace where mutation is expected.

## Synthetic producer data

All producer data is deliberately synthetic:

```text
class: acceptance_class
assignment: acceptance_quiz
student: synthetic_student
```

The fixture uses a three-question unaligned assignment and route-free
`plain_paper_manual` results. This keeps academic-registry acceptance independent
of scanners, Poppler, QR decoding, retained scan evidence, and PDS2 routing while
still exercising ScoreForm's production schema-v2 result writer.

No real student or school data belongs in this harness.

## Lifecycle

The installed acceptance executes production services in this order:

1. verify installed package provenance and versions;
2. initialize canonical ScoreForm managed work;
3. write and re-read a valid native `assignment.json`;
4. append one schema-v2 manual attempt through the production result writer;
5. explicitly register the Academic Work and replay the exact registration;
6. generate immutable Academic Result Manifest revision 1;
7. read revision 1 through `scoreform.academic_result_reader`;
8. publish revision 1 through ScoreForm's publication workflow;
9. replay the exact publication and require the same Core Publication Record;
10. explicitly rebuild/query the Core academic catalog;
11. verify the Publication Record's manifest path and SHA-256 through Core;
12. pass the verified bytes through the public ScoreForm reader;
13. append a second native attempt without removing attempt 1;
14. generate immutable manifest revision 2;
15. supersede the exact Core revision-1 head;
16. rebuild/query the successor catalog state;
17. verify revision-2 bytes and resolve both attempts independently;
18. withdraw the exact revision-2 head;
19. rebuild/query the withdrawn-head state;
20. run Core's bounded academic-registry audit;
21. prove producer manifests and Core Publication Records remained immutable.

## Canonical and derived state

Canonical truth remains:

- ScoreForm native assignment/results;
- immutable ScoreForm manifest revisions;
- Core Academic Work Registration revisions;
- Core Publication Records;
- Core Publication Withdrawals.

`registry/catalog.sqlite` is derived state. The harness rebuilds and queries it
through Core APIs and never writes or inspects SQLite directly to establish
canonical truth.

The harness never writes Core registration/publication/withdrawal JSON directly.

## Reader boundary

Core first verifies the exact Publication Record path and bound SHA-256. The
verified manifest bytes are then read through:

```text
scoreform.academic_result_reader
```

The reader must preserve exact producer semantics, including separate attempts,
blank responses, ambiguous responses, points, correctness, and manual provenance.

The harness does not select a latest, highest, best, official, or Grade-bearing
attempt.

## Supersession and withdrawal

Revision 2 must supersede the exact publication ID recorded for revision 1.
Revision 1 remains historical and immutable.

After the revision-2 head is withdrawn:

- both Publication Records remain;
- both producer manifests remain;
- the withdrawal is a separate immutable Core record;
- the withdrawn head remains the series head;
- revision 1 does not become current again;
- the current-selectable catalog query returns no publication.

## Audit

The final Core registry audit covers:

```text
registrations
publications
manifests
contracts
catalog
locks
```

for the synthetic ScoreForm work and requires the installed producer profile and
catalog to be available. The completed acceptance requires no error findings.

## Privacy and output

The harness prints stage-level progress only. It does not print full manifest
JSON, response arrays, selected-answer collections, result-history contents, or
student evidence.

Failures identify the lifecycle stage and a bounded reason. Underlying exceptions
remain chained for debugging but are not rendered as tracebacks by the harness.

## Deliberate exclusions

This acceptance does not:

- exercise physical scanning or PDS2 intake;
- create Academic Period membership;
- calculate proficiency, mastery, or Grade;
- create Meridian evidence;
- create portfolio projections;
- change producer contracts;
- change package versions or dependency ranges;
- publish a release.

Final compatibility and release audit remain assigned to issue #170.
