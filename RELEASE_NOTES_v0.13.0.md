# ScoreForm v0.13.0

ScoreForm v0.13.0 combines the completed producer-reader compatibility work
and operational reliability improvements since the published v0.12.1 release.

## Reader compatibility

- Declares `scoreform_academic_result_reader_v1` through Core v0.6.5
  `PublicationReaderSupport` for `scoreform_academic_result_manifest_v1`.
- Requires `pds-core>=0.6.5,<0.7` and Python >=3.11.
- Preserves canonical source evidence, punctuation-bearing Standards/Profile
  identities, independent attempts, and distinct answer states.
- The producer reader does **not** grade, select official attempts, calculate
  proficiency, or execute Meridian/Vitrine policy.

## Reliability and safety

- Improves QR print reliability with larger vector QR symbols and adds a
  bounded ZXing decoding recovery path after OpenCV failure.
- Provides supervised scan-recovery safeguards and read-only preflight.
- Adds recoverable roster/class-metadata persistence, durable create-only
  assignment creation, and CSV spreadsheet-formula injection protection.

## Compatibility boundaries

Existing `scoreform_academic_work_v1` and Academic Result Manifest v1 contract
identities remain unchanged. Previously released v0.12.1 evidence and artifacts
are not replaced. Meridian #111 and Vitrine #103 must independently qualify
consumption of this new release and its public reader contract.

Physical printer/scanner acceptance: `physical_acceptance: not_claimed`,
unless an independent owner-operated test is recorded in the release audit.

## Release evidence

The exact qualified source commit, Git tree, wheel/sdist SHA-256 hashes,
installed qualification outcomes, and GitHub asset verification will be
recorded when the release is finalized. Do not interpret this document as
publication authorization or a completed release.
