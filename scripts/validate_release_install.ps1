param(
    [Parameter(Mandatory = $true)][string]$Python,
    [string]$Version = "0.10.0",
    [string]$ExpectedCoreVersion = "0.6.0"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Dist = Join-Path $RepoRoot "dist"
$Wheel = @(Get-ChildItem -LiteralPath $Dist -Filter "scoreform-$Version-*.whl" -File)
$Sdist = @(Get-ChildItem -LiteralPath $Dist -Filter "scoreform-$Version.tar.gz" -File)
if ($Wheel.Count -ne 1 -or $Sdist.Count -ne 1) {
    throw "Expected exactly one ScoreForm $Version wheel and source distribution."
}

$Root = Join-Path ([System.IO.Path]::GetTempPath()) (
    "scoreform-$Version-release-install-" + [guid]::NewGuid().ToString("N")
)
if (Test-Path -LiteralPath $Root) {
    throw "Refusing to reuse release-install root: $Root"
}

function Invoke-Checked {
    param([string]$Name, [scriptblock]$Action)
    Write-Host "Running: $Name" -ForegroundColor Yellow
    & $Action
    if ($LASTEXITCODE -ne 0) {
        throw "FAILED: $Name (exit $LASTEXITCODE)"
    }
    Write-Host "PASSED: $Name" -ForegroundColor Green
}

function Test-InstalledArtifact {
    param(
        [string]$Venv,
        [string]$Artifact,
        [string]$Label,
        [switch]$RunProducerAcceptance,
        [switch]$RunPresetAcceptance,
        [switch]$RunBulkEntryAcceptance
    )
    $VenvPython = Join-Path $Venv "Scripts\python.exe"
    $VenvScoreForm = Join-Path $Venv "Scripts\scoreform.exe"
    $Workspace = Join-Path $Root "$Label-workspace-must-not-exist"
    $Outside = Join-Path $Root "$Label-outside"
    New-Item -ItemType Directory -Path $Outside | Out-Null

    Invoke-Checked "Create $Label clean environment" { & $Python -m venv $Venv }
    Invoke-Checked "Install $Label noneditable artifact" {
        if (-not (Test-Path Env:PDS_CORE_WHEEL)) {
            throw "PDS_CORE_WHEEL must name the exact released Core $ExpectedCoreVersion wheel."
        }
        & $VenvPython -m pip install $env:PDS_CORE_WHEEL $Artifact --quiet
    }
    Invoke-Checked "Run $Label pip check" { & $VenvPython -m pip check }

    $savedWorkspace = $env:PDS_WORKSPACE_ROOT
    $workspaceWasSet = Test-Path Env:PDS_WORKSPACE_ROOT
    $env:PDS_WORKSPACE_ROOT = $Workspace
    Push-Location $Outside
    try {
        Invoke-Checked "Verify $Label installed metadata and routing/publication profiles" {
            & $VenvPython (Join-Path $RepoRoot "scripts\verify_installed_release.py") `
                --version $Version --workspace $Workspace `
                --expected-core-version $ExpectedCoreVersion
        }
        Invoke-Checked "Show $Label installed version flag" { & $VenvScoreForm --version }
        Invoke-Checked "Show $Label installed version command" { & $VenvScoreForm version }
        Invoke-Checked "Show $Label installed help flag" { & $VenvScoreForm --help }
        Invoke-Checked "Show $Label installed short help" { & $VenvScoreForm -h }
        Invoke-Checked "Show $Label installed help command" { & $VenvScoreForm help }
        Invoke-Checked "Show $Label installed publication help" { & $VenvScoreForm publication --help }
        foreach ($PublicationAction in @(
            "status", "publish", "supersede", "republish-after-withdrawal",
            "withdraw", "rebuild-catalog"
        )) {
            Invoke-Checked "Show $Label installed publication $PublicationAction help" {
                & $VenvScoreForm publication $PublicationAction --help
            }
        }
        Invoke-Checked "Import $Label installed public boundaries" {
            & $VenvPython -c "import scoreform; import scoreform.academic_result_reader; import scoreform.academic_result_manifest_generation; import scoreform.academic_result_publication; import scoreform.academic_work_registration; import scoreform.cli; import scoreform.cli_academic_work; import scoreform.cli_manifest; import scoreform.cli_publication; import scoreform.assignment_bulk_entry; import scoreform.assignment_bulk_mutation; import scoreform.cli_assignment_bulk; import scoreform.assignment_presets; import scoreform.cli_assignment_presets; import scoreform.menu_assignment_presets; import scoreform.menu_publication; import scoreform.pds_contract; import scoreform.pds_module; import scoreform.pds_publication; import pds_core"
        }
        $ForbiddenRegistryPaths = @(
            "classes",
            "settings\academic_periods",
            "registry\work",
            "registry\publications",
            "registry\withdrawals",
            "registry\catalog.sqlite",
            "registry\.locks",
            "exports\manifests"
        )
        foreach ($RelativePath in $ForbiddenRegistryPaths) {
            if (Test-Path -LiteralPath (Join-Path $Workspace $RelativePath)) {
                throw "$Label validation created forbidden registry state: $RelativePath"
            }
        }
        if (Test-Path -LiteralPath $Workspace) {
            throw "$Label import/help/version/profile discovery created workspace data."
        }

        if ($RunPresetAcceptance) {
            $PresetAcceptanceWorkspace = Join-Path $Root "$Label-preset-acceptance-workspace"
            if (Test-Path -LiteralPath $PresetAcceptanceWorkspace) {
                throw "$Label preset-acceptance workspace unexpectedly exists."
            }
            $env:PDS_WORKSPACE_ROOT = $PresetAcceptanceWorkspace
            Invoke-Checked "Run $Label installed assignment-preset acceptance" {
                & $VenvPython (Join-Path $RepoRoot "scripts\verify_installed_assignment_preset_acceptance.py") `
                    --workspace $PresetAcceptanceWorkspace `
                    --version $Version `
                    --expected-core-version $ExpectedCoreVersion
            }
            if (-not (Test-Path -LiteralPath $PresetAcceptanceWorkspace -PathType Container)) {
                throw "$Label preset acceptance did not create its expected workspace."
            }
            $env:PDS_WORKSPACE_ROOT = $Workspace
        }

        if ($RunBulkEntryAcceptance) {
            $BulkAcceptanceWorkspace = Join-Path $Root "$Label-bulk-entry-acceptance-workspace"
            if (Test-Path -LiteralPath $BulkAcceptanceWorkspace) {
                throw "$Label bulk-entry acceptance workspace unexpectedly exists."
            }
            $env:PDS_WORKSPACE_ROOT = $BulkAcceptanceWorkspace
            Invoke-Checked "Run $Label installed assignment bulk-entry acceptance" {
                & $VenvPython (Join-Path $RepoRoot "scripts\verify_installed_assignment_bulk_entry_acceptance.py") `
                    --workspace $BulkAcceptanceWorkspace `
                    --version $Version `
                    --expected-core-version $ExpectedCoreVersion
            }
            if (-not (Test-Path -LiteralPath $BulkAcceptanceWorkspace -PathType Container)) {
                throw "$Label bulk-entry acceptance did not create its expected workspace."
            }
            $env:PDS_WORKSPACE_ROOT = $Workspace
        }

        if ($RunProducerAcceptance) {
            $AcceptanceWorkspace = Join-Path $Root "$Label-producer-acceptance-workspace"
            if (Test-Path -LiteralPath $AcceptanceWorkspace) {
                throw "$Label producer-acceptance workspace unexpectedly exists."
            }
            $env:PDS_WORKSPACE_ROOT = $AcceptanceWorkspace
            Invoke-Checked "Run $Label installed producer acceptance" {
                & $VenvPython (Join-Path $RepoRoot "scripts\verify_installed_producer_acceptance.py") `
                    --workspace $AcceptanceWorkspace `
                    --version $Version `
                    --expected-core-version $ExpectedCoreVersion
            }
            if (-not (Test-Path -LiteralPath $AcceptanceWorkspace -PathType Container)) {
                throw "$Label producer acceptance did not create its expected workspace."
            }
            $env:PDS_WORKSPACE_ROOT = $Workspace
        }
    }
    finally {
        Pop-Location
        if ($workspaceWasSet) {
            $env:PDS_WORKSPACE_ROOT = $savedWorkspace
        }
        else {
            Remove-Item Env:PDS_WORKSPACE_ROOT -ErrorAction SilentlyContinue
        }
    }
}

try {
    New-Item -ItemType Directory -Path $Root | Out-Null
    Test-InstalledArtifact `
        -Venv (Join-Path $Root "wheel-venv") `
        -Artifact $Wheel[0].FullName `
        -Label "wheel" `
        -RunProducerAcceptance `
        -RunPresetAcceptance `
        -RunBulkEntryAcceptance
    Test-InstalledArtifact `
        -Venv (Join-Path $Root "sdist-venv") `
        -Artifact $Sdist[0].FullName `
        -Label "sdist"
}
finally {
    if (Test-Path -LiteralPath $Root) {
        $ResolvedRoot = [System.IO.Path]::GetFullPath($Root)
        $ResolvedTemp = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
        $Leaf = Split-Path -Leaf $ResolvedRoot
        if (
            -not $ResolvedRoot.StartsWith($ResolvedTemp, [System.StringComparison]::OrdinalIgnoreCase) -or
            -not $Leaf.StartsWith("scoreform-$Version-release-install-", [System.StringComparison]::Ordinal)
        ) {
            throw "Refusing to remove unexpected release-install root: $ResolvedRoot"
        }
        Remove-Item -LiteralPath $ResolvedRoot -Recurse -Force
    }
}
