$ErrorActionPreference = "Stop"

param(
  [string]$Config = "configs/ftmo_v1.yaml"
)

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $root

if (-not (Test-Path ".venv")) {
  py -3.11 -m venv .venv
}
. .\.venv\Scripts\Activate.ps1
python -m pip install -e .[dev] | Out-Null
pip install MetaTrader5 | Out-Null

$env:PYTHONPATH = "src"

if (-not $env:MT5_LOGIN) { $env:MT5_LOGIN = Read-Host "MT5_LOGIN" }
if (-not $env:MT5_SERVER) { $env:MT5_SERVER = Read-Host "MT5_SERVER" }
if (-not $env:MT5_PASSWORD) {
  $secure = Read-Host "MT5_PASSWORD" -AsSecureString
  $env:MT5_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
  )
}
if (-not $env:FTMO_FORCE_DISCONNECT) {
  $env:FTMO_FORCE_DISCONNECT = Join-Path $env:TEMP "ftmo_force_disconnect"
}

python scripts\freeze_config.py $Config

if (-not (Select-String -Path $Config -Pattern "broker: mt5" -Quiet)) {
  Write-Warning "execution.broker is not mt5 in $Config"
}

$serviceScript = Join-Path $root "scripts\start_service.ps1"
Start-Process -FilePath "powershell" -WorkingDirectory $root `
  -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$serviceScript`" -Config `"$Config`"" | Out-Null

$runId = ""
if (Test-Path "runtime\run_state.json") {
  $runId = (Get-Content "runtime\run_state.json" | ConvertFrom-Json).run_id
}
if ($runId) {
  $runId | Set-Content "runtime\gate_run_id.txt"
}

Write-Host "Gate run started."
Write-Host "run_id:" $runId
Write-Host "bundles: reports\daily_bundles\$runId\YYYY-MM-DD\"
Write-Host "daily check: scripts\gate_daily_check.ps1"
Write-Host "end-of-run summary:"
Write-Host "python scripts\analyze_bundles.py --bundle-root reports/daily_bundles --run-id $runId --last 5 --output-dir reports/bundle_summary"
Write-Host "Logs: runtime\service.log (crash marker: runtime\service_crash.txt)"
