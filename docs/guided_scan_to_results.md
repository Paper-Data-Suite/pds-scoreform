# Guided Scan-to-Results Workflow

ScoreForm issue #189 implements `SF-AC07`, the guided retained-scan-to-result-review journey for the v0.11.0 teacher workflow milestone.

## Teacher workflow

The ordinary retained PDS2 path is:

```text
Assignment Management
→ Process Scans
→ Score scanned responses
→ choose a scan
→ Retained PDS2 Core page dispatch
→ Scan Processing Summary
→ review recorded assignment results and/or review unresolved items
```

Manual scoring with an explicit answer-key JSON remains a separate scoring mode.

The retained path is continuous: ScoreForm processes the selected scan once, reports what became durable, and offers only next actions supported by that completed operation. Returning to `Process Scans` does not rerun the scan.

## One structured scoring operation

The teacher menu and direct routed-scoring CLI share the same application operation for:

1. PDS2 source preflight;
2. Core source retention;
3. Core ordered page dispatch;
4. ScoreForm attempt assembly;
5. result export/idempotency;
6. Core-v2 scan-review persistence; and
7. existing eligible scan filing.

The guided menu consumes the structured result of that operation. It does not parse CLI output and does not invoke scoring a second time.

Direct `scoreform score <scan>` remains prompt-free, context-free, and deterministic.

## Durable result targets

A guided result target is derived only from confirmed result-export outcomes:

- newly appended attempts; or
- attempts already present under the existing idempotency contract.

A completed in-memory assembly is not enough. If export fails, the assembled attempt does not become guided assignment context.

For each durable result, ScoreForm retains only the exact:

```text
<class_id, assignment_id>
```

target needed for continuation.

Before activation, that target is canonically re-resolved through the current ScoreForm/Core workspace discovery rules from #188.

### One target

When exactly one durable assignment target exists, ScoreForm can open `Review Results` without asking the teacher to select the class and assignment again.

### Multiple targets

When one retained scan creates durable results for more than one ScoreForm assignment, the teacher explicitly chooses which result target to open.

ScoreForm never selects:

- the first target;
- the latest target;
- the previously active target; or
- an inferred “best” target.

### No durable target

QR text, a valid locator, a successful page dispatch, or a completed-but-unexported attempt cannot establish active assignment context by itself.

## Result review is evidence review, not grading policy

The result view continues to show ScoreForm-owned attempt evidence.

ScoreForm does not use this workflow to decide:

- official attempt;
- best attempt;
- latest attempt for grading;
- proficiency; or
- Grade.

Those policies remain outside ScoreForm and are not introduced by #189.

## Partial success and unresolved review

A retained scan may produce both:

- durable ScoreForm attempts; and
- unresolved review items.

The summary reports both truths. The teacher may review recorded results and may open unresolved items from the same scan.

The guided review path is filtered by the exact Core `source_scan_id` returned for the retained intake event. It does not silently open the global review queue.

The ordinary global `Resolve scan review items` entry remains available separately.

## Mixed-module retained scans

Core may successfully dispatch pages to other installed modules.

ScoreForm reports successful foreign pages only as an opaque count. It does not:

- inspect another module's result payload;
- activate ScoreForm context from a foreign result;
- write sibling-module records; or
- reinterpret a foreign work ID as a ScoreForm assignment.

Broader suite-level mixed-module returned-paper orchestration remains outside this ScoreForm-local workflow.

## Teacher-facing summary and privacy

The primary post-scan summary is intentionally bounded. It may report:

- safe source filename;
- retention success;
- source pages processed;
- complete ScoreForm attempts;
- newly recorded attempts;
- already-recorded/idempotent attempts;
- unresolved review occurrences persisted;
- review-persistence failures;
- successful foreign-module page count;
- exact durable ScoreForm class/assignment targets; and
- overall outcome.

It does not use the primary summary to print:

- answers;
- student names or IDs;
- raw QR payloads;
- route/page/issuance IDs;
- hashes;
- raw grades; or
- unrestricted absolute paths.

Detailed existing result/review screens remain available after the teacher chooses those actions.

## Cancellation after retention

Once Core retention or later durable writes have happened, `Back` or `Return to Process Scans` is navigation, not rollback.

ScoreForm states this explicitly:

```text
Returning does not delete retained evidence, results, or review records.
```

The workflow does not create a separate guided-session file, recent-scan database, or shadow results store.

## Direct and manual compatibility

The following remain distinct:

```text
interactive retained PDS2 mode
    → guided scan-to-results workflow

interactive manual answer-key mode
    → existing manual scoring

scoreform score ...
    → existing deterministic direct CLI
```

Interactive assignment context is not a hidden default for direct commands.

## Acceptance boundary

`SF-AC07` is qualified at source level and from a clean installed ScoreForm wheel with synthetic data.

The installed verifier exercises:

- isolated installed-package provenance;
- exact PDS Core compatibility;
- a real ScoreForm-generated registered PDS2 PDF;
- real retained routed scoring and result export;
- zero class/assignment reselection for exact result continuation;
- exact `source_scan_id` review scoping for QR-less retained failures;
- absence of guided shadow persistence; and
- deterministic prompt-free direct-score failure behavior.

This does **not** claim real printer/scanner acceptance. Physical printing, rescanning, registration-mark/QR readability, and representative classroom-paper adjudication remain the combined physical gate in #195.
