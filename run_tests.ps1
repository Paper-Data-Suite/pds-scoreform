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

    $Individual = Get-ChildItem -LiteralPath (Join-Path $ManagedRoot "templates\individual") -Filter "*.pdf" -File | Select-Object -First 1
    if (-not $Individual) {
        throw "Managed generation did not create an individual synthetic artifact."
    }
    Invoke-Step "Decode an actual generated ScoreForm QR through the installed command" {
        & $ScoreForm decode-qr $Individual.FullName
    }
    Invoke-Step "Score an actual generated ScoreForm artifact through Core dispatch" {
        & $ScoreForm score $Individual.FullName
    }
    $ResultsPath = Join-Path $ManagedRoot "results.csv"
    if (-not (Test-Path -LiteralPath $ResultsPath -PathType Leaf)) {
        throw "Real CLI scoring did not export the managed result history."
    }
    $FullRows = @(Import-Csv -LiteralPath $ResultsPath)
    if ($FullRows.Count -ne 1 -or $FullRows[0].result_schema_version -ne "2" -or $FullRows[0].result_origin -ne "pds2_scan") {
        throw "Real CLI scoring did not export one schema-v2 PDS2 attempt."
    }
    $ReviewRoot = Join-Path $SmokeRoot "scans\review"
    if (Test-Path -LiteralPath $ReviewRoot) {
        $UnexpectedFailures = @(Get-ChildItem -LiteralPath $ReviewRoot -Filter "*.json" -File)
        if ($UnexpectedFailures.Count -ne 0) {
            throw "Full-success CLI scoring unexpectedly wrote failure metadata."
        }
    }

    $PartialScan = Join-Path $SmokeRoot "synthetic_partial.pdf"
    Invoke-Step "Build deterministic synthetic partial-batch fixture" {
        & $Python scripts\build_partial_cli_smoke.py $Individual.FullName $PartialScan
    }
    $FiledBeforePartial = @(
        Get-ChildItem -LiteralPath (Join-Path $ManagedRoot "scans") -File
    ).Count
    Write-Host ""
    Write-Host "Running expected nonzero real #145 partial-batch command" -ForegroundColor Yellow
    $PartialOutput = & $ScoreForm score $PartialScan 2>&1
    $PartialCode = $LASTEXITCODE
    if ($PartialCode -eq 0) {
        throw "Partial-batch score command unexpectedly exited zero.`n$($PartialOutput -join "`n")"
    }
    if (($PartialOutput -join "`n") -match "Traceback") {
        throw "Partial-batch score command exposed a traceback.`n$($PartialOutput -join "`n")"
    }
    Write-Host "PASSED EXPECTED NONZERO: real #145 partial-batch command" -ForegroundColor Green
    $PartialRows = @(Import-Csv -LiteralPath $ResultsPath)
    if ($PartialRows.Count -ne 2 -or @($PartialRows | Where-Object { $_.result_schema_version -ne "2" }).Count -ne 0) {
        throw "Partial CLI batch did not preserve one full-success export per command."
    }
    $FailureFiles = @(Get-ChildItem -LiteralPath $ReviewRoot -Filter "*.json" -File)
    if ($FailureFiles.Count -ne 1) {
        $FailureSummary = @(
            $FailureFiles | ForEach-Object {
                $value = Get-Content -Raw -LiteralPath $_.FullName | ConvertFrom-Json
                "$($_.Name): $($value.stage)/$($value.failure_category) page=$($value.source_page_number)"
            }
        ) -join "; "
        throw "Partial CLI batch persisted $($FailureFiles.Count) failures instead of one: $FailureSummary`n$($PartialOutput -join "`n")"
    }
    $FailureId = $FailureFiles[0].BaseName
    $FailureHash = (Get-FileHash -LiteralPath $FailureFiles[0].FullName -Algorithm SHA256).Hash
    Invoke-Step "Strictly reload the real CLI failure through Core" {
        & $Python -c "import sys; from pds_core.scan_failure_metadata import load_routing_failure_metadata; value=load_routing_failure_metadata(sys.argv[1], sys.argv[2]); raise SystemExit(0 if value.failure_id == sys.argv[2] and value.schema_version == '2' else 1)" $SmokeRoot $FailureId
    }
    Invoke-Step "List the real CLI review failure" {
        $text = & $ScoreForm list-scan-review 2>&1
        if (($text -join "`n") -notmatch [regex]::Escape($FailureId)) { exit 1 }
    }
    Invoke-Step "Append deferred resolution through the installed command" {
        & $ScoreForm resolve-scan-review $FailureId --action defer
    }
    Invoke-Step "Append final resolution through the installed command" {
        & $ScoreForm resolve-scan-review $FailureId --action cannot_route
    }
    $ResolutionFiles = @(Get-ChildItem -LiteralPath (Join-Path $ReviewRoot "resolutions") -Filter "*.json" -File)
    if ($ResolutionFiles.Count -ne 2) {
        throw "Real CLI smoke did not preserve both append-only resolutions."
    }
    if ((Get-FileHash -LiteralPath $FailureFiles[0].FullName -Algorithm SHA256).Hash -ne $FailureHash) {
        throw "Resolution commands mutated immutable failure bytes."
    }
    $MetadataText = @($FailureFiles + $ResolutionFiles | ForEach-Object { Get-Content -Raw -LiteralPath $_.FullName }) -join "`n"
    if ($MetadataText -match '"schema_version"\s*:\s*"1"') {
        throw "Real CLI smoke wrote schema-v1 failure or resolution metadata."
    }
    $FiledAfterPartial = @(
        Get-ChildItem -LiteralPath (Join-Path $ManagedRoot "scans") -File
    ).Count
    if ($FiledAfterPartial -ne $FiledBeforePartial) {
        throw "Partial CLI scoring performed automatic assignment-local scan filing."
    }

    Invoke-Step "Run deterministic #145 partial-batch scan-review smoke" {
        & $Python -m pytest @(
            "tests/test_attempt_assembly.py::test_deterministic_review_smoke_exports_complete_and_preserves_review_history"
        ) -q
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
