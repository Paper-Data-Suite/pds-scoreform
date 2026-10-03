# Issue #219 Slice 5 — Core v0.6.4 compatibility migration

Slice 5 raises ScoreForm's active Core boundary to:

```text
pds-core>=0.6.4,<0.7
```

ScoreForm remains package version `0.11.0` during this slice. The later
Issue #219 release-preparation work promotes the package to `0.12.0`.

## Exact released reference

Active qualification uses the published GitHub Release wheel:

```text
pds_core-0.6.4-py3-none-any.whl
SHA-256: 48cea9317f2967bdc0f2d4c14349a56677c7c3f8211f0f33978ccb1a1c75859b
```

Core v0.6.4 was qualified from source commit:

```text
152d1c65064c4f8fe55249ff2ca3379d7c4d6ccb
```

## Why the floor changes

ScoreForm Issue #216 exposed a retained-source path-budget problem whose
shared fix belongs in Core. Core Issue #226 shipped that bounded retained
writer in v0.6.4 while preserving historical Core 0.6 paths and provenance.

The next ScoreForm release therefore specifically requires the Core v0.6.4
writer; advertising a `>=0.6.2` floor would claim support for Core versions
that do not provide the boundary this release depends on.

## Local release gate

`run_tests.ps1` no longer exports a sibling Core tag and builds a substitute
wheel.

If `PDS_CORE_WHEEL` is absent, it downloads the published v0.6.4 wheel.
Whether supplied or downloaded, the wheel must match the exact published
SHA-256 above before qualification continues.

A locally rebuilt, merely version-equivalent Core wheel therefore does not
satisfy this gate.

## CI and installed acceptance

Routine CI, Release Readiness, operations-wheel acceptance, Issue #216
installed acceptance, Share Results acceptance, and the combined installed
workflow all move to exact Core 0.6.4.

The operations-wheel matrix no longer qualifies Core 0.6.2: Core 0.6.4 is
now both the declared minimum and current reference endpoint.

## Workspace compatibility

No workspace migration is introduced. Existing retained scans, retained
paths, source-scan IDs, Scan Review records, routed results, assignments,
routes, publications, and diagnostic history are not renamed or rewritten.

## Historical evidence

Historical v0.11.0 release notes and the v0.11.0 release audit remain
unchanged where they truthfully record original qualification against Core
0.6.3.

## Deferred

This slice does not change ScoreForm to 0.12.0, create final v0.12 installed
reporting acceptance, make the physical carry-forward decision, build final
v0.12 artifacts, tag, or publish the release.
