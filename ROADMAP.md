# ScoreForm Roadmap

## Project status

ScoreForm 0.11.0 is the current v0.11 release candidate. It keeps the exact
PDS2 evidence and Core 0.6 publication contracts established in v0.10.0 while
reducing repetitive teacher work around assignment setup, multi-class
generation, retained scanning, recovery, result review, and publication.

ScoreForm remains pre-1.0. Scan quality affects reliability, and teachers must
manually verify every result before recording a grade. ScoreForm does not select
an official attempt, infer proficiency/mastery, calculate a course Grade, or
decide portfolio candidacy/selection.

Future planning is tracked in GitHub issues. This document does not promise a
next version or milestone.

## v0.11.0 — Teacher-local workflow usability and recovery

The v0.11.0 milestone adds:

- safe assignment copying without inherited evidence history;
- reusable non-student setup presets;
- previewed, atomic bulk answer-key and standards-alignment entry;
- semantic multi-class generation planning and execution;
- task-oriented Assignment Management;
- session-scoped active/recent assignment context;
- guided retained PDS2 scan-to-results review;
- teacher-facing scan-quality recovery and append-only resolution;
- one guided Share Results with Meridian path through Core-owned registration,
  producer manifests, publication, and supersession;
- privacy-conscious local diagnostics;
- separate readiness and attention providers through Core module operations;
- combined clean-wheel installed acceptance plus project-owner physical
  printer/scanner qualification.

The final v0.11.0 release retains `pds-core>=0.6.2,<0.7`, qualifies the bounded
operations floor at Core 0.6.2, and uses the exact released Core 0.6.3 wheel for
full release qualification.

The producer/reader contract is intentionally unchanged:
`scoreform_academic_work_v1`, `scoreform_academic_result_manifest_v1`,
`academic_result_set`, `academic_results`, `points`, `question_evidence`, and
`multiple_attempts`. Distribution version 0.11.0 does not create a v2 producer
schema.

## v0.10.0 — Core 0.6 academic publication integration

The historical v0.10.0 release established ScoreForm Academic Work
Registration, immutable academic-result manifests, Core-owned publication
lifecycle workflows, the installed publication-producer profile, and the
consumer-neutral `scoreform.academic_result_reader`.

Downstream modules bind to exact released reader versions they explicitly
qualify. ScoreForm does not import or depend on Meridian, Vitrine, Quillan,
Concord, Portia, or the Paper Data Suite shell.

## v0.9.1 — Core 0.5 and PDS2 migration

The v0.9.1 release established module-qualified ScoreForm work, immutable
issuance/page/route identity, retained-source Core dispatch, routed-results
schema v2, append-only scan-review resolution, and the registered standard and
compact layouts.

PDS1 and OMR1 sheets are unsupported. Historical schema-v1 routed results are
not migrated, old unqualified assignment workspaces are not discovered, and
previously printed legacy sheets cannot be assigned fabricated routes.

## Historical milestones

Milestones v0.1.0 through v0.8.1 introduced the initial scoring, auditability,
terminal menu, installable command, roster and assignment management, flexible
forms, robustness work, and workflow polish.

## Future planning principles

- Keep ScoreForm local-first and preserve synthetic public examples.
- Improve physical-scan reliability without weakening manual verification.
- Keep result history auditable; do not select an official attempt or grade.
- Keep sibling modules isolated behind PDS Core contracts.
- Treat gradebook, LMS export, reporting, and broader UI work as separately
  approved features.
- Keep release, privacy, schema, CLI, and physical-test documentation aligned
  with runtime behavior.

See the repository's open GitHub issues for approved future work.
