# Starts the MEP Takeoff UI on http://127.0.0.1:8501 (reachable from this computer only)
# and opens it in the default browser. First run creates .venv and installs dependencies.
param([switch]$NoBrowser)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
$url = "http://127.0.0.1:8501"

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    $basePython = Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe"
    if (-not (Test-Path $basePython)) {
        Write-Host "Python 3.11 not found. Install it once with:" -ForegroundColor Yellow
        Write-Host "  winget install -e --id Python.Python.3.11 --scope user" -ForegroundColor Yellow
        exit 1
    }
    & $basePython -m venv .venv
    & $venvPython -m pip install --upgrade pip
    & $venvPython -m pip install -r requirements.txt
}

$env:PYTHONUTF8 = "1"
$streamlitArgs = @(
    "-m", "streamlit", "run", "app.py",
    "--server.address", "127.0.0.1",
    "--server.port", "8501",
    "--server.headless", "true",
    "--server.enableXsrfProtection", "true",
    "--server.enableCORS", "true",
    "--browser.gatherUsageStats", "false"
)
$server = Start-Process -FilePath $venvPython -ArgumentList $streamlitArgs -NoNewWindow -PassThru

$ready = $false
for ($attempt = 0; $attempt -lt 60 -and -not $server.HasExited; $attempt++) {
    try {
        Invoke-WebRequest -Uri "$url/_stcore/health" -UseBasicParsing -TimeoutSec 2 | Out-Null
        $ready = $true
        break
    } catch {
        Start-Sleep -Seconds 1
    }
}
if (-not $ready) {
    Write-Host "MEP Takeoff did not start. See the messages above." -ForegroundColor Red
    exit 1
}

Write-Host "MEP Takeoff is running: $url  (close this window or press Ctrl+C to stop)" -ForegroundColor Green
if (-not $NoBrowser) { Start-Process $url }
Wait-Process -Id $server.Id
