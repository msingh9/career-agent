# Launches Google Chrome with the classic remote-debugging protocol so the
# Career Agent app can auto-fill and submit applications in a real Chrome that
# reuses your logged-in sessions (LinkedIn, Greenhouse, Lever, etc.).
#
# This is SEPARATE from the "Remote debugging" toggle used by chrome-devtools-mcp:
#   - The toggle Chrome (port 9222) is a secured endpoint only the MCP can attach to.
#   - Playwright (which powers the app's auto-apply) needs the classic protocol,
#     which this script starts on a DIFFERENT port with a DEDICATED profile.
#
# Usage:
#   .\start-chrome-debug.ps1
# Then, the first time, log into any job sites you need inside this Chrome window.
# Leave it open while you use Auto-apply in Career Agent.

$ErrorActionPreference = "Stop"

$Port = 9333
$ProfileDir = Join-Path $PSScriptRoot "data\chrome-debug-profile"

$chromeCandidates = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
)
$chrome = $chromeCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $chrome) {
    Write-Error "Could not find chrome.exe. Install Google Chrome or edit this script's paths."
    exit 1
}

New-Item -ItemType Directory -Force -Path $ProfileDir | Out-Null

Write-Host "Launching Chrome with classic remote debugging" -ForegroundColor Cyan
Write-Host "  chrome      : $chrome"
Write-Host "  debug port  : $Port"
Write-Host "  profile dir : $ProfileDir"
Write-Host ""
Write-Host "Career Agent connects via CHROME_CDP_URL=http://127.0.0.1:$Port" -ForegroundColor Green
Write-Host "First time: log into any job sites (LinkedIn, etc.) in this window; logins persist." -ForegroundColor Yellow

Start-Process -FilePath $chrome -ArgumentList @(
    "--remote-debugging-port=$Port",
    "--user-data-dir=`"$ProfileDir`"",
    "--no-first-run",
    "--no-default-browser-check",
    "about:blank"
)

Write-Host ""
Write-Host "Chrome launched. Leave this window open while auto-applying." -ForegroundColor Green
