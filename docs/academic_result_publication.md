# Academic Result Publication

ScoreForm publication is always explicit. An immutable producer manifest is not
discoverable through the Core registry until a teacher invokes the publication
CLI or the **Academic Result Publications** assignment menu.

ScoreForm publishes exactly one series per managed assignment:

- kind `academic_result_set`;
- record-set ID `academic_results`;
- contract `scoreform_academic_result_manifest_v1`;
- capabilities `multiple_attempts`, `points`, and `question_evidence`;
- no source record.

The selected manifest must be the producer head and publication requires the
exact current, noncancelled Academic Work Registration revision. Initial publish
and exact replay use Core's first-publication service. Supersession requires the
caller's exact expected canonical head and validates the producer manifest
transition before Core creates the new record. A withdrawn head remains the
predecessor; it is never deleted and no earlier publication is restored.
The transition is bound by a validated `PublicationSupersessionRequirement`:
exact expected Core-head ID, publication kind, record-set ID, predecessor
revision, and successor revision. The validated expected ID is passed unchanged
to Core's supersession service. The head is derived from the complete validated
series and predecessor relationships, not only from Core's current-selectable
query, so a withdrawn head remains visible.

Republication after withdrawal is a separate explicit operation. It creates one
greater producer revision for unchanged native state or reuses an already durable
unpublished successor, then asks Core to supersede the withdrawn head. Retries do
not allocate repeated manifest revisions.

Withdrawal targets one exact publication ID and delegates creation of the
separate immutable withdrawal record to Core. ScoreForm never rewrites the
publication, its manifest, or native assignment/results files. Withdrawal reason
text is accepted by write workflows but is not echoed by the CLI or menu.

Every successful or exactly replayed write reloads canonical state, validates the
complete series, verifies the exact manifest through Core, loads the referenced
registration revision, evaluates the installed producer profile, rebuilds the
full Core catalog, and compares the exact catalog row with canonical state.
Catalog or post-write verification failures are partial success: durable state is
not rolled back, and the exact operation can be replayed to reconcile it.

The frozen, slotted status result distinguishes producer head, Core chain head,
Core-head withdrawal, current selectable publication, and derived-catalog state.
Partial-success results separately report whether canonical state is uncertain
or confirmed and whether catalog rebuild, replacement, and verification occurred.
Original Core exceptions remain available through exception chaining.

Read-only `status`, `list`, and `show` do not build a missing catalog. The direct
commands are available under `scoreform publication`; run
`scoreform publication help` for their exact grammar.
