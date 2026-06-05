$ErrorActionPreference = "Stop"

Write-Host "=== ScoreForm Fast Test Script ===" -ForegroundColor Cyan

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

Invoke-Test "Run pytest suite" "python -m pytest"
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
Write-Host "All fast tests passed." -ForegroundColor Green
