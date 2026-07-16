# ScoreForm v0.9.1 release checklist

This checklist separates release-candidate preparation from publication. No
publication item may proceed until the real-paper gate passes and the project
owner explicitly authorizes publication.

## Preparation

- [ ] implementation diff reviewed
- [x] all local automated checks pass
- [x] repository compatibility audit reviewed
- [x] docs agree with runtime behavior
- [x] version is exactly 0.9.1
- [x] wheel and sdist built
- [x] twine check passes
- [x] artifact contents audited
- [x] artifact hashes recorded
- [x] clean wheel installation passes
- [x] clean source-distribution installation passes
- [x] installed module profile discovered
- [x] import/help side-effect boundary passes
- [x] standard one-page E2E passes
- [x] standard multi-page E2E passes
- [x] compact-layout E2E passes
- [x] duplicate/conflict/missing tests pass
- [x] manual workflows pass
- [x] scan-review workflows pass
- [x] mixed-module dispatch passes
- [x] physical-paper procedure supplied
- [ ] GitHub Actions Python 3.11 release-readiness workflow passes

## Physical acceptance and authorization

- [ ] working tree is clean before candidate build
- [ ] candidate commit and tree recorded
- [ ] release gate rerun from the candidate commit
- [ ] wheel rebuilt from the candidate commit
- [ ] rebuilt candidate wheel SHA-256 recorded
- [ ] physical-paper acceptance passes
- [ ] sanitized physical result recorded
- [ ] project owner authorizes release

## Publication

- [ ] draft PR marked ready only after authorization
- [ ] final checks pass and diff is reviewed
- [ ] PR merged
- [ ] merged-main release gate passes
- [ ] tagged commit verified
- [ ] GitHub Release created
- [ ] release assets and hashes verified
- [ ] no package-index publication occurred
- [ ] #147 closed
- [ ] #137 closed
- [ ] v0.9.1 milestone closed
- [ ] post-release clean installation passes
