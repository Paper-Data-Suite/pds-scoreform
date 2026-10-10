# Issue #227 — Slice 8 candidate final-acceptance record

## Scope and release boundary

This record qualifies **producer-side** ScoreForm compatibility with Core
v0.6.5 and the public reader contract
`scoreform_academic_result_reader_v1` for
`scoreform_academic_result_manifest_v1`. This is an **unreleased source
candidate**, not a restatement or replacement of the published ScoreForm
v0.12.1 release. Package version remains `0.12.1` during Issue #227
implementation. The release version, final wheel/sdist, tag, and authorization
are separate release decisions.

Historical `docs/release_checklist.md`, `RELEASE_NOTES_v0.12.1.md`, and
`docs/v0.12.1_release_audit.md` describe an **actual completed 0.12.1
release**, including Core 0.6.4. They must not be overwritten or silently
reinterpreted as this candidate's qualification. Use this document for
Issue #227 candidate acceptance instead.

## Completed local evidence (as reported by project owner)

- Baseline candidate source at installed Slice 6 qualification: `e83c550`
  (October 10, 2026). Exact installed candidate wheel version: `0.12.1`.
- Slice 6 clean noneditable wheel acceptance **passed** on Windows with Core
  `0.6.5`; the runner reported:
  - ScoreForm candidate wheel SHA-256:
    `9fa5d910f574dd29f024c6d5f08bbaa774078d0cbf4e9503a9c8d9cd27252624`
  - Core release wheel SHA-256:
    `9ace75f17b23b7f0ed6a709d531af5120db43d0325b4148d26f2d6ba1d4b3c18`
  - Installed isolation: `noneditable-wheel-outside-source`.
  - Workspace sentinel: `not_created`.
- Slice 7 and Core 0.6.5 gate reconciliation committed and pushed at `82824a0`.
- Full local suite on Windows at `82824a0` (before Slice 8 changes):
  **2,451 passed, 16 skipped**; Ruff passed; mypy passed for 125 source
  files; `scripts/verify_release_compatibility.py` passed; `pip check`
  reported no broken requirements; `git diff --check` passed.
- Earlier Slice 6 candidate wheel hash is **not** evidence for the later
  `82824a0` commit or any Slice 8/final merge commit. Repeat build and
  installed qualification for the final accepted source.

## Slice 8 gates to complete before issue acceptance

- [ ] Slice 8 source changes: fresh complete pytest, Ruff, mypy, dependency,
      compatibility, and diff checks; record test skip reasons if material.
- [ ] Candidate wheel/sdist build and artifact inspection from a clean tree,
      including `python -m twine check`, and exact hashes for both artifacts.
- [ ] Rerun the clean-wheel Issue #227 reader acceptance from the current
      source commit using the authenticated Core 0.6.5 release wheel.
- [ ] Pull request CI green: routine Windows/Ubuntu Python 3.11–3.14
      matrix, combined v0.12, operations, Issue 216, Results Analysis,
      installed reader-wheel matrix, and release-readiness.
- [ ] Review PR diff and history for accidental rewriting of historical
      0.12.1 release evidence, Core compatibility weakening, or unauthorized
      consumer policy changes.
- [ ] Record final merged issue commit, candidate wheel/sdist hashes, runner
      environment and CI URLs/results. A branch wheel hash is not the final
      release artifact hash.
- [ ] Handoff producer contract identity, exact qualified candidate and
      artifact evidence to Meridian #111 and Vitrine #103. Their consumer
      compatibility is **not** established by this producer qualification.

## Local final-candidate check

Use a dedicated disposable directory outside this repository and outside the
live OneDrive classroom workspace. The installed reader harness requires an
**absent or empty** `--work`; it builds the candidate itself and records a
new candidate wheel hash. The commands below do not publish a release.

```powershell
python -m pytest tests -q
python -m ruff check .
python -m mypy scoreform
python scripts/verify_release_compatibility.py
python -m pip check
python -m build --wheel --sdist --outdir "$env:TEMP\scoreform-issue227-final-artifacts"
python -m twine check "$env:TEMP\scoreform-issue227-final-artifacts\*"
python scripts/verify_release_artifacts.py `
  --version 0.12.1 `
  --dist "$env:TEMP\scoreform-issue227-final-artifacts"

$coreWheel = Join-Path $HOME "Downloads\pds_core-0.6.5-py3-none-any.whl"
python scripts/verify_core_wheel.py $coreWheel
python scripts/run_issue227_reader_contract_wheel_acceptance.py `
  --repository . `
  --work (Join-Path $env:TEMP "scoreform-issue227-reader-final-unique") `
  --core-wheel $coreWheel
```

Choose **fresh empty** directories or cleanly selected unique names; artifact
inspection requires exactly one wheel and one sdist. Also record:
`git rev-parse HEAD`, `git status --short`,
`Get-FileHash -Algorithm SHA256` for both artifacts, and the PR check summary.
**Avoid** running installed qualification against the live OneDrive workspace.

## Non-goals and physical qualification

No Meridian/Vitrine grade or portfolio policy, no Core API modification,
no new manifest contract, and no live workspace migration. QR software
regressions remain within the synthetic suites. Actual physical
printing/scanning is **not claimed** (`physical_acceptance: not_claimed`)
unless the owner separately performs and records it. The Issue #227 release
boundary remains an explicit, separate approval after implementation and CI.

## Slice 8 CI correction: active combined v0.12 wheel gate

The first Issue #227 PR #228 CI attempt at `871f166` qualified the new
reader-contract wheel on both Windows and Ubuntu, but the active combined
v0.12 wheel test failed on both platforms. The verifier
`scripts/verify_installed_v012_combined_acceptance.py` still asserted
Core `0.6.4` and `pds-core>=0.6.4,<0.7`, while its CI/runner now correctly
installs the authenticated Core `0.6.5` wheel and candidate ScoreForm metadata
requires `pds-core>=0.6.5,<0.7`. Fix 1 reconciles **only that active
v0.12 combined verifier**, with a regression guard. It does not alter
`verify_installed_v011_combined_acceptance.py` or any historical release
audit; passing local tests alone does not clear the CI gate.
