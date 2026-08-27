# ScoreForm v0.11.0

ScoreForm v0.11.0 is the teacher-workflow usability release built across issues
#182–#196. It keeps the exact PDS2 evidence, Academic Work, producer-manifest,
publication, and consumer-reader contracts established before this milestone
while reducing repetitive teacher setup, navigation, scan-recovery, and sharing
work.

## Highlights

- Safe assignment copying without copied result, scan, issuance, manifest, or
  publication history.
- Reusable setup presets containing non-student configuration only.
- Fast bulk answer-key and standards-alignment entry with normalization,
  validation, complete preview, and explicit atomic commit.
- Multi-class generation planning and execution with fresh physical identity for
  every artifact/issuance/page/route.
- Task-oriented Assignment Management plus session-scoped active/recent
  assignment context.
- Guided retained PDS2 scan processing that leads naturally to result review.
- Teacher-facing missing-page and scan-quality recovery with immutable failure
  evidence and append-only resolutions.
- Share Results with Meridian as one guided path through Core-owned Academic Work
  Registration, immutable ScoreForm manifests, first publication, and exact
  supersession. ScoreForm does not invoke Meridian.
- Privacy-minimal local diagnostics.
- Separate Core module-operations readiness and attention providers.
- Combined clean-wheel installed acceptance and owner-operated physical
  printer/scanner qualification.

## Release contract

```text
distribution:          scoreform
version:               0.11.0
Python:                 >=3.11
Core dependency:       pds-core>=0.6.2,<0.7
full Core reference:   0.6.3
module ID:              scoreform
Academic Work:         scoreform_academic_work_v1
publication kind:      academic_result_set
manifest contract:     scoreform_academic_result_manifest_v1
record set:            academic_results
capabilities:          points, question_evidence, multiple_attempts
attempt policy:        preserve all; select none
```

The v0.11.0 distribution-version change does not create a new producer schema or
reader contract.

## Authority boundaries

ScoreForm produces exact assessment evidence. It does not:

- select the latest, highest, best, official, or Grade-bearing attempt;
- infer proficiency or mastery from standards alignments;
- calculate a course Grade or gradebook policy;
- determine portfolio eligibility or Candidate selection;
- invoke Meridian as a runtime dependency;
- bypass Core-owned source retention, routing, Academic Work Registration, or
  Publication Records.

## Physical qualification

Issue #195 completed the project-owner physical workflow against the corrected
frozen candidate from commit
`a34a5524a66823d9072450aadf529c269f13c8db`.

That candidate still carried distribution metadata `0.10.0`; its exact wheel
SHA-256 was:

```text
13780dfff55428394baaab5deab76e340ae969fe7f96cb461ccc092df7e5679b
```

Issue #196 adds a deterministic metadata-only bridge. The final 0.11.0 wheel
must prove that every shipped `scoreform/` runtime member, entry point,
`Requires-Python`, and runtime dependency is unchanged from that exact physical
candidate. Automation reports only equivalence and explicitly reports physical
acceptance as `not_claimed`; the project owner decides whether to carry the
physical observation forward. Any runtime/dependency/entry-point difference
requires physical retesting.

## Downstream compatibility

The released Paper Data Suite v0.1.0 composition continues to exact-qualify its
historical ScoreForm 0.10.0 artifact. ScoreForm does not rewrite that immutable
Suite release.

Meridian's current ScoreForm adapter likewise exact-binds to ScoreForm 0.10.0.
The underlying producer/reader contract remains structurally unchanged in
ScoreForm 0.11.0, but Meridian must separately and explicitly qualify/add
ScoreForm 0.11.0 before claiming support for the new distribution identity.

## Installation

Use the authenticated Core 0.6.3 and ScoreForm 0.11.0 GitHub Release wheels in a
fresh Python 3.11+ environment:

```powershell
python -m pip install .\pds_core-0.6.3-py3-none-any.whl
python -m pip install .\scoreform-0.11.0-py3-none-any.whl
python -m pip check
scoreform --version
```

GitHub Release assets remain the release distribution mechanism. Do not infer
PyPI availability.

## Known limitations and privacy

ScoreForm remains pre-1.0. Printer scaling, scan quality, alignment, lighting,
focus, and imaging processing can affect mark detection. Teachers must manually
verify scored results before recording grades.

Rosters, generated sheets, scans, retained sources, results, review evidence,
publication manifests, and diagnostics may contain sensitive student
information. Keep classroom artifacts out of source control and follow
applicable school, district, state, and federal requirements.
