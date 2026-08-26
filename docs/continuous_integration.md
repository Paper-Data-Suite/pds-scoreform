# Continuous integration

ScoreForm uses two deliberately different GitHub Actions validation layers.
They answer different questions and should remain separate.

## Routine cross-platform CI

`.github/workflows/ci.yml` runs for pull requests and pushes to `main`. Its
matrix covers the currently supported routine environments:

| Operating system | Python versions |
| --- | --- |
| Windows (`windows-latest`) | 3.11, 3.12, 3.13, 3.14 |
| Ubuntu (`ubuntu-latest`) | 3.11, 3.12, 3.13, 3.14 |

Python 3.11 remains the language and package-metadata floor. Testing newer
interpreters proves compatibility; it does not permit source syntax that would
break Python 3.11.

Every matrix cell:

1. installs Poppler using a platform-appropriate deterministic path;
2. downloads and authenticates the official released PDS Core 0.6.3 wheel;
3. installs that Core wheel and ScoreForm's development dependencies;
4. verifies the installed Core version and runs `pip check`;
5. runs the complete ordinary pytest suite;
6. runs Ruff and mypy;
7. runs the lightweight release-compatibility audit; and
8. verifies Git whitespace plus tracked and untracked repository cleanliness.

The Windows Poppler archive is version-pinned and SHA-256 authenticated before
its executables are added to `PATH`. The Core 0.6.3 release wheel is also
SHA-256 authenticated and then validated by `scripts/verify_core_wheel.py`.
CI does not use a sibling editable Core checkout.

Mypy runs with the Python target of the current matrix cell. The Python 3.11
cells therefore remain the authoritative type-checking floor, while newer
cells type-check against their own interpreter contract. This avoids falsely
parsing dependency stubs that legitimately use newer Python syntax as though
they had to be valid Python 3.11 source. ScoreForm's own source compatibility
floor remains Python 3.11 and is not raised by this matrix behavior.

Test, linter, type-checker, and Python bytecode caches are kept outside the
repository checkout where practical. CI fixtures must be synthetic and the
workflow is noninteractive.

## Operations-wheel compatibility qualification

CI also runs a dedicated `operations-wheel-qualification` matrix on Windows and
Ubuntu using Python 3.11. It builds the current ScoreForm wheel and source
distribution, installs the wheel noneditably outside the checkout, and discovers
ScoreForm through Core's `paper_data_suite.module_operations` entry-point
contract.

That matrix qualifies both authenticated Core endpoints:

- Core 0.6.2: minimum-floor operations-provider loading, validation, absent and
  empty workspace semantics, and read-only Core invocation.
- Core 0.6.3: the full current installed attention acceptance, including scan
  attention, Share Results attention, diagnostic-history nonauthority, privacy,
  and zero-write checks.

This job is intentionally separate from the ordinary 3.11-3.14 source matrix.
It proves built-artifact compatibility at the new minimum Core floor without
replacing the exact Core 0.6.3 release-readiness reference.

## Heavyweight release readiness

`.github/workflows/release-readiness.yml` remains the canonical deep release
gate on Ubuntu/Python 3.11. It owns release-specific work such as distribution
building, Twine/artifact checks, clean installed wheel validation, installed
assignment workflow acceptance, installed multi-class generation acceptance,
and the installed producer lifecycle.

Those expensive checks are intentionally **not** multiplied across all eight
routine CI environments. A green matrix means the normal repository contract
works across the supported OS/Python combinations; a green Release readiness
check means the canonical release artifacts can be built, installed, and
accepted against the exact release contract.

Neither workflow constitutes real printer/scanner acceptance. Combined
installed and physical workflow acceptance remains separate release work.

## Local pre-PR validation

Developers should run the repository's normal local gate before pushing a PR.
On Windows, the authoritative local release qualification remains:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_tests.ps1
```

For a faster change-focused pass, run the relevant tests plus:

```powershell
python -m ruff check .
python -m mypy scoreform
git diff --check
```

GitHub CI adds independent Windows/Ubuntu and Python 3.11-3.14 evidence that a
single local environment cannot provide.

## Compatibility boundaries

- Python package metadata remains `requires-python = ">=3.11"`.
- Routine CI currently covers Windows and Ubuntu only; macOS is not implied.
- ScoreForm continues to declare `pds-core>=0.6.2,<0.7`.
- The exact authenticated CI/release baseline for this development line is PDS
  Core 0.6.3 unless that baseline is deliberately revised in a separate
  compatibility change.
