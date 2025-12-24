$ErrorActionPreference = "Stop"

param(
  [string]$Config = "configs/ftmo_v1.yaml"
)

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $root

if (-not $env:PYTHONPATH) {
  $env:PYTHONPATH = "src"
}

if (-not $env:FTMO_FORCE_DISCONNECT) {
  $env:FTMO_FORCE_DISCONNECT = Join-Path $env:TEMP "ftmo_force_disconnect"
}

New-Item -ItemType Directory -Force -Path "runtime" | Out-Null
$logPath = "runtime\service.log"
$crashPath = "runtime\service_crash.txt"
Remove-Item $crashPath -ErrorAction SilentlyContinue

python scripts\run_service_loop.py --config "$Config" --resume --simulate-disconnect-path "$env:FTMO_FORCE_DISCONNECT" 2>&1 | Tee-Object -FilePath $logPath -Append

if ($LASTEXITCODE -ne 0) {
  "service exited with code $LASTEXITCODE at $(Get-Date -Format o)" | Out-File $crashPath -Append
}
