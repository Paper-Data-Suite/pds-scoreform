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

function Run-TestExpectFailure {
    param (
        [string]$Name,
        [string]$Command
    )

    Write-Host ""
    Write-Host "Running expected failure: $Name" -ForegroundColor Yellow
    Write-Host $Command -ForegroundColor DarkGray

    Invoke-Expression $Command

    if ($LASTEXITCODE -eq 0) {
        Write-Host "FAILED: Expected command to fail but it succeeded: $Name" -ForegroundColor Red
        exit 1
    }

    Write-Host "PASSED EXPECTED FAILURE: $Name" -ForegroundColor Green
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

function Assert-FileContains {
    param (
        [string]$Path,
        [string]$Text
    )

    if (-not (Select-String -Path $Path -Pattern $Text -Quiet)) {
        Write-Host "FAILED: Expected '$Text' in $Path" -ForegroundColor Red
        exit 1
    }

    Write-Host "FOUND TEXT: '$Text'" -ForegroundColor Green
}

function Assert-FileDoesNotContain {
    param (
        [string]$Path,
        [string]$Text
    )

    if (Select-String -Path $Path -Pattern $Text -Quiet) {
        Write-Host "FAILED: Did not expect '$Text' in $Path" -ForegroundColor Red
        exit 1
    }

    Write-Host "CONFIRMED ABSENT: '$Text'" -ForegroundColor Green
}

function Assert-CsvValueCount {
    param (
        [string]$Path,
        [string]$Column,
        [string]$Value,
        [int]$ExpectedCount
    )

    $rows = Import-Csv $Path
    $count = ($rows | Where-Object { $_.$Column -eq $Value }).Count

    if ($count -ne $ExpectedCount) {
        Write-Host "FAILED: Expected $ExpectedCount rows with $Column=$Value in $Path, found $count" -ForegroundColor Red
        exit 1
    }

    Write-Host "FOUND CSV COUNT: $Column=$Value appears $ExpectedCount time(s)" -ForegroundColor Green
}

Write-Host ""
Write-Host "Cleaning old generated test outputs..." -ForegroundColor Yellow
Remove-Item "results.csv" -ErrorAction SilentlyContinue
Remove-Item "debug_corners_page_*.png" -ErrorAction SilentlyContinue
Remove-Item "debug_warped_page_*.png" -ErrorAction SilentlyContinue
Remove-Item "classes\english9_p2\assignments\rj_act1_quiz\debug\debug_corners_page_*.png" -ErrorAction SilentlyContinue
Remove-Item "classes\english9_p2\assignments\rj_act1_quiz\debug\debug_warped_page_*.png" -ErrorAction SilentlyContinue
Remove-Item "conflicting_assignment.json" -ErrorAction SilentlyContinue

Run-Test "Validate assignment" "python main.py validate-assignment examples\sample_assignment.json"
Run-Test "Validate roster" "python main.py validate-roster examples\sample_roster_english9_p2.csv"

Run-Test "Generate generic template" "python main.py generate"

Write-Host ""
Write-Host "Checking generic template files..." -ForegroundColor Yellow
Assert-Exists "template.pdf"
Assert-Exists "template.png"

Run-Test "Generate class assignment materials" "python main.py generate examples\sample_assignment.json --rosters examples\sample_roster_english9_p2.csv"

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
Assert-Exists "scans_inbox"

Run-Test "Decode QR from generated individual PDF" "python main.py decode-qr classes\english9_p2\assignments\rj_act1_quiz\templates\individual\1001_doe_jane.pdf"

Run-Test "Setup assignment folder" "python main.py setup-assignment examples\sample_assignment.json examples\sample_roster_english9_p2.csv"

Write-Host ""
Write-Host "Testing collision protection..." -ForegroundColor Yellow

# Verify original assignment.json exists and contains expected title
Assert-FileContains "classes\english9_p2\assignments\rj_act1_quiz\assignment.json" "Romeo and Juliet Act 1 Quiz"
Write-Host "CONFIRMED: Original assignment.json has expected title" -ForegroundColor Green

# Create conflicting assignment with same assignment_id but different content
$conflictingAssignment = @{
    assignment_id = "rj_act1_quiz"
    title = "Romeo and Juliet Act 1 Quiz - CONFLICTING VERSION"
    question_count = 10
    choices = @("A", "B", "C", "D")
    answer_key = @{
        "1" = "B"
        "2" = "A"
        "3" = "C"
        "4" = "D"
        "5" = "B"
        "6" = "A"
        "7" = "B"
        "8" = "D"
        "9" = "A"
        "10" = "C"
    }
} | ConvertTo-Json -Depth 5
[System.IO.File]::WriteAllText("conflicting_assignment.json", $conflictingAssignment, (New-Object System.Text.UTF8Encoding $false))

Run-Test "Validate conflicting assignment fixture" "python main.py validate-assignment conflicting_assignment.json"

# Attempt setup with conflicting assignment - should fail
Run-TestExpectFailure "Attempt setup with conflicting assignment (should fail)" "python main.py setup-assignment conflicting_assignment.json examples\sample_roster_english9_p2.csv"

# Verify original assignment.json was NOT overwritten
Assert-FileContains "classes\english9_p2\assignments\rj_act1_quiz\assignment.json" "Romeo and Juliet Act 1 Quiz"
Assert-FileDoesNotContain "classes\english9_p2\assignments\rj_act1_quiz\assignment.json" "CONFLICTING VERSION"
Write-Host "CONFIRMED: Original assignment.json was protected and not overwritten" -ForegroundColor Green

# Clean up test artifact
Remove-Item "conflicting_assignment.json" -ErrorAction SilentlyContinue

Run-Test "Score generated template PDF" "python main.py score template.pdf results.csv examples\answer_key.json"

Write-Host ""
Write-Host "Checking scoring output files..." -ForegroundColor Yellow
Assert-Exists "results.csv"
Assert-Exists "debug_corners_page_1.png"
Assert-Exists "debug_warped_page_1.png"

Write-Host ""
Write-Host "Testing QR-aware scoring..." -ForegroundColor Yellow
Remove-Item "qr_metadata_results.csv" -ErrorAction SilentlyContinue
Run-Test "Score with QR-aware metadata extraction" "python main.py score classes\english9_p2\assignments\rj_act1_quiz\templates\individual\1001_doe_jane.pdf qr_metadata_results.csv"

Write-Host ""
Write-Host "Checking QR-aware scoring output..." -ForegroundColor Yellow
Assert-Exists "qr_metadata_results.csv"
Assert-FileContains "qr_metadata_results.csv" "source_file"
Assert-FileContains "qr_metadata_results.csv" "1001_doe_jane.pdf"

Write-Host ""
Write-Host "Testing mixed-scan QR-aware scoring..." -ForegroundColor Yellow
Remove-Item "mixed_scan_results.csv" -ErrorAction SilentlyContinue
Run-Test "Score class packet with QR-aware mixed-scan mode" "python main.py score classes\english9_p2\assignments\rj_act1_quiz\templates\class_packet.pdf mixed_scan_results.csv"

Write-Host ""
Write-Host "Checking mixed-scan scoring output..." -ForegroundColor Yellow
Assert-Exists "mixed_scan_results.csv"
Assert-FileContains "mixed_scan_results.csv" "1001"
Assert-FileContains "mixed_scan_results.csv" "1002"
Assert-FileContains "mixed_scan_results.csv" "1003"
Assert-FileContains "mixed_scan_results.csv" "english9_p2"
Assert-FileContains "mixed_scan_results.csv" "rj_act1_quiz"

Write-Host ""
Write-Host "Testing result routing..." -ForegroundColor Yellow
Remove-Item "classes\english9_p2\assignments\rj_act1_quiz\results.csv" -ErrorAction SilentlyContinue
Run-Test "Score class packet with result routing" "python main.py score classes\english9_p2\assignments\rj_act1_quiz\templates\class_packet.pdf"

Write-Host ""
Write-Host "Checking routed results output..." -ForegroundColor Yellow
Assert-Exists "classes\english9_p2\assignments\rj_act1_quiz\results.csv"
Assert-FileContains "classes\english9_p2\assignments\rj_act1_quiz\results.csv" "1001"
Assert-FileContains "classes\english9_p2\assignments\rj_act1_quiz\results.csv" "1002"
Assert-FileContains "classes\english9_p2\assignments\rj_act1_quiz\results.csv" "1003"
Assert-FileContains "classes\english9_p2\assignments\rj_act1_quiz\results.csv" "english9_p2"
Assert-FileContains "classes\english9_p2\assignments\rj_act1_quiz\results.csv" "rj_act1_quiz"
Assert-FileContains "classes\english9_p2\assignments\rj_act1_quiz\results.csv" "Doe"
Assert-FileContains "classes\english9_p2\assignments\rj_act1_quiz\results.csv" "Jane"
Assert-FileContains "classes\english9_p2\assignments\rj_act1_quiz\results.csv" "Smith"
Assert-FileContains "classes\english9_p2\assignments\rj_act1_quiz\results.csv" "Marcus"
Assert-FileContains "classes\english9_p2\assignments\rj_act1_quiz\results.csv" "Brown"
Assert-FileContains "classes\english9_p2\assignments\rj_act1_quiz\results.csv" "Alyssa"
Assert-FileContains "classes\english9_p2\assignments\rj_act1_quiz\results.csv" "2"
Assert-FileContains "classes\english9_p2\assignments\rj_act1_quiz\results.csv" "source_file"
Assert-FileContains "classes\english9_p2\assignments\rj_act1_quiz\results.csv" "class_packet.pdf"
Assert-FileContains "classes\english9_p2\assignments\rj_act1_quiz\results.csv" "scan_timestamp"

Write-Host ""
Write-Host "Testing duplicate/attempt handling for routed results..." -ForegroundColor Yellow
Run-Test "Score class packet with result routing again for attempt tracking" "python main.py score classes\english9_p2\assignments\rj_act1_quiz\templates\class_packet.pdf"
Assert-Exists "classes\english9_p2\assignments\rj_act1_quiz\results.csv"
Assert-CsvValueCount "classes\english9_p2\assignments\rj_act1_quiz\results.csv" "attempt_number" "1" 3
Assert-CsvValueCount "classes\english9_p2\assignments\rj_act1_quiz\results.csv" "attempt_number" "2" 3
Assert-FileContains "classes\english9_p2\assignments\rj_act1_quiz\results.csv" "source_file"
Assert-FileContains "classes\english9_p2\assignments\rj_act1_quiz\results.csv" "scan_timestamp"
Assert-Exists "classes\english9_p2\assignments\rj_act1_quiz\debug\debug_corners_page_1.png"
Assert-Exists "classes\english9_p2\assignments\rj_act1_quiz\debug\debug_warped_page_1.png"
Assert-Exists "classes\english9_p2\assignments\rj_act1_quiz\debug\debug_corners_page_2.png"
Assert-Exists "classes\english9_p2\assignments\rj_act1_quiz\debug\debug_warped_page_2.png"
Assert-Exists "classes\english9_p2\assignments\rj_act1_quiz\debug\debug_corners_page_3.png"
Assert-Exists "classes\english9_p2\assignments\rj_act1_quiz\debug\debug_warped_page_3.png"

Write-Host ""
Write-Host "All tests passed." -ForegroundColor Green