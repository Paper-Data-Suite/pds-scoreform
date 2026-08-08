# ScoreForm v0.10.0 release checklist

Issue #170 is the release closeout for the Core 0.6 academic-publication
milestone. Publication remains blocked until the project owner completes the
required source-menu rehearsal and physical paper test, the release-preparation
PR is merged, the exact merged artifacts pass final verification, and the
project owner explicitly authorizes release.

Use synthetic identities only. Do not commit generated PDFs, filled sheets,
scans, classroom results, diagnostic images, or machine-specific paths.

## Integrated milestone baseline

- [x] #161 Academic Result Manifest v1 is merged
- [x] #162 publication revision/supersession policy is merged
- [x] #163 released Core 0.6 adoption is merged
- [x] #164 Academic Work Registration is merged
- [x] #165 immutable manifest generation is merged
- [x] #166 publication producer profile is merged
- [x] #167 publication/supersession/withdrawal workflows are merged
- [x] #168 consumer-neutral reader is merged
- [x] #169 clean-wheel installed producer acceptance is merged
- [ ] #170 compatibility/release preparation diff is reviewed

## Release identity and policy audit

- [ ] package/release identity is exactly `scoreform 0.10.0`
- [ ] `pds-core>=0.6,<0.7` is the only live Core runtime range
- [ ] exact Core 0.6.0 wheel is the release qualification baseline
- [ ] no live Core 0.5 compatibility constraint remains
- [ ] no sibling PDS runtime dependency/import remains
- [ ] no automatic latest/highest/best/official attempt selection exists
- [ ] no standards rating/proficiency/mastery inference exists
- [ ] no course Grade policy exists
- [ ] no portfolio Candidate/eligibility/selection/placement policy exists
- [ ] installed producer profile matches the frozen v0.10.0 contract
- [ ] installed `scoreform.academic_result_reader` imports successfully
- [ ] all attempts and non-score response states remain independently readable

## Project-owner source-menu rehearsal

The prior release rehearsal does not satisfy this release because runtime,
dependency, publication, and package identity changed after that candidate.

- [ ] create a fresh disposable synthetic workspace
- [ ] run the teacher menu from the v0.10.0 release-preparation source checkout
- [ ] create the synthetic roster through **Roster Management**
- [ ] create the synthetic assignment through **Assignment Management**
- [ ] generate answer sheets through the teacher menu
- [ ] open/visually inspect every class-packet page and at least one individual PDF
- [ ] process a supported retained PDS2 scan through the normal menu
- [ ] identical scan content appends zero new attempts
- [ ] results viewer shows the expected student, score, total, and attempt count
- [ ] actual schema-v2 `results.csv` column order is inspected
- [ ] blank/Return post-generation behavior is rehearsed
- [ ] direct generation/regeneration commands remain prompt-free
- [ ] exact interpreter version used for the rehearsal is recorded

See `docs/physical_acceptance_test.md` for the exact procedure.

## Authoritative automated gate and artifacts

- [ ] `run_tests.ps1` passes on the reviewed release-preparation commit
- [ ] Python 3.11 minimum-version CI/release testing passes
- [ ] release compatibility audit passes
- [ ] strict mypy passes for changed release scripts
- [ ] GitHub Actions pass on the release-preparation PR
- [ ] working tree is clean before candidate build
- [ ] candidate commit and tree are recorded
- [ ] exactly one v0.10.0 wheel and one v0.10.0 sdist are built
- [ ] `twine check` passes
- [ ] artifact-content audit passes
- [ ] artifact SHA-256 values are recorded
- [ ] clean noneditable Core 0.6.0 + ScoreForm 0.10.0 wheel install passes
- [ ] installed routing/publication profile discovery passes
- [ ] installed reader import and exact CLI version checks pass
- [ ] #169 installed producer acceptance passes under the 0.10.0 identity
- [ ] clean sdist installation/profile/import smoke passes

## Merge, final candidate freeze, physical acceptance, and authorization

The established ScoreForm physical-release order is merge first, then rebuild
and qualify the exact reconciled release commit, then run the real paper test.
Do not perform the authoritative physical acceptance against an unmerged branch
artifact.

- [ ] release-preparation PR is squash-merged
- [ ] local `main` is reconciled and clean
- [ ] reconciled `main` equals `origin/main`
- [ ] final release commit and tree are recorded
- [ ] authoritative release gate passes again on the reconciled release commit
- [ ] final v0.10.0 wheel/sdist and SHA-256 values are recorded from that commit
- [ ] clean noneditable installation of the exact final wheel passes
- [ ] project owner installs that exact recorded v0.10.0 final candidate wheel
- [ ] project owner runs the required real printed-and-scanned workflow
- [ ] physical-paper acceptance passes
- [ ] sanitized physical result is recorded
- [ ] project owner explicitly authorizes release

Any runtime, package, dependency, layout, routing, scoring, assembly,
result-contract, menu-workflow, build-script, behavioral-test, or runtime-smoke
change after the paper test invalidates it. Documentation-only recording of the
completed result does not require another paper run.

## Tag and GitHub Release

Only after physical acceptance and explicit owner authorization:

- [ ] `v0.10.0` tag points to the exact physically qualified release commit
- [ ] tag is pushed without rewriting an existing release tag
- [ ] GitHub Release is created from `v0.10.0`
- [ ] wheel/sdist assets attached to the GitHub Release are the verified artifacts
- [ ] release asset SHA-256 values match the physically qualified final artifacts
- [ ] no package-index publication occurs

## Post-release verification

- [ ] released Core 0.6.0 wheel and ScoreForm 0.10.0 wheel are downloaded into a fresh directory
- [ ] released ScoreForm wheel installs noneditably in a fresh venv
- [ ] `pip check` passes
- [ ] installed metadata reports exactly `scoreform 0.10.0`
- [ ] `scoreform --version` reports exactly `ScoreForm 0.10.0`
- [ ] `scoreform version` reports exactly `ScoreForm 0.10.0`
- [ ] `scoreform.academic_result_reader` imports from installed site-packages
- [ ] installed routing profile discovery succeeds
- [ ] installed publication producer profile discovery succeeds
- [ ] bounded installed reader/profile smoke passes
- [ ] #169 producer lifecycle is re-run against the released wheel when practical
- [ ] Meridian #9 exact `scoreform 0.10.0` reader identity is verified/unblocked
- [ ] Vitrine non-regression boundary is verified
- [ ] #170 is closed
- [ ] #160/milestone v0.10.0 is closed only after all release verification passes

ScoreForm and PDS Core use GitHub Release wheel assets. Core 0.6.0 is not
published to PyPI, and ScoreForm v0.10.0 must not introduce package-index
publication merely to satisfy a downstream consumer.
