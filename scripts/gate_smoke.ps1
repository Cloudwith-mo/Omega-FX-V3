$ErrorActionPreference = "Stop"

param(
  [int]$Minutes = 30,
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
$proc = Start-Process -FilePath "powershell" -WorkingDirectory $root `
  -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$serviceScript`" -Config `"$Config`"" `
  -PassThru

Write-Host "Smoke running for $Minutes minutes (service PID $($proc.Id))..."
Start-Sleep -Seconds ($Minutes * 60)

$stopped = $false
if (-not $proc.HasExited) {
  Stop-Process -Id $proc.Id -Force
  $stopped = $true
}

$runId = ""
if (Test-Path "runtime\run_state.json") {
  $runId = (Get-Content "runtime\run_state.json" | ConvertFrom-Json).run_id
}
if ($runId) {
  $runRoot = Join-Path "reports\daily_bundles" $runId
  $dayDirs = @()
  if (Test-Path $runRoot) {
    $dayDirs = Get-ChildItem -Path $runRoot -Directory -ErrorAction SilentlyContinue
  }
  if (-not (Test-Path $runRoot) -or -not $dayDirs) {
    python scripts\generate_daily_bundle.py --config $Config --run-id $runId --output-dir reports/daily_bundles | Out-Null
  }
}
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
if ($runId) {
  $summaryDir = Join-Path "reports\bundle_summary" "$runId-$stamp"
  python scripts\analyze_bundles.py --bundle-root reports/daily_bundles --run-id $runId --last 1 --output-dir $summaryDir
} else {
  $summaryDir = Join-Path "reports\bundle_summary" $stamp
  python scripts\analyze_bundles.py --bundle-root reports/daily_bundles --last 1 --output-dir $summaryDir
}

$summaryPath = Join-Path $summaryDir "summary.json"
if (-not (Test-Path $summaryPath)) {
  throw "summary.json missing: $summaryPath"
}

$summary = Get-Content $summaryPath | ConvertFrom-Json
Write-Host "run_id:" $summary.run_id
Write-Host "go_no_go:" $summary.go_no_go
Write-Host "passes_policy_1:" $summary.passes_policy_1
Write-Host "passes_policy_2:" $summary.passes_policy_2
Write-Host "daily_buffer_stop_count:" $summary.totals.daily_buffer_stop_count
Write-Host "breach_events:" $summary.totals.breach_events
Write-Host "unresolved_drift_events:" $summary.totals.unresolved_drift_events
Write-Host "duplicate_order_events:" $summary.totals.duplicate_order_events
Write-Host "safe_mode_unexpected_events:" $summary.totals.safe_mode_unexpected_events

if (-not $stopped -and $proc.HasExited) {
  Write-Warning "Service exited early. Last 200 log lines:"
  if (Test-Path "runtime\service.log") {
    Get-Content "runtime\service.log" -Tail 200
  }
}
if (Test-Path "runtime\service_crash.txt") {
  Write-Warning "Crash marker:"
  Get-Content "runtime\service_crash.txt"
}
Write-Host "Logs: runtime\service.log"
