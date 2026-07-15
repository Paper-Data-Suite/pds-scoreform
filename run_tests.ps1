$ErrorActionPreference = "Stop"

$RepoRoot = $PSScriptRoot
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$VenvScoreForm = Join-Path $RepoRoot ".venv\Scripts\scoreform.exe"

if (Test-Path -LiteralPath $VenvPython -PathType Leaf) {
    $Python = $VenvPython
}
else {
    $PythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $PythonCommand) {
        throw "Python was not found. Create .venv with Python 3.11 or newer."
    }
    $Python = $PythonCommand.Source
}

function Invoke-Step {
    param([string]$Name, [scriptblock]$Action)

    Write-Host ""
    Write-Host "Running: $Name" -ForegroundColor Yellow
    & $Action
    if ($LASTEXITCODE -ne 0) {
        throw "FAILED: $Name (exit $LASTEXITCODE)"
    }
    Write-Host "PASSED: $Name" -ForegroundColor Green
}

function Invoke-MigrationGate {
    param([string]$Name, [string[]]$Arguments, [string]$Issue)

    Write-Host ""
    Write-Host "Running expected migration gate: $Name" -ForegroundColor Yellow
    $output = & $ScoreForm @Arguments 2>&1
    $code = $LASTEXITCODE
    if ($code -eq 0) {
        throw "FAILED: $Name unexpectedly succeeded."
    }
    $text = $output -join "`n"
    if ($text -notmatch "temporarily unavailable" -or $text -notmatch [regex]::Escape($Issue)) {
        throw "FAILED: $Name did not report the expected actionable $Issue migration message.`n$text"
    }
    if ($text -match "Traceback") {
        throw "FAILED: $Name exposed a traceback.`n$text"
    }
    Write-Host "PASSED EXPECTED MIGRATION GATE: $Name" -ForegroundColor Green
}

Write-Host "=== ScoreForm Core 0.5 Foundation Validation ===" -ForegroundColor Cyan
Write-Host "Using Python: $Python" -ForegroundColor DarkGray

Invoke-Step "Require Python 3.11+" {
    & $Python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
}
Invoke-Step "Install ScoreForm editable with development extras" {
    & $Python -m pip install -e ".[dev]" --quiet
}
Invoke-Step "Check installed dependency consistency" {
    & $Python -m pip check
}
Invoke-Step "Compile ScoreForm" {
    & $Python -m compileall -q scoreform
}
Invoke-Step "Import ScoreForm, PDS contract, CLI, and Core" {
    & $Python -c "import pds_core; import scoreform; import scoreform.pds_contract; import scoreform.cli"
}
Invoke-Step "Run pytest suite" {
    & $Python -m pytest tests -q
}
Invoke-Step "Run Ruff" {
    & $Python -m ruff check .
}

if (Test-Path -LiteralPath $VenvScoreForm -PathType Leaf) {
    $ScoreForm = $VenvScoreForm
}
else {
    $ScoreFormCommand = Get-Command scoreform -ErrorAction SilentlyContinue
    if (-not $ScoreFormCommand) {
        throw "The scoreform console command was not installed."
    }
    $ScoreForm = $ScoreFormCommand.Source
}

$SmokeRoot = Join-Path ([System.IO.Path]::GetTempPath()) (
    "scoreform-foundation-smoke-" + [guid]::NewGuid().ToString("N")
)
if (Test-Path -LiteralPath $SmokeRoot) {
    throw "Refusing to use an existing smoke workspace: $SmokeRoot"
}
$workspaceWasSet = Test-Path Env:PDS_WORKSPACE_ROOT
$savedWorkspace = $env:PDS_WORKSPACE_ROOT
$env:PDS_WORKSPACE_ROOT = $SmokeRoot
try {
    Invoke-Step "Show installed CLI help" { & $ScoreForm --help }
    Invoke-Step "Show installed CLI short help" { & $ScoreForm -h }
    Invoke-Step "Show installed CLI help command" { & $ScoreForm help }
    Invoke-Step "Show installed CLI version" { & $ScoreForm --version }
    Invoke-Step "Show installed CLI version command" { & $ScoreForm version }
    Invoke-Step "Show direct main.py help" { & $Python main.py --help }
    Invoke-Step "Validate an assignment file" {
        & $ScoreForm validate-assignment examples\sample_assignment.json
    }
    Invoke-Step "Validate a roster file" {
        & $ScoreForm validate-roster examples\sample_roster_english9_p2.csv
    }

    if (Test-Path -LiteralPath $SmokeRoot) {
        throw "Imports/help/version/validation created workspace data: $SmokeRoot"
    }

    Invoke-MigrationGate "Personalized generation" @(
        "generate", "examples\sample_assignment.json", "--rosters",
        "examples\sample_roster_english9_p2.csv"
    ) "#139"
    Invoke-MigrationGate "QR-aware scoring" @("score", "missing-scan.pdf") "#143"
    Invoke-MigrationGate "QR decoding" @("decode-qr", "missing-scan.pdf") "#143"
    Invoke-MigrationGate "Assignment-folder setup" @(
        "setup-assignment", "examples\sample_assignment.json",
        "examples\sample_roster_english9_p2.csv"
    ) "#139"

    if (Test-Path -LiteralPath $SmokeRoot) {
        throw "A migration-gated command created partial workspace artifacts: $SmokeRoot"
    }
}
finally {
    if ($workspaceWasSet) {
        $env:PDS_WORKSPACE_ROOT = $savedWorkspace
    }
    else {
        Remove-Item Env:PDS_WORKSPACE_ROOT -ErrorAction SilentlyContinue
    }
}

Invoke-Step "Run dependency checker" {
    powershell -ExecutionPolicy Bypass -File .\check_dependencies.ps1
}

Write-Host ""
Write-Host "All ScoreForm Core 0.5 foundation checks passed." -ForegroundColor Green
