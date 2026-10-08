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
