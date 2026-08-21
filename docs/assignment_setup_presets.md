# Assessment Setup Presets Contract

Assessment setup presets are a ScoreForm v0.11 teacher-workflow capability
introduced by issue #184. They implement `SF-AC03` from
`docs/v0.11.0_usability_acceptance_cases.md`.

The teacher problem is:

> I repeatedly use the same assessment shape, key structure, and standards
> alignment. Let me save that non-student setup once and reuse it without
> turning an old assignment into a mutable template.

The central invariant is:

```text
assignment != preset

preset application =
  reusable configuration
  + fresh teacher-selected assignment identity/title
  + current Core class/roster/standards authority
```

A preset is not class-qualified work, not an alias to an old assignment, and not
a live inheritance relationship.

## Ownership and canonical storage

Presets are owned by ScoreForm and are workspace-local rather than class-local.

Canonical storage is:

```text
<workspace>/modules/scoreform/presets/<preset_id>.json
```

They deliberately do not live under class-qualified ScoreForm work and do not
use `local_outputs/` as durable authority.

## Preset v1 record

A v1 preset contains only:

```json
{
  "schema_version": 1,
  "module": "scoreform",
  "record_type": "assignment_setup_preset",
  "preset_id": "english10_short_quiz",
  "label": "English 10 Short Quiz",
  "question_count": 15,
  "choices": ["A", "B", "C", "D"],
  "layout_id": "standard_15q_abcd_v1",
  "answer_key": {
    "1": "A"
  },
  "standards": {
    "1": []
  },
  "standards_profile_id": "optional_profile_id"
}
```

`standards_profile_id` is optional. All other fields shown above are required.

The answer key is complete because a normal ScoreForm assignment requires a
complete key. It is teacher-authored non-student setup, not result evidence.

Unknown top-level fields are rejected. Strict JSON parsing also rejects malformed
UTF-8, duplicate object keys, and nonfinite numbers.

## Explicitly excluded state

A preset never stores or inherits:

- class ID;
- assignment ID or assignment title;
- roster rows or student IDs;
- period or school-year authority;
- generated answer sheets or PDFs;
- page, issuance, route, or QR identity;
- scans or scan-review history;
- attempts, answers, scores, totals, or `results.csv`;
- Academic Work Registration;
- academic-result manifests;
- Publication Records/catalog state;
- debug/export artifacts; or
- arbitrary unknown future assignment/work descendants.

The label may default to a source assignment title when saving from an
assignment, but that does not create lineage or a live source reference.

## Creating a preset from an assignment

The teacher selects one exact canonical source by `source class_id` and
`source assignment_id`.

ScoreForm reuses the hardened source boundary introduced for assignment copying:

- canonical class-qualified work path;
- safe ancestor chain;
- regular non-symlink `assignment.json`;
- strict JSON bytes;
- assignment ID/path agreement;
- current Core standards/profile validation; and
- exact source bytes plus SHA-256 snapshot.

The preset is built with a positive allowlist only:

```text
question_count
choices
layout_id
answer_key
standards
standards_profile_id when present
```

The source class, source assignment ID, and operational descendants are not
persisted.

Commit reloads the source immediately before the preset write. If source bytes,
path safety, identity, or standards authority changed after preview, the save
fails closed.

Once saved, the preset is independent. The original assignment may later be
edited or removed without changing the preset.

## Manual creation

A teacher may also create a preset directly without selecting a class or
fabricating a temporary assignment identity.

The teacher supplies preset ID, label, layout, question count, complete answer
key, and optional Core standards/profile alignment.

Inside A-D answer-key entry, `B` remains the valid answer choice B. The explicit
word `BACK` cancels that answer-entry sequence; `M`/`Q` retain navigation
behavior.

Issue #185 extends manual preset creation with the shared bulk answer-key entry
methods (paste, CSV, JSON, or per-question). A valid bulk key receives the same
complete normalized preview and explicit `USE` staging boundary as normal
assignment creation. See [`assignment_bulk_entry.md`](assignment_bulk_entry.md).

## Standards authority

Presets store references, not copied Core standards definitions.

Whenever a preset with standards/profile references is created, updated, or
applied, ScoreForm validates those references against the current Core
standards library.

Stale references fail closed. ScoreForm does not silently discard, remap, or
rewrite standards authority.

## Lifecycle and concurrency

Supported lifecycle operations are:

```text
list
view/show
create
update/edit
delete
apply
```

Create is create-only.

Update and delete are based on an exact reviewed preset snapshot. Commit
revalidates exact current bytes/digest. If the preset changed after preview, the
teacher must review a new plan.

Editing or deleting a preset never cascades into assignments previously created
from that preset. Assignments do not retain live inheritance or synchronization.

## Applying a preset

Applying a preset creates one or more normal independent ScoreForm assignments.

The teacher supplies:

```text
preset_id
fresh target assignment_id
fresh target title
one or more target Core classes
```

The candidate assignment copies the reviewed preset values by value and receives
the teacher-selected fresh assignment identity/title.

Before any write, ScoreForm validates:

- exact preset snapshot;
- preset path/link safety;
- candidate digest and normal assignment validity;
- current standards authority;
- every target Core roster;
- duplicate target selection;
- canonical target path safety;
- target work-root absence;
- known Core Academic Work Registration history; and
- known Core Publication Record history.

A target with any existing ScoreForm work root is a collision.

There is no overwrite, force, merge, adopt, clean, or delete-and-recreate mode.

## Staged review and editing

The teacher-facing apply workflow shows the complete candidate key and standards
alignment before mutation.

The teacher may create the assignment exactly as shown or stage edits to title,
answer key, or standards alignment before confirmation. Those staged edits
apply only to the new assignment candidate and do not silently update the saved
preset.

Issue #185 routes preset answer-key/alignment editing and staged preset-derived
assignment editing through the same shared bulk parsers and previews used by
normal assignments. #184's exact preset snapshot and guarded plan/commit
semantics remain unchanged.

Final mutation boundaries use exact confirmations:

```text
SAVE
UPDATE
DELETE
CREATE
```

## Multi-target semantics

One preset may be applied to several classes in one operation.

All predictable failures are checked before the first write.

If an unexpected runtime/I/O failure occurs after an earlier target has already
been durably created, the earlier target remains, the failed target is reported,
later targets are not attempted, and the overall operation reports partial
failure.

## Teacher workflow

Until issue #187 reorganizes Assignment Management, presets are exposed through:

```text
14. Assessment setup presets
```

with:

```text
1. Create preset from an assignment
2. Create preset manually
3. View presets
4. Edit preset
5. Delete preset
6. Create assignment from preset
```

No preset workflow automatically generates sheets, registers Academic Work,
creates manifests, or publishes results.

## Direct CLI

```powershell
scoreform preset list

scoreform preset show `
  --preset-id <preset_id>

scoreform preset save `
  --preset-id <preset_id> `
  --source-class-id <class_id> `
  --source-assignment-id <assignment_id> `
  [--label <label>] `
  [--apply]

scoreform preset apply `
  --preset-id <preset_id> `
  --target-assignment-id <assignment_id> `
  --title <title> `
  --target-class-id <class_id> `
  [--target-class-id <class_id> ...] `
  [--apply]

scoreform preset delete `
  --preset-id <preset_id> `
  [--apply]
```

`list` and `show` are read-only.

`save`, `apply`, and `delete` are plan-only by default. Without `--apply`, they
write nothing.

`--force` and `--overwrite` are intentionally unsupported.

## Privacy and authority boundaries

Teacher-facing preset output may show preset configuration, class IDs, target
student counts, period summaries, and workspace-relative paths. It does not need
to print roster student IDs to preview an application.

Core continues to own class/roster authority, standards authority, shared work
identity contracts, Academic Work Registration, and Publication Records/catalog
state.

ScoreForm owns its preset record and setup workflow.

Preset application does not select best/latest/official attempts, compute
proficiency/mastery, calculate a Grade, or introduce a Meridian runtime
dependency.

## Relationship to neighboring v0.11 issues

Issue #185 extends #184 with shared bulk/paste/CSV/JSON key and alignment entry
without changing preset storage, independence, or concurrency semantics.

Issue #184 does not implement:

- #186 multi-class answer-sheet generation;
- #187 the final task-oriented Assignment Management redesign;
- #188 recent/active context;
- #189 scan-to-results;
- #190 diagnostics;
- #191 guided publication; or
- later suite integration.

A preset is reusable setup. It is not a historical assignment transformed into
a mutable template.

## Acceptance

`SF-AC03` is covered by focused service, direct-CLI, and teacher-menu tests plus
clean installed-wheel acceptance through:

```text
scripts/verify_installed_assignment_preset_acceptance.py
```

Installed acceptance runs the real installed `scoreform` console script outside
the source tree and proves:

- plan-only save is non-mutating;
- the persisted preset contains only allowed non-student fields;
- removing the source assignment does not alter or invalidate the preset;
- plan-only apply is non-mutating;
- multi-class apply creates fresh normal assignments;
- target Core rosters remain unchanged;
- no sheets/results/registrations/manifests/publications are inherited or
  created;
- plan-only delete is non-mutating;
- explicit preset deletion leaves prior assignments unchanged; and
- the clean installed environment passes `pip check`.

Physical print/scan validation remains owned by issue #195.
