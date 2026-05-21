$ErrorActionPreference = "Stop"

Write-Host "=== ScoreForm Test Script ===" -ForegroundColor Cyan

function Run-Test {
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

Run-Test "Validate assignment" "python main.py validate-assignment sample_assignment.json"
Run-Test "Validate roster" "python main.py validate-roster sample_roster_english9_p2.csv"
Run-Test "Generate generic template" "python main.py generate"
Run-Test "Generate class assignment materials" "python main.py generate sample_assignment.json --rosters sample_roster_english9_p2.csv"
Run-Test "Setup assignment folder" "python main.py setup-assignment sample_assignment.json sample_roster_english9_p2.csv"
Run-Test "Score batch PDF" "python main.py score pdf_batch_test.pdf"

Write-Host ""
Write-Host "All tests passed." -ForegroundColor Green