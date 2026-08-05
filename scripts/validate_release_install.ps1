param(
    [Parameter(Mandatory = $true)][string]$Python,
    [string]$Version = "0.9.1",
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
    param([string]$Venv, [string]$Artifact, [string]$Label)
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
        Invoke-Checked "Verify $Label installed metadata and module profile" {
            & $VenvPython (Join-Path $RepoRoot "scripts\verify_installed_release.py") `
                --version $Version --workspace $Workspace `
                --expected-core-version $ExpectedCoreVersion
        }
        Invoke-Checked "Show $Label installed version flag" { & $VenvScoreForm --version }
        Invoke-Checked "Show $Label installed version command" { & $VenvScoreForm version }
        Invoke-Checked "Show $Label installed help flag" { & $VenvScoreForm --help }
        Invoke-Checked "Show $Label installed short help" { & $VenvScoreForm -h }
        Invoke-Checked "Show $Label installed help command" { & $VenvScoreForm help }
        Invoke-Checked "Import $Label installed public boundaries" {
            & $VenvPython -c "import scoreform; import scoreform.academic_result_manifest_generation; import scoreform.academic_work_registration; import scoreform.cli; import scoreform.cli_academic_work; import scoreform.cli_manifest; import scoreform.pds_contract; import scoreform.pds_module; import pds_core"
        }
        $ForbiddenRegistryPaths = @(
            "settings\academic_periods",
            "registry\work",
            "registry\publications",
            "registry\withdrawals",
            "registry\catalog.sqlite",
            "registry\.locks"
        )
        foreach ($RelativePath in $ForbiddenRegistryPaths) {
            if (Test-Path -LiteralPath (Join-Path $Workspace $RelativePath)) {
                throw "$Label validation created forbidden registry state: $RelativePath"
            }
        }
        if (Test-Path -LiteralPath $Workspace) {
            throw "$Label import/help/version/profile discovery created workspace data."
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
        -Label "wheel"
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
