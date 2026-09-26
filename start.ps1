# AquaSafe - Start Frontend + Backend together
# Usage: .\start.ps1

$ROOT = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "   AquaSafe - Starting All Services     " -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Start Backend (FastAPI + uvicorn) in a new terminal window
Write-Host "[1/2] Starting Backend on http://localhost:8000 ..." -ForegroundColor Yellow
$backendCmd = if (Test-Path "$ROOT\.venv\Scripts\uvicorn.exe") {
    "& '$ROOT\.venv\Scripts\uvicorn' main:app --host 0.0.0.0 --port 8000 --reload"
} else {
    "python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload"
}

Start-Process powershell -ArgumentList "-NoExit", "-Command", `
    "cd '$ROOT\backend'; Write-Host 'Backend starting...' -ForegroundColor Green; $backendCmd"

# Give backend a moment to boot
Start-Sleep -Seconds 2

# Start Frontend in a new terminal window
Write-Host "[2/2] Starting Frontend on http://localhost:5173 ..." -ForegroundColor Yellow
$frontendCmd = if ((Test-Path "$ROOT\frontend\node_modules") -and (Get-Command npm -ErrorAction SilentlyContinue)) {
    "npm run dev"
} else {
    "python -m http.server 5173"
}

Start-Process powershell -ArgumentList "-NoExit", "-Command", `
    "cd '$ROOT\frontend'; Write-Host 'Frontend starting...' -ForegroundColor Green; $frontendCmd"

Start-Sleep -Seconds 1

Write-Host ""
Write-Host "----------------------------------------" -ForegroundColor Green
Write-Host "  Backend  -> http://localhost:8000"      -ForegroundColor Green
Write-Host "  API Docs -> http://localhost:8000/docs" -ForegroundColor Green
Write-Host "  Frontend -> http://localhost:5173"      -ForegroundColor Green
Write-Host "  Proof Gallery -> http://localhost:5173/satellite-proof.html" -ForegroundColor Green
Write-Host "----------------------------------------" -ForegroundColor Green
Write-Host ""
Write-Host "Opening Satellite Proof Gallery in browser..." -ForegroundColor Cyan
Start-Process "http://localhost:5173/satellite-proof.html"
