# Issue #216 — Guided diagnostic warning aggregation

ScoreForm diagnostic-image persistence is auxiliary. A page that scores
successfully remains a successful page even when one or more optional diagnostic
images could not be saved.

The retained dispatch result exposes a bounded count of diagnostic artifact
warnings attached to successful ScoreForm page results. The guided teacher
summary projects that count as:

```text
Diagnostic images unavailable: N
```

The count is deliberately aggregate-only. It does not expose student identity,
page identity, route identity, filenames, paths, answers, scores, QR payloads, or
exception prose.

Diagnostic warning counts do not change the guided scan outcome. A scan that
otherwise satisfies the `complete` contract remains `complete`; no scan-review
item is created solely because a diagnostic image is unavailable.

Substantive page-scoring failures remain outside this aggregate. Those failures
continue through the existing failure/review contracts, while any simultaneous
diagnostic-persistence warning remains subordinate technical state and is also
available through the privacy-conscious diagnostic event surface.
