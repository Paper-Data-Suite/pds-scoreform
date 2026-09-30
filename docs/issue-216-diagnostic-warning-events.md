# Issue #216 — Slice 4: diagnostic warning events

Slice 4 projects ScoreForm's already-subordinate diagnostic artifact warnings into the
existing privacy-conscious diagnostic event system.

## Event contract

When routed page scoring carries one or more diagnostic artifact warnings, ScoreForm may
record one page-level event:

- component: `scoring`
- workflow: `score_scan`
- stage: `diagnostic_persistence`
- outcome: `partial_success`
- code: `diagnostic_artifact_write_failed`
- category: `diagnostics`

The fixed safe summary is:

> Optional scoring diagnostic artifact could not be persisted.

The event may retain the warning's validated exception class name, such as
`PermissionError`. It does not retain exception prose, traceback data, answers, scores,
student identity, QR payloads, or unrestricted absolute paths.

The diagnostic path context is sanitized to the assignment's managed
`debug/<diagnostic>` location.

## Authority boundary

Event persistence is best-effort and non-authoritative.

A failure to build or persist this event cannot:

- turn a successful page score into a failure;
- replace a substantive OMR classification;
- create scan-review authority;
- alter routed result identity, provenance, or attempt assembly.

Artifact-level detail remains on the in-memory `diagnostic_warnings` tuple. The durable
event is intentionally one page-level signal when any optional diagnostic persistence
degrades, avoiding a shadow result store or unnecessary event duplication.

Teacher-facing aggregation is deferred to a later slice.
