# ScoreForm Roadmap

## Project status

ScoreForm 0.10.0 is the current pre-1.0 release candidate. It generates
registered answer sheets, scores retained scans through PDS Core 0.6, and
publishes immutable academic-result evidence through Core-owned publication
contracts. Scan quality affects reliability, and teachers must manually verify
every result before recording a grade.

Future planning is tracked in GitHub issues. This document does not promise a
next version or milestone.

## v0.10.0 — Core 0.6 academic publication integration

The v0.10.0 milestone keeps the v0.9.1 PDS2 routing/scoring foundation and adds:

- released `pds-core>=0.6,<0.7` integration;
- explicit ScoreForm Academic Work Registration;
- immutable `scoreform_academic_result_manifest_v1` generation;
- the installed ScoreForm publication producer profile;
- Core-owned publication, supersession, withdrawal, and catalog workflows;
- the consumer-neutral `scoreform.academic_result_reader`;
- clean-wheel end-to-end producer acceptance preserving multiple attempts;
- a unique `scoreform 0.10.0` reader distribution identity for downstream
  consumers without adding Meridian or Vitrine runtime dependencies.

ScoreForm does not select an official attempt, infer proficiency/mastery,
calculate a course Grade, or decide portfolio candidacy/selection.

## v0.9.1 — Core 0.5 and PDS2 migration

The v0.9.1 release established the routing and storage foundation:

- ScoreForm work is stored below
  `classes/<class_id>/modules/scoreform/work/<assignment_id>/`.
- Every generated routable page has immutable issuance and page records plus a
  unique Core route registration before its PDS2 locator is rendered.
- The installed `paper_data_suite.modules` entry point supplies ScoreForm's
  side-effect-free module profile and defensive one-page route handler.
- Core retains source bytes before decoding and dispatches pages through its
  installed module registry.
- ScoreForm assembles complete standard or compact multi-page attempts by
  issuance identity and writes routed-results schema version 2.
- Scan failures and append-only resolutions use Core metadata schema version 2.
- Copy, move, and off scan-filing modes preserve Core's retained source.
- Manual answer-key scoring and plain-paper entry remain separate from routed
  PDS2 scoring.

PDS1 and OMR1 sheets are unsupported. Historical schema-v1 routed results are
not migrated, old unqualified assignment workspaces are not discovered, and
previously printed legacy sheets cannot be assigned fabricated routes.

## Historical milestones

Milestones v0.1.0 through v0.8.1 introduced the initial scoring, auditability,
terminal menu, installable command, roster and assignment management, flexible
forms, robustness work, and workflow polish. Those releases predate and are
superseded by the v0.9.1 routing and storage contracts where their behavior
conflicts with the current architecture.

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
