# JobHunt one-time setup (Windows PowerShell 5.1+).
#
# Run from the project folder:
#   powershell -ExecutionPolicy Bypass -File .\setup.ps1
# Or after allowing local scripts once:
#   Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
#   .\setup.ps1
#
# What it does:
#   1. Checks Python 3.10+
#   2. Installs Python packages (requirements.txt)
#   3. Ensures the bundled tectonic LaTeX engine (downloads it if missing)
#   4. Creates .env from .env.example if missing
#   5. Runs the interactive `python agent.py setup` wizard (skip with -SkipWizard)
#   6. Runs `python agent.py doctor` to prove everything works
param(
    [switch]$SkipWizard
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $RepoRoot

$TectonicVersion = "0.17.0"
$TectonicUrl = "https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%400.17.0/tectonic-0.17.0-x86_64-pc-windows-msvc.zip"
$TectonicDir = Join-Path $RepoRoot "tools\tectonic"
$TectonicExe = Join-Path $TectonicDir "tectonic.exe"

function Fail($msg) {
    Write-Host ""
    Write-Host "SETUP FAILED: $msg" -ForegroundColor Red
    exit 1
}

Write-Host "== JobHunt setup ==" -ForegroundColor Cyan

# 1. Python 3.10+
Write-Host "-- Checking Python... " -NoNewline
try {
    $pyOut = & python --version 2>&1
} catch {
    Fail "Python not found. Install Python 3.10+ from https://www.python.org/downloads/ (tick 'Add python.exe to PATH'), then re-run."
}
if ($pyOut -match "Python (\d+)\.(\d+)") {
    $major, $minor = [int]$Matches[1], [int]$Matches[2]
    if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 10)) {
        Fail "Found $pyOut, need Python 3.10+. Get it from https://www.python.org/downloads/."
    }
    Write-Host "$pyOut OK" -ForegroundColor Green
} else {
    Fail "Could not parse Python version ('$pyOut')."
}

# 2. Python packages
Write-Host "-- Installing requirements... (first run downloads ~100 MB)"
try {
    & python -m pip install --upgrade pip 2>&1 | Out-Null
} catch {
    Write-Host "  (pip upgrade skipped: $_)" -ForegroundColor Yellow
}
try {
    & python -m pip install -r (Join-Path $RepoRoot "requirements.txt")
    if ($LASTEXITCODE -ne 0) { throw "pip exited with code $LASTEXITCODE" }
} catch {
    Fail "pip install failed: $_. Check your network and re-run."
}
Write-Host "  requirements OK" -ForegroundColor Green

# 3. Tectonic (bundled; download only if missing)
Write-Host "-- Checking tectonic... " -NoNewline
if (Test-Path -LiteralPath $TectonicExe) {
    Write-Host "bundled copy OK" -ForegroundColor Green
} else {
    Write-Host "missing, downloading v$TectonicVersion (~21 MB)..."
    $zipPath = Join-Path ([System.IO.Path]::GetTempPath()) "tectonic.zip"
    try {
        Invoke-WebRequest -Uri $TectonicUrl -OutFile $zipPath -UseBasicParsing
        New-Item -ItemType Directory -Path $TectonicDir -Force | Out-Null
        Expand-Archive -LiteralPath $zipPath -DestinationPath $TectonicDir -Force
        Remove-Item -LiteralPath $zipPath -Force -ErrorAction SilentlyContinue
    } catch {
        Fail "tectonic download failed: $_. Manual fix: download tectonic-*-x86_64-pc-windows-msvc.zip from https://github.com/tectonic-typesetting/tectonic/releases and unpack tectonic.exe to tools\tectonic\."
    }
    if (-not (Test-Path -LiteralPath $TectonicExe)) {
        Fail "tectonic.exe not found after unpacking. See manual steps above."
    }
    Write-Host "  tectonic v$TectonicVersion installed to tools\tectonic\" -ForegroundColor Green
}

# 4. .env scaffold
$envFile = Join-Path $RepoRoot ".env"
$envExample = Join-Path $RepoRoot ".env.example"
if (-not (Test-Path -LiteralPath $envFile)) {
    if (-not (Test-Path -LiteralPath $envExample)) {
        Fail ".env.example missing — are you in the JobHunt project folder?"
    }
    Copy-Item -LiteralPath $envExample -Destination $envFile
    Write-Host "-- Created .env from .env.example" -ForegroundColor Green
} else {
    Write-Host "-- .env already exists, kept as-is" -ForegroundColor Green
}

# 5. Interactive key wizard (or skip)
if ($SkipWizard) {
    Write-Host "-- Skipping interactive wizard (-SkipWizard)" -ForegroundColor Yellow
} else {
    Write-Host "-- Starting interactive setup (Ctrl+C keeps saved progress)..."
    & python agent.py setup
}

# 6. Prove it
Write-Host ""
Write-Host "-- Final check:"
& python agent.py doctor

Write-Host ""
Write-Host "Done. Launch the app with:  .\run.ps1" -ForegroundColor Cyan
