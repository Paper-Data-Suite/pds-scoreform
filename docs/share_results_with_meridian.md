# Share Results with Meridian

`Share Results with Meridian` is ScoreForm's guided teacher workflow for making one managed assignment's exact ScoreForm result evidence current in the shared PDS Core publication architecture.

The workflow name is teacher-facing language. ScoreForm does **not** import, invoke, install, probe, or wait for Meridian. A successful result means:

> Results are published through Core and available for Meridian to consume.

It does not mean that Meridian has already imported or projected the evidence.

## Ordinary teacher journey

From **Assignment Management > Share Results**:

```text
1. Share Results with Meridian
2. Academic Work Registration
3. Academic Result Manifests
4. Academic Result Publications
```

Option 1 is the ordinary guided path. Options 2–4 preserve the exact advanced operations for diagnostics, repair, explicit registration changes, withdrawal, republish-after-withdrawal, catalog recovery, and other non-routine work.

The guided path retains one exact assignment context for its entire run. A valid active assignment is reused through the issue #188 context contract; otherwise the teacher performs one canonical class/assignment selection. The workflow does not select an assignment by title, first/latest ordering, or publication metadata.

## Exact stages

The guided layer repeatedly derives state from canonical ScoreForm/Core data. It does not create wizard state or another persistence format.

When registration is absent, the teacher explicitly chooses academic intent and lifecycle and confirms `REGISTER`. An existing valid registration is reused; the guided path never silently updates registration metadata.

When current producer evidence must be created or exactly replayed, the teacher confirms `GENERATE`. The existing immutable manifest generator owns source validation, replay, revision allocation, digest, conflict detection, and durability. The guided UI does not calculate a revision.

For a first publication, the teacher confirms `PUBLISH`. If the exact producer revision is already the current Core publication, no publication write occurs.

For a successor, ScoreForm resolves the exact canonical Core head internally and the teacher confirms `SUPERSEDE`. The exact predecessor publication ID is passed unchanged to the existing supersession service. A changed/stale head is never substituted automatically; the teacher must review fresh state and confirm again.

A withdrawn head is not treated as an empty publication series. The guided workflow stops and directs the teacher to **Academic Result Publications** for the exact `republish-after-withdrawal` operation.

## Cancellation and partial success

`REGISTER`, `GENERATE`, `PUBLISH`, and `SUPERSEDE` remain separate commit boundaries. Cancellation never claims that already-durable earlier stages rolled back.

Examples:

- cancelling after registration reports the durable registration revision;
- cancelling after manifest generation reports the durable/reused manifest;
- cancelling before supersession states that the previous Core publication remains current;
- typed partial-success conditions stop automatic progression and require canonical reload/inspection before retry.

The workflow never blindly retries a registration, manifest generation, publication, or supersession after a typed partial-success or stale-head condition.

## Privacy and authority

The guided application layer stores no student, response, score, scan, attempt, manifest payload, publication payload, or Meridian projection record merely to provide navigation.

Teacher-first status does not expose raw result rows, answer payloads, absolute paths, publication IDs, digests, or Core registry internals unless the teacher uses an existing exact advanced/technical workflow.

Authority remains:

```text
ScoreForm
  owns assignment/results evidence and producer manifest generation

Core
  owns Academic Work Registration and canonical Publication Records/catalog

Meridian
  owns evidence consumption, attempt policy, proficiency, Grades, and reporting
```

ScoreForm does not choose the official/best/latest attempt, calculate proficiency, or create Grades.

## Compatibility and release qualification

Issue #191 keeps the package compatibility range:

```text
Python >=3.11
pds-core>=0.6,<0.7
ScoreForm package version 0.10.0 during development
```

The current release-qualification reference is `pds-core 0.6.3`; that does not raise ScoreForm's dependency floor to `pds-core>=0.6.3`.

Clean installed acceptance qualifies both ordinary paths:

- `SF-AC10`: first publication through registration, immutable manifest, and Core publication;
- `SF-AC11`: successor manifest, safe cancellation before supersession, exact predecessor-preserving supersession, and final current state.

The installed acceptance also verifies that no Meridian distribution or import is required.

Direct CLI surfaces remain unchanged and available for deterministic automation:

```text
scoreform academic-work show|register|update
scoreform manifest list|show|validate|generate
scoreform publication status|list|show|publish|supersede|republish-after-withdrawal|withdraw|rebuild-catalog
```
