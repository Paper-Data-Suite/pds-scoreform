$ErrorActionPreference = "Continue"

$RepoRoot = $PSScriptRoot
$VenvDir = Join-Path $RepoRoot ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$PdsCoreDir = Join-Path (Split-Path -Parent $RepoRoot) "pds-core"
$script:Failures = 0

function Pass {
    param ([string]$Message)

    Write-Host "PASS: $Message" -ForegroundColor Green
}

function Fail {
    param ([string]$Message)

    Write-Host "FAIL: $Message" -ForegroundColor Red
    $script:Failures += 1
}

function Info {
    param ([string]$Message)

    Write-Host $Message -ForegroundColor DarkGray
}

function Test-PythonExecutable {
    param (
        [string]$Path
    )

    try {
        $output = & $Path --version 2>&1
        if ($LASTEXITCODE -eq 0) {
            return ($output -join "`n")
        }
    }
    catch {
        return $null
    }

    return $null
}

function Check-PythonImport {
    param (
        [string]$Module,
        [string]$DisplayName = $Module
    )

    if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
        Fail "Cannot check import '$DisplayName' because .venv\Scripts\python.exe is missing."
        return
    }

    $output = & $VenvPython -c "import $Module" 2>&1
    if ($LASTEXITCODE -eq 0) {
        Pass "$DisplayName is importable from .venv."
        return
    }

    Fail "$DisplayName is not importable from .venv."
    if ($output) {
        Info ($output -join "`n")
    }
}

Write-Host "=== ScoreForm Dependency Check ===" -ForegroundColor Cyan
Info "Repository: $RepoRoot"
Write-Host ""

$venvPythonVersion = $null
if (Test-Path -LiteralPath $VenvPython -PathType Leaf) {
    $venvPythonVersion = Test-PythonExecutable $VenvPython
}

if ($venvPythonVersion) {
    Pass "Python is available through the repo-local virtual environment: $venvPythonVersion"
}
else {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        $pythonVersion = Test-PythonExecutable $pythonCommand.Source
        if ($pythonVersion) {
            Pass "Python is available on PATH: $pythonVersion"
        }
        else {
            Fail "Python command exists but did not run successfully."
        }
    }
    else {
        Fail "Python was not found on PATH and .venv\Scripts\python.exe is unavailable."
    }
}

if (Test-Path -LiteralPath $VenvDir -PathType Container) {
    Pass "Repo-local virtual environment exists: .venv"
}
else {
    Fail "Repo-local virtual environment is missing: .venv"
}

if (Test-Path -LiteralPath $VenvPython -PathType Leaf) {
    if ($venvPythonVersion) {
        Pass ".venv\Scripts\python.exe exists and runs: $venvPythonVersion"
    }
    else {
        Fail ".venv\Scripts\python.exe exists but did not run successfully."
    }
}
else {
    Fail ".venv\Scripts\python.exe is missing."
}

if (Test-Path -LiteralPath $PdsCoreDir -PathType Container) {
    Pass "Sibling pds-core repo exists: ..\pds-core"
}
else {
    Fail @"
Missing sibling repo.

Expected layout:
Paper-Data-Suite/
  pds-core/
  pds-scoreform/

Fix:
Clone pds-core beside pds-scoreform, then rerun:

.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
"@
}

if (Test-Path -LiteralPath $VenvPython -PathType Leaf) {
    $pdsCoreOutput = & $VenvPython -c "import pds_core" 2>&1
    if ($LASTEXITCODE -eq 0) {
        Pass "pds_core is importable from .venv."
    }
    elseif (Test-Path -LiteralPath $PdsCoreDir -PathType Container) {
        Fail @"
pds-core exists but is not importable in this virtual environment.

Fix:
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
"@
        if ($pdsCoreOutput) {
            Info ($pdsCoreOutput -join "`n")
        }
    }
    else {
        Fail "pds_core is not importable because the sibling ..\pds-core repo is missing."
    }

    Check-PythonImport "scoreform" | Out-Null

    Write-Host ""
    Write-Host "Checking third-party Python imports..." -ForegroundColor Yellow
    Check-PythonImport "cv2" | Out-Null
    Check-PythonImport "numpy" | Out-Null
    Check-PythonImport "reportlab" | Out-Null
    Check-PythonImport "PIL" | Out-Null
    Check-PythonImport "pdf2image" | Out-Null
}
else {
    Fail "Skipped Python import checks because .venv\Scripts\python.exe is missing."
}

Write-Host ""
Write-Host "Checking external tools..." -ForegroundColor Yellow
$pdftoppm = Get-Command pdftoppm -ErrorAction SilentlyContinue
if ($pdftoppm) {
    Pass "Poppler pdftoppm is available: $($pdftoppm.Source)"
}
else {
    Fail "Poppler pdftoppm was not found on PATH. PDF scoring/conversion requires Poppler."
}

Write-Host ""
if ($script:Failures -eq 0) {
    Write-Host "Dependency check passed." -ForegroundColor Green
    exit 0
}

Write-Host "Dependency check failed with $script:Failures required problem(s)." -ForegroundColor Red
exit 1
