# Issue #227 — Hardening A: coordinated class roster and metadata

Core v0.6.5's `write_class_roster()` and `write_class_metadata_for_class()` each stage and atomically replace *one* file. They do not provide an atomic two-file transaction. ScoreForm must not report these independent writes as one atomic commit.

## A1: bounded synchronous failure compensation

`scoreform.class_pair_commit.commit_class_pair()` validates both planned file targets before writing, refuses symlink/non-file destinations, validates existing content before authorized replacement, and retains existing class metadata `created_at` and `module_details`. It writes metadata first so metadata failures cannot mutate a roster. If the subsequent roster write fails, it restores the original metadata bytes only if the just-written metadata still matches exactly; otherwise it reports explicit partial state for manual reconciliation. If a roster writer could have committed before raising, it retains the new metadata and reports uncertain partial state rather than rolling metadata back and leaving the committed roster orphaned. A metadata writer that raises after committing is also reported as partial, without attempting a roster write. Existing ScoreForm's `write_roster_with_class_metadata()` retains its dictionary-on-success/`None`-on-failure UI contract and clearly prints `PARTIAL CLASS UPDATE` for uncertain outcomes.

**Limit:** This A1 slice covers ordinary exceptions, not process termination/power loss between the Core writes. A cross-file crash journal and coordinated concurrent-writer protocol require a separate A2 qualification. Do not claim crash-atomicity or full Hardening A acceptance after A1. Existing class-folder layout remains unchanged and no historical records are modified by applying the patch.

## Validation

Run `tests/test_issue227_hardening_a_class_pair.py` and existing roster/CLI tests, Ruff, mypy, and the release compatibility verifier. Test input uses temporary synthetic workspaces exclusively.
