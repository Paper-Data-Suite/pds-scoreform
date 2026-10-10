# Issue #227 — installed reader-contract v1 qualification

This is a **candidate** ScoreForm producer qualification, not a new ScoreForm release or an approval for consumer adapters. It uses the exact independently released PDS Core 0.6.5 wheel. The reader declaration remains metadata-only: Core discovery never executes or imports the ScoreForm reader.

## Exact artifact baseline

- PDS Core: `pds_core-0.6.5-py3-none-any.whl`
- Expected SHA-256: `9ace75f17b23b7f0ed6a709d531af5120db43d0325b4148d26f2d6ba1d4b3c18`
- ScoreForm candidate: wheel **built from the current Issue #227 checkout**, initially carrying package version `0.12.1`; neither the file's name nor the package version means it is the previously released wheel.
- Publication kind: `academic_result_set`
- Manifest contract: `scoreform_academic_result_manifest_v1`
- Reader contract: `scoreform_academic_result_reader_v1`

## Run isolated wheel acceptance on Windows

Using the repository development environment, with `python -m build` installed and the authenticated Core wheel at the location shown:

```powershell
$work = Join-Path $env:TEMP "scoreform-issue227-reader-acceptance"
$wheel = Join-Path $HOME "Downloads\pds_core-0.6.5-py3-none-any.whl"

# Choose an absent or empty --work directory; the runner refuses existing content.
python scripts/run_issue227_reader_contract_wheel_acceptance.py `
  --repository . `
  --work $work `
  --core-wheel $wheel
```

The runner validates the Core wheel filename, metadata and SHA-256, copies the checkout to an isolated staging root, builds a wheel and sdist, checks candidate artifact contracts, installs Core and ScoreForm **noneditably** in a new environment, verifies `pip check`, and runs the verifier outside the checkout.

The installed verifier checks exact package identities and site-packages origins, profile discovery/registry and exact reader lookup before reader import, missing and legacy reader declarations, canonical public reader behavior, separate attempts and provenance, selected/blank/ambiguous responses, punctuation-bearing Standards identity, and explicit failure cases. It reads the committed **synthetic** manifest fixture only. `PDS_WORKSPACE_ROOT` is overridden to a deliberately absent sentinel, which must remain absent.

The candidate wheel SHA-256 and installed qualification result are printed. The isolated `--work` tree is not deleted automatically. The operator owns its cleanup.

## Continuous qualification

`release-readiness.yml` reuses the already-installed candidate wheel and authenticated Core 0.6.5 to run the same installed verifier from `$RUNNER_TEMP`, outside checkout. The separate runner permits local direct acceptance independently of CI. It is not added to every cross-platform CI cell.

This qualification does **not** replace ScoreForm's full installed producer lifecycle, establish Meridian #111 or Vitrine #103 consumer compatibility, claim physical scan/print testing, or authorize a ScoreForm release. Final wheel artifacts and source commits must be independently recorded at the release boundary.
