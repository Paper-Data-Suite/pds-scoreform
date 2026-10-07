# ScoreForm v0.12.1 release checklist

Issue #222 owns the v0.12.1 compatibility-repair release boundary.

## 1. Release-preparation branch

- [ ] Working tree contains only intended #222 changes.
- [ ] `pyproject.toml` reports exactly `0.12.1`.
- [ ] `pds-core>=0.6.4,<0.7` remains exact.
- [ ] `scoreform_academic_result_manifest_v1` remains the producer contract.
- [ ] Historical v0.10.0/v0.11.0/v0.12.0 release evidence remains truthful.
- [ ] `RELEASE_NOTES_v0.12.1.md` and `docs/v0.12.1_release_audit.md` are current.
- [ ] focused #222 regressions, release compatibility, pytest/Ruff/mypy, and
  `git diff --check` pass.

## 2. Installed release gates

- [ ] installed producer acceptance covers punctuation-bearing Standards identity.
- [ ] installed Share Results acceptance reaches first publication with the same identity.
- [ ] combined v0.12 clean-wheel installed workflow passes as ScoreForm 0.12.1.
- [ ] Results Analysis clean-wheel installed acceptance still passes.
- [ ] clean wheel/sdist install validation passes.
- [ ] producer/reader/module-operations gates pass.
- [ ] exact released Core v0.6.4 is used, with wheel SHA-256
  `48cea9317f2967bdc0f2d4c14349a56677c7c3f8211f0f33978ccb1a1c75859b`.

## 3. Authoritative local gate

```powershell
powershell -ExecutionPolicy Bypass -File .\run_tests.ps1
```

Require a complete pass before merge.

## 4. Merge and freeze

- [ ] squash-merge the #222 release-preparation PR;
- [ ] return to `main` and `git pull --ff-only`;
- [ ] require clean `main == origin/main`;
- [ ] record final release commit/tree;
- [ ] rerun `run_tests.ps1` on that exact merged commit;
- [ ] build exactly one `scoreform-0.12.1` wheel and one sdist;
- [ ] run `twine check`;
- [ ] record SHA-256 for both artifacts;
- [ ] do not rebuild different artifacts after qualification.

Branch artifacts are not final release artifacts.

## 5. Physical printer/scanner boundary

Issue #222 changes manifest Standards-identity validation and release metadata; it
does not change answer-sheet generation, QR layout, printing, scan ingestion,
registration marks, OMR image processing, answer detection, or manual scan
review. A new physical rerun is therefore not required for this compatibility
repair.

Automation and the v0.12.1 release record must state:

```text
physical_acceptance: not_claimed
```

unless the project owner separately performs and records a new physical
qualification. Synthetic or installed-wheel acceptance must never be relabeled
as a physical pass.

## 6. Owner authorization

- [ ] release audit has no unresolved software blocker;
- [ ] final wheel/sdist hashes are recorded;
- [ ] physical boundary is recorded truthfully as `not_claimed` unless separately run;
- [ ] project owner explicitly authorizes v0.12.1 publication.

## 7. Tag and GitHub Release

```text
tag: v0.12.1
release name: ScoreForm v0.12.1
```

- [ ] tag points to the exact qualified merged commit;
- [ ] tag is pushed normally and never rewritten;
- [ ] release body is based on `RELEASE_NOTES_v0.12.1.md`;
- [ ] exact wheel and sdist are attached;
- [ ] uploaded hashes match the audit;
- [ ] no package-index publication occurs unless separately approved.

## 8. Fresh-download verification

- [ ] freshly download both GitHub Release assets;
- [ ] filenames and SHA-256 hashes match the qualified artifacts exactly;
- [ ] exact Core v0.6.4 installs;
- [ ] ScoreForm installs noneditably and `pip check` passes;
- [ ] installed ScoreForm metadata/version commands report 0.12.1;
- [ ] entry points resolve from the installed artifact;
- [ ] representative punctuation-bearing manifest generation/reader checks pass;
- [ ] installed producer acceptance passes;
- [ ] installed Share Results acceptance passes;
- [ ] combined v0.12 installed acceptance passes;
- [ ] Results Analysis installed acceptance passes;
- [ ] audit records final commit/tree/hashes and verification outcome.

## 9. Downstream Meridian handoff

- [ ] open a separate Meridian patch ticket after the authenticated ScoreForm
  v0.12.1 artifacts exist;
- [ ] require exact ScoreForm 0.12.1 reader-wheel qualification;
- [ ] include punctuation-bearing Standard-ID interoperability acceptance;
- [ ] do not silently broaden Meridian's exact-reader-version rule.
