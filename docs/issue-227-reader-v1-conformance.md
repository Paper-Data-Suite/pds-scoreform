# Issue #227 — academic-result reader v1 conformance matrix

Slice 5 freezes behavior for **ScoreForm's producer-owned reader contract**
`scoreform_academic_result_reader_v1`. This is a development conformance
qualification, not a new release, a consumer authorization, or a change to the
manifest v1 schema.

## Authoritative implementation and test basis

- Public reader: `scoreform.academic_result_reader`, using the existing
  `scoreform.academic_result_manifest` decoder, validator, and canonical writer.
- Declaration: Core `PublicationReaderSupport` for `academic_result_set` and
  `scoreform_academic_result_manifest_v1`, advertised by distribution `scoreform`.
- Fixture: `tests/fixtures/publication/scoreform_academic_result_manifest_v1.json`,
  with only synthetic students, attempts, and native provenance.
- Test gate: `tests/test_issue227_reader_v1_conformance.py`; it is included in
  the existing routine pytest and Release Readiness pytest jobs.
- Installed evidence: Slice 4's separate authenticated Core v0.6.5 / noneditable
  ScoreForm candidate wheel acceptance, which must remain green.

## Conformance requirements

| Area | Reader v1 obligation | Test coverage |
| --- | --- | --- |
| Input | Accept exact `bytes` only | Reject text, bytearray, memoryview, bytes subclass, null, and number |
| Decode | Reject malformed UTF-8/JSON, duplicate keys and nonfinite numbers | Bounded public `ScoreFormAcademicResultReaderDecodeError` without echoing payload |
| Canonical encoding | Match ScoreForm canonical serializer byte-for-byte | Reject altered whitespace, newlines, and indentation despite unchanged meaning |
| Manifest schema | Preserve v1 record/contract identity, keys, source snapshots and cross-model invariants | Reject unknown/missing fields, mismatched work, source metadata, and timestamps |
| Attempt integrity | Preserve every exact student + attempt identity | Reject duplicate/unordered students/attempts, invalid response order, scores or states |
| Provenance | Preserve PDS2, manual, and review origins without opening retained source files | Reject unsafe retained paths, inconsistent PDS2 arrays or incorrect origin/provenance shape |
| Lookup | Exact sources, students, attempts, questions and responses | Validation vs. not-found distinctions, no fallback to another student/attempt/question |
| Standards | Keep Standards Profile and Standard IDs unchanged; these are **not** routing/path identifiers | Preserve punctuation-bearing and valid Unicode identity values in canonical bytes and question lookups |
| Immutability | Return producer-owned frozen models | Deterministic reading, canonical round trip, mutation rejection |
| Boundaries | No filesystem access, stdout, consumer grades, policy, or publication-head decisions | In-memory source lookups and controlled file-access prohibition |

The conformance suite calls the **real public reader** and producer manifest
functions. It does not duplicate their parsing or validation logic. Each invalid
schema payload is intentionally encoded as syntactically valid JSON so that the
reader's own decoding boundary is tested.

## Ownership and release meaning

Reader contract v1 is a compatibility **promise about interpretation and API**,
not a synonym for manifest version v1 or the distribution version. A future
ScoreForm distribution release may preserve reader v1 only after independently
passing these conformance checks and the installed-wheel gate. A breaking
reader/API change requires a separately declared reader contract version;
metadata alone never proves conformance.

Core verifies publication metadata, registries and the publication envelope.
ScoreForm decodes its own verified manifest bytes. Consumers independently own
authorization, policy, Grade selection, portfolio projection, and any adapter
compatibility. This Slice 5 gate does **not** qualify any different ScoreForm
distribution version, establish consumer compatibility, or claim physical
scanner/printer acceptance.

## Focused local commands

```powershell
python -m pytest -q `
  tests/test_issue227_reader_v1_conformance.py `
  tests/test_academic_result_reader.py `
  tests/test_issue227_reader_contract_foundation.py `
  tests/test_issue227_publication_reader_metadata.py `
  tests/test_issue227_installed_reader_contract.py

python -m ruff check .
python -m mypy scoreform
python scripts/verify_release_compatibility.py
git diff --check
```

The full suite, Core v0.6.5 installed-wheel acceptance, and cross-platform
checks remain final issue qualification work.
