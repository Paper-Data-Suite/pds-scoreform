# Issue #227 — Hardening A2: recoverable paired class writes

A1 coordinates *ordinary* failures but cannot recover an interrupted two-file write after the process exits. Core 0.6.5's roster CSV and `class.json` writers are individually atomic, **not a combined atomic transaction**.

A2 creates a class-local, create-only `.scoreform-class-pair.intent.json` **before the first Core write**. This journal gates concurrent **ScoreForm paired** operations and records the previous roster/metadata digests, semantic fingerprints of the planned next models, and the prior metadata bytes for exact restoration. It is located beside the class data in the user's configured workspace, not a temporary directory. No student names or roster payloads are stored in the journal; previous metadata can include `module_details`, so protect the journal as class data. The journal is created with filesystem mode `0600` where supported.

On ordinary success, both Core files are rechecked against the journal and the journal is cleared. On normal roster failure with confirmed metadata rollback, the journal is cleared. On interruption, the journal remains and all later paired writes refuse to proceed until an operator explicitly recovers it.

## Recovery states

- `none`: No journal; no recovery required.
- `unchanged`: Both canonical files match their exact prior bytes; clearing the journal is safe.
- `restore_metadata`: Roster retains its exact previous bytes and metadata matches the planned next *model*. Recovery restores only the previous metadata bytes (or removes newly created metadata), then verifies the prior pair and clears the journal.
- `completed`: Both canonical files match the intended models; clear the journal without changing either file.
- `conflict`: A file is missing, malformed, or differs from both known states. **Do not modify either file**; require manual reconciliation.

Recovery must be performed only after stopping all ScoreForm and other PDS writers for the selected class. A crash while Core owns its independent `.roster.write.lock` may also leave that Core lock behind; investigate such a lock rather than deleting it automatically. The journal is not an operating-system lock for arbitrary Core writers. Filesystem fingerprint checks guard unexpected intervening writes but cannot eliminate all TOCTOU races or OneDrive conflict-copy semantics. The journal is fsynced, and its directory is synced where supported; Windows directory fsync and power-loss durability across both independent Core writers are not guaranteed. This primarily qualifies process-interruption recovery, not crash-atomicity or fully isolated cross-module transactions.

## Operator workflow

Inspect (read-only):

```powershell
python scripts/recover_issue227_class_pair.py `
  --workspace "C:\path\to\PDS_WORKSPACE" `
  --class-id english12_p2
```

After verifying **all writers are stopped** and reviewing the disposition:

```powershell
python scripts/recover_issue227_class_pair.py `
  --workspace "C:\path\to\PDS_WORKSPACE" `
  --class-id english12_p2 `
  --apply `
  --confirm-writers-stopped
```

Never apply recovery to a live classroom operation, delete the journal blindly, or replace conflicting files to make a digest match. `conflict` requires a separate operator investigation with backups. A retained journal intentionally prevents additional ScoreForm paired updates until resolved.

## Tests and boundaries

`tests/test_issue227_hardening_a2_recovery.py` tests both new-class and overwrite paths, simulated interruption before and after roster commit, deterministic retry, metadata byte restoration, concurrent ScoreForm writers, divergent Core writers, and malformed journal handling. Existing A1 and roster tests must also pass. No Core v0.6.5 API, public reader, manifest, result history, academic publication contract or release version changes.
