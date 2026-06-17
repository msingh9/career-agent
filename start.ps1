$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Find-Python {
    $candidates = @(
        @("py", "-3.10"),
        @("py", "-3.11"),
        @("py", "-3.12"),
        @("py", "-3.13"),
        @("py", "-3.14"),
        @("python3"),
        @("python")
    )

    foreach ($candidate in $candidates) {
        try {
            $version = & $candidate[0] $candidate[1..($candidate.Length - 1)] -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
            if ($LASTEXITCODE -ne 0 -or -not $version) { continue }
            $parts = $version.Trim().Split(".")
            $major = [int]$parts[0]
            $minor = [int]$parts[1]
            if ($major -gt 3 -or ($major -eq 3 -and $minor -ge 10)) {
                return $candidate
            }
        } catch {
            continue
        }
    }

    throw "Python 3.10+ is required. Install from https://www.python.org/downloads/ then rerun start.ps1"
}

$pythonCmd = Find-Python

$venvPython = ".\.venv\Scripts\python.exe"
$needsVenv = !(Test-Path $venvPython)

if (!$needsVenv) {
    $venvVersion = & $venvPython -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    $parts = $venvVersion.Trim().Split(".")
    if ([int]$parts[0] -lt 3 -or ([int]$parts[0] -eq 3 -and [int]$parts[1] -lt 10)) {
        Write-Host "Removing old virtual environment (Python $($venvVersion.Trim()) is too old)..."
        Remove-Item -Recurse -Force ".venv"
        $needsVenv = $true
    }
}

if ($needsVenv) {
    Write-Host "Creating virtual environment with $($pythonCmd -join ' ')..."
    & $pythonCmd[0] $pythonCmd[1..($pythonCmd.Length - 1)] -m venv .venv
    & $venvPython -m pip install --upgrade pip
    & $venvPython -m pip install -r requirements.txt
}

Write-Host "Starting Semiconductor Career Agent at http://127.0.0.1:8000"

$portPids = netstat -ano | Select-String ":8000\s.*LISTENING" | ForEach-Object {
    ($_.Line -split '\s+')[-1]
} | Sort-Object -Unique

foreach ($procId in $portPids) {
    taskkill /F /PID $procId 2>$null | Out-Null
}

Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*uvicorn*app.main*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

Start-Sleep -Seconds 1

.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000
