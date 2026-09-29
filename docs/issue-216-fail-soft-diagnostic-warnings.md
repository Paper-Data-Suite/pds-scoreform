# Issue #216 Slice 3 — Fail-soft diagnostic warnings

ScoreForm diagnostic PNGs are auxiliary troubleshooting evidence. Slice 3 separates their persistence outcome from authoritative OMR truth.

## Scoring contract

A diagnostic artifact write failure now produces a bounded `DiagnosticArtifactWarning` with diagnostic kind, persistence stage, fixed code `diagnostic_artifact_write_failed`, and an optional bounded exception class name.

It does not carry arbitrary exception prose, answers, scores, QR payloads, roster data, or unrestricted filesystem paths.

When OMR succeeds, diagnostic persistence failure is returned as subordinate warning state and the page result remains valid. When OMR itself fails, the substantive scoring classification remains authoritative and any earlier diagnostic warning is attached separately.

Existing diagnostic path authorization is unchanged: successfully written artifacts must still pass the route handler's managed-debug-root containment and regular-file checks.

Teacher-facing warning aggregation and durable diagnostic-event projection are intentionally deferred to later slices.
