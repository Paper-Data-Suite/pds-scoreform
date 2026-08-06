# ScoreForm Publication Producer Profile

ScoreForm exposes publication compatibility independently from PDS2 routing.
Core discovers the metadata-only provider through the installed entry point:

```text
paper_data_suite.publication_producers
    scoreform = scoreform.pds_publication:get_publication_producer_profile
```

`scoreform.pds_publication:get_publication_producer_profile` is a zero-argument,
deterministic provider returning Core's immutable `PublicationProducerProfile`.
It is separate from the routing `ModuleProfile` in `paper_data_suite.modules`:
the routing profile contains a route handler and registration validator, while
the publication profile contains no callback, parser, reader, generator, or
state-changing operation.

## Exact compatibility matrix

| Field | Supported value |
|---|---|
| Module ID | `scoreform` |
| Display name | `ScoreForm` |
| Core Publication Record schema | `1` |
| Academic Work producer contract | `scoreform_academic_work_v1` |
| Publication kind | `academic_result_set` |
| Manifest contract | `scoreform_academic_result_manifest_v1` |
| Capabilities | `points`, `question_evidence`, `multiple_attempts` |
| Publication source-record contracts | none |
| Missing Publication Record source | allowed and required for compatibility |

The profile does not advertise `standards_ratings`, `criterion_scores`,
`moderated_scores`, `intervention_history`, `intervention_status`, or
`intervention_outcomes`. Question `standard_ids` are assignment-alignment
metadata, and response correctness is evidence; neither is a producer-created
standards rating. Attempt selection, proficiency, rubric policy, moderation,
Grades, and intervention semantics remain outside ScoreForm's declaration.

## Three distinct source boundaries

The Academic Work Registration contains one unversioned assignment
`ModuleRecordRef`. A compatible ScoreForm Publication Record has
`source_record=None`; the profile therefore has no source-record support rows.
The manifest separately binds exact SHA-256 snapshots of `assignment.json` and
the schema-2 `results.csv` history. Those manifest snapshots are producer
metadata and do not create a durable native result-set record identity.

## Metadata-only boundary

Import, direct invocation, installed discovery, and registry construction do
not read a workspace or native file; generate or parse a manifest; access an
Academic Work Registration, Publication Record, withdrawal, catalog, or lock;
invoke the CLI, menu, or route handler; or import a sibling producer or Meridian.
The returned value only declares versions and capabilities.

Installed discovery is not authorization. Compatibility evaluation only checks
the Core envelope, exact referenced registration metadata, and the producer's
declared support; it does not inspect manifest bytes or prove that a specific
publication is valid, current, authorized, or consumable. Issue #167 owns
publication, supersession, and withdrawal workflows. Issue #168 owns the
consumer-neutral manifest reader. Issue #169 owns installed end-to-end producer
acceptance.

The Core package version, routing contract, QR schema, route-registration
schema, Publication Record schema, Academic Work Registration schema and
producer contract, manifest contract, routed-results schema, and publication
compatibility contract are independent version namespaces. This installed Core
dataclass is not a serialized ScoreForm schema and has no ScoreForm profile
schema or revision.
