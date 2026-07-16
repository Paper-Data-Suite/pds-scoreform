# Prepare ScoreForm v0.9.1 release

Refs #147
Refs #137

## Summary

Completes the v0.9.1 documentation, packaging, compatibility audit, automated
release gate, artifact validation, clean-install validation, and physical-test
procedure for the Core 0.5/PDS2 migration.

## Validation

- Automated release gate: passed locally on Python 3.14.1 (768 passed, 7 skipped)
- Compatibility audit: reviewed; remaining terms are historical policy,
  negative fixtures/assertions, or the unrelated current-only
  `QrPayloadDetectionResult` name
- Provisional pre-commit working-tree `scoreform-0.9.1-py3-none-any.whl`
  SHA-256 (not yet tied to a clean candidate commit):
  `cf63c60f4c8ea267fa4930f5cd57a9233c1329388b523eb4412a72e082f443f3`
- Provisional pre-commit working-tree `scoreform-0.9.1.tar.gz` SHA-256:
  `1ea67f70d91f8c1a04185b2d1f9de6efed0efadc764163036fbd6c59619ecc41`
- Clean noneditable wheel/sdist install: passed with separately built
  `pds-core 0.5.0` wheel
- Installed profile discovery and import/help/version side-effect checks: passed
- GitHub Actions Python 3.11 validation: pending PR execution

Physical-paper acceptance: pending

Release publication: blocked

No tag, release, issue closure, milestone closure, or package-index publication
is part of this preparation PR.
