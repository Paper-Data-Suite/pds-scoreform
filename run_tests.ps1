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

function Assert-Exists {
    param (
        [string]$Path
    )

    if (-not (Test-Path $Path)) {
        Write-Host "FAILED: Expected file/folder not found: $Path" -ForegroundColor Red
        exit 1
    }

    Write-Host "FOUND: $Path" -ForegroundColor Green
}

Run-Test "Validate assignment" "python main.py validate-assignment sample_assignment.json"
Run-Test "Validate roster" "python main.py validate-roster sample_roster_english9_p2.csv"

Run-Test "Generate generic template" "python main.py generate"

Write-Host ""
Write-Host "Checking generic template files..." -ForegroundColor Yellow
Assert-Exists "template.pdf"
Assert-Exists "template.png"

Run-Test "Generate class assignment materials" "python main.py generate sample_assignment.json --rosters sample_roster_english9_p2.csv"

Write-Host ""
Write-Host "Checking generated class/assignment files..." -ForegroundColor Yellow
Assert-Exists "classes\english9_p2\roster.csv"
Assert-Exists "classes\english9_p2\assignments\rj_act1_quiz\assignment.json"
Assert-Exists "classes\english9_p2\assignments\rj_act1_quiz\templates"
Assert-Exists "classes\english9_p2\assignments\rj_act1_quiz\templates\individual"
Assert-Exists "classes\english9_p2\assignments\rj_act1_quiz\templates\class_packet.pdf"
Assert-Exists "classes\english9_p2\assignments\rj_act1_quiz\templates\individual\1001_doe_jane.pdf"
Assert-Exists "classes\english9_p2\assignments\rj_act1_quiz\templates\individual\1002_smith_marcus.pdf"
Assert-Exists "classes\english9_p2\assignments\rj_act1_quiz\templates\individual\1003_brown_alyssa.pdf"
Assert-Exists "classes\english9_p2\assignments\rj_act1_quiz\scans"
Assert-Exists "classes\english9_p2\assignments\rj_act1_quiz\debug"

Run-Test "Setup assignment folder" "python main.py setup-assignment sample_assignment.json sample_roster_english9_p2.csv"

Run-Test "Score batch PDF" "python main.py score pdf_batch_test.pdf"

Write-Host ""
Write-Host "Checking scoring output files..." -ForegroundColor Yellow
Assert-Exists "results.csv"
Assert-Exists "debug_corners_page_1.png"
Assert-Exists "debug_warped_page_1.png"

Write-Host ""
Write-Host "All tests passed." -ForegroundColor Green