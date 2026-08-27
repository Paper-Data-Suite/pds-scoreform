# Security Policy

## Project Status and Supported Environment

ScoreForm is a pre-1.0, local-first classroom OMR and assessment-evidence tool
for Paper Data Suite. It is designed for teacher-controlled local use and is not
designed as a hosted service.

The v0.11 release line supports:

- Python 3.11 or newer; and
- `pds-core>=0.6.2,<0.7`.

Pre-1.0 support does not imply long-term support or permanent compatibility for
older development versions. Unless a release says otherwise, security and
maintenance fixes target the current supported release line.

ScoreForm depends on PDS Core for shared workspace, source-retention, routing,
Academic Work Registration, publication, and module-operation contracts.
Security behavior therefore depends on both the ScoreForm and compatible Core
versions actually installed.

## Reporting Security, Privacy, or Data-Safety Concerns

Use GitHub Issues only for concerns that can be described without sensitive
information.

Do **not** put any of the following in a public issue, pull request, discussion,
CI log, screenshot, or attachment:

- real student names, IDs, rosters, responses, scores, grades, or writing;
- scans or photographs of real student work;
- generated classroom sheets or packets containing real student information;
- retained source scans or scan-review evidence from real classroom use;
- result files, manifests, publication records, or diagnostic records tied to
  real classroom work;
- private school or district documents;
- filesystem paths or screenshots that expose private user or school
  information when that information is not necessary;
- passwords, access tokens, API keys, credentials, secrets, or private
  configuration.

If a concern requires sensitive details, describe the problem only in general
terms and request a private follow-up channel. Do not publish the sensitive
material first and attempt to redact it later.

When reporting a non-sensitive concern, include the affected ScoreForm and Core
versions, operating system, relevant command or workflow, expected behavior,
actual behavior, and a minimal synthetic reproduction when possible.

## Security Model and Trust Boundaries

ScoreForm assumes the teacher's operating-system account and local filesystem
are part of the trusted environment.

ScoreForm does not replace:

- operating-system account security;
- filesystem permissions;
- device encryption;
- endpoint protection;
- approved backup or sync controls;
- physical security for printed classroom materials; or
- school or district access-control and retention policies.

Anyone who can read the Paper Data Suite workspace may be able to read sensitive
student or classroom records stored there. Protect the workspace and its
backups accordingly.

Repository ignore rules reduce accidental commits but are **not** a privacy or
security boundary.

PDS2 locators, route IDs, issuance IDs, page IDs, artifact IDs, work IDs,
publication IDs, and similar workflow identifiers are identity/routing
mechanisms, not a substitute for filesystem authorization or user
authentication.

## Student Data and Privacy

All repository examples, fixtures, tests, screenshots, logs, and documentation
samples must use synthetic data only.

Do not commit or publicly post:

- real student names or IDs;
- real rosters;
- real answer keys tied to confidential assessments when disclosure is
  prohibited;
- real student responses, writing, scores, or grades;
- real scanned student work;
- real generated answer sheets or class packets;
- real `results.csv` or other classroom result exports;
- real scan-review failures or resolutions;
- real Academic Work records, producer manifests, or publication evidence;
- real diagnostic output containing classroom identifiers or private paths;
- debug images produced from real scans;
- parent, guardian, or other private contact information;
- private school or district documents;
- local workspace folders or archived classroom workspaces;
- secrets, credentials, tokens, or private configuration.

Before committing a fixture, screenshot, image, PDF, log, diagnostic sample, or
generated file, inspect both visible content and metadata for copied classroom
data, private paths, identifying filenames, or embedded information.

Synthetic examples should use clearly fictional student, class, assignment, and
school identifiers.

Teachers and other users remain responsible for following applicable school,
district, state, and federal requirements when handling student information.

## Sensitive ScoreForm and Core Artifacts

A normal ScoreForm/PDS2 workflow can create or retain sensitive artifacts in
multiple places. Treat each of these as potentially sensitive even when a
particular file looks harmless:

- Core-retained source scans under the shared workspace;
- ScoreForm assignment definitions and standards alignments;
- personalized answer sheets and class packets;
- scanned answer sheets and assignment-local scan copies;
- routed result history and plain-paper manual results;
- immutable issuance, page, route, and attempt provenance;
- scan-review failure records;
- append-only scan-review resolutions;
- debug corner/warp or other diagnostic images;
- privacy-minimal diagnostic events;
- Academic Work Registration records;
- immutable ScoreForm academic-result manifests;
- Core Publication Records and catalog-derived views;
- exported PDFs, CSVs, JSON, screenshots, or troubleshooting bundles; and
- backups, synced copies, temporary copies, or archived workspaces containing
  any of the above.

"Privacy-minimal" does not mean "safe to publish without review." Diagnostics
are intentionally bounded, but users should still inspect them before sharing.

## Local-First Storage, Backups, and Retention

ScoreForm is intended to operate on a teacher-controlled Paper Data Suite
workspace. Keep real classroom workspaces outside the source repository.

If the workspace is stored in a synchronized or backed-up folder, the sync or
backup service becomes part of the data-handling environment. Use only
organization-approved storage and review its access, sharing, retention,
recovery, and account-security settings.

Core retains source scan evidence before ScoreForm routing/scoring. ScoreForm's
assignment-local scan-filing modes do not override that Core retention.
Deleting, moving, or filing an inbox copy therefore does not imply that every
retained or backed-up copy has been erased.

Scan-review records and their resolutions are append-only evidence. Academic
result manifests and publication history are also designed to preserve
historical evidence. Withdrawal, supersession, dismissal, or workflow recovery
must not be interpreted as guaranteed physical deletion of every historical
record.

Users who require deletion or retention schedules must apply those policies to
the complete workspace, retained evidence, exports, backups, and synchronized
copies according to their organization's requirements.

## Printed Materials and Physical Scan Security

Generated answer sheets and class packets may contain identifiable classroom
information and operational PDS2 locators. Protect printed materials before,
during, and after classroom use.

Do not assume that a QR code or PDS2 locator is an authorization mechanism.
Routing identity is resolved against authoritative Core and ScoreForm records;
access to the underlying workspace is controlled by the local environment.

Dispose of unwanted printed materials according to applicable school or
district policy rather than treating them as ordinary public paper.

Scanners, scan software, printer queues, OS preview caches, temporary folders,
and cloud-connected device software may create additional copies outside the
ScoreForm workspace. Users are responsible for configuring those systems
appropriately for student data.

## Scoring Integrity and Manual Verification

OMR scoring depends on physical printing, mark placement, scanning, image
quality, registration-mark detection, and interpretation of blank or ambiguous
responses.

ScoreForm therefore requires teacher verification before results are recorded
as grades or otherwise used for consequential decisions.

Manual verification remains especially important for:

- physical scan quality and page geometry;
- detected marks, blanks, and ambiguous responses;
- missing, duplicated, conflicting, or mixed pages;
- repeated attempts and duplicate-byte handling;
- scan-review recovery or manual-resolution decisions;
- plain-paper manual entry;
- assignment key or standards-alignment changes; and
- deciding what evidence should ultimately be used outside ScoreForm.

ScoreForm preserves attempts; it does not select the latest, highest, best,
official, or Grade-bearing attempt.

ScoreForm does not calculate proficiency, mastery, or a course Grade. Those are
downstream policy decisions.

## Core, ScoreForm, and Meridian Boundaries

PDS Core owns shared infrastructure such as workspace identity, retained source
evidence, routing/dispatch, Academic Work Registration, Publication Records,
catalogs, and module-operations contracts.

ScoreForm owns its assessment definitions, generated physical identity,
scoring, attempt assembly, native result history, scan-review workflow,
producer manifests, and ScoreForm-local workflow composition.

ScoreForm may publish exact academic-result evidence through Core so that an
authorized downstream consumer such as Meridian can consume it. ScoreForm does
not invoke Meridian as part of its runtime workflow and does not make Meridian's
interpretive or grading decisions.

Meridian or another downstream consumer remains responsible for its own
evidence-eligibility, attempt-selection, proficiency/mastery, Grade,
reassessment/replacement, aggregation, and reporting policies.

Do not weaken these ownership boundaries as a workaround for access,
compatibility, or troubleshooting problems.

## Repository and Development Hygiene

Use synthetic data for all automated tests and public examples.

Before every commit or pull request:

1. review `git status`;
2. review staged diffs;
3. confirm that no workspace, scan, PDF, image, result, debug, or diagnostic
   artifact from real classroom use is staged;
4. confirm that no credentials, tokens, private configuration, or sensitive
   filesystem information is staged; and
5. remove generated build/test residue that is not intentionally part of the
   change.

Do not copy a real classroom workspace into the repository merely to reproduce
a bug. Build a synthetic reproduction instead.

Do not use real student data in CI. Public CI logs and artifacts must remain
safe to expose.

When adding troubleshooting output, prefer bounded identifiers and actionable
state over answer payloads, student records, raw QR payloads, raw scans,
tracebacks containing private paths, or complete workspace dumps.

## Dependencies and Release Artifacts

Dependencies should remain minimal and should be reviewed before updates are
merged. Security-relevant dependency updates should be evaluated promptly,
tested against the supported ScoreForm/Core environment, and documented when
they materially affect the release.

Do not assume an old checkout remains supported because it still runs locally.
Review the current release documentation and dependency constraints.

Use the project's documented GitHub Release artifacts and verification
procedures for release installations. Verify expected artifact identity and
hashes when the release process provides them. A filename alone is not proof
that a wheel, source distribution, or Core dependency is the artifact qualified
by the project.

ScoreForm must not gain runtime dependencies on sibling Paper Data Suite modules
as a shortcut around Core contracts.

## Suspected Exposure or Incident

If real student data, credentials, or private school information is accidentally
committed or posted publicly:

1. stop further sharing of the material;
2. remove public access when possible;
3. rotate exposed credentials or tokens immediately;
4. notify the appropriate school or district contact according to local policy;
5. preserve only the minimum non-sensitive information needed to understand and
   remediate the software issue; and
6. do not rely on a normal Git revert alone as proof that sensitive historical
   content is no longer retrievable.

Repository history, forks, caches, CI artifacts, backups, and synchronized
copies may retain previously exposed content. Follow the applicable incident
response and records-management process rather than assuming deletion from the
current working tree resolves the exposure.
