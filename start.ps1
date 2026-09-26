# AquaWatch - Start Frontend + Backend together
# Usage: .\start.ps1

$ROOT = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "   AquaSafe - Starting All Services     " -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Start Backend (FastAPI + uvicorn) in a new terminal window
Write-Host "[1/2] Starting Backend on http://localhost:8000 ..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-Command", `
    "cd '$ROOT\backend'; Write-Host 'Backend starting...' -ForegroundColor Green; & '$ROOT\.venv\Scripts\uvicorn' main:app --host 0.0.0.0 --port 8000 --reload"

# Give backend a moment to boot
Start-Sleep -Seconds 2

# Start Frontend (Vite dev server) in a new terminal window
Write-Host "[2/2] Starting Frontend on http://localhost:5173 ..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-Command", `
    "cd '$ROOT\frontend'; Write-Host 'Frontend starting...' -ForegroundColor Green; npm run dev"

Write-Host ""
Write-Host "----------------------------------------" -ForegroundColor Green
Write-Host "  Backend  -> http://localhost:8000"      -ForegroundColor Green
Write-Host "  API Docs -> http://localhost:8000/docs" -ForegroundColor Green
Write-Host "  Frontend -> http://localhost:5173"      -ForegroundColor Green
Write-Host "----------------------------------------" -ForegroundColor Green
Write-Host ""
Write-Host "Both services launched in separate windows." -ForegroundColor Cyan
Write-Host "Close those windows to stop the servers."   -ForegroundColor Cyan
