$ErrorActionPreference = "Stop"

Write-Host "=== ScoreForm Fast Developer Checks ===" -ForegroundColor Cyan
Write-Host "This is a fast precheck. run_tests.ps1 remains the release-readiness gate." -ForegroundColor DarkGray

$Python = ".\.venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    Write-Host "FAILED: Repo-local virtual environment not found at .venv\Scripts\python.exe" -ForegroundColor Red
    Write-Host "Create it and install development dependencies first:" -ForegroundColor Yellow
    Write-Host "  python -m venv .venv" -ForegroundColor DarkGray
    Write-Host "  .\.venv\Scripts\Activate.ps1" -ForegroundColor DarkGray
    Write-Host "  .venv\Scripts\python.exe -m pip install -r requirements-dev.txt" -ForegroundColor DarkGray
    exit 1
}

function Invoke-Test {
    param (
        [string]$Name,
        [string]$Command
    )

    Write-Host ""
    Write-Host "Running: $Name" -ForegroundColor Yellow
    Write-Host $Command -ForegroundColor DarkGray

    Invoke-Expression $Command

    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAILED: $Name" -ForegroundColor Red
        exit 1
    }

    Write-Host "PASSED: $Name" -ForegroundColor Green
}

Invoke-Test "Check dependency/import environment" ".\check_dependencies.ps1"
Invoke-Test "Run Ruff checks" "$Python -m ruff check ."
Invoke-Test "Run pytest suite" "$Python -m pytest --basetemp=.pytest-tmp-fast"
Remove-Item ".\.pytest-tmp-fast" -Recurse -Force -ErrorAction SilentlyContinue
Invoke-Test "Check diff whitespace" "git diff --check"

Write-Host ""
Write-Host "Checking for tracked generated/private artifacts..." -ForegroundColor Yellow
$trackedArtifacts = git ls-files classes local_outputs scans_inbox

if ($trackedArtifacts) {
    Write-Host "FAILED: Generated/private artifact paths are tracked by Git." -ForegroundColor Red
    $trackedArtifacts | ForEach-Object { Write-Host $_ -ForegroundColor Red }
    exit 1
}

Write-Host "PASSED: No tracked generated/private artifacts found." -ForegroundColor Green
Write-Host ""
Write-Host "All fast developer checks passed." -ForegroundColor Green
Write-Host "Reminder: run_tests.ps1 is still the release-readiness gate." -ForegroundColor Cyan
