# ScoreForm v0.12.1

ScoreForm v0.12.1 is a compatibility patch for Academic Result Manifest
Standards identity handling.

## Fixed

ScoreForm 0.12.0 incorrectly applied Core's generic safe routing/path identifier
grammar to two Standards-derived manifest fields:

```text
assignment.standards_profile_id
question.standard_ids[]
```

That could reject authoritative Core Standards identities containing punctuation,
including values such as `RL.TS.11-12.4`, `W.NW.11-12.3.D`, or namespaced durable
identities such as `njsls-ela:RL.TS.11-12.4`.

v0.12.1 validates those fields in the durable Core Standards identity domain and
preserves their exact normalized text. It does not slug, transliterate, rewrite,
or substitute another identifier. Generic manifest routing, work, student, record
set, publication, and provenance identifiers retain their existing strict
validation.

## Contract compatibility

The manifest identity remains exactly:

```text
scoreform_academic_result_manifest_v1
```

This is a correction to an over-restrictive validation rule, not a structural
manifest-v2 change. Existing v1 manifests remain valid.

Compatibility consequence:

```text
ScoreForm <= 0.12.0 readers may reject a v1 manifest containing
Core-valid punctuation-bearing Standard/Profile identities.

ScoreForm >= 0.12.1 corrects that reader/producer defect.
```

The public consumer-neutral reader preserves producer-native Standards identity
without slugging, translation, resolution, proficiency inference, or Grade
policy.

## Teacher workflow

The normal guided path now accepts a Core-valid punctuation-bearing Standards
alignment through:

```text
Assignment Management
-> Share Results with Meridian
-> readiness
-> explicit manifest generation
-> explicit first Core publication
```

Generation remains distinct from publication, and publication retains explicit
teacher confirmation. ScoreForm still does not invoke or depend on Meridian.

## Installed qualification

The installed producer and guided Share Results acceptance paths now build a real
Core Standards Library/Profile containing punctuation-bearing durable identities
and verify exact identity preservation through generation, public reading, Core
publication, and the existing successor/supersession lifecycle.

Release qualification remains against the exact authenticated Core v0.6.4 wheel:

```text
pds_core-0.6.4-py3-none-any.whl
SHA-256: 48cea9317f2967bdc0f2d4c14349a56677c7c3f8211f0f33978ccb1a1c75859b
```

Runtime compatibility remains:

```text
Python >=3.11
pds-core>=0.6.4,<0.7
```

## Physical acceptance

Issue #222 does not change answer-sheet generation, QR layout, printing, scanner
ingestion, registration marks, OMR image processing, answer detection, or manual
scan review. No new physical rerun is required solely for this manifest-contract
repair. Automated qualification records:

```text
physical_acceptance: not_claimed
```

unless a separate owner-operated physical qualification is performed.

## Downstream Meridian

Meridian must separately inspect and qualify the exact released ScoreForm 0.12.1
reader artifact before claiming compatibility. Its exact-reader-version rule must
not be silently broadened. The expected downstream work is a Meridian patch
release with punctuation-bearing Standards interoperability acceptance.

## Historical release evidence

`RELEASE_NOTES_v0.12.0.md` and `docs/v0.12.0_release_audit.md` remain unchanged
historical release records.
