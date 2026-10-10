# Issue #227 — Slice 7: synthetic cross-version and operational regression qualification

## Scope

The newly added `tests/test_issue227_slice7_distribution_independence.py` validates Core v0.6.5 reader-support lookup against *hypothetical* ScoreForm distribution version labels. It does **not** modify installed distribution metadata, build a future ScoreForm release, or assert that any future distribution has been qualified. Every real release still requires its own wheel acceptance and exact artifact digest.

Tests distinguish independent distribution identity from stable reader-contract identity, changed contract identities, missing legacy metadata, exact manifest binding, and policy-neutral public reader behavior using only the committed synthetic manifest fixture.

## Operational coverage reused from the existing repository

The following suite exercises the existing operational implementation and the three pre-release hardening changes. It operates on pytest's synthetic temporary directories; do not point it at live OneDrive classroom data.

```powershell
python -m pytest -q `
  tests/test_issue227_slice7_distribution_independence.py `
  tests/test_issue227_publication_reader_metadata.py `
  tests/test_issue227_reader_v1_conformance.py `
  tests/test_issue225_qr_vector_rendering.py `
  tests/test_issue225_qr_zxing_recovery.py `
  tests/test_issue225_scan_recovery_dispatch.py `
  tests/test_guided_scan_release_integration_issue189.py `
  tests/test_manual_entry.py `
  tests/test_results_v2_strict.py `
  tests/test_assignment_standard_alignments.py `
  tests/test_academic_work_registration.py `
  tests/test_academic_result_manifest_generation.py `
  tests/test_academic_result_publication.py `
  tests/test_publication_revision_policy.py `
  tests/test_guided_share_results_supersession_issue191.py `
  tests/test_issue227_hardening_a2_recovery.py `
  tests/test_issue227_hardening_b_assignment_creation.py `
  tests/test_issue227_hardening_c_csv_safety.py
```

Also run:

```powershell
python -m ruff check .
python -m mypy scoreform
python scripts/verify_release_compatibility.py
git diff --check
git status --short
```

Record the exact Python/OS environment, result counts, and any skipped test reasons. The full pytest suite, cross-platform GitHub Actions, candidate release metadata and release-version transition remain Slice 8 and final release qualification responsibilities. Slice 6's successful installed wheel SHA is candidate evidence tied to the source commit and Python/platform, not a historical release digest.

## Core v0.6.5 installed-gate reconciliation

The integrated pytest run exposed historical acceptance tests expecting Core 0.6.4 despite the current Core 0.6.5 floor. Two active installed acceptance verifiers also enforced the old Core requirement: the module operations verifier and the Share Results verifier. Both active verifiers and the corresponding regression guards were reconciled to Core 0.6.5 without changing archived release documents or synthetic early-refusal fixtures. Re-run the full suite and installed-wheel qualifications before acceptance. This change alone does not claim an installed acceptance result.
