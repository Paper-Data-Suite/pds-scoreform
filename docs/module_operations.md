# ScoreForm module operations

ScoreForm exposes teacher-attention facts through PDS Core's version-1
`paper_data_suite.module_operations` contract.

The installed entry point is:

```text
paper_data_suite.module_operations
    scoreform = scoreform.pds_operations:get_module_operations_profile
```

The profile has module ID `scoreform`, supports Core operations contract `1`,
and currently exposes `attention_provider` only. `readiness_provider` remains
`None` until the separate suite doctor/launcher work in issue #194.

## Compatibility

The operations contract was introduced in PDS Core 0.6.2, so active ScoreForm
metadata requires:

```text
pds-core>=0.6.2,<0.7
```

Core 0.6.2 is the minimum operations-provider compatibility endpoint. Core 0.6.3
remains ScoreForm's exact current release-readiness reference. The authenticated
0.6.3 wheel SHA-256 is:

```text
98d7596ce0eed26e4d56a17bbbbd644db3014259b56a45783a173fe8237af5e5
```

Minimum-floor qualification and current release qualification are intentionally
different checks.

## Ownership boundary

ScoreForm owns the meaning of ScoreForm state and derives attention from current
authoritative ScoreForm/Core records. Core owns the neutral structures,
validation, discovery, invocation, bounds, and provider-failure isolation. A
suite shell may aggregate and present the resulting summaries, but it must not
inspect ScoreForm private storage or recreate ScoreForm semantics.

Attention evaluation is observation only. It does not create a workspace,
register Academic Work, generate manifests, publish or supersede results,
resolve scan review, score scans, write results, update recent-assignment
context, emit diagnostic events, launch menus, or execute owner actions.

## Request behavior

The neutral Core request may contain an explicit workspace, active school year,
and class ID.

- No explicit workspace returns `evaluation="unavailable"`.
- An unsafe/uninspectable workspace returns unavailable with fixed safe text.
- A successfully inspected workspace with no current attention returns
  `evaluation="evaluated"` and no summaries.
- A supplied class ID is an exact filter. ScoreForm never falls back to another
  class or recent assignment.
- ScoreForm does not invent school-year semantics merely because the neutral
  request carries an active-school-year field.

Partial evaluation keeps valid summaries when another source cannot be
inspected safely and adds one bounded `scoreform_attention_partial` notice.
Raw exception text and absolute paths are not copied into shared reports.

## Attention taxonomy

ScoreForm emits at most one aggregate per stable code, in deterministic order:

| Code | Count unit | Owner action |
| --- | --- | --- |
| `scoreform_incomplete_attempt` | open incomplete-attempt review items | `open_scan_review` |
| `scoreform_scan_review` | other open scan-review items | `open_scan_review` |
| `scoreform_results_registration_pending` | assignments | `open_share_results` |
| `scoreform_results_manifest_pending` | assignments | `open_share_results` |
| `scoreform_results_publication_pending` | assignments | `open_share_results` |
| `scoreform_results_supersession_pending` | assignments | `open_share_results` |
| `scoreform_results_publication_recovery` | assignments | `open_share_results` |
| `scoreform_results_state_attention` | assignments | `open_share_results` |

The two scan counts do not overlap.

## Scan-review authority

Current scan attention comes from `discover_scan_review_items(...)`.
Normal discovery retains unresolved and deferred items and excludes resolved
items.

The distinction between incomplete attempts and other scan review reuses the
public issue-#190 teacher diagnostic projection
`project_teacher_scan_diagnostic(...)`. In particular, the existing
`incomplete_attempt` diagnostic family is the semantic authority; the operations
provider does not maintain a second missing-page classifier.

Unscoped shared class/work identity is emitted only when it comes from validated
locator/target identity. Diagnostic or observed student identity is never
promoted into the Core attention report.

## Share Results authority

Publication attention reuses issue #191's side-effect-free
`plan_share_results_readiness(...)` state machine:

```text
REGISTER
    -> scoreform_results_registration_pending

GENERATE_MANIFEST
    -> scoreform_results_manifest_pending

PUBLISH_FIRST
    -> scoreform_results_publication_pending

SUPERSEDE
    -> scoreform_results_supersession_pending

WITHDRAWN_HEAD_REQUIRES_EXACT_RECOVERY
    -> scoreform_results_publication_recovery

REPAIR_REQUIRED
    -> scoreform_results_state_attention
```

`NOT_READY` and `ALREADY_CURRENT` emit no Share Results attention.

Share Results counts are assignment counts, never student, attempt, result-row,
answer, or score counts. The shared provider reports Core publication state only;
it never claims that Meridian imported or processed results.

## Context and owner actions

Core summaries may carry exact `class_id` and `ModuleWorkRef` values. ScoreForm
includes them only when an aggregate has one truthful exact context. Aggregates
spanning multiple assignments omit `work_ref`; aggregates spanning multiple
classes omit unscoped `class_id`.

Owner actions are opaque references:

```text
scoreform / open_scan_review
scoreform / open_share_results
```

They are not commands, URLs, Python targets, menu numbers, or serialized
arguments. Issue #193 does not implement remote action execution.

## Privacy

The shared report does not contain student names or IDs, roster rows, answers,
answer keys, scores, percentages, result rows, raw scans, PDFs/images, source
filenames, diagnostic paths, QR payloads, failure IDs, publication record
bodies, manifest bodies, registration bodies, teacher notes, credentials,
tokens, raw exceptions, tracebacks, or absolute workspace paths.

Fixed labels and notices are code-owned. Underlying titles, failure messages,
student identities, planner blocking reasons, and exception strings are not used
to construct shared text.

## Diagnostics are not attention authority

Issue #192 diagnostic events are historical troubleshooting evidence. The
attention modules do not import the diagnostic-event store, and changing only
diagnostic history must not alter an attention report.

Likewise, querying attention does not emit, rotate, or modify diagnostic events.

```text
diagnostic history != current operational attention
```

## Recent assignment context is not attention authority

Issue #188 recent/active assignment context is session-local navigation state.
Recency does not mean important, unfinished, urgent, or actionable. Operations
attention derives from persisted current state and the explicit Core request.

## Qualification

Release qualification includes:

- source tests for taxonomy, aggregation, exact class/work context, scan
  classification reuse, Share Results mapping, privacy, and zero-write behavior;
- Core invocation/validation tests;
- installed-wheel provider discovery outside the source checkout;
- Core provider diagnostics;
- absent-workspace and empty-workspace semantics;
- installed scan attention and diagnostic-history nonauthority;
- installed Share Results registration, manifest, publication-pending, and
  already-current projections;
- minimum-floor installed provider qualification against authenticated Core
  0.6.2; and
- full current installed operations qualification against authenticated Core
  0.6.3.

The dedicated cross-platform operations-wheel CI job runs on Windows and Ubuntu.
Core 0.6.2 qualification is deliberately narrow to the minimum provider
contract; Core 0.6.3 remains the full current release-reference acceptance.
