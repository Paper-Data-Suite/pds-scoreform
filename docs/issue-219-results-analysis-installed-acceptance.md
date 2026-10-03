# Issue #219 Slice 6 — Installed Results Analysis acceptance

Slice 6 adds an isolated installed-wheel acceptance for the complete Results
Analysis surface introduced by Issue #217 and polished by Issue #219.

The runner is candidate-version-aware: it builds the current source tree,
reads the version from the built wheel, installs that wheel noneditably beside
exact released Core v0.6.4, runs `pip check`, and executes the verifier outside
the source checkout. This lets the same acceptance qualify the current 0.11.0
candidate and carry forward when the later release-preparation slice promotes
ScoreForm to 0.12.0.

The installed scenario proves the most-recent display-attempt basis is not a
best-attempt rule; preserved historical Student Detail remains available;
correct/incorrect/blank/ambiguous states and response distributions reconcile;
multi-Standard and unaligned counting remain descriptive; current assignment
alignment remains the Standard basis; and no proficiency or Grade inference is
introduced.

A synthetic Core Standards Library proves teacher-readable labels, inactive
labeling, durable-ID fallback for an unknown aligned Standard, current profile
ordering, and deterministic tail ordering. The library is changed after report
snapshot preparation so CSV, JSON, and PDF must all retain the projection
frozen into the snapshot.

Output custody proves zero-write planning, format-aware directory identity,
cross-format same-second coexistence, same-format create-only replay failure,
privacy-minimized directory names, rendered-format mismatch rejection, and
cleanup after a synthetic second-artifact write failure.

Local-open acceptance calls ScoreForm's real generated-output containment layer
while mocking only Core's final OS-open primitive. Automation therefore verifies
the exact created file/folder without launching a GUI.

Physical printer/scanner acceptance is explicitly `not_claimed`.

Slice 6 creates and locally qualifies the reusable gate. The later v0.12
release-preparation slice will wire this candidate-version-aware acceptance
into the final version-specific CI and Release Readiness surface.
