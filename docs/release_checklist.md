# ScoreForm v0.9.1 release checklist

Publication remains blocked until the project owner completes the final paper
test and explicitly authorizes release. Codex may prepare implementation,
automated tests, review material, and instructions, but may not claim a
physical pass or mark the physical-acceptance item complete.

## Review and pre-build normal-use acceptance

- [x] implementation is complete
- [x] focused automated tests pass
- [x] complete diff is reviewed
- [x] project owner rehearsed the normal teacher menu from the source checkout
- [x] rehearsal covered **Roster Management** > **Create a class roster**
- [x] rehearsal covered **Assignment Management** > **Create an assignment**
- [x] rehearsal covered **Generate answer sheets** and the new
  **Open class packet for printing** action
- [x] project owner visually inspected every packet page and at least one
  individual PDF
- [x] rehearsal covered retained PDS2 **Score scanned responses** through the
  normal menu
- [x] identical scan content appended zero new attempts
- [x] **View assignment results** showed the correct student, score, total, and
  one attempt in its compact terminal summary
- [x] the actual `results.csv` was separately inspected and had the required
  teacher-first prefix, contiguous question pairs, then page/provenance columns
- [x] single-assignment regeneration opened the individual-sheets folder
- [x] generic blank-template generation and opening worked
- [ ] reviewed corrections are committed and merged

The normal-use rehearsal is deliberately before the release build. It is not
the final physical acceptance test.

## Authoritative gate, artifacts, and installed smoke

- [ ] authoritative automated release gate passes on the merged commit
- [ ] Python 3.11 minimum-version CI/release testing passes
- [ ] GitHub Actions pass on the corrections pull request
- [ ] working tree is clean before building
- [ ] candidate commit and tree are recorded
- [ ] wheel and source distribution are built from that exact commit
- [ ] `twine check` and artifact-content audit pass
- [ ] artifact hashes are recorded
- [ ] clean noneditable PDS Core and ScoreForm wheel installation passes
- [ ] installed module profile and import/help/version boundaries pass
- [ ] installed standard, multipage, and compact smokes pass
- [ ] installed normal-menu smoke passes

Package support remains `Python >=3.11`. The project-owner menu and physical
tests may use Python 3.11, 3.12, 3.13, 3.14, or a later compatible interpreter;
record the exact version used.

## Physical acceptance and authorization

- [ ] project owner runs the exact reviewed installed wheel through the real
  printed-and-scanned workflow
- [ ] physical-paper acceptance passes
- [ ] sanitized physical result is recorded
- [ ] project owner explicitly authorizes release

Any runtime, package, dependency, layout, routing, scoring, assembly,
result-contract, or menu-workflow change after this paper test invalidates it.
Documentation-only recording of a completed result does not require another
paper run.

## Publication

- [ ] tagged commit is verified
- [ ] GitHub Release is created
- [ ] release assets and hashes are verified
- [ ] no package-index publication occurred
- [ ] #147 is closed
- [ ] #137 is closed
- [ ] v0.9.1 milestone is closed
- [ ] post-release clean installation passes
