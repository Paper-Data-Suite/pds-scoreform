# ScoreForm v0.11.0 release checklist

Issue #196 owns the final v0.11.0 release boundary.

## 1. Reconcile and validate the release-preparation branch

- [ ] Working tree contains only intended #196 changes.
- [ ] `pyproject.toml` reports exactly `0.11.0`.
- [ ] `pds-core>=0.6.2,<0.7` remains exact.
- [ ] Historical v0.10.0 release evidence remains truthful.
- [ ] `RELEASE_NOTES_v0.11.0.md` and `docs/v0.11.0_release_audit.md` are current.
- [ ] No production `scoreform/` runtime file changed from the #195 qualified baseline unless a deliberate defect correction requires physical retesting.
- [ ] `python scripts/verify_release_compatibility.py` passes.
- [ ] `python -m pytest` passes.
- [ ] `python -m ruff check .` passes.
- [ ] `python -m mypy scoreform` passes.
- [ ] `git diff --check` passes.

## 2. Run the authoritative release gate

Use the exact authenticated Core artifacts expected by `run_tests.ps1`.

```powershell
powershell -ExecutionPolicy Bypass -File .\run_tests.ps1
```

Require:

- [ ] Core 0.6.2 operations-floor qualification PASS.
- [ ] exact Core 0.6.3 full qualification PASS.
- [ ] clean wheel/sdist install validation PASS.
- [ ] installed producer lifecycle PASS.
- [ ] installed module-operations PASS.
- [ ] combined v0.11 installed acceptance PASS.
- [ ] automation continues to report physical acceptance as `not_claimed`.

## 3. Merge and freeze the final candidate

After PR review/CI:

- [ ] Squash-merge #196.
- [ ] Return to `main`.
- [ ] `git pull --ff-only`.
- [ ] Require clean `main == origin/main`.
- [ ] Record final release commit and tree.
- [ ] Rerun `run_tests.ps1` on that exact merged commit.
- [ ] Rebuild exactly one `scoreform-0.11.0` wheel and one sdist.
- [ ] Run `twine check`.
- [ ] Record SHA-256 for both final artifacts.

Branch artifacts are not final release artifacts.

## 4. Bridge or repeat physical acceptance

Baseline #195 wheel SHA-256:

```text
13780dfff55428394baaab5deab76e340ae969fe7f96cb461ccc092df7e5679b
```

Run:

```powershell
python scripts/verify_v011_physical_equivalence.py `
  --baseline-wheel <exact-#195-wheel> `
  --release-wheel .\dist\scoreform-0.11.0-py3-none-any.whl
```

- [ ] Runtime payload equivalence PASS.
- [ ] Entry points PASS.
- [ ] Requires-Python PASS.
- [ ] Requires-Dist PASS.
- [ ] Output says `physical_acceptance: not_claimed`.
- [ ] Project owner explicitly approves carrying #195 physical evidence forward.

If any runtime/dependency/entry-point/physical-workflow behavior changed, stop and
repeat the physical procedure instead.

## 5. Owner authorization

Before tagging:

- [ ] Release audit has no unresolved release blocker.
- [ ] Final wheel/sdist hashes are recorded.
- [ ] Physical evidence is validly carried forward or retested.
- [ ] Project owner explicitly authorizes v0.11.0 publication.

## 6. Tag and GitHub Release

```text
tag: v0.11.0
release name: ScoreForm v0.11.0
```

- [ ] Tag points to the exact qualified merged commit.
- [ ] Tag is pushed normally and never rewritten.
- [ ] GitHub Release body is based on `RELEASE_NOTES_v0.11.0.md`.
- [ ] Exact qualified wheel attached.
- [ ] Exact qualified sdist attached.
- [ ] Uploaded asset hashes match the recorded hashes.
- [ ] No PyPI/package-index publication occurs unless separately approved.

## 7. Post-release fresh-download verification

Download the actual GitHub Release assets into a fresh directory/venv.

Verify:

- [ ] tag resolves to expected commit;
- [ ] asset filenames exact;
- [ ] asset hashes exact;
- [ ] exact Core 0.6.3 installs;
- [ ] ScoreForm installs noneditably;
- [ ] `pip check` passes;
- [ ] `importlib.metadata.version("scoreform") == "0.11.0"`;
- [ ] `scoreform --version` reports `ScoreForm 0.11.0`;
- [ ] `scoreform version` reports `ScoreForm 0.11.0`;
- [ ] module, producer, and module-operations entry points resolve exactly;
- [ ] `scoreform.academic_result_reader` imports from site-packages;
- [ ] bounded installed acceptance passes.

Record the post-release result and final hashes in
`docs/v0.11.0_release_audit.md` / #196 before closing the issue.

## Downstream note

ScoreForm v0.11.0 preserves the existing producer/reader contract, but Meridian
currently exact-qualifies reader distribution version 0.10.0. Meridian must add
0.11.0 support in a Meridian-owned change after this final wheel identity is
available. Paper Data Suite v0.1.0 likewise remains an immutable exact
composition containing ScoreForm 0.10.0.
