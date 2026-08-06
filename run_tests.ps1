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

Write-Host "=== ScoreForm v0.9.1 Release Readiness ===" -ForegroundColor Cyan
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
Invoke-Step "Validate tracked release text encoding" {
    & $Python scripts\verify_text_encoding.py
}
Invoke-Step "Import ScoreForm, PDS contracts, profiles, CLI, and Core" {
    & $Python -c "import pds_core; import scoreform; import scoreform.academic_work_registration; import scoreform.cli_academic_work; import scoreform.pds_contract; import scoreform.pds_module; import scoreform.pds_publication; import scoreform.cli"
}
Invoke-Step "Run focused installed-profile contract tests" {
    & $Python -m pytest @(
        "tests/test_pds_module.py",
        "tests/test_pds_publication.py"
    ) -q
}
Invoke-Step "Run focused retained PDS2 boundary tests" {
    & $Python -m pytest @(
        "tests/test_pds2_scan_dispatch.py",
        "tests/test_pds2_cli_boundaries.py",
        "tests/test_removed_legacy_surfaces.py",
        "tests/test_path_input_normalization.py"
    ) -q
}
Invoke-Step "Run current-only workspace, payload, history, and viewer tests" {
    & $Python -m pytest @(
        "tests/test_work_paths.py",
        "tests/test_pds2_scan_dispatch.py::test_unsupported_payload_is_preserved_without_locator_or_request",
        "tests/test_results_export.py::test_v1_history_is_rejected_without_mutation",
        "tests/test_results_v2_strict.py",
        "tests/test_results_viewer.py",
        "tests/test_removed_legacy_surfaces.py"
    ) -q
}
Invoke-Step "Run pytest suite" {
    & $Python -m pytest tests -q
}
Invoke-Step "Run Ruff" {
    & $Python -m ruff check .
}
Invoke-Step "Run mypy" {
    & $Python -m mypy scoreform
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

    $UnsupportedRoot = Join-Path $SmokeRoot "unsupported-workspace"
    $UnsupportedArtifact = Join-Path $SmokeRoot "fixtures\unsupported-pds1.png"
    Invoke-Step "Build deterministic unsupported-schema QR artifact" {
        & $Python scripts\build_unsupported_qr_smoke.py $UnsupportedArtifact
    }
    $env:PDS_WORKSPACE_ROOT = $UnsupportedRoot

    Write-Host ""
    Write-Host "Running expected nonzero installed decode-qr unsupported-schema smoke" -ForegroundColor Yellow
    $UnsupportedDecodeOutput = & $ScoreForm decode-qr $UnsupportedArtifact 2>&1
    $UnsupportedDecodeCode = $LASTEXITCODE
    $UnsupportedDecodeText = $UnsupportedDecodeOutput -join "`n"
    if ($UnsupportedDecodeCode -eq 0) {
        throw "Unsupported-schema decode unexpectedly succeeded.`n$UnsupportedDecodeText"
    }
    if (
        $UnsupportedDecodeText -match "Traceback" -or
        $UnsupportedDecodeText -match "(?m)^(Schema: PDS2|Module:|Class:|Work:|Route:|Canonical payload:)"
    ) {
        throw "Unsupported-schema decode printed routed identity or a traceback.`n$UnsupportedDecodeText"
    }
    Write-Host "PASSED EXPECTED NONZERO: installed decode-qr unsupported schema" -ForegroundColor Green

    Write-Host ""
    Write-Host "Running expected nonzero installed score unsupported-schema smoke" -ForegroundColor Yellow
    $UnsupportedScoreOutput = & $ScoreForm score $UnsupportedArtifact 2>&1
    $UnsupportedScoreCode = $LASTEXITCODE
    $UnsupportedScoreText = $UnsupportedScoreOutput -join "`n"
    if ($UnsupportedScoreCode -eq 0) {
        throw "Unsupported-schema score unexpectedly succeeded.`n$UnsupportedScoreText"
    }
    if ($UnsupportedScoreText -match "Traceback") {
        throw "Unsupported-schema score exposed a traceback.`n$UnsupportedScoreText"
    }
    $UnsupportedReviewRoot = Join-Path $UnsupportedRoot "scans\review"
    $UnsupportedFailures = @(
        Get-ChildItem -LiteralPath $UnsupportedReviewRoot -Filter "*.json" -File
    )
    if ($UnsupportedFailures.Count -ne 1) {
        throw "Unsupported-schema score persisted $($UnsupportedFailures.Count) review records instead of one."
    }
    $UnsupportedFailure = Get-Content -Raw -LiteralPath $UnsupportedFailures[0].FullName | ConvertFrom-Json
    $UnsupportedDetails = $UnsupportedFailure.module_details.scoreform
    if ($null -eq $UnsupportedDetails) {
        throw "Unsupported-schema review record is missing module_details.scoreform."
    }
    if (
        $UnsupportedDetails.record_kind -ne "failure" -or
        $UnsupportedDetails.failure_origin -ne "page_decode" -or
        $UnsupportedDetails.scoreform_category -ne "payload_schema_unsupported"
    ) {
        throw "Unsupported-schema review record has incorrect ScoreForm failure details."
    }
    $UnsupportedContext = $UnsupportedDetails.context
    if ($null -eq $UnsupportedContext) {
        throw "Unsupported-schema review record is missing ScoreForm context."
    }
    if (
        $UnsupportedFailure.detected_payload -ne "PDS1|module=scoreform|class=class1" -or
        $null -ne $UnsupportedFailure.route_locator -or
        $null -ne $UnsupportedFailure.target
    ) {
        throw "Unsupported-schema review record fabricated routed identity."
    }
    $ExpectedNullContextFields = @(
        "page_locator",
        "request_locator",
        "resolution_locator",
        "registration_locator",
        "registration_target",
        "profile_module_id"
    )
    $ActualContextFields = @($UnsupportedContext.PSObject.Properties.Name)
    foreach ($Field in $ExpectedNullContextFields) {
        if ($Field -notin $ActualContextFields) {
            throw "Unsupported-schema review context is missing '$Field'."
        }
        $Value = $UnsupportedContext.PSObject.Properties[$Field].Value
        if ($null -ne $Value) {
            throw "Unsupported-schema review context fabricated '$Field'."
        }
    }
    if (
        "decode_method" -notin $ActualContextFields -or
        -not ($UnsupportedContext.decode_method -is [string]) -or
        [string]::IsNullOrWhiteSpace($UnsupportedContext.decode_method)
    ) {
        throw "Unsupported-schema review context has no decode_method."
    }
    $ForbiddenUnsupportedFiles = @(
        Get-ChildItem -LiteralPath $UnsupportedRoot -Recurse -File |
            Where-Object { $_.Name -eq "results.csv" }
    )
    $ForbiddenUnsupportedDirs = @(
        Get-ChildItem -LiteralPath $UnsupportedRoot -Recurse -Directory |
            Where-Object { $_.Name -in @("answer_sheets", "issuances", "routes", "assignments") }
    )
    if ($ForbiddenUnsupportedFiles.Count -ne 0 -or $ForbiddenUnsupportedDirs.Count -ne 0) {
        throw "Unsupported-schema score created results, page, issuance, route, or unqualified assignment storage."
    }
    Write-Host "PASSED EXPECTED NONZERO: installed score unsupported schema with null identity" -ForegroundColor Green

    $V1Root = Join-Path $SmokeRoot "schema-v1-workspace"
    $env:PDS_WORKSPACE_ROOT = $V1Root
    Invoke-Step "Set up isolated schema-v1 rejection assignment" {
        & $ScoreForm @(
            "setup-assignment", "examples\sample_assignment.json",
            "examples\sample_roster_english9_p2.csv"
        )
    }
    Invoke-Step "Generate isolated current PDS2 sheet for schema-v1 rejection" {
        & $ScoreForm @(
            "generate", "examples\sample_assignment.json", "--rosters",
            "examples\sample_roster_english9_p2.csv"
        )
    }
    $V1ManagedRoot = Join-Path $V1Root (
        "classes\english9_p2\modules\scoreform\work\rj_act1_quiz"
    )
    $V1Individual = Get-ChildItem -LiteralPath (Join-Path $V1ManagedRoot "templates\individual") -Filter "*.pdf" -File | Select-Object -First 1
    if (-not $V1Individual) {
        throw "Schema-v1 rejection smoke did not generate a current PDS2 artifact."
    }
    $V1ResultsPath = Join-Path $V1ManagedRoot "results.csv"
    $V1Headers = @(
        "Page", "class_id", "assignment_id", "student_id", "last_name",
        "first_name", "period", "source_file", "attempt_number",
        "scan_timestamp", "Score", "Total"
    )
    foreach ($number in 1..10) {
        $V1Headers += "Q$number"
        $V1Headers += "Q${number}_Correct"
    }
    [System.IO.File]::WriteAllText(
        $V1ResultsPath,
        (($V1Headers -join ",") + "`r`n"),
        [System.Text.UTF8Encoding]::new($false)
    )
    $V1HashBefore = (Get-FileHash -LiteralPath $V1ResultsPath -Algorithm SHA256).Hash

    Write-Host ""
    Write-Host "Running expected nonzero installed score against schema-v1 history" -ForegroundColor Yellow
    $V1ScoreOutput = & $ScoreForm score $V1Individual.FullName 2>&1
    $V1ScoreCode = $LASTEXITCODE
    $V1ScoreText = $V1ScoreOutput -join "`n"
    if ($V1ScoreCode -eq 0) {
        throw "Scoring against schema-v1 history unexpectedly succeeded.`n$V1ScoreText"
    }
    if ($V1ScoreText -match "Traceback") {
        throw "Schema-v1 rejection exposed a traceback.`n$V1ScoreText"
    }
    $V1HashAfter = (Get-FileHash -LiteralPath $V1ResultsPath -Algorithm SHA256).Hash
    if ($V1HashAfter -ne $V1HashBefore) {
        throw "Schema-v1 results history changed during rejected export."
    }
    if (@(Import-Csv -LiteralPath $V1ResultsPath).Count -ne 0) {
        throw "Schema-v1 rejection appended a routed result row."
    }
    if (@(Get-ChildItem -LiteralPath $V1ManagedRoot -Filter ".results.*.tmp" -File).Count -ne 0) {
        throw "Schema-v1 rejection left a temporary results replacement."
    }
    $V1ReviewFiles = @(
        Get-ChildItem -LiteralPath (Join-Path $V1Root "scans\review") -Filter "*.json" -File
    )
    if ($V1ReviewFiles.Count -lt 1) {
        throw "Schema-v1 export failure was not represented in scan review."
    }
    $V1ReviewText = @($V1ReviewFiles | ForEach-Object { Get-Content -Raw -LiteralPath $_.FullName }) -join "`n"
    if ($V1ReviewText -notmatch '"stage"\s*:\s*"evidence"') {
        throw "Schema-v1 export failure did not use the current evidence/review boundary."
    }
    if ((Get-Content -Raw -LiteralPath $V1ResultsPath) -match "result_schema_version|legacy_scan") {
        throw "Schema-v1 rejection installed schema-v2 or legacy-origin content."
    }
    Write-Host "PASSED EXPECTED NONZERO: schema-v1 history remained byte-identical" -ForegroundColor Green

    $env:PDS_WORKSPACE_ROOT = $SmokeRoot

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
            throw "Managed setup created an artifact outside the setup contract: $forbidden"
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
    if (@($FullRows | Where-Object { $_.result_origin -notin @("pds2_scan", "plain_paper_manual", "scan_review_manual") }).Count -ne 0) {
        throw "Real CLI scoring wrote an unsupported result origin."
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

    foreach ($Case in @(
        @{
            Name = "standard multi-page"
            ClassId = "release_standard"
            AssignmentId = "standard_30"
            Questions = 30
            Layout = $null
            ExpectedPages = 2
        },
        @{
            Name = "compact multi-page"
            ClassId = "release_compact"
            AssignmentId = "compact_30"
            Questions = 30
            Layout = "compact_25q_abcd_v1"
            ExpectedPages = 2
        }
    )) {
        $FixtureRoot = Join-Path $SmokeRoot ("fixtures\" + $Case.AssignmentId)
        $FixtureArgs = @(
            "scripts\build_release_e2e_fixture.py", $FixtureRoot,
            "--class-id", $Case.ClassId,
            "--assignment-id", $Case.AssignmentId,
            "--questions", [string]$Case.Questions
        )
        if ($Case.Layout) {
            $FixtureArgs += @("--layout-id", $Case.Layout)
        }
        Invoke-Step "Build $($Case.Name) installed E2E inputs" {
            & $Python @FixtureArgs
        }
        $AssignmentPath = Join-Path $FixtureRoot "assignment.json"
        $RosterPath = Join-Path $FixtureRoot "roster.csv"
        Invoke-Step "Set up $($Case.Name) installed E2E work" {
            & $ScoreForm setup-assignment $AssignmentPath $RosterPath
        }
        Invoke-Step "Generate $($Case.Name) registered sheets" {
            & $ScoreForm generate $AssignmentPath --rosters $RosterPath
        }
        $CaseRoot = Join-Path $SmokeRoot (
            "classes\$($Case.ClassId)\modules\scoreform\work\$($Case.AssignmentId)"
        )
        $CasePacket = Join-Path $CaseRoot "templates\class_packet.pdf"
        $CasePages = @(Get-ChildItem -LiteralPath (Join-Path $CaseRoot "answer_sheets\pages") -Filter "*.json" -File)
        $CaseRoutes = @(Get-ChildItem -LiteralPath (Join-Path $CaseRoot "routes") -Filter "*.json" -File -Recurse)
        $ExpectedRegisteredPages = 2 * $Case.ExpectedPages
        if (
            $CasePages.Count -ne $ExpectedRegisteredPages -or
            $CaseRoutes.Count -ne $ExpectedRegisteredPages
        ) {
            throw "$($Case.Name) did not create separate individual and packet page/route identities."
        }
        Invoke-Step "Decode $($Case.Name) registered pages" {
            & $ScoreForm decode-qr $CasePacket
        }
        Invoke-Step "Score and assemble $($Case.Name) installed E2E" {
            & $ScoreForm score $CasePacket
        }
        $CaseRows = @(Import-Csv -LiteralPath (Join-Path $CaseRoot "results.csv"))
        if (
            $CaseRows.Count -ne 1 -or
            $CaseRows[0].result_schema_version -ne "2" -or
            $CaseRows[0].result_origin -ne "pds2_scan"
        ) {
            throw "$($Case.Name) did not export one schema-v2 routed attempt."
        }
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

$BuildDir = Join-Path $RepoRoot "build"
$DistDir = Join-Path $RepoRoot "dist"
foreach ($GeneratedDir in @($BuildDir, $DistDir)) {
    $ResolvedGenerated = [System.IO.Path]::GetFullPath($GeneratedDir)
    $ResolvedRepo = [System.IO.Path]::GetFullPath($RepoRoot)
    if (-not $ResolvedGenerated.StartsWith(
        $ResolvedRepo + [System.IO.Path]::DirectorySeparatorChar,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Refusing to clean generated directory outside repository: $ResolvedGenerated"
    }
    if ((Split-Path -Leaf $ResolvedGenerated) -notin @("build", "dist")) {
        throw "Refusing to clean unexpected generated directory: $ResolvedGenerated"
    }
    if (Test-Path -LiteralPath $ResolvedGenerated) {
        Remove-Item -LiteralPath $ResolvedGenerated -Recurse -Force
    }
}

Invoke-Step "Build wheel and source distribution" {
    $SavedErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $BuildOutput = & $Python -m build 2>&1
    $BuildExitCode = $LASTEXITCODE
    $ErrorActionPreference = $SavedErrorActionPreference
    $BuildOutput | ForEach-Object { Write-Host $_ }
    if ($BuildExitCode -ne 0) { exit $BuildExitCode }
}
Invoke-Step "Check release artifacts with twine" {
    & $Python -m twine check .\dist\*
}
Invoke-Step "Validate release artifact names, metadata, and contents" {
    & $Python scripts\verify_release_artifacts.py --version 0.9.1 --dist .\dist
}
$CoreWheelRoot = $null
$CoreExportRoot = $null
$CoreWheelWasSet = Test-Path Env:PDS_CORE_WHEEL
$SavedCoreWheel = $env:PDS_CORE_WHEEL
try {
    if (-not $CoreWheelWasSet) {
        $CoreSource = Join-Path (Split-Path -Parent $RepoRoot) "pds-core"
        if (-not (Test-Path -LiteralPath (Join-Path $CoreSource ".git") -PathType Container)) {
            throw "Core v0.6.0 tag cannot be exported; set PDS_CORE_WHEEL to the released pds-core 0.6.0 wheel."
        }
        $CoreWheelRoot = Join-Path ([System.IO.Path]::GetTempPath()) (
            "scoreform-core-wheel-" + [guid]::NewGuid().ToString("N")
        )
        $CoreExportRoot = Join-Path ([System.IO.Path]::GetTempPath()) (
            "scoreform-core-export-" + [guid]::NewGuid().ToString("N")
        )
        New-Item -ItemType Directory -Path $CoreWheelRoot | Out-Null
        New-Item -ItemType Directory -Path $CoreExportRoot | Out-Null
        $CoreArchive = Join-Path $CoreExportRoot "pds-core-v0.6.0.zip"
        $CoreExport = Join-Path $CoreExportRoot "source"
        Invoke-Step "Export exact pds-core v0.6.0 tag" {
            git -c "safe.directory=$($CoreSource.Replace('\', '/'))" -C $CoreSource `
                archive --format=zip --output=$CoreArchive v0.6.0
        }
        Expand-Archive -LiteralPath $CoreArchive -DestinationPath $CoreExport
        Invoke-Step "Build separate pds-core 0.6.0 test wheel" {
            $SavedErrorActionPreference = $ErrorActionPreference
            $ErrorActionPreference = "Continue"
            $CoreBuildOutput = & $Python -m build --wheel --outdir $CoreWheelRoot $CoreExport 2>&1
            $CoreBuildExitCode = $LASTEXITCODE
            $ErrorActionPreference = $SavedErrorActionPreference
            $CoreBuildOutput | ForEach-Object { Write-Host $_ }
            if ($CoreBuildExitCode -ne 0) { exit $CoreBuildExitCode }
        }
        $CoreWheels = @(Get-ChildItem -LiteralPath $CoreWheelRoot -Filter "pds_core-0.6.0-*.whl" -File)
        if ($CoreWheels.Count -ne 1) {
            throw "Expected exactly one pds_core-0.6.0-*.whl from the v0.6.0 export."
        }
        $env:PDS_CORE_WHEEL = $CoreWheels[0].FullName
    }
    Invoke-Step "Validate exact pds-core 0.6.0 baseline wheel" {
        & $Python scripts\verify_core_wheel.py $env:PDS_CORE_WHEEL
    }
    Invoke-Step "Validate clean wheel and source-distribution installations" {
        powershell -ExecutionPolicy Bypass -File .\scripts\validate_release_install.ps1 `
            -Python $Python -Version 0.9.1
    }
}
finally {
    if ($CoreWheelWasSet) {
        $env:PDS_CORE_WHEEL = $SavedCoreWheel
    }
    else {
        Remove-Item Env:PDS_CORE_WHEEL -ErrorAction SilentlyContinue
    }
    if ($null -ne $CoreWheelRoot -and (Test-Path -LiteralPath $CoreWheelRoot)) {
        $ResolvedCoreWheelRoot = [System.IO.Path]::GetFullPath($CoreWheelRoot)
        $ResolvedTempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
        if (
            -not $ResolvedCoreWheelRoot.StartsWith($ResolvedTempRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
            -not (Split-Path -Leaf $ResolvedCoreWheelRoot).StartsWith("scoreform-core-wheel-")
        ) {
            throw "Refusing to remove unexpected Core-wheel root: $ResolvedCoreWheelRoot"
        }
        Remove-Item -LiteralPath $ResolvedCoreWheelRoot -Recurse -Force
    }
    if ($null -ne $CoreExportRoot -and (Test-Path -LiteralPath $CoreExportRoot)) {
        $ResolvedCoreExportRoot = [System.IO.Path]::GetFullPath($CoreExportRoot)
        $ResolvedTempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
        if (
            -not $ResolvedCoreExportRoot.StartsWith($ResolvedTempRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
            -not (Split-Path -Leaf $ResolvedCoreExportRoot).StartsWith("scoreform-core-export-")
        ) {
            throw "Refusing to remove unexpected Core-export root: $ResolvedCoreExportRoot"
        }
        Remove-Item -LiteralPath $ResolvedCoreExportRoot -Recurse -Force
    }
}
Invoke-Step "Verify exact CLI version output" {
    $VersionOutput = & $ScoreForm --version
    if (($VersionOutput -join "`n") -ne "ScoreForm 0.9.1") { exit 1 }
}
Invoke-Step "Check Git whitespace" {
    git diff --check
}
Invoke-Step "Report release artifact SHA-256" {
    Get-FileHash -Algorithm SHA256 -LiteralPath @(
        (Get-ChildItem -LiteralPath $DistDir -Filter "scoreform-0.9.1-*.whl" -File).FullName,
        (Get-ChildItem -LiteralPath $DistDir -Filter "scoreform-0.9.1.tar.gz" -File).FullName
    ) | Format-Table -AutoSize
}

Write-Host ""
Write-Host "All ScoreForm v0.9.1 release-readiness checks passed." -ForegroundColor Green
