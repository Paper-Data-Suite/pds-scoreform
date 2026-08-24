# Teacher-facing scan-quality recovery

Issue: #190  
Acceptance case: `SF-AC08`

## Purpose

ScoreForm's primary scan-review experience is organized for recovery rather than
for implementation inspection. A teacher should be able to answer three
questions without interpreting PDS2 internals:

1. What happened?
2. Is the original scan safely retained?
3. What should I do next?

The primary hierarchy is:

```text
Problem
→ Evidence
→ Recommended next step
→ Available actions
→ Technical details
```

This is a presentation and recovery layer over the existing immutable Core-v2
failure records and ScoreForm-owned failure details. It does not create a second
failure database.

## Structured diagnostic classification

Teacher wording is derived from stable structured state, including Core failure
category/stage and ScoreForm-owned `scoreform_category`. OMR failures that
previously risked collapsing into generic processing prose now carry a closed
`ScoreFormPageScoringError.diagnostic_code`.

Important examples include:

- `registration_marks_missing`
- `omr_processing_failed`
- `malformed_page_result`
- `diagnostic_write_failed`

The teacher projection does not classify a registration failure by searching the
human exception message for phrases such as "registration marks."

## Recovery families

The projection covers the major `SF-AC08` families:

- source intake and retention;
- registration/alignment and OMR processing;
- QR/payload recognition;
- route and target resolution;
- module compatibility;
- missing/incomplete page sets;
- duplicate and conflicting evidence;
- mixed/inconsistent issuance identity;
- persistence failures;
- otherwise-safe generic processing failure.

Missing-page guidance uses logical physical page membership when present (for
example, "page 2 of 3") rather than requiring the teacher to interpret page IDs.

## Evidence status

The primary view explicitly distinguishes:

- **retained** — both canonical `source_scan_id` and retained-source provenance
  are present;
- **not retained** — no canonical retained-source provenance is present;
- **uncertain** — only part of the expected retained-source provenance is
  available.

The projection does not infer retention from filenames, diagnostic images,
timestamps, route identity, or directory guesses.

Leaving the review flow does not delete retained source evidence or append-only
review history.

## Recommended actions

Recommendations are always intersected with the actions that the current review
item can actually perform through `allowed_review_actions(...)`.

The presentation layer therefore cannot recommend an invented action or a manual
fallback that the existing service does not permit.

Manual entry/manual marks remain explicit fallbacks. They do not fabricate
routed provenance, do not override incomplete-attempt rules, and do not select
an official attempt.

## Technical details

The ordinary teacher view does not lead with:

- failure IDs;
- route IDs;
- page IDs;
- issuance IDs;
- hashes;
- raw PDS2 payloads;
- retained-source paths;
- diagnostic artifact paths;
- resolution-history internals.

Those values remain available through the explicit read-only:

```text
T. Technical details
```

surface for development, support, and exact recovery.

Paths shown by ScoreForm-owned diagnostic details remain validated
workspace-relative paths. Deep full-page debugging remains governed by the
existing opt-in behavior and the broader privacy/retention policy work in #192.

## Cancellation

Cancellation reporting reflects the action actually abandoned.

Examples include:

- `Manual Entry Cancelled`
- `Manual Marks Cancelled`
- `Route Selection Cancelled`
- `Route Correction Cancelled`
- generic `Scan Review Not Updated` for ordinary non-manual actions such as
  `rescan_needed` or `defer`.

A cancellation before `WRITE` states that no new result or resolution record was
written. It does not imply that earlier retained evidence or immutable review
history was rolled back.

## Source-scoped guided recovery

The #189 guided workflow continues to call:

```python
launch_scan_review_menu(source_scan_id=...)
```

with the exact retained source identifier. #190 changes how those items are
explained, not how the source filter works.

Filename, timestamps, "latest", and directory ordering are not substitutes for
`source_scan_id`.

## Direct CLI compatibility

The exact direct commands remain separate developer/recovery surfaces:

```text
scoreform list-scan-review ...
scoreform resolve-scan-review ...
scoreform score ...
```

The interactive teacher menu becoming less technical does not remove the
machine/developer-facing classification and identity output of those commands.

## Privacy boundary

#190 does not add a persistent teacher-diagnostic event store.

The primary teacher view avoids raw answer payloads, result rows, roster detail,
raw grades, unrestricted absolute paths, raw PDS2 payloads, hashes, and opaque
route/page/issuance identity.

Existing canonical retained scans, results, Core review metadata, and bounded
ScoreForm diagnostic artifacts remain in their established locations.

Persistent diagnostic-event policy, rotation, retention, and deep-debug
controls remain #192.

## Automated and installed acceptance

Source tests cover diagnostic projection, structured OMR classification, action
intersection, primary/technical separation, cancellation wording, and #189
source scoping.

The clean-wheel `SF-AC08` verifier additionally exercises:

- a real synthetic QR-less retained PNG through the production routed-scoring
  failure pipeline;
- strict Core-v2/ScoreForm review fixtures for registration failure,
  missing-page recovery, and conflicting duplicate evidence;
- primary teacher recovery rendering;
- explicit technical-detail access;
- truthful non-manual cancellation with no resolution append;
- exact `source_scan_id` scoping;
- deterministic direct scan-review CLI preservation;
- absence of a new diagnostic shadow store.

## Physical gate

Automated acceptance does **not** establish printer/scanner usability.

Issue #195 must physically confirm representative synthetic paper cases,
including:

- cropped or incomplete registration marks;
- skew/rotation/alignment failure;
- missing or unreadable QR;
- missing page from a multi-page issuance;
- duplicate/conflicting page;
- visibly ambiguous mark where applicable;
- successful rescan/recovery guidance.

Those observations remain project-owner adjudicated.
