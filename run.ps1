# JobHunt launcher (Windows PowerShell 5.1+).
#
# Easiest: double-click run.cmd in Explorer.
# From a terminal:
#   .\run.ps1                 # start the web UI (opens http://127.0.0.1:8765)
#   .\run.ps1 --port 9000     # extra args are passed straight to `agent.py ui`
#   .\run.ps1 --help          # show the UI options
#
# First time here? Run .\setup.ps1 once, then come back.
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$UiArgs
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $RepoRoot

if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot "agent.py"))) {
    Write-Host "agent.py not found — run this script from the JobHunt project folder." -ForegroundColor Red
    exit 1
}

& python agent.py ui @UiArgs
