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
Invoke-Step "Run focused retained PDS2 boundary tests" {
    & $Python -m pytest @(
        "tests/test_pds2_scan_dispatch.py",
        "tests/test_pds2_cli_boundaries.py",
        "tests/test_qr_validation.py",
        "tests/test_path_input_normalization.py"
    ) -q
}
Invoke-Step "Run pytest suite" {
    & $Python -m pytest tests -q
}
Invoke-Step "Run #144 mixed-candidate non-happy-path smoke" {
    & $Python -m pytest @(
        "tests/test_attempt_assembly.py::test_nonhappy_mixed_candidates_export_only_complete_without_filing_or_review"
    ) -q
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

    Invoke-Step "Set up module-qualified managed assignment" {
        & $ScoreForm @(
        "setup-assignment", "examples\sample_assignment.json",
        "examples\sample_roster_english9_p2.csv"
        )
    }

    $ManagedRoot = Join-Path $SmokeRoot (
        "classes\english9_p2\modules\scoreform\work\rj_act1_quiz"
    )
    if (-not (Test-Path -LiteralPath (Join-Path $ManagedRoot "assignment.json") -PathType Leaf)) {
        throw "Managed setup did not write canonical assignment.json: $ManagedRoot"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $SmokeRoot "classes\english9_p2\roster.csv") -PathType Leaf)) {
        throw "Managed setup did not write the shared class roster."
    }
    foreach ($relative in @("templates", "templates\individual", "scans", "debug")) {
        if (-not (Test-Path -LiteralPath (Join-Path $ManagedRoot $relative) -PathType Container)) {
            throw "Managed setup did not create required directory: $relative"
        }
    }
    foreach ($forbidden in @("results.csv", "templates\class_packet.pdf", "routes")) {
        if (Test-Path -LiteralPath (Join-Path $ManagedRoot $forbidden)) {
            throw "Managed setup created a forbidden later-migration artifact: $forbidden"
        }
    }
    if (Test-Path -LiteralPath (Join-Path $SmokeRoot "classes\english9_p2\assignments")) {
        throw "Managed setup recreated the former unqualified assignment layout."
    }

    Invoke-Step "Generate managed PDS2 answer sheets" {
        & $ScoreForm @(
            "generate", "examples\sample_assignment.json", "--rosters",
            "examples\sample_roster_english9_p2.csv"
        )
    }
    if (-not (Test-Path -LiteralPath (Join-Path $ManagedRoot "templates\class_packet.pdf") -PathType Leaf)) {
        throw "Managed generation did not create the class packet."
    }
    $PageRecords = @(
        Get-ChildItem -LiteralPath (Join-Path $ManagedRoot "answer_sheets\pages") -Filter "*.json" -File
    )
    $RouteRecords = @(
        Get-ChildItem -LiteralPath (Join-Path $ManagedRoot "routes") -Filter "*.json" -File -Recurse
    )
    if ($PageRecords.Count -eq 0 -or $PageRecords.Count -ne $RouteRecords.Count) {
        throw "Managed generation page/route cardinality mismatch: pages=$($PageRecords.Count), routes=$($RouteRecords.Count)"
    }

    $ClassPacket = Join-Path $ManagedRoot "templates\class_packet.pdf"
    Invoke-Step "Decode retained PDS2 pages through Core grammar" {
        & $ScoreForm decode-qr $ClassPacket
    }
    Invoke-Step "Dispatch and score retained PDS2 pages through Core" {
        & $ScoreForm score $ClassPacket
    }
    if (-not (Test-Path -LiteralPath (Join-Path $ManagedRoot "results.csv") -PathType Leaf)) {
        throw "#144 routed scoring did not write results.csv."
    }
    $ResultHeader = Get-Content -LiteralPath (Join-Path $ManagedRoot "results.csv") -TotalCount 1
    if ($ResultHeader -notmatch "result_schema_version" -or $ResultHeader -notmatch "issuance_id") {
        throw "#144 routed scoring did not write schema-v2 provenance columns."
    }
    $ReviewRoot = Join-Path $SmokeRoot "scans\review"
    if (
        (Test-Path -LiteralPath $ReviewRoot -PathType Container) -and
        (Get-ChildItem -LiteralPath $ReviewRoot -File -Recurse)
    ) {
        throw "#144 scoring unexpectedly persisted #145 scan-review metadata."
    }
}
finally {
    if ($workspaceWasSet) {
        $env:PDS_WORKSPACE_ROOT = $savedWorkspace
    }
    else {
        Remove-Item Env:PDS_WORKSPACE_ROOT -ErrorAction SilentlyContinue
    }
    if (Test-Path -LiteralPath $SmokeRoot) {
        $resolvedSmokeRoot = [System.IO.Path]::GetFullPath($SmokeRoot)
        $resolvedTempRoot = [System.IO.Path]::GetFullPath(
            [System.IO.Path]::GetTempPath()
        )
        $smokeLeaf = Split-Path -Leaf $resolvedSmokeRoot
        if (
            -not $resolvedSmokeRoot.StartsWith(
                $resolvedTempRoot,
                [System.StringComparison]::OrdinalIgnoreCase
            ) -or
            -not $smokeLeaf.StartsWith(
                "scoreform-foundation-smoke-",
                [System.StringComparison]::Ordinal
            )
        ) {
            throw "Refusing to remove unexpected smoke workspace: $resolvedSmokeRoot"
        }
        Remove-Item -LiteralPath $resolvedSmokeRoot -Recurse -Force
    }
}

Invoke-Step "Run dependency checker" {
    powershell -ExecutionPolicy Bypass -File .\check_dependencies.ps1
}

Write-Host ""
Write-Host "All ScoreForm Core 0.5 foundation checks passed." -ForegroundColor Green
