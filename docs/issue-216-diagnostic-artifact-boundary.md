# Issue #216: Diagnostic Artifact Boundary

Slice 1 establishes a ScoreForm-owned persistence boundary for optional page-scoring diagnostic images. It is intentionally additive: this slice does **not** yet route `score_image()` through the new writer, so current scoring behavior remains unchanged until the behavioral migration slice.

## Contract

`scoreform.diagnostic_artifacts` owns four concerns that were previously entangled with OMR code:

1. deterministic opaque diagnostic filenames;
2. PNG encoding through OpenCV's in-memory encoder;
3. create-only filesystem persistence through Python-owned I/O; and
4. bounded structured write outcomes that do not require propagating an operational diagnostic failure.

The supported initial kinds are:

```text
registration_marks
warped_page
```

The artifact filename is derived from a SHA-256 digest over a versioned canonical tuple containing the diagnostic kind, retained-source SHA-256, retained-source page number, and answer-sheet page ID. Only a fixed 20-hex-character digest prefix is retained in the leaf name.

Representative names are:

```text
sfdiag_corners_<20 hex>.png
sfdiag_warped_<20 hex>.png
```

Create-only collision candidates append a bounded two-digit suffix. The public `MAX_DIAGNOSTIC_FILENAME_LENGTH` constant defines the leaf-name budget and is independent of source filename, class ID, assignment ID, route ID, issuance ID, source-scan ID, page ID length, and workspace depth.

## Persistence semantics

The writer:

- encodes with `cv2.imencode(".png", ...)` rather than `cv2.imwrite(...)`;
- creates the authorized diagnostic root if needed, while rejecting a symlinked or non-directory root;
- resolves the authorized root before opening a child;
- opens artifacts with exclusive-create binary mode (`xb`);
- flushes and `fsync`s successful writes;
- checks the opened descriptor is a regular file;
- never replaces an existing artifact;
- removes a partial artifact after a write failure where possible;
- verifies the completed path remains a regular, non-symlink file beneath the resolved diagnostic root; and
- bounds collision attempts rather than searching without limit.

## Failure model

Operational encoding and persistence problems return a `DiagnosticArtifactWriteResult` with a `DiagnosticArtifactWarning` instead of raising the underlying filesystem/OpenCV exception. The warning exposes only bounded technical state:

```text
code = diagnostic_artifact_write_failed
kind
stage
exception_type
```

It does not preserve arbitrary exception prose, raw paths, QR payloads, answers, scores, roster data, or tracebacks.

Programmer-contract errors (for example an invalid SHA-256 or non-positive source page number) still raise immediately. Those indicate misuse of the internal API rather than an optional artifact persistence failure.

## Ownership boundary

This subsystem does not make a page score authoritative and does not define scan-review behavior. The scoring layer remains responsible for preserving the primary OMR outcome, and the route handler remains responsible for validating any successful diagnostic evidence against the managed ScoreForm debug root.

The next behavioral slice can replace the identity-heavy `diagnostic_stem` / `cv2.imwrite` path in `score_image()` with this boundary and carry warnings separately from authoritative page results.
