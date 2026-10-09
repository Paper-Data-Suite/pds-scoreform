# Issue #225 — QR print and decode reliability: Slice 1 baseline

Status: **Slice 1 characterization; Slice 2 layout change documented below. Payload, routing, and decoder unchanged**.

## Confirmed current code paths

- `scoreform/templates.py`: `make_qr_image` uses Python `qrcode.QRCode(version=1, error_correction=ERROR_CORRECT_L, box_size=10, border=4)`, followed by `make(fit=True)`. `draw_qr_code` embeds the resulting bitmap using ReportLab `drawImage`, scaled to `layout.qr_size * layout.pdf_scale` in both dimensions.
- `scoreform/layouts.py`: both `standard_15q_abcd_v1` and `compact_25q_abcd_v1` set `qr_size=100` on 1275-pixel-wide template geometry. PDF width is 612 points, yielding **48 points / 0.667 inches including the quiet zone**.
- `scoreform/pds2_scan_dispatch.py`: `detect_qr_payload_text` attempts `cv2.QRCodeDetector().detectAndDecode` on candidates from `_qr_candidate_images` and retains existing QR failure diagnostics. `_decode_pages` subsequently parses and dispatches; preserve those boundaries in later slices.
- `pyproject.toml`: current version 0.12.1; `qrcode[pil]`, `opencv-python`, NumPy, ReportLab, PDF2Image; no independent ZXing decoder declared.
- `README.md`: PDS2 QR payload schema; PDS Core >=0.6.4,<0.7.

## Reproducible density measurement

`scoreform.qr_print_baseline.measure_qr_print_baseline(layout, payload)` reproduces the existing `qrcode` error-correction and border settings, and reports payload length, QR matrix width, overall module count, physical square size, and resulting module pitch. This function does **not** render, decode, validate, or persist a sheet.

Use sanitized representative payloads for automated tests. Do not commit classroom scans, student identifiers, or diagnostic crops to the repository.

## Real-world acceptance set

Retain the teacher-provided 29-page `MP1 Locke ScoreForm Check P4a.pdf` **outside the Git repository** as a local qualification artifact. Pages **4, 11, 25, and 28** were reported as ScoreForm failures. Only page 4 was reportedly readable by phone; the other three were not readable on either of two phones. These reports are observations, not proof of what any future decoder can recover.

A next slice should capture per-page baseline outcomes on the teacher's installed environment, with the original bytes retained, and only redacted/aggregate results committed. Do not change existing decoding or routing to inflate successes.

## Next decisions

1. Evaluate a larger QR square and required header reflow with collision tests, including the registration markers and first answer row.
2. Measure true module pitch for representative canonical PDS2 payloads and select an empirically qualified minimum.
3. Independently qualify ZXing-C++ packaging across supported Python/Windows architectures before adding the fallback.
4. Keep data contract changes for Core #229 and Meridian/Vitrine out of this issue's runtime modifications.


## Slice 2: enlarged QR square and guarded header layout

Slice 1 measured the historical **48 pt / 0.667 in** printed QR square, which
remains documented above. Slice 2 enlarges the active standard and compact
layouts to **145 template units = 69.6 pt / approximately 0.967 in** including
the existing four-module quiet zone. The top moves from y=220 to y=185 in
1275 x 1650 template coordinates. Assignment-title baseline remains at y=220
through an independent header-title anchor; student metadata and both full
printed identifiers stay in their established columns.

The header planner now rejects QR collisions with registration marks, the page
boundary and the first question region. Existing text/QR separation checks
remain active. New tests guard both layouts, printed identifiers, title
placement, intentionally invalid geometric variants, and complete containment of
the enlarged symbol in the preexisting ScoreForm tight QR crop.

**Not yet qualified:** module fidelity after raster resampling, printed error
correction, independent decoders, historical scan recovery, or real printer
performance. The current `qrcode` PNG renderer and PDS2 payload are unchanged;
these require later slices and physical acceptance. The characterization helper
now reports the *current* layout size, while this document preserves the
historical baseline.


## Slice 3: native vector QR rendering

The active `draw_qr_code` path now paints the canonical `qrcode` matrix as
native ReportLab/PDF vector rectangles rather than embedding and downscaling a
PNG. The complete matrix includes the four-module quiet zone. A white
background fills the complete geometry; black modules are grouped by horizontal
runs and painted as a single vector path, without strokes or interpolation.
Canvas state is saved/restored. The old `make_qr_image` helper remains available
for existing callers, but no longer participates in active PDF QR drawing.

The following remain unchanged: PDS2 payload serialization, route-validation
authority, QR error correction L, QR matrix construction, enlarged Slice 2
layout, and OpenCV scan detection. Vector drawing does not guarantee that
physically tiny modules will survive every printer/scanner; that determination
requires real paper qualification. Decoder fallback and review recovery remain
future slices.

Tests verify PDF image-free vector output, exact module/run placement and
quiet-zone geometry, state restoration, both active layouts, and rejection of
invalid dimensions. Test fixtures use synthetic PDS2 text only.

## Slice 4 — Independent ZXing-C++ adapter (isolated)

This slice adds `scoreform.qr_zxing_fallback.decode_qr_with_zxing` as an independent QR-only decoding adapter. **Nothing invokes it in production yet.** The existing OpenCV attempts, diagnostic persistence, Core PDS2 parsing, route authority, and scan review behavior remain unchanged.

- Lazy, optional `zxingcpp` import. An absent package or native-library load failure returns `unavailable`; native decoder exceptions return `decoder_error`.
- One native `read_barcodes` call per adapter invocation, QR format only, on a nonempty uint8 grayscale or BGR array. Inputs are limited to 5000 pixels per side and 12 million pixels total. At most eight barcode results and 4096 characters per candidate are accepted.
- Distinct decoded text candidates are returned unchanged and in discovery order. The adapter intentionally does not parse PDS2 or choose between multiple identities. Conflict handling belongs to the later orchestration/validation slice.
- An optional `qr-zxing` installation extra declares `zxing-cpp>=3.1.1,<4`. The base ScoreForm installation continues without it, including unsupported native environments. This is **not** evidence that installed-wheel qualification has been completed.
- ZXing-C++ 3.1.1 provides published Windows AMD64 and ARM64 wheels for supported CPython versions on PyPI (check exact interpreter and Windows architecture during installed qualification). Source builds may require a compiler.
- Native calls are input-sized and invocation-count bounded; they are not a hard CPU-time sandbox. The later orchestration slice must strictly cap the number of adapter invocations.

Focused unit tests use a fake backend, with an additional real ZXing round-trip test that runs when `zxing-cpp` is installed. No classroom scans or student identifiers are committed.

**Next slice:** inspect the primary pipeline's attempt ordering, add fallback only after primary failure, and enforce canonical parsing, identity ambiguity handling, and bounded escalation. Do not make a failed native decoder a fatal batch error.

## Slice 5 — Bounded ZXing recovery after OpenCV

- `scoreform/qr_zxing_recovery.py` is an additive, bounded recovery orchestrator. It uses the existing ScoreForm QR crop positions (compatible with both historic and enlarged symbols), a nearest-neighbor tight-crop enlargement, an Otsu variant, a broad crop, and the full source image when input limits permit. At most five native decoder invocations and 16 million candidate pixels are consumed per page; the Slice 4 adapter also bounds any individual candidate.
- `scoreform/pds2_scan_dispatch.py` now tries this recovery **only after all existing OpenCV attempts return no QR text**. Existing OpenCV successes preserve their exact output and bypass ZXing. Optional ZXing unavailability, decoder errors, or exhausted attempts retain the original unresolved/review behavior.
- One unique recovered raw text is labeled `zxing-cpp:<candidate>` and passed through the same `parse_pds2_payload`, `RouteDispatchRequest`, and Core dispatch logic as an OpenCV result. No fallback result establishes an identity by itself.
- Multiple distinct raw payloads from ZXing, including conflicting results across candidate images, fail closed as an unreadable QR. No payload text is emitted in the error message. Normal bounded diagnostic handling remains in place.
- `tests/test_issue225_qr_zxing_recovery.py` covers bounds, single/duplicate/conflicting payload behavior, absent backend, OpenCV-first ordering, fail-soft behavior, and canonical PDS2 parsing.
- No QR encoding changes, manifest changes, cross-suite contract changes, or release/version bump are introduced. Physical scan qualification and ARM64 installed acceptance remain future work.

## Slice 6 — Local real-scan qualification (no routing or grading)

`scoreform.qr_scan_qualification` and `scripts/qualify_issue225_qr_scans.py` produce a **sanitized QR/PDS2 qualification report**, using the existing ScoreForm retained-page loader, OpenCV-first detection and ZXing fallback, and the canonical Core PDS2 parser. **This is not a Core route-registration check, student-identity verification, answer scoring, publication, or installation acceptance.** The report deliberately records no decoded payloads, class/work/route/student IDs, source names, source paths, original-image hashes, crops, or scanner exception strings. It contains page numbers, image dimensions, decoder family, and terminal parsing status only.

The harness uses Core retention in a newly created `tempfile.TemporaryDirectory` and therefore **temporarily copies the source scan**, which is removed on ordinary completion along with diagnostic images. Avoid placing confidential scans in an untrusted temp location; abrupt process termination can leave residual temporary files. No student scan should be added to Git. Existing diagnostics from the scan path are confined to that temporary directory. The teacher's normal OneDrive workspace is never used; the harness does not register or dispatch routes.

For the original 29-page Locke PDF, run first against known failing pages, then against the complete file. Run from an editable ScoreForm development environment with Poppler and `zxing-cpp` installed (the optional `qr-zxing` extra). Update the example source path to the actual local file location:

```powershell
python scripts/qualify_issue225_qr_scans.py `
  "$HOME\Downloads\MP1 Locke ScoreForm Check P4a.pdf" `
  --pages 4,11,25,28 `
  --output "$HOME\Downloads\issue225_locke_focus_qualification.json"

python scripts/qualify_issue225_qr_scans.py `
  "$HOME\Downloads\MP1 Locke ScoreForm Check P4a.pdf" `
  --output "$HOME\Downloads\issue225_locke_full_qualification.json"
```

The JSON output uses **create-only** semantics and will not overwrite a previous run. Check that it contains no identifying information before distributing it. A positive `valid_pds2` outcome means only that ScoreForm decoded text and the Core grammar accepted a locator; it does **not** prove a registration exists, that a record maps to a particular student, or that the answers can be graded. A previously unreadable sheet may remain unresolved if print information was destroyed. Real-world outcomes must be collected, not fabricated as test fixtures. A separate physical print-to-scan qualification is still required for the improved vector QR generator.

### Slice 6 Fix 1 — Suppress temporary qualification diagnostics on stdout

The local qualification harness discards nested scanner-internal stdout
messages, which previously included temporary diagnostic directory paths.
The optional diagnostic images remain inside the disposable qualification
workspace and are cleaned with it; no production scan behavior changes.
Sanitized per-page progress and create-only JSON output remain visible.

### Slice 7 — Teacher-supervised registered-route recovery preflight (read-only)

The revised Issue #225 requires actual recovery of an already-retained failed
physical page, following Quillan #419's separation between a recorded route
decision and verified operational recovery. The existing ScoreForm actions
`route_selected` and `route_corrected` currently append review decisions; they
do **not** re-dispatch the page or produce an assembled durable result.

Slice 7 introduces `prepare_scoreform_scan_recovery` as a strictly read-only
boundary. It discovers even historically resolved ScoreForm failures, requires
an original physical page and Core-retained provenance, reconstructs the
original retention event **without calling `retain_source_scan`**, verifies
canonical containment, symlink/junction restrictions, full source SHA-256 and
page count, and validates a teacher-selected or explicitly reused prior route
against Core registration and the immutable issued ScoreForm answer-sheet page.
Recorded route decisions are rechecked against full page authority. Changing
an observed route requires explicit correction intent. An unresolved QR alone
is never treated as authority for a student's identity.

The returned preview is not a capability token and is **not** recovery evidence.
Future execution must revalidate it and invoke Core dispatch on the original
source page; then ScoreForm must score, assemble all required issuance pages,
write/verify the canonical result, and only then acknowledge completed recovery.
Partial issuance, duplicate evidence and historical metadata-only resolutions
require explicit truthful state handling. No writer, menu, CLI, grading or
production scanning behavior is changed in Slice 7.

The original 29-page classroom assessment qualified in Slice 6 yielded 24
OpenCV valid PDS2 pages, two ZXing-C++ valid PDS2 pages (4 and 20), and three
unreadable pages (11, 25 and 28). This does not establish a decoder defect:
printing damage is a plausible remaining cause. New printed-sheet physical
qualification remains outstanding. The independent plain-paper manual-entry
path remains available.

### Slice 8 — Authoritative retained-page recovery dispatch (Issue #225)

The Slice 7 read-only `PreparedScoreFormScanRecovery` preview can be passed to
`dispatch_prepared_scoreform_scan_recovery` in
`scoreform/qr_scan_recovery_dispatch.py`.

- Re-run the full original-source SHA-256, physical-page, historical-resolution,
  issued-page, and registered-route preflight immediately before any dispatch.
  A stale or fabricated preview is rejected without dispatch.
- Build Core's canonical `RouteDispatchRequest` with the *original* retained
  source and physical page. Call Core `dispatch_route`; do not decode QR again,
  call `retain_source_scan` again, or fabricate a QR payload.
- Invoke the existing ScoreForm module handler through Core. Verify Core's
  exact registered target/profile/request relationship, the returned strict
  `ScoreFormPageDispatchResult`, every authoritative page identity and source
  provenance field, and diagnostic-path authorization. Re-preflight after the
  synchronous dispatch to detect concurrent source or route changes.
- Support explicit teacher-confirmed route correction and previously resolved
  route_selected/route_corrected history by reusing the Slice 7 authority.
- The returned `DispatchedScoreFormScanRecovery` contains one scored physical
  page only. **It is not a completed recovery, grading result, or durable student
  attempt.** This slice deliberately does not assemble other pages, append
  `results.csv`, write Core scan-resolution metadata, or update menu/CLI state.
- ScoreForm's existing page-scoring diagnostics may still be generated by its
  production route handler; those are subordinate to established path, privacy,
  and fail-soft contracts. Do not characterize dispatch as universally read-only.
- Subsequent slices must assemble all authoritative issuance pages (including
  preexisting attempts if permitted by canonical policies), safely persist
  results through the shared v2 writer, reconcile historical metadata-only
  resolutions, and implement explicit teacher-facing menu/CLI confirmation.

Focused test coverage uses Core's real dispatch and ScoreForm route handler with
synthetic retained input and only optical mark-recognition substituted in tests;
it also rejects altered preview/source/issuance/route/result identities. Source
and installed-wheel acceptance remain separate release gates.

### Slice 9 — Read-only recovery-aware complete-attempt assembly (Issue #225)

`scoreform/qr_scan_recovery_assembly.py` adds
`prepare_scoreform_recovery_assembly(workspace_root, recovered_pages, *, original_batch=None)`.
This is a *non-persistent assessment*, not a recovery completion or a write
authorization. An eventual writer **must repeat** preflight, scoring provenance,
assembly, and results-history checks immediately before appending a result.

The service accepts one or more Slice 8 `DispatchedScoreFormScanRecovery`
values for **one issuance and one exact retained source**, optionally combined
with Core-verified ScoreForm successes from the corresponding original
`Pds2ScanDispatchResult`. The original batch must cover every physical source
page and must refer to the same retained source; failed QR pages provide no
identity candidate and are never fabricated into successes. The teacher's
registered route is the authority for each recovered page.

The assembly check revalidates the recovered preflights, routes, ScoreForm
registrations, currently issued page records, full question coverage and
original source provenance. It reuses `ScoreFormRoutedResult`,
`ScoreFormPageObservation`, and `ScoreFormAssembledAttempt` without weakening
any of their identity or completeness contracts.

The read-only plan has four explicit outcomes:

- `needs_pages`: one or more required logical pages remain absent; no incomplete
  student result may be generated.
- `review_required`: duplicate/conflicting pages or existing results need an
  explicit teacher decision; no result is supplied for persistence.
- `ready_to_persist`: a canonical complete attempt is available, **not saved**.
- `already_persisted`: a semantically equivalent result already exists under
  the same source SHA-256 and issuance ID; do not create another attempt.

Managed `results.csv` is read using ScoreForm's existing strict history reader.
A previously saved different result for the same source and issuance, a result
from another source for the same issuance, or a relevant manual-result history
is not silently superseded. Any existing conflicting result requires review.

**Compatibility boundary:** current `pds2_scan` result rows describe one source
scan. Combining pages from *different* source retention events would require
additional explicit provenance and result-contract design. This slice rejects
such combinations instead of misattributing them to one source.

**No writes** are made by the Slice 9 assembly service to retained scans,
scan-review records, `results.csv`, routing registrations, answer-sheet records,
or result history. The existing Slice 8 dispatch still performs page scoring
and may emit its already-authorized diagnostics; assembly does not repeat
scoring. No menu/CLI surface, release version, or Core consumer contract changes.

Qualification covers single-page, two-page incomplete/complete attempts,
recovered-plus-original-batch siblings, previously selected routes, duplicate
physical pages, changed scans, forged page identities, cross-source rejection,
and existing-history idempotency. Synthetic classroom-independent fixtures only.

### Slice 10 — Guarded persistence of complete recovered attempts (Issue #225)

`scoreform/qr_scan_recovery_persistence.py` adds
`persist_scoreform_recovery_attempt(root, approved_plan, recovered_pages, *, original_batch=None)`.
It accepts a teacher-reviewed **Slice 9 complete** preview and the original
Slice 8 dispatch evidence. It is a bounded result writer, **not** an automatic
scan-review resolution. No menu, CLI, Core resolution, or new persistence
schema is introduced in this slice.

Before any write, the service recomputes the full Slice 9 assembly from the
original retained source, Core-registered pages, existing routed scoring output,
and current schema-v2 `results.csv`. Incomplete or conflicting plans do not
write. An outdated plan is rejected; one deliberate exception allows an approved
`ready_to_persist` preview to become `already_persisted` when the **identical**
result has since been saved (e.g. safe retry after interrupted completion).
An already-persisted preview never authorizes recreating a missing result.

A new complete result is sent **only** to the existing
`export_scoreform_result_models` managed schema-v2 writer. The service does not
invent a QR payload, manually edit CSV, or create a replacement attempt. It
requires a single writer confirmation, rereads the managed history to verify
exactly one equivalent issuance result, and reruns recovery assembly after
writing. It returns `appended` or `already_present` with the canonical results
path and attempt number only after the stored record is verified. Existing
manual results, different or duplicate issuance results, or inconsistent
provenance require review, not silent replacement.

Because the underlying writer may have saved its row before reporting a
failure, errors occurring after the writer is invoked are classified
`ScoreFormRecoveryPersistenceUncertainError`. The exception includes
`row_verified` (`True`, `False`, or unknown) and `attempt_number` when a
best-effort read can prove an equivalent row. An unknown or unverified outcome
must **never** be represented as a completed recovery. Retrying always begins
with a new read-only preflight/assembly/history check; already-saved equivalent
attempts are reused rather than appended again. The existing schema-v2 writer
provides its own staging and collision semantics; this slice does not claim a
new cross-process transaction lock or guarantee concurrent writers serialize.

Even after the saved student score is verified, the original scan-review
failure is **not** closed and historical route-resolution records remain
untouched. Teacher-facing preview, confirmation, workflow completion, and
interruption-resumption semantics are separate subsequent slices. This slice
supports only pages from one Core-retained source as established by Slice 9;
cross-scan assembly awaits a distinct provenance contract.

### Slice 11 — Durable read-only recovery completion verification (Issue #225)

`scoreform/qr_scan_recovery_completion.py` introduces
`inspect_scoreform_recovery_completion(root, failure_id)` for a restart-safe,
**read-only** answer to whether an original failed physical page has a
verified, completed ScoreForm attempt. A selected registered route is a teacher
decision, **not** score materialization. A saved score alone is **not** proof
that a teacher authorized reassociation of an unreadable physical QR.

The reader requires a currently reusable Core `route_selected` or
`route_corrected` resolution, redoes Slice 7's full retained-source SHA-256,
physical-page, issued-page and registration validation, and reads managed
schema-v2 result history. It requires exactly one result for the issuance,
with matching source scan and SHA-256, immutable student identity, complete
issued-page and route sequence, exact logical-to-physical page mapping, and
current valid Core registrations for **every** page in the result. The result
must use the same retained source for all issued pages. No QR guessing,
manual-result promotion, arbitrary result adoption, partial attempt, or
cross-retained-scan provenance combination is permitted.

Four explicit states: `route_selection_needed` (no current teacher route
selection), `result_missing` (a route decision exists but no complete result),
`verified_complete` (both teacher authority and saved attempt proved), and
`review_required` (invalid/stale sources or routes, contradictory history,
manual-result overlap or competing latest teacher decision). These states
are **derived** from authoritative records rather than a second durable
completion ledger. Inspection may be safely repeated after process restart,
and is not a lock against subsequent changes.

`confirm_scoreform_recovery_completion(root, persisted, recovered_pages, *,
original_batch=None)` additionally accepts a Slice 10 result receipt and the
original Slice 8 page evidence. It rechecks Slice 9 assembly against managed
history and returns per-failure completion statuses. A stored result without
an already-recorded teacher route decision remains `route_selection_needed`;
it is never silently promoted to a successful recovered route. Mismatched or
stale receipts fail closed. This operation does not rescore, write a result,
append Core metadata, or create a completion file.

Core scan-resolution metadata is intentionally left untouched: its current
schema does not define a result-verified recovery-completion action, and an
automatic generic `other` resolution would hide the last teacher route
decision from historical recovery preflight. Later menu/CLI integration must
make teacher route selection an explicit step, verify the persisted result,
and display the derived completion state separately from Core review status.
If an existing manual result already represents the student's response, the
existing manual workflow remains a separate fallback requiring teacher
reconciliation. No release, Core schema, scoring, or scanner changes here.

### Slice 12 — Explicit teacher-confirmed ScoreForm recovery workflow (Issue #225)

`scoreform/qr_scan_recovery_workflow.py` coordinates the **existing** Slice 7–11
services without introducing a second scan decoder, result format, or mutable
completion flag. This is a callable workflow seam for the later teacher menu
and CLI; **no interactive menu, CLI wiring, new release, or Core API change** is
part of Slice 12.

`preview_scoreform_recovery_workflow(root, selections)` is read-only. Each
`ScoreFormRecoveryRouteSelection` contains an explicit teacher-selected Core
`RouteLocator` (optionally checked against an exact Core target), or an explicit
`use_recorded_route=True` choice. It reuses existing Slice 7 provenance and
issuance checks. All selected physical pages must come from **one original
retained scan and one issued student attempt**, with unique failure IDs and
physical page numbers. The preview names decisions that would need appending;
it is not itself a token authorizing a write. A different historical route
cannot be replaced unless `allow_route_correction=True`; a final non-route
teacher decision (e.g., manual recovery or rescan needed) cannot be silently
overridden. Deferred decisions require a fresh explicit selection, not
implicit recorded-route reuse.

`execute_approved_scoreform_recovery_workflow(root, preview,
*, teacher_confirmed=True, original_batch=None, registry=None)` refuses
execution without an **exact current preview** and the explicit confirmation
flag. Before writing anything it recreates and compares the entire preview.
It then reuses identical validated historical route decisions rather than
appending duplicate events. A newly approved route goes through the existing
`resolve_scan_review_item` entry point using the registered PDS2 locator;
changing a historical route uses `route_corrected`. Every selected decision is
then validated again using Slice 7's **recorded** route path before Core page
dispatch. Route selection is a teacher decision, **not** a recorded result.

The workflow checks Slice 11 completion before rescoring: a restart/retry with
all linked failures already verified returns `already_complete` without calling
the optical scorer or appending a result. If there is an unreconciled saved
result, it returns `review_required` rather than writing another score.
Otherwise it dispatches the original retained physical pages via Slice 8,
assembles via Slice 9, and persists via Slice 10 **only when all issued pages
are present and consistent**. A missing page returns `needs_pages` with its
logical-page numbers and writes no partial result. A conflicting assembly
returns `review_required`; neither result implies recovery completion. A saved
complete attempt is reread through Slice 11; `verified_complete` is reported
only when every linked failed page has a current valid teacher route and an
identical complete managed schema-v2 attempt. Core resolution history remains
append-only and no synthetic completion resolution is added.

Execution may leave a **durable route decision** even when later optical
scoring, attempt assembly, or result persistence fails. Stage-qualified
`ScoreFormRecoveryWorkflowError` states which operation stopped; failed
persistence remains uncertain unless the result history confirms the write.
After an interrupted operation, reopen a **new** preview and retry; do not
reuse a stale approval or assume that a route decision implies grading.
Only ScoreForm's schema-v2 result writer may persist the completed attempt.
A previous equivalent result is reused; no duplicate teacher decision,
partial score, or extra attempt is intentionally produced. This coordinator
does not claim cross-process writer locking or permission to combine scans
from distinct retained sources. Subsequent slices will add explicit teacher
menu/CLI selection, confirmation, and installed end-to-end qualification.

Synthetic qualification covers read-only preview, confirmation boundaries,
new and historical route decisions, idempotent restart with no rescoring,
incomplete and subsequently completed two-page attempts, stale previews,
retained-source changes, final manual decisions, interrupted dispatch,
failed result persistence, invalid batch evidence, and saved-score-before-route
reconciliation. No student materials are part of the fixtures.
