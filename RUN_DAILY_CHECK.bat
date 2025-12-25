@echo off
setlocal
cd /d "%~dp0"

set "REPO=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "& { $repo = (Resolve-Path '%REPO%').Path; Set-Location $repo; if (Test-Path '.\.venv\Scripts\Activate.ps1') { . '.\.venv\Scripts\Activate.ps1' }; $env:PYTHONPATH='src'; .\scripts\gate_daily_check.ps1 }"

pause
