# ScoreForm v0.12.0 release checklist

Issue #219 owns the v0.12.0 release boundary.

## 1. Release-preparation branch

- [ ] Working tree contains only intended #219 changes.
- [ ] `pyproject.toml` reports exactly `0.12.0`.
- [ ] `pds-core>=0.6.4,<0.7` remains exact.
- [ ] Historical v0.10.0/v0.11.0 release evidence remains truthful.
- [ ] `RELEASE_NOTES_v0.12.0.md` and `docs/v0.12.0_release_audit.md` are current.
- [ ] release compatibility, focused tests, complete pytest/Ruff/mypy, and
  `git diff --check` pass.

## 2. Installed release gates

- [ ] v0.12 combined clean-wheel installed workflow passes.
- [ ] Results Analysis clean-wheel installed acceptance passes.
- [ ] clean wheel/sdist install validation passes.
- [ ] producer/reader/module-operations gates pass.
- [ ] automation reports `physical_acceptance: not_claimed`.

## 3. Authoritative local gate

```powershell
powershell -ExecutionPolicy Bypass -File .\run_tests.ps1
```

Require a complete pass before merge.

## 4. Merge and freeze

- [ ] squash-merge the #219 release-preparation PR;
- [ ] return to `main` and `git pull --ff-only`;
- [ ] require clean `main == origin/main`;
- [ ] record final release commit/tree;
- [ ] rerun `run_tests.ps1` on that exact merged commit;
- [ ] rebuild exactly one `scoreform-0.12.0` wheel and one sdist;
- [ ] run `twine check`;
- [ ] record SHA-256 for both artifacts.

Branch artifacts are not final release artifacts.

## 5. Physical printer/scanner gate

The v0.11 physical-equivalence bridge must **not** be used: v0.12 changes
shipped runtime code and the Core dependency floor.

- [ ] project owner determines the required v0.12 physical procedure;
- [ ] required physical acceptance is completed and recorded;
- [ ] owner approves the physical evidence for the exact release candidate.

Automation may report only `physical_acceptance: not_claimed`.

## 6. Owner authorization

- [ ] release audit has no unresolved blocker;
- [ ] final wheel/sdist hashes are recorded;
- [ ] physical gate is resolved;
- [ ] project owner explicitly authorizes v0.12.0 publication.

## 7. Tag and GitHub Release

```text
tag: v0.12.0
release name: ScoreForm v0.12.0
```

- [ ] tag points to the exact qualified merged commit;
- [ ] tag is pushed normally and never rewritten;
- [ ] release body is based on `RELEASE_NOTES_v0.12.0.md`;
- [ ] exact wheel and sdist are attached;
- [ ] uploaded hashes match the audit;
- [ ] no package-index publication occurs unless separately approved.

## 8. Fresh-download verification

- [ ] filenames and hashes exact;
- [ ] exact Core v0.6.4 installs;
- [ ] ScoreForm installs noneditably and `pip check` passes;
- [ ] installed ScoreForm metadata/version commands report 0.12.0;
- [ ] entry points resolve;
- [ ] combined v0.12 installed acceptance passes;
- [ ] Results Analysis installed acceptance passes;
- [ ] audit records final commit/tree/hashes and verification outcome.
