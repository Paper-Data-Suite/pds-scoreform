# ScoreForm v0.10.0

ScoreForm v0.10.0 publishes the Core 0.6 academic-result producer boundary built
across issues #161–#170. It retains the v0.9.1 PDS2 scanning foundation while
adding explicit Academic Work Registration, immutable academic-result manifests,
Core-owned publication lifecycle workflows, and a consumer-neutral producer
reader.

This release uses the unique distribution identity `scoreform 0.10.0`. The
historical `v0.9.1` release used PDS Core 0.5 and does not contain this
publication/reader contract.

## Highlights

- Requires `pds-core>=0.6,<0.7` and is release-qualified against the exact
  PDS Core 0.6.0 wheel.
- Registers managed ScoreForm assignments through
  `scoreform_academic_work_v1`.
- Generates immutable canonical
  `scoreform_academic_result_manifest_v1` revisions from exact native
  assignment/results snapshots.
- Exposes the installed `paper_data_suite.publication_producers` ScoreForm
  profile for `academic_result_set`.
- Advertises exactly `points`, `question_evidence`, and `multiple_attempts`.
- Uses `source_record=None` for ScoreForm academic-result Publication Records.
- Publishes, replays, supersedes, republishes after withdrawal, withdraws, and
  rebuilds the derived Core catalog through Core-owned services.
- Exposes `scoreform.academic_result_reader` for canonical immutable bytes and
  exact source/student/attempt/question/response lookup.
- Runs a clean-wheel installed producer acceptance covering registration,
  manifest revisions, publication, Core path/digest verification, independent
  multi-attempt reading, supersession, withdrawal, catalog state, registry
  audit, and immutability.
- Adds a release compatibility audit that enforces the Core range, producer
  profile, explicit-attempt reader boundary, and sibling-module isolation.

## Attempt, standards, grading, and portfolio policy

ScoreForm remains a producer of exact assessment evidence.

It does not:

- select the latest, highest, best, or official attempt;
- provide a fallback attempt;
- infer proficiency or mastery from question-to-standard alignments;
- calculate a course Grade or Grade-item policy;
- create Meridian evidence;
- create Vitrine Candidates;
- determine portfolio eligibility, ranking, selection, placement, or Snapshot
  construction.

All attempts remain independently represented. `selected`, `blank`, and
`ambiguous` response states remain distinct. Standards IDs remain alignments,
not learner ratings.

## Downstream compatibility

### Meridian

After the v0.10.0 GitHub Release assets pass clean-install verification, Meridian
may bind to the exact reader identity:

```text
producer_reader_distribution: scoreform
supported reader version:     0.10.0
reader module:                 scoreform.academic_result_reader
producer module:               scoreform
publication kind:              academic_result_set
Academic Work contract:        scoreform_academic_work_v1
manifest contract:             scoreform_academic_result_manifest_v1
source_record:                 absent
capabilities:                  points, question_evidence, multiple_attempts
attempt policy:                preserve all; select none
```

ScoreForm does not import or depend on Meridian.

### Vitrine

ScoreForm supplies exact producer evidence only. It does not emit portfolio
Candidates or perform portfolio curation. Exact work/student/attempt/question
identity, standards alignments, and provenance remain available so Vitrine can
implement producer discovery and Candidate projection later as an additive
downstream layer.

ScoreForm does not import or depend on Vitrine.

## Installation

Obtain `pds_core-0.6.0-py3-none-any.whl` from the verified PDS Core `v0.6.0`
GitHub Release and obtain `scoreform-0.10.0-py3-none-any.whl` from the ScoreForm
`v0.10.0` GitHub Release. Install both noneditably in a fresh Python 3.11+
environment:

```powershell
python -m pip install .\pds_core-0.6.0-py3-none-any.whl
python -m pip install .\scoreform-0.10.0-py3-none-any.whl
python -m pip check
scoreform --version
```

PDS Core 0.6.0 is not published to PyPI. The established ScoreForm release
process likewise publishes verified GitHub Release assets rather than a package
index. ScoreForm does not bundle Core.

## Existing PDS2 compatibility boundary

PDS1 and OMR1 sheets remain unsupported. Historical schema-v1 routed-result
files are not migrated. Previously printed legacy sheets cannot be assigned
fabricated PDS2 routes. Generate new v0.10.0 PDS2 sheets for routed scoring.

The v0.9.1 module-qualified storage, immutable issuance/page/route identity,
retained-source dispatch, schema-v2 results, scan-review, filing, standard and
compact layouts, and teacher workflows remain the scanning foundation.

## Known limitations

ScoreForm remains pre-1.0. Physical scan quality, printer scaling, lighting,
focus, alignment, and camera/scanner processing affect detection reliability.
Teachers must manually verify scored results before recording grades.

## Privacy

Generated sheets, packets, rosters, assignments, original and retained scans,
filed copies, results, publication manifests, review metadata, evidence, and
diagnostics may contain sensitive student information. Keep them out of source
control and follow applicable school, district, state, and federal privacy
requirements.

## Release validation

v0.10.0 publication is blocked until the project owner completes the documented
source-menu rehearsal, the release-preparation PR and CI pass and are merged,
the authoritative automated gate is rerun on the exact reconciled release
commit, and the project owner passes the real printed-and-scanned physical
acceptance using that exact final wheel and explicitly authorizes the GitHub
Release.

See:

- `docs/release_checklist.md`
- `docs/physical_acceptance_test.md`
- `docs/v0.10.0_release_compatibility.md`
