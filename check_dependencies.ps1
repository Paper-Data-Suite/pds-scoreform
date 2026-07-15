$ErrorActionPreference = "Continue"

$RepoRoot = $PSScriptRoot
$VenvDir = Join-Path $RepoRoot ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$script:Failures = 0

function Pass([string]$Message) {
    Write-Host "PASS: $Message" -ForegroundColor Green
}

function Fail([string]$Message) {
    Write-Host "FAIL: $Message" -ForegroundColor Red
    $script:Failures += 1
}

function Info([string]$Message) {
    Write-Host $Message -ForegroundColor DarkGray
}

function Check-PythonImport {
    param([string]$Module, [string]$DisplayName = $Module)

    $output = & $Python -c "import $Module" 2>&1
    if ($LASTEXITCODE -eq 0) {
        Pass "$DisplayName is importable."
    }
    else {
        Fail "$DisplayName is not importable in the selected ScoreForm environment."
        if ($output) { Info ($output -join "`n") }
    }
}

Write-Host "=== ScoreForm Dependency Check ===" -ForegroundColor Cyan
Info "Repository: $RepoRoot"

if (Test-Path -LiteralPath $VenvDir -PathType Container) {
    if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
        Fail "The repo-local .venv exists but .venv\Scripts\python.exe is missing. Recreate it with Python 3.11 or newer."
        Write-Host "Dependency check failed." -ForegroundColor Red
        exit 1
    }
    $Python = $VenvPython
    Pass "Using the repo-local virtual environment."
}
else {
    $PythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $PythonCommand) {
        Fail "Python was not found. Install Python 3.11 or newer, create .venv, then run: .venv\Scripts\python.exe -m pip install -e `".[dev]`""
        Write-Host "Dependency check failed." -ForegroundColor Red
        exit 1
    }
    $Python = $PythonCommand.Source
    Info "No repo-local .venv exists; checking Python from PATH: $Python"
}

$versionText = & $Python -c "import sys; print('.'.join(map(str, sys.version_info[:3]))); raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" 2>&1
if ($LASTEXITCODE -eq 0) {
    Pass "Python $versionText satisfies >=3.11."
}
else {
    Fail "Python $versionText is unsupported; ScoreForm requires Python 3.11 or newer."
}

Check-PythonImport "scoreform" "ScoreForm"
Check-PythonImport "pds_core" "pds-core"

$coreVersion = & $Python -c "from importlib.metadata import version; print(version('pds-core'))" 2>&1
if ($LASTEXITCODE -eq 0) {
    Info "Installed pds-core distribution version: $coreVersion"
    $coreRangeOutput = & $Python -c "from importlib.metadata import version; from pip._vendor.packaging.specifiers import SpecifierSet; value=version('pds-core'); raise SystemExit(0 if value in SpecifierSet('>=0.5,<0.6') else 1)" 2>&1
    if ($LASTEXITCODE -eq 0) {
        Pass "pds-core $coreVersion satisfies >=0.5,<0.6."
    }
    else {
        Fail "pds-core $coreVersion is incompatible; install a version in >=0.5,<0.6."
    }
}
else {
    Fail "The pds-core distribution is not installed. Run: $Python -m pip install -e `".[dev]`""
}

Write-Host ""
Write-Host "Checking third-party Python imports..." -ForegroundColor Yellow
Check-PythonImport "cv2" "opencv-python (cv2)"
Check-PythonImport "numpy"
Check-PythonImport "reportlab"
Check-PythonImport "PIL" "Pillow (PIL)"
Check-PythonImport "pdf2image"

$pipCheck = & $Python -m pip check 2>&1
if ($LASTEXITCODE -eq 0) {
    Pass "pip reports a consistent installed dependency set."
}
else {
    Fail "pip detected dependency conflicts. Run: $Python -m pip install -e `".[dev]`""
    if ($pipCheck) { Info ($pipCheck -join "`n") }
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
Write-Host "Remediation: install Python 3.11+, create .venv, and run .venv\Scripts\python.exe -m pip install -e `".[dev]`"" -ForegroundColor Yellow
exit 1
