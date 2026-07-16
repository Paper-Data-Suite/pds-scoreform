# ScoreForm v0.9.1 physical acceptance test

Publication is blocked until the project owner completes this test with a wheel
built from the clean reviewed candidate commit, reports a pass, and explicitly
authorizes release. Use synthetic identities only. Do not commit or upload
generated PDFs, filled sheets, scans, results, or diagnostic images.

## 1. Freeze and build the candidate

From the ScoreForm repository, require a clean working tree before building:

```powershell
$RepoRoot = (Get-Location).Path
git status --short
$CandidateCommit = git rev-parse HEAD
$CandidateTree = git rev-parse "HEAD^{tree}"
if (git status --short) { throw "The physical candidate must be a clean commit." }

powershell -ExecutionPolicy Bypass -File .\run_tests.ps1
$ScoreFormWheels = @(Get-ChildItem .\dist\scoreform-0.9.1-*.whl -File)
if ($ScoreFormWheels.Count -ne 1) { throw "Expected exactly one ScoreForm wheel." }
$ScoreFormWheel = $ScoreFormWheels[0]
$ScoreFormWheelHash = (Get-FileHash -LiteralPath $ScoreFormWheel.FullName `
    -Algorithm SHA256).Hash

$CandidateCommit
$CandidateTree
$ScoreFormWheel.FullName
$ScoreFormWheelHash
```

Record all four values. The physical test must use that exact rebuilt wheel.
Any later runtime, dependency, packaging, build-script, layout, behavioral-test,
or runtime-smoke change invalidates the test. Documentation-only recording of
the completed result does not require another paper run.

## 2. Obtain and install both release distributions

Download `pds_core-0.5.0-py3-none-any.whl` from the verified PDS Core `v0.5.0`
GitHub Release. Core 0.5.0 was not published to PyPI. ScoreForm's metadata
enforces `pds-core>=0.5,<0.6`, but pip cannot obtain Core unless its wheel is
made available explicitly. The ScoreForm release does not repackage or bundle
Core, and an editable sibling checkout is for development only.

Copy the verified Core wheel and the exact candidate ScoreForm wheel into a new
temporary test directory, then run:

```powershell
$TestRoot = Join-Path $env:TEMP "scoreform-v0.9.1-physical-acceptance"
if (Test-Path -LiteralPath $TestRoot) {
    throw "Choose a new empty physical-test directory: $TestRoot"
}
New-Item -ItemType Directory -Path $TestRoot | Out-Null

# Copy the two verified wheel files into $TestRoot before continuing.
$CoreWheel = Get-Item (Join-Path $TestRoot "pds_core-0.5.0-py3-none-any.whl")
$CandidateWheel = Get-Item (Join-Path $TestRoot "scoreform-0.9.1-py3-none-any.whl")
if ((Get-FileHash $CandidateWheel.FullName -Algorithm SHA256).Hash -ne $ScoreFormWheelHash) {
    throw "The copied ScoreForm wheel is not the recorded candidate wheel."
}

$Venv = Join-Path $TestRoot "venv"
py -3.11 -m venv $Venv
$Python = Join-Path $Venv "Scripts\python.exe"
& $Python -c @"
import sys

print(sys.version)
raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 1)
"@
$ScoreForm = Join-Path $Venv "Scripts\scoreform.exe"
& $Python -m pip install $CoreWheel.FullName
& $Python -m pip install $CandidateWheel.FullName
& $Python -m pip check
& $ScoreForm --version
& $Python -c "from importlib.metadata import version; print(version('pds-core'))"
```

Record the full Python version printed by the exact Python 3.11 check, along
with the PDS Core and ScoreForm versions.

## 3. Create the exact synthetic inputs

Use these stable identities:

```text
class_id: physical_acceptance
assignment_id: physical_acceptance_30
student_id: synthetic1
layout_id: standard_15q_abcd_v1
```

Create the isolated workspace and fixture directory:

```powershell
$Workspace = Join-Path $TestRoot "workspace"
$FixtureRoot = Join-Path $TestRoot "fixture"
New-Item -ItemType Directory -Path $FixtureRoot | Out-Null
$env:PDS_WORKSPACE_ROOT = $Workspace
Push-Location $FixtureRoot
Copy-Item `
    (Join-Path $RepoRoot "tests\fixtures\release\physical_acceptance_assignment.json") `
    (Join-Path $FixtureRoot "assignment.json")
Copy-Item `
    (Join-Path $RepoRoot "tests\fixtures\release\physical_acceptance_roster.csv") `
    (Join-Path $FixtureRoot "roster.csv")
```

The copied `assignment.json` has exactly this content:

```json
{
  "assignment_id": "physical_acceptance_30",
  "title": "ScoreForm v0.9.1 Physical Acceptance",
  "question_count": 30,
  "choices": ["A", "B", "C", "D"],
  "layout_id": "standard_15q_abcd_v1",
  "answer_key": {
    "1": "A", "2": "B", "3": "C", "4": "D",
    "5": "A", "6": "B", "7": "C", "8": "D",
    "9": "A", "10": "B", "11": "C", "12": "D",
    "13": "A", "14": "B", "15": "C", "16": "D",
    "17": "A", "18": "B", "19": "C", "20": "D",
    "21": "A", "22": "B", "23": "C", "24": "D",
    "25": "A", "26": "B", "27": "C", "28": "D",
    "29": "A", "30": "B"
  }
}
```

The copied `roster.csv` has exactly this content:

```csv
class_id,student_id,last_name,first_name,period
physical_acceptance,synthetic1,Synthetic,Student,1
```

## 4. Generate and verify both independent print copies

Run the installed commands:

```powershell
& $ScoreForm setup-assignment .\assignment.json .\roster.csv
& $ScoreForm generate .\assignment.json --rosters .\roster.csv
& $ScoreForm scan-filing set copy

$WorkRoot = Join-Path $Workspace `
    "classes\physical_acceptance\modules\scoreform\work\physical_acceptance_30"
$IndividualPdfs = @(Get-ChildItem `
    (Join-Path $WorkRoot "templates\individual") -Filter "*.pdf" -File)
if ($IndividualPdfs.Count -ne 1) { throw "Expected one individual PDF." }
$IndividualPdf = $IndividualPdfs[0]
$PacketPdf = Get-Item (Join-Path $WorkRoot "templates\class_packet.pdf")
$IssuanceFiles = @(Get-ChildItem `
    (Join-Path $WorkRoot "answer_sheets\issuances") -Filter "*.json" -File)
$PageFiles = @(Get-ChildItem `
    (Join-Path $WorkRoot "answer_sheets\pages") -Filter "*.json" -File)
$RouteFiles = @(Get-ChildItem `
    (Join-Path $WorkRoot "routes") -Filter "*.json" -File -Recurse)

if ($IssuanceFiles.Count -ne 2) { throw "Expected two issuances." }
if ($PageFiles.Count -ne 4) { throw "Expected four page records." }
if ($RouteFiles.Count -ne 4) { throw "Expected four route registrations." }
```

Generation must create two independent two-page print copies:

- one two-page individual artifact;
- one two-page class-packet artifact;
- two separate issuances;
- four immutable page records;
- four distinct route registrations.

Select only the individual PDF for the physical test and identify its issuance:

```powershell
$Issuances = @($IssuanceFiles | ForEach-Object {
    Get-Content -Raw -LiteralPath $_.FullName | ConvertFrom-Json
})
$SelectedIssuances = @($Issuances | Where-Object {
    $_.generation_context.output_kind -eq "individual_pdf"
})
$UnusedPacketIssuances = @($Issuances | Where-Object {
    $_.generation_context.output_kind -eq "class_packet_pdf"
})
if ($SelectedIssuances.Count -ne 1 -or $UnusedPacketIssuances.Count -ne 1) {
    throw "Expected one individual issuance and one class-packet issuance."
}
$SelectedIssuance = $SelectedIssuances[0]
$UnusedPacketIssuance = $UnusedPacketIssuances[0]
$SelectedIssuanceId = $SelectedIssuance.issuance_id
$SelectedPageIds = @($SelectedIssuance.page_ids)

$Pages = @($PageFiles | ForEach-Object {
    Get-Content -Raw -LiteralPath $_.FullName | ConvertFrom-Json
})
$SelectedPages = @($Pages | Where-Object {
    $_.issuance_id -eq $SelectedIssuanceId
} | Sort-Object logical_page)
$Routes = @($RouteFiles | ForEach-Object {
    Get-Content -Raw -LiteralPath $_.FullName | ConvertFrom-Json
})
$SelectedRoutes = @($Routes | Where-Object {
    $_.target.record_id -in $SelectedPageIds
})

if ($SelectedPages.Count -ne 2) { throw "Selected issuance must have two pages." }
if ($SelectedRoutes.Count -ne 2) { throw "Selected issuance must have two routes." }
if (@($SelectedPages.page_id | Select-Object -Unique).Count -ne 2) {
    throw "Selected page IDs must be distinct."
}
if (@($SelectedRoutes.locator.route_id | Select-Object -Unique).Count -ne 2) {
    throw "Selected route IDs must be distinct."
}
if ((@($SelectedPages.logical_page) -join ",") -ne "1,2") {
    throw "Selected logical pages must be 1 and 2."
}

"Selected PDF: $($IndividualPdf.FullName)"
"Unused packet PDF: $($PacketPdf.FullName)"
"Selected issuance: $SelectedIssuanceId"
"Unused packet issuance: $($UnusedPacketIssuance.issuance_id)"
$SelectedPages | Select-Object logical_page,page_id,issuance_id
$SelectedRoutes | ForEach-Object {
    [pscustomobject]@{
        page_id = $_.target.record_id
        route_id = $_.locator.route_id
    }
}
```

Record the selected issuance ID, its two page IDs, and its two route IDs. Print
only `$IndividualPdf` at actual size/100%. Do not use "fit to page". Do not print
or scan the unused class-packet PDF.

## 5. Mark the exact answer pattern

The answer key repeats A, B, C, D. Mark every keyed answer except:

- Q5: mark B instead of keyed A (incorrect, page 1);
- Q20: mark A instead of keyed D (incorrect, page 2);
- Q30: leave blank instead of keyed B (blank, page 2).

This produces exactly 27 correct, 2 incorrect, 1 blank, expected score 27/30.
All other questions must have one unambiguous mark matching the key.

## 6. Scan, decode, and score

Scan the two printed pages through the intended classroom scanner/camera into
one PDF named `physical-scan.pdf` in `$FixtureRoot`. Record scanner orientation,
auto-rotation, and enhancement settings, then run:

```powershell
& $ScoreForm decode-qr .\physical-scan.pdf
& $ScoreForm score .\physical-scan.pdf
```

## 7. Locate and verify every output

```powershell
$ResultsPath = Join-Path $WorkRoot "results.csv"
$ResultRows = @(Import-Csv -LiteralPath $ResultsPath)
$RetainedSources = @(Get-ChildItem `
    (Join-Path $Workspace "scans\source") -Filter "*.pdf" -File -Recurse)
$ReviewRecords = @()
$ReviewRoot = Join-Path $Workspace "scans\review"
if (Test-Path -LiteralPath $ReviewRoot) {
    $ReviewRecords = @(Get-ChildItem $ReviewRoot -Filter "*.json" -File)
}
$FiledCopies = @(Get-ChildItem (Join-Path $WorkRoot "scans") `
    -Filter "*_scored.pdf" -File)

if ($ResultRows.Count -ne 1) { throw "Expected exactly one result row." }
$Result = $ResultRows[0]
if ($Result.issuance_id -ne $SelectedIssuanceId) {
    throw "Result resolved to the unused packet issuance."
}
if ($Result.issuance_id -eq $UnusedPacketIssuance.issuance_id) {
    throw "Result must not use the unused packet issuance."
}
if ($Result.Score -ne "27" -or $Result.Total -ne "30") {
    throw "Expected score 27/30."
}
if ($Result.result_origin -ne "pds2_scan" -or `
    $Result.result_schema_version -ne "2") {
    throw "Expected one schema-v2 PDS2 result."
}
if ($ReviewRecords.Count -ne 0) { throw "Unexpected scan-review record." }
if ($FiledCopies.Count -ne 1) { throw "Copy mode must create one filed copy." }
if ($RetainedSources.Count -lt 2) {
    throw "Decode and score should each retain their selected intake."
}

$ResultsPath
$RetainedSources.FullName
$FiledCopies.FullName
$ReviewRecords.FullName
```

Use the `source_scan_id`, `retained_source_path`, and `source_sha256` in the
result row to select the scoring intake's retained source. Confirm its SHA-256
matches the recorded result digest. Confirm `page_ids`, `route_ids`,
`logical_pages`, and `source_pages` each contain two aligned values, with
logical pages 1 and 2. Confirm the selected original `physical-scan.pdf`, the
Core retained source, and the assignment-local filed copy all remain because
filing mode is `copy`. Confirm no
`classes\physical_acceptance\assignments\` directory exists.

## Required pass conditions

- Both physical QR codes decode and dispatch through Core.
- All four registration marks are found on both physical pages.
- The observations resolve to `$SelectedIssuanceId`, not the unused packet
  issuance.
- Selected logical pages are 1 and 2 with distinct page and route IDs.
- All 30 detected answers match the documented physical marks.
- The result is exactly 27/30 with one schema-v2 `pds2_scan` row.
- Route/page/logical/source arrays are aligned.
- Retained source path and SHA-256 are correct.
- No unexpected review record exists.
- Copy-mode filing creates one verified assignment-local copy while preserving
  the selected original and Core retained source.
- No unqualified assignment directory exists.

## Sanitized result record

Record only:

```text
date:
candidate commit SHA:
candidate tree SHA:
wheel SHA-256:
Python/Core/ScoreForm versions:
printer/scanner workflow description:
selected issuance ID:
layout: standard_15q_abcd_v1
question count: 30
physical page count: 2
decoded page count:
scored page count:
assembled result-row count:
expected score: 27/30
actual score:
unexpected review-record count:
pass/fail:
notes:
```

Run `Pop-Location` when finished. If the test fails, do not publish. Correct the
branch, obtain approval for a new clean candidate commit, rerun the complete
release gate and build, and repeat this entire physical test with the new wheel.
