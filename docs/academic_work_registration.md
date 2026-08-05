# ScoreForm Academic Work Registration

Academic Work Registration is an explicit teacher or caller declaration that an
existing managed ScoreForm assignment is eligible for later academic
publication. Registration does not publish results, select an attempt, assign
work to an Academic Period, calculate proficiency, or create a Grade.

## Identity and eligibility

The complete identity is
`ModuleWorkRef(module_id="scoreform", class_id=<class_id>,
work_id=<assignment_id>)`. Only an existing canonical work root at
`classes/<class_id>/modules/scoreform/work/<assignment_id>/` with a regular,
nonsymlink, valid `assignment.json` is eligible. The file's `assignment_id` must
equal the work-directory identity. Arbitrary paths, generic blank sheets, and
route-free answer-key files are not eligible. Registration never creates a
producer work root and roster data is not registration identity.

## ScoreForm contract mapping

The fixed producer contract is `scoreform_academic_work_v1`; the fixed work kind
is `assignment`. The title is always read from the current validated canonical
assignment. The request contains exactly one unversioned source record:

```text
ModuleRecordRef(
    module_id="scoreform",
    record_kind="assignment",
    record_id=<assignment_id>,
    contract_version=None,
)
```

The source record is unversioned because ScoreForm's active native assignment
JSON is unversioned. Registration does not change that JSON contract or embed
intent, lifecycle, registry identity, revision, or timestamps in it.

Academic intent must be selected explicitly from `formative`, `summative`,
`diagnostic`, `practice`, `feedback_only`, and `reporting_only`. Lifecycle must
be selected explicitly from `planned`, `active`, `closed`, and `cancelled`.
Neither value is inferred from assignment content, dates, results, generation,
scanning, or publication state.

## Core-owned persistence

ScoreForm calls Core's `register_academic_work` for initial registration and
exact replay, and `update_academic_work_registration` for an explicit update.
Core owns serialization, locking, revision allocation, timestamps, immutable
revision files, and the explicit `current.json` selection beneath
`registry/work/<class_id>/scoreform/<assignment_id>/`.

An initial request creates revision 1. An exact replay returns `existing` and
changes no bytes. Different metadata supplied to initial registration conflicts
and must use update. Updates require an explicit positive
`expected_current_revision`; a matching change returns `updated` with the next
revision, while an exact request may return `existing`. Stale and future
expectations fail closed. Core's current pointer is authoritative.

If Core reports partial success, ScoreForm preserves the durable state and
reports the operation, known registration revision, canonical path, and current
selection status. It neither deletes state nor retries with a guessed revision.

## User workflows and exclusions

Direct commands are `scoreform academic-work show`, `register`, and `update`.
Assignment Management also provides **Academic Work Registration**, displaying
the assignment and current registration, collecting explicit intent and
lifecycle values, showing the proposed request, and requiring typed `REGISTER`
or `UPDATE` confirmation.

Assignment title edits remain producer-native. If a registered title snapshot
becomes stale, the edit succeeds and ScoreForm prints a notice directing the
teacher to the explicit update workflow. Answer-key and standards edits alone
do not require a registration revision.

Setup, creation, editing, generation, regeneration, QR decoding, PDS2 scoring,
manual answer-key scoring, plain-paper entry, scan-review resolution, result
viewing, discovery, import, help, and version display never create or update
registration. Generic blank sheets and arbitrary route-free manual work cannot
be registered.

## Later publication boundary

A future Publication Record must reference the exact current registration
revision. A stale revision and a cancelled current registration cannot be used
for publication; a closed registration remains canonical history. Registration
itself creates neither a publication nor Grade membership. Manifest generation
is a separate explicit operation implemented by #165 and does not require or
update registration. Producer-profile advertisement is owned by #166;
publication, supersession, and withdrawal are owned by #167.
