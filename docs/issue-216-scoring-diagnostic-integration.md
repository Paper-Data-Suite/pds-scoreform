# Issue #216 Slice 2 — OMR Diagnostic Persistence Integration

Slice 2 wires the bounded diagnostic-artifact service from Slice 1 into the
existing `score_image()` OMR path without changing the authority relationship
between scoring and diagnostics yet.

## Scope

This slice changes the persistence mechanism for the two scoring diagnostics:

- registration-mark visualization (`registration_marks`); and
- warped-page visualization (`warped_page`).

Both now use `write_png_diagnostic_artifact()` rather than `cv2.imwrite()`.
OpenCV remains responsible for PNG encoding through `cv2.imencode()` inside the
Slice 1 service; Python-owned exclusive-create I/O remains responsible for
filesystem persistence.

## Routed identity

`score_authoritative_answer_sheet_page()` passes only the canonical retained
source SHA-256, source page number, and immutable answer-sheet page ID into the
diagnostic writer. `source_scan_id` and the former concatenated
`diagnostic_stem` no longer participate in the filesystem leaf name.

The resulting names remain bounded and opaque, for example:

```text
sfdiag_corners_<opaque-token>.png
sfdiag_warped_<opaque-token>.png
```

The complete route/source/page provenance continues to live in authoritative
ScoreForm/Core records rather than being duplicated into diagnostic filenames.

## Manual / legacy call compatibility

The `diagnostic_stem` keyword remains accepted by `score_image()` so existing
direct callers do not break, but it is no longer a filename authority and is
intentionally ignored for persistence naming.

When a non-routed caller does not supply canonical source identity, ScoreForm
uses a collision-safe random internal source token for that one scoring call and
a fixed non-classroom page context. It does not hash answer marks or encode the
legacy stem into the filename.

## Failure semantics deliberately unchanged in Slice 2

This slice does **not** yet make scoring diagnostics fail-soft.

To isolate the persistence migration from the authority change:

- registration diagnostic persistence failure still raises the existing
  `diagnostic_write_failed` page-scoring failure when strict scoring is enabled;
- warped diagnostic persistence failure retains its existing default
  `page_scoring_error` classification; and
- successful prior diagnostic evidence remains attached to a later strict
  scoring failure.

Slice 3 can therefore change diagnostic persistence from authoritative failure
to subordinate warning without simultaneously changing filename/storage
mechanics.

## Qualification focus

Slice 2 tests prove that:

- `score_image()` no longer depends on `cv2.imwrite()` for its two OMR images;
- filenames are bounded and opaque at the live scoring call site;
- a very long legacy `diagnostic_stem` cannot expand the filesystem leaf;
- routed scoring supplies retained source SHA-256 and authoritative page ID to
  the new boundary; and
- existing strict failure codes are preserved for this migration slice.
