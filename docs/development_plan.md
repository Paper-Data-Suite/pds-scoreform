# ScoreForm development plan

## Current architecture (v0.9.1)

This document describes the current implementation boundary. Historical plans
from the PDS1 era have been removed because they no longer describe supported
behavior; public milestone history remains in `CHANGELOG.md` and `ROADMAP.md`.

ScoreForm is a local-first PDS module for printable multiple-choice answer
sheets. It supports Python 3.11 or newer and `pds-core>=0.5,<0.6`.

### Storage and identity

Managed work uses the canonical root:

```text
classes/<class_id>/modules/scoreform/work/<assignment_id>/
```

For ScoreForm, `module_id=scoreform` and `work_id=assignment_id`. Routable pages
are represented by immutable issuance and page records and unique Core route
registrations before PDF rendering. QR payloads contain only canonical PDS2
locator identity. Student, layout, logical-page, question-range, answer-key,
attempt, and result-destination semantics come from authoritative records.

### Installed module boundary

The distribution exposes exactly this entry point:

```text
paper_data_suite.modules
    scoreform = scoreform.pds_module:get_module_profile
```

The zero-argument provider declares Core routing contract `1`, QR schema PDS2,
route-registration schema `1`, and dispatchable status `active`. Discovery is
side-effect free. Runtime code imports no sibling module implementation.

### Generation and scoring

Standard and compact layouts are active. One-page and multi-page assignments
generate registered PDS2 sheets. Core retains the complete source before QR
parsing, resolves each page's registered route, and dispatches the retained
source page to ScoreForm. ScoreForm validates immutable records, scores the
page, and assembles only complete, unambiguous issuances.

Routed results use schema version 2 and `result_origin=pds2_scan`. Route, page,
logical-page, source-page, retained-path, source-scan, digest, and intake
provenance remain aligned. Duplicate, conflicting, missing, mixed-issuance, or
malformed observations do not produce an invalid attempt row.

Manual answer-key scoring remains route-free. Plain-paper entry uses
`result_origin=plain_paper_manual`; review-linked manual results use
`scan_review_manual`. ScoreForm does not select an official grade.

### Review, evidence, and filing

Routing failures and resolutions use Core schema version 2. Failure bytes are
immutable; decisions are append-only. Review actions include routing
correction, manual entry/marks, rescan-needed, cannot-route, mixed-assignment,
evidence-filed, dismissed-duplicate, other, and defer.

Core retained sources are immutable. Assignment-local filing supports `copy`,
`move`, and `off`; only eligible full-success single-target batches file
automatically. Move mode never removes the Core retained source.

### Unsupported history

PDS1 and OMR1 are rejected. Unqualified assignment work roots are not searched.
Schema-v1 routed-result histories and schema-v1 Core review metadata are not
migrated. There is no generic migration gate and no route reconstruction for
previously printed sheets. Generate new PDS2 sheets for current routed scoring.

## Release validation

The authoritative local release-readiness command is:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_tests.ps1
```

It covers dependency consistency, compilation, Ruff, mypy, pytest, focused
contracts, installed CLI/E2E smoke tests, artifact build and inspection,
noneditable clean installs, installed profile discovery, side-effect checks,
and Git diff hygiene. `run_fast_tests.ps1` is only a development precheck.

The nonpublishing GitHub Actions release-readiness workflow provides Linux
coverage. A successful real printed two-page assessment remains mandatory and
must use the reviewed wheel before the project owner may authorize publication.

## Development principles

- Do not redesign Core routing, PDS2 grammar, or established sheet geometry in
  release-closeout work.
- Preserve immutable evidence and append-only audit history.
- Keep manual and routed scoring boundaries explicit.
- Use synthetic data in tests and documentation.
- Never commit physical scans, filled sheets, classroom results, or private
  student data.
- Track future work in approved GitHub issues rather than inventing milestones
  in release documentation.
