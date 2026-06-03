$ErrorActionPreference = "Stop"

Write-Host "=== ScoreForm Test Script ===" -ForegroundColor Cyan

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

function Invoke-TestExpectFailure {
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

$LocalOutputsDir = "local_outputs"
$LocalTemplatesDir = Join-Path $LocalOutputsDir "templates"
$LocalResultsDir = Join-Path $LocalOutputsDir "results"
$LocalDebugDir = Join-Path $LocalOutputsDir "debug"
$LocalTempDir = Join-Path $LocalOutputsDir "temp"
$TemplatePdf = Join-Path $LocalTemplatesDir "template.pdf"
$TemplatePng = Join-Path $LocalTemplatesDir "template.png"
$DefaultResultsCsv = Join-Path $LocalResultsDir "results.csv"
$QrMetadataResultsCsv = Join-Path $LocalResultsDir "qr_metadata_results.csv"
$MixedScanResultsCsv = Join-Path $LocalResultsDir "mixed_scan_results.csv"
$ConflictingAssignmentJson = Join-Path $LocalTempDir "conflicting_assignment.json"
$MenuRosterClassDir = Join-Path "classes" "000_test_class_v5"
$MenuRosterCsv = Join-Path $MenuRosterClassDir "roster.csv"
$TempAssignmentJson = Join-Path $MenuRosterClassDir "assignments\test_assignment_v5\assignment.json"

Write-Host ""
Write-Host "Cleaning old generated test outputs..." -ForegroundColor Yellow
Remove-Item "results.csv" -ErrorAction SilentlyContinue
Remove-Item "debug_corners_page_*.png" -ErrorAction SilentlyContinue
Remove-Item "debug_warped_page_*.png" -ErrorAction SilentlyContinue
Remove-Item "classes\english9_p2\assignments\rj_act1_quiz\debug\debug_corners_page_*.png" -ErrorAction SilentlyContinue
Remove-Item "classes\english9_p2\assignments\rj_act1_quiz\debug\debug_warped_page_*.png" -ErrorAction SilentlyContinue
Remove-Item "conflicting_assignment.json" -ErrorAction SilentlyContinue
Remove-Item "temp_test_roster.csv" -ErrorAction SilentlyContinue
Remove-Item "temp_test_assignment.json" -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $LocalTemplatesDir, $LocalResultsDir, $LocalDebugDir, $LocalTempDir -Force | Out-Null
Remove-Item $TemplatePdf -ErrorAction SilentlyContinue
Remove-Item $TemplatePng -ErrorAction SilentlyContinue
Remove-Item $DefaultResultsCsv -ErrorAction SilentlyContinue
Remove-Item $QrMetadataResultsCsv -ErrorAction SilentlyContinue
Remove-Item $MixedScanResultsCsv -ErrorAction SilentlyContinue
Remove-Item "$LocalDebugDir\debug_corners_page_*.png" -ErrorAction SilentlyContinue
Remove-Item "$LocalDebugDir\debug_warped_page_*.png" -ErrorAction SilentlyContinue
Remove-Item $ConflictingAssignmentJson -ErrorAction SilentlyContinue
Remove-Item $MenuRosterClassDir -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $TempAssignmentJson -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "Installing ScoreForm in editable mode (with dev extras)..." -ForegroundColor Yellow
Invoke-Test "Install ScoreForm in editable mode (with dev extras)" "python -m pip install -e .[dev] --quiet"

$pythonScriptsDir = python -c "import sysconfig; print(sysconfig.get_path('scripts'))"
if ($pythonScriptsDir -and (Test-Path $pythonScriptsDir)) {
    $env:Path = "$pythonScriptsDir;$env:Path"
    Write-Host "Added Python Scripts directory to PATH for this test run: $pythonScriptsDir" -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "Running pytest suite..." -ForegroundColor Yellow
Invoke-Test "Run pytest suite" "python -m pytest"

Write-Host ""
Write-Host "Testing installed scoreform command..." -ForegroundColor Yellow
Invoke-Test "Show scoreform help" "scoreform --help"
Invoke-Test "Show scoreform short help" "scoreform -h"
Invoke-Test "Show scoreform help command" "scoreform help"
Invoke-Test "Show scoreform version" "scoreform --version"
Invoke-Test "Show scoreform version command" "scoreform version"
Invoke-Test "Launch installed scoreform command with menu exit" "Write-Output '8' | scoreform"
Invoke-Test "Launch installed scoreform menu subcommand and exit" "Write-Output '8' | scoreform menu"
Invoke-Test "Validate assignment with installed scoreform command" "scoreform validate-assignment examples\sample_assignment.json"
Invoke-Test "Validate roster with installed scoreform command" "scoreform validate-roster examples\sample_roster_english9_p2.csv"
$qrValidationCmd = @'
python -c "from scoreform.scoring import validate_qr_metadata; assert validate_qr_metadata({'class_id':'english9_p2','assignment_id':'rj_act1_quiz','student_id':'1001'}); assert not validate_qr_metadata({'class_id':'../secret','assignment_id':'rj_act1_quiz','student_id':'1001'}); assert not validate_qr_metadata({'class_id':'classes/foo','assignment_id':'rj_act1_quiz','student_id':'1001'}); assert not validate_qr_metadata({'class_id':'english9_p2','assignment_id':'rj.act1.quiz','student_id':'1001'}); assert not validate_qr_metadata({'class_id':'english9_p2','assignment_id':'rj_act1_quiz','student_id':r'C:\Users\Teacher'});"
'@
Invoke-Test "Validate QR payload identifier helper" $qrValidationCmd

Write-Host ""
Write-Host "Testing direct python main.py compatibility..." -ForegroundColor Yellow
Invoke-Test "Validate assignment with python main.py" "python main.py validate-assignment examples\sample_assignment.json"
Invoke-Test "Validate roster" "python main.py validate-roster examples\sample_roster_english9_p2.csv"

Invoke-Test "Generate generic template" "python main.py generate"

Write-Host ""
Write-Host "Checking generic template files..." -ForegroundColor Yellow
Assert-Exists $TemplatePdf
Assert-Exists $TemplatePng

Invoke-Test "Generate class assignment materials" "python main.py generate examples\sample_assignment.json --rosters examples\sample_roster_english9_p2.csv"

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

Invoke-Test "Decode QR from generated individual PDF" "python main.py decode-qr classes\english9_p2\assignments\rj_act1_quiz\templates\individual\1001_doe_jane.pdf"

Invoke-Test "Setup assignment folder" "python main.py setup-assignment examples\sample_assignment.json examples\sample_roster_english9_p2.csv"

Invoke-Test "Launch menu help and exit" "Write-Output '7', '8' | python main.py menu"

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
[System.IO.File]::WriteAllText($ConflictingAssignmentJson, $conflictingAssignment, (New-Object System.Text.UTF8Encoding $false))

Invoke-Test "Validate conflicting assignment fixture" "python main.py validate-assignment $ConflictingAssignmentJson"

# Attempt setup with conflicting assignment - should fail
Invoke-TestExpectFailure "Attempt setup with conflicting assignment (should fail)" "python main.py setup-assignment $ConflictingAssignmentJson examples\sample_roster_english9_p2.csv"

# Verify original assignment.json was NOT overwritten
Assert-FileContains "classes\english9_p2\assignments\rj_act1_quiz\assignment.json" "Romeo and Juliet Act 1 Quiz"
Assert-FileDoesNotContain "classes\english9_p2\assignments\rj_act1_quiz\assignment.json" "CONFLICTING VERSION"
Write-Host "CONFIRMED: Original assignment.json was protected and not overwritten" -ForegroundColor Green

# Clean up test artifact
Remove-Item $ConflictingAssignmentJson -ErrorAction SilentlyContinue

Invoke-Test "Score generated template PDF with manual defaults" "python main.py score $TemplatePdf examples\answer_key.json"

Write-Host ""
Write-Host "Checking scoring output files..." -ForegroundColor Yellow
Assert-Exists $DefaultResultsCsv
Assert-Exists "$LocalDebugDir\debug_corners_page_1.png"
Assert-Exists "$LocalDebugDir\debug_warped_page_1.png"

Write-Host ""
Write-Host "Testing QR-aware scoring..." -ForegroundColor Yellow
Remove-Item $QrMetadataResultsCsv -ErrorAction SilentlyContinue
Invoke-Test "Score with QR-aware metadata extraction" "python main.py score classes\english9_p2\assignments\rj_act1_quiz\templates\individual\1001_doe_jane.pdf $QrMetadataResultsCsv"

Write-Host ""
Write-Host "Checking QR-aware scoring output..." -ForegroundColor Yellow
Assert-Exists $QrMetadataResultsCsv
Assert-FileContains $QrMetadataResultsCsv "source_file"
Assert-FileContains $QrMetadataResultsCsv "1001_doe_jane.pdf"

Write-Host ""
Write-Host "Testing mixed-scan QR-aware scoring..." -ForegroundColor Yellow
Remove-Item $MixedScanResultsCsv -ErrorAction SilentlyContinue
Invoke-Test "Score class packet with QR-aware mixed-scan mode" "python main.py score classes\english9_p2\assignments\rj_act1_quiz\templates\class_packet.pdf $MixedScanResultsCsv"

Write-Host ""
Write-Host "Checking mixed-scan scoring output..." -ForegroundColor Yellow
Assert-Exists $MixedScanResultsCsv
Assert-FileContains $MixedScanResultsCsv "1001"
Assert-FileContains $MixedScanResultsCsv "1002"
Assert-FileContains $MixedScanResultsCsv "1003"
Assert-FileContains $MixedScanResultsCsv "english9_p2"
Assert-FileContains $MixedScanResultsCsv "rj_act1_quiz"

Write-Host ""
Write-Host "Testing result routing..." -ForegroundColor Yellow
Remove-Item "classes\english9_p2\assignments\rj_act1_quiz\results.csv" -ErrorAction SilentlyContinue
Invoke-Test "Score class packet with result routing" "python main.py score classes\english9_p2\assignments\rj_act1_quiz\templates\class_packet.pdf"

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
Invoke-Test "Score class packet with result routing again for attempt tracking" "python main.py score classes\english9_p2\assignments\rj_act1_quiz\templates\class_packet.pdf"
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
Write-Host "Testing roster creation through menu..." -ForegroundColor Yellow

# Clean up test roster if it exists
Remove-Item $MenuRosterClassDir -Recurse -Force -ErrorAction SilentlyContinue

# Use piped input to create a test roster through the menu
# Main menu: 5 = Roster management
# Roster menu: 1 = Create a class roster
# Then respond to prompts
@(
    "5",                    # Main menu -> Roster management
    "1",                    # Roster menu -> Create a class roster
    "Menu Test Class V5",   # Class name
    "000_test_class_v5",    # Override suggested class_id
    "5",                    # period
    "5001",                 # student 1 id
    "Test",                 # student 1 last_name
    "Alice",                # student 1 first_name
    "y",                    # add another? yes
    "5002",                 # student 2 id
    "Student",              # student 2 last_name
    "Bob",                  # student 2 first_name
    "n",                    # add another? no
    "3",                    # Return to main menu
    "8"                     # Exit
) | python main.py menu

if ($LASTEXITCODE -ne 0) {
    Write-Host "FAILED: Roster creation through menu" -ForegroundColor Red
    exit 1
}

Write-Host "PASSED: Roster creation through menu" -ForegroundColor Green

Write-Host ""
Write-Host "Checking roster creation output..." -ForegroundColor Yellow
Assert-Exists $MenuRosterCsv
Assert-FileContains $MenuRosterCsv "class_id,student_id,last_name,first_name,period"
Assert-FileContains $MenuRosterCsv "000_test_class_v5"
Assert-FileContains $MenuRosterCsv "5001"
Assert-FileContains $MenuRosterCsv "5002"
Assert-FileContains $MenuRosterCsv "Alice"
Assert-FileContains $MenuRosterCsv "Bob"

Invoke-Test "Validate created roster" "python main.py validate-roster $MenuRosterCsv"

Write-Host ""
Write-Host "Testing assignment creation through menu..." -ForegroundColor Yellow

# Clean up temp assignment if it exists
Remove-Item $TempAssignmentJson -ErrorAction SilentlyContinue

# Use piped input to create a test assignment through the menu
@(
    "6",                        # Main menu -> Assignment management
    "1",                        # Assignment menu -> Create an assignment for class(es)
    "1",                        # Select first available class (000_test_class_v5)
    "Test Assignment V5",       # title
    "test_assignment_v5",       # Override suggested assignment_id
    "10",                       # question_count
    "A", "B", "C", "D", "A", "B", "C", "D", "A", "B", # Q1-Q10
    "3",                        # Return to main menu
    "8"                         # Exit
) | python main.py menu

if ($LASTEXITCODE -ne 0) {
    Write-Host "FAILED: Assignment creation through menu" -ForegroundColor Red
    exit 1
}

Write-Host "PASSED: Assignment creation through menu" -ForegroundColor Green

Write-Host ""
Write-Host "Checking assignment creation output..." -ForegroundColor Yellow
Assert-Exists $TempAssignmentJson
Assert-FileContains $TempAssignmentJson "assignment_id"
Assert-FileContains $TempAssignmentJson "test_assignment_v5"
Assert-FileContains $TempAssignmentJson "question_count"
Assert-FileContains $TempAssignmentJson "10"
Assert-FileContains $TempAssignmentJson "choices"
Assert-FileContains $TempAssignmentJson "answer_key"
Assert-FileContains $TempAssignmentJson "standards"

Invoke-Test "Validate created assignment" "python main.py validate-assignment $TempAssignmentJson"

Write-Host ""
Write-Host "Testing answer sheet generation through menu class/assignment selection..." -ForegroundColor Yellow

@(
    "1",                        # Main menu -> Generate answer sheets
    "1",                        # Generate menu -> Existing class assignment
    "1",                        # Select first available class (000_test_class_v5)
    "1",                        # Select first available assignment (test_assignment_v5)
    "y",                        # Confirm generation
    "8"                         # Exit
) | python main.py menu

if ($LASTEXITCODE -ne 0) {
    Write-Host "FAILED: Answer sheet generation through menu" -ForegroundColor Red
    exit 1
}

Write-Host "PASSED: Answer sheet generation through menu" -ForegroundColor Green

Write-Host ""
Write-Host "Checking menu generation output..." -ForegroundColor Yellow
Assert-Exists "classes\000_test_class_v5\assignments\test_assignment_v5\templates\class_packet.pdf"
Assert-Exists "classes\000_test_class_v5\assignments\test_assignment_v5\templates\individual\5001_test_alice.pdf"
Assert-Exists "classes\000_test_class_v5\assignments\test_assignment_v5\templates\individual\5002_student_bob.pdf"

# Clean up test roster and assignment
Remove-Item $MenuRosterClassDir -Recurse -Force -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "All tests passed." -ForegroundColor Green
