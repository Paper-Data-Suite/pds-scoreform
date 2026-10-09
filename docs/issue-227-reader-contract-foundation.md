# Issue #227 — ScoreForm reader-contract baseline

This document freezes the *producer-owned* reader contract prior to changing
ScoreForm's Core minimum, publication profile, or installed qualification. It
is a development contract and does not claim a new ScoreForm release.

## Separate identities

| Identity | Current value | Purpose |
| --- | --- | --- |
| Distribution | `scoreform` | Exact installed implementation; consumers retain its version for provenance and cache identity |
| Academic Work | `scoreform_academic_work_v1` | Core Academic Work registration |
| Manifest | `scoreform_academic_result_manifest_v1` | Durable canonical bytes, schema, and meaning |
| Reader | `scoreform_academic_result_reader_v1` | Stable public API and interpretation across compatible ScoreForm versions |

The reader name is declared as
`SCOREFORM_ACADEMIC_RESULT_READER_CONTRACT_VERSION` in
`scoreform.pds_contract`. This *does not* yet advertise that name through
Core's installed producer metadata. That integration follows the coordinated
Core 0.6.5 dependency migration.

## Public behavior and ownership

The stable import is `scoreform.academic_result_reader`; the primary call is
`read_academic_result_manifest(value: bytes) -> AcademicResultManifest`.
The module's existing `__all__` is the public import/call surface; see
[`academic_result_reader.md`](academic_result_reader.md) and
`tests/test_academic_result_reader.py` for the full baseline.

Reader v1 guarantees:

- Immutable byte input, exact canonical manifest decoding and validation;
  noncanonical and malformed values fail closed.
- Existing frozen public models, validated source/student/attempt/question/
  response lookups, and documented exception hierarchy.
- Exact Standards Profile and Standards IDs, including permitted punctuation;
  independent attempts and selected/blank/ambiguous answer distinctions.
- Native source snapshots and manual/PDS2/review provenance without source-file
  access, current-publication selection, hidden grading, or consumer policy.
- No workspace I/O, publisher mutations, logging of private source content,
  or dependencies on Meridian/Vitrine and other consumers.

An incompatible API, model, validation, or interpretation change requires a
new reader-contract version even when the manifest contract remains v1.
Each ScoreForm release must independently prove conformance. Mere metadata
presence is not verification or authorization.

## Core 0.6.5 dependency migration inventory

Core v0.6.5 publishes metadata-only `PublicationReaderSupport` and
`lookup_publication_reader_support` in
`pds_core.publication_compatibility`. The exact release wheel is
`pds_core-0.6.5-py3-none-any.whl`, SHA-256
`9ace75f17b23b7f0ed6a709d531af5120db43d0325b4148d26f2d6ba1d4b3c18`.

**Next migration is atomic:** update the active package minimum to
`pds-core>=0.6.5,<0.7` *together with* release/installed verifiers, local
`run_tests.ps1`, `check_dependencies.ps1`, CI and release-readiness wheel
sources and authenticated hashes, and active dependency tests. Existing CI
currently bootstraps 0.6.4, so changing `pyproject.toml` alone would be unsafe.

The historical 0.6.4-focused tests and issue-specific wheel harnesses must be
reconciled as *current gates versus historical release evidence*; do not simply
silence old tests or rewrite release audit records. In particular audit:

- `tests/test_core064_migration_issue219.py`
- `tests/test_v012_release_preparation_issue219.py`
- `tests/test_cross_platform_ci_issue202.py`
- `tests/test_release_artifacts.py`
- `tests/test_pds_contract.py` and `tests/test_pds_operations_issue193.py`
- `scripts/verify_core_wheel.py` and current installed-wheel harnesses
- `.github/workflows/ci.yml` and `.github/workflows/release-readiness.yml`
- `README.md` and `docs/continuous_integration.md`

Preserve the actual v0.12.0/v0.12.1 audits and their prior 0.6.4 artifact
identity. No version bump or release is authorized by Slice 1.

## Subsequent gates

1. Reconcile Core dependency and active qualification infrastructure as one
   testable migration, retaining historical evidence.
2. Add exact manifest-bound `PublicationReaderSupport` to the producer profile;
   ensure discovery never imports the reader.
3. Qualify actual public reader v1 behavior, including exact Standards identity.
4. Prove Core profile lookup and installed-wheel contract behavior against
   the authenticated released 0.6.5 wheel.
5. Complete CI, release artifact inspection, and consumer handoff. Meridian
   #111 alone owns removal of exact-version runtime gating.
