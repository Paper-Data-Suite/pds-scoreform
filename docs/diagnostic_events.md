# Privacy-Conscious Diagnostic Events

ScoreForm retains a bounded local troubleshooting history for selected operational
failures, partial-success conditions, verified recoveries, and a small number of
verified durable workflow boundaries.

This facility is intentionally **not** telemetry, analytics, an audit log, a
teacher-activity log, a student-activity history, or domain authority.

## Ownership and storage

Diagnostic events are owned by ScoreForm and stored beneath the selected PDS
workspace:

```text
shared/
  scoreform/
    diagnostics/
      events/
        diag_<32-lowercase-hex>.json
```

Core does not own this event family. The event store is not part of Core's
registry, publication catalog, scan-review records, or future module-operations
attention contract.

A missing diagnostic directory is a valid empty state. Read-only listing and
showing do not create it. If the configured workspace root itself does not yet
exist, `scoreform diagnostics list` also leaves that workspace path absent.

Deleting the diagnostic event directory while ScoreForm is not using it removes
troubleshooting history only. It does not alter assignments, rosters, answer
sheets, scans, scan-review records, results, Academic Work Registration,
Academic Result manifests, Publication Records, catalogs, or any future current
attention state.

## Schema v1

Every retained file is one immutable schema-v1 JSON object. The fixed fields are:

```text
schema_version
module
record_type
event_id
occurred_at
scoreform_version
core_version
component
workflow
stage
outcome
category
code
class_id
assignment_id
exception_type
safe_summary
path_context
```

Fixed identity is:

```text
schema_version = "1"
module = "scoreform"
record_type = "diagnostic_event"
```

Unknown fields are rejected. There is no arbitrary `metadata`, `details`,
`context`, `payload`, or `extra` dictionary.

`event_id` is opaque and carries no classroom identity. `occurred_at` is
UTC. `scoreform_version` and `core_version` identify the installed runtime that
produced the event.

`class_id` and `assignment_id` are optional bounded work context. Schema v1 has
no generic student/person field.

## Privacy boundary

Generic event JSON must not contain:

- student names or student IDs;
- roster rows or guardian/contact data;
- answer choices, answer keys, question-level responses, scores, percentages, or
  result/attempt rows;
- raw scans, PDFs, images, OCR text, or image bytes;
- raw/full QR or PDS2 payloads;
- whole assignment, scan-review, manifest, registration, or Publication records;
- teacher private notes;
- credentials, tokens, cookies, or environment dumps;
- absolute machine paths;
- tracebacks, locals, exception argument dumps, or arbitrary exception messages.

Event summaries are owned by fixed diagnostic codes. Callers do not provide
persistent free-form prose. When exception context is useful, only the validated
exception class name is retained automatically.

A workspace-relative path is retained only when it matches an allowlisted
ScoreForm diagnostic context. Student-specific/raw filenames are generalized to
placeholders such as `<source>`, `<artifact>`, `<diagnostic>`, or `<failure>`.

## Relationship to scan-review records

Core scan-review records under:

```text
scans/review/
scans/review/resolutions/
```

remain the canonical detailed recovery evidence. Their contracts may retain
information that generic diagnostic events intentionally do not, including exact
route/recovery provenance needed to resolve a paper.

Diagnostic events answer a different question: **what bounded operational event
happened recently?** They never replace the complete Core recovery record.

## Relationship to teacher scan diagnostics

Teacher-facing scan-quality diagnostics project current actionable problems from
canonical scan-review state. Historical diagnostic events do not decide whether
a scan currently needs attention.

A historical `qr_missing` event may remain after the teacher has already
rescanned and resolved the page.

## Relationship to current attention and suite doctor

Issue #193 owns current ScoreForm attention/next-action state. That state must be
derived from current authoritative Core/ScoreForm records, not diagnostic
history.

Issue #194 owns suite doctor/launcher behavior. The diagnostic event store is not
required for ScoreForm launch readiness and does not create a Core-wide event
store.

## Event-emission policy

ScoreForm deliberately does not emit an event for every function or menu action.
Routine reads and navigation do not create history.

Instrumented owner-service boundaries include representative:

- assignment copy conflict, partial success, and verified target creation;
- multi-class generation blocked/stale, partial, and verified target outcomes;
- scan preflight, QR/payload, route-dispatch, and ScoreForm integration failures;
- result persistence failure/partial success and batch-level verified persistence;
- scan-review resolution failure and verified recovery actions;
- Academic Work Registration conflicts and partial success;
- Academic Result manifest failure/partial success and new verified revisions;
- Core publication conflict/partial success/catalog reconciliation and verified
  first publication/supersession.

Successful result/generation events are batch/target-level. ScoreForm does not
create per-student success history. Exact replay does not falsely create a new
success event for an already-existing attempt, manifest revision, or
already-current publication.

## Non-interference

Diagnostics are subordinate to the primary domain operation. If event persistence
fails, the primary success/failure/partial-success outcome remains unchanged.
ScoreForm does not roll back canonical state, retry the primary operation, or
recursively diagnose the diagnostic-write failure.

Production instrumentation uses the nonthrowing diagnostic emission boundary.

## Immutable persistence and retention

Events are create-only immutable UTF-8 JSON files with deterministic
serialization and filename/event-ID coupling.

Default retained canonical event count:

```text
500
```

After successful creation, ScoreForm prunes only proven oldest canonical events.
Ordering uses `occurred_at` plus `event_id`, not filesystem mtime. Malformed,
unknown, unrelated, or unsafe entries are not rewritten or blindly deleted merely
to reach the cap. A retention problem does not change the primary workflow
result. There is no background cleanup worker, watcher, streamer, or daemon.

## Direct CLI

Diagnostics are an advanced direct CLI surface rather than a routine teacher
dashboard:

```powershell
scoreform diagnostics list
scoreform diagnostics list --limit 20
scoreform diagnostics list --format json
scoreform diagnostics show --event-id <event_id>
scoreform diagnostics show --event-id <event_id> --format json
```

`list` defaults to 50 events and accepts at most 200. Events are newest-first.
Text output is concise. JSON output exposes only the fixed privacy-minimal event
schema. Both operations are read-only.

There are intentionally no issue-#192 commands for delete, clear, tail, watch,
stream, upload, send, or support-bundle export.

## QR diagnostic images and deep debug

Structured events are separate from existing QR diagnostic image artifacts.
Default QR diagnostic image behavior remains privacy-minimized. Full-page QR
diagnostic images require explicit developer opt-in:

```text
PDS_SCOREFORM_FULL_PAGE_DIAGNOSTICS
```

That opt-in may permit the separately stored full-page diagnostic image and
therefore may retain classroom marks/content. It does **not** relax the generic
diagnostic-event schema. Full-page diagnostics are never enabled automatically.

## No telemetry or cloud transport

The diagnostic event subsystem is local and offline. It does not upload, email,
stream, or transmit events and does not depend on remote logging, analytics,
crash-reporting, Sentry, or OpenTelemetry exporters.

No Paper Data Suite shell or Meridian runtime dependency is required.

## Support use

Start with:

```powershell
scoreform diagnostics list --limit 20
```

Then inspect one exact event:

```powershell
scoreform diagnostics show --event-id <event_id>
```

Use the event code, stage, installed versions, and optional class/assignment
context to choose the authoritative subsystem to inspect next. Do not infer
current scan, result, publication, or attention state from event history alone.
